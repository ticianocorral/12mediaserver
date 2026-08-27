#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  TicianoFlix — hardening do acesso ao Google Drive
#
#  Deixa o TicianoFlix com o menor privilegio possivel no Drive:
#
#    gdrive         scope=drive.readonly + root_folder_id da pasta TicianoFlix
#                   -> so LE, e so enxerga a pasta TicianoFlix
#    gdrive_backup  scope=drive.file
#                   -> so enxerga arquivos que o proprio TicianoFlix criou
#
#  Depois disso, nem um bug de path traversal alcanca o resto do seu Drive.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REMOTE="gdrive"
BACKUP_REMOTE="gdrive_backup"
FOLDER_NAME="TicianoFlix"

c_red=$'\033[0;31m'; c_grn=$'\033[0;32m'; c_yel=$'\033[1;33m'
c_cyn=$'\033[0;36m'; c_rst=$'\033[0m'

info() { printf '%s\n' "${c_cyn}$*${c_rst}"; }
ok()   { printf '%s\n' "${c_grn}✓ $*${c_rst}"; }
warn() { printf '%s\n' "${c_yel}! $*${c_rst}"; }
die()  { printf '%s\n' "${c_red}✗ $*${c_rst}" >&2; exit 1; }

command -v rclone >/dev/null 2>&1 || die "rclone nao encontrado. Instale com: brew install rclone"

CONF="$(rclone config file | tail -n1)"
[ -f "$CONF" ] || die "rclone.conf nao encontrado em: $CONF"

# Sem pipe aqui de proposito: com 'set -o pipefail', um 'grep -q' que sai na
# primeira linha manda SIGPIPE pro rclone, o pipeline vira 141 e o '|| die'
# dispara mesmo com o remote existindo.
REMOTES="$(rclone listremotes)"
grep -qx "${REMOTE}:" <<<"$REMOTES" \
  || die "Remote '${REMOTE}' nao existe. Rode 'rclone config' e crie ele primeiro."

# ── 1. Backup do config ──────────────────────────────────────
STAMP="$(date +%Y%m%d-%H%M%S)"
cp "$CONF" "${CONF}.bak-${STAMP}"
ok "Config salvo em ${CONF}.bak-${STAMP}"

# ── 2. Descobrir o ID da pasta TicianoFlix ───────────────────
# Precisa acontecer ANTES de escopar, enquanto o remote ainda ve a raiz.
EXISTING_ROOT="$(rclone config show "$REMOTE" | sed -n 's/^root_folder_id[[:space:]]*=[[:space:]]*//p')"

if [ -n "$EXISTING_ROOT" ]; then
  warn "root_folder_id ja configurado (${EXISTING_ROOT}) — mantendo"
  FOLDER_ID="$EXISTING_ROOT"
else
  info "Procurando a pasta '${FOLDER_NAME}' no seu Drive..."
  FOLDER_ID="$(rclone lsjson "${REMOTE}:" --dirs-only 2>/dev/null \
    | python3 -c "
import json,sys
try:
    entries = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for e in entries:
    if e.get('Name') == '${FOLDER_NAME}':
        print(e.get('ID',''))
        break
")"
  [ -n "$FOLDER_ID" ] || die "Pasta '${FOLDER_NAME}' nao encontrada na raiz do Drive."
  ok "Pasta encontrada: ${FOLDER_ID}"
fi

# ── 3. Escopar + downgrade pra somente-leitura ───────────────
info "Aplicando root_folder_id e scope=drive.readonly em '${REMOTE}'..."
rclone config update "$REMOTE" root_folder_id "$FOLDER_ID" --non-interactive >/dev/null
rclone config update "$REMOTE" scope drive.readonly --non-interactive >/dev/null
ok "Config atualizado"

# ── 4. Reconectar (obrigatorio) ──────────────────────────────
# O token que ja existe carrega o scope 'drive' concedido la atras. Mudar o
# campo no config NAO rebaixa esse token — so um consentimento novo faz isso.
cat <<EOF

${c_yel}┌────────────────────────────────────────────────────────────┐
│  ATENCAO — este passo e o que realmente protege o Drive    │
└────────────────────────────────────────────────────────────┘${c_rst}

O token atual ainda tem permissao de ESCRITA no Drive inteiro. Editar o
arquivo de config nao muda isso: quem decide o que o token pode fazer e o
Google, no momento do consentimento.

Vai abrir o navegador. Confira que a tela de permissao diz algo como
${c_cyn}"Ver e baixar seus arquivos do Google Drive"${c_rst} — e nao "editar" ou
"excluir". Se aparecer permissao de escrita, cancele e me avise.

EOF
read -r -p "Pressione ENTER para reconectar (ou Ctrl+C pra abortar) "

rclone config reconnect "${REMOTE}:" || die "Falha ao reconectar '${REMOTE}'"
ok "Token de leitura emitido"

# ── 5. Remote de backup (escrita minima) ─────────────────────
if grep -qx "${BACKUP_REMOTE}:" <<<"$(rclone listremotes)"; then
  warn "Remote '${BACKUP_REMOTE}' ja existe — pulando"
else
  cat <<EOF

Agora o remote de ${c_cyn}backup${c_rst}. Ele usa scope ${c_cyn}drive.file${c_rst}: enxerga
exclusivamente os arquivos que o proprio TicianoFlix criar. Seus filmes,
documentos e o resto do Drive ficam invisiveis pra ele.

EOF
  read -r -p "Pressione ENTER para criar '${BACKUP_REMOTE}' "
  # Herda o client_id do remote principal. Sem isso o rclone cai no client_id
  # compartilhado dele, que o Google esta aposentando ao longo de 2026 — o
  # backup pararia de funcionar sozinho, sem aviso.
  CID="$(rclone config show "$REMOTE" | sed -n 's/^client_id[[:space:]]*=[[:space:]]*//p')"
  CSEC="$(rclone config show "$REMOTE" | sed -n 's/^client_secret[[:space:]]*=[[:space:]]*//p')"
  if [ -n "$CID" ]; then
    rclone config create "$BACKUP_REMOTE" drive \
      scope drive.file client_id "$CID" client_secret "$CSEC" \
      || die "Falha ao criar '${BACKUP_REMOTE}'"
    ok "Remote de backup criado (client_id proprio)"
  else
    warn "'${REMOTE}' nao tem client_id proprio — usando o compartilhado do rclone"
    warn "Ele sera aposentado durante 2026; crie um client_id no Google Cloud Console"
    rclone config create "$BACKUP_REMOTE" drive scope drive.file \
      || die "Falha ao criar '${BACKUP_REMOTE}'"
    ok "Remote de backup criado"
  fi
fi

# ── 6. Verificacao ───────────────────────────────────────────
echo
info "── Verificando ──"

if rclone lsjson "${REMOTE}:" --dirs-only >/tmp/tf-verify.json 2>/dev/null; then
  python3 - <<'PY'
import json
names = [e.get("Name", "") for e in json.load(open("/tmp/tf-verify.json"))]
print("  Pastas visiveis pro remote principal:")
for n in names[:12]:
    print(f"    - {n}")
if any(n in ("Documentos", "Maya", "OpenEmu") for n in names):
    print("\n  \033[0;31m✗ O remote ainda ve a raiz do Drive.\033[0m")
else:
    print("\n  \033[0;32m✓ Escopado: so o conteudo da pasta TicianoFlix.\033[0m")
PY
  rm -f /tmp/tf-verify.json
else
  warn "Nao consegui listar pra verificar"
fi

printf '  Escrita bloqueada? '
if echo test | rclone rcat "${REMOTE}:__tf_write_probe.tmp" >/dev/null 2>&1; then
  printf '%s\n' "${c_red}✗ NAO — o remote ainda escreve!${c_rst}"
  rclone delete "${REMOTE}:__tf_write_probe.tmp" >/dev/null 2>&1 || true
  warn "O reconnect provavelmente nao aplicou o scope novo. Rode de novo."
else
  printf '%s\n' "${c_grn}✓ sim, somente-leitura${c_rst}"
fi

cat <<EOF

${c_grn}Pronto.${c_rst} Reinicie o TicianoFlix:

  pkill -9 -f 'python.*server.py'; python3 server.py

Para reverter:  cp "${CONF}.bak-${STAMP}" "$CONF"

EOF
