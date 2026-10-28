#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  12:00 Media Server — Instalador visual para Linux
#
#  Diálogos gráficos via zenity (GNOME) ou kdialog (KDE); sem
#  ambiente gráfico, cai para o terminal mesmo — nunca falha.
#
#  Uso: bash Instalador-Media-Server-Linux.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${MEDIA_SERVER_REPO:-ticianocorral/TicianoFlix}"
REF="${MEDIA_SERVER_REF:-main}"

# ── Qual caixa de diálogo temos? ─────────────────────────────
ZENITY="$(command -v zenity 2>/dev/null || true)"
KDIALOG="$(command -v kdialog 2>/dev/null || true)"

pergunta() { # pergunta TITULO TEXTO -> "0" se continuar
    local titulo="$1" texto="$2"
    if [ -n "$ZENITY" ]; then
        "$ZENITY" --question --title="$titulo" --text="$texto" --ok-label="Continuar" --cancel-label="Cancelar" && return 0
        return 1
    elif [ -n "$KDIALOG" ]; then
        [ "$("$KDIALOG" --title "$titulo" --yesno "$texto" 2>/dev/null)" = "0" ] && return 0
        return 1
    fi
    # Sem caixa gráfica: texto puro, sem as marcas do zenity.
    echo ""
    echo "  $titulo"
    echo "  $(echo "$texto" | sed -e 's/<[^>]*>//g')"
    read -r -p "  Continuar? [S/n] " r
    [ "${r:-s}" = "s" ] || [ "${r:-s}" = "S" ]
}

info() {
    local titulo="$1" texto="$2"
    if [ -n "$ZENITY" ]; then
        "$ZENITY" --info --title="$titulo" --text="$texto" 2>/dev/null || true
    elif [ -n "$KDIALOG" ]; then
        "$KDIALOG" --title "$titulo" --msgbox "$texto" 2>/dev/null || true
    else
        echo ""
        echo "  $texto"
    fi
}

# ── Boas-vindas ──────────────────────────────────────────────
pergunta "12:00 Media Server — Instalador" "🎬 <b>Bem-vindo ao 12:00 Media Server</b>

Seus filmes com cara de Netflix — self-hosted, leve e instantâneo.

O instalador vai:
  • verificar e instalar o Python e o rclone (se faltar)
  • instalar o app e o serviço systemd que sobe com o login
  • abrir o navegador no final" || { echo "Instalação cancelada."; exit 0; }

# ── Projeto ao lado ou baixar ────────────────────────────────
if [ ! -f "$DIR/install.sh" ]; then
    pergunta "install.sh não encontrado" "O instalador oficial (<b>install.sh</b>) não está junto deste arquivo. Vou baixá-lo do GitHub — se o repositório for privado, baixe o projeto e rode este arquivo de dentro da pasta." || exit 0
    curl -fsSL "https://raw.githubusercontent.com/$REPO/$REF/install.sh" -o "$DIR/install.sh" \
        || { info "Erro" "Não consegui baixar o install.sh (repositório privado?). Baixe o projeto e tente de novo."; exit 1; }
fi
chmod +x "$DIR/install.sh"

# ── Instalar ─────────────────────────────────────────────────
# A instalação em si roda no terminal (a saída colorida é o progresso de
# verdade e o sudo, se precisar, pergunta ali mesmo).
TERMINAL=""
for t in gnome-terminal konsole xterm xfce4-terminal; do
    command -v "$t" >/dev/null 2>&1 && { TERMINAL="$t"; break; }
done

if [ -n "$ZENITY" ] || [ -n "$KDIALOG" ]; then
    pergunta "Abrir a janela de instalação" "Vou abrir uma janela de terminal com a instalação rodando.
Deixe-a terminar — ela mostra o progresso e o código de instalação no final." || exit 0
    case "$TERMINAL" in
        gnome-terminal)  gnome-terminal -- bash -c "bash '$DIR/install.sh'; echo; read -rp 'Terminei — Enter para fechar...'"; WAIT=0 ;;
        konsole)         konsole -e bash -c "bash '$DIR/install.sh'; echo; read -rp 'Terminei — Enter para fechar...'"; WAIT=0 ;;
        xfce4-terminal)  xfce4-terminal -e bash -c "bash '$DIR/install.sh'; echo; read -rp 'Terminei — Enter para fechar...'"; WAIT=0 ;;
        xterm)           xterm -e bash -c "bash '$DIR/install.sh'; echo; read -rp 'Terminei — Enter para fechar...'" & WAIT=1 ;;
        *)               WAIT=1 ;;
    esac
    if [ "${WAIT:-1}" = "1" ]; then
        # Sem terminal conhecido: roda aqui mesmo.
        bash "$DIR/install.sh"
    else
        # Acompanha pelo log até o serviço responder.
        info "Instalando..." "A instalação está rodando na janela que abri. Quando ela terminar, clique em OK para continuar."
        for _ in $(seq 1 60); do
            curl -fsS -o /dev/null "http://localhost:${MEDIA_SERVER_PORT:-9187}/api/auth/status" 2>/dev/null && break
            sleep 2
        done
    fi
else
    bash "$DIR/install.sh"
fi

# ── Encerramento ─────────────────────────────────────────────
URL="http://localhost:${MEDIA_SERVER_PORT:-9187}"
if pergunta "Instalação concluída" "✅ <b>O 12:00 Media Server está no ar</b>

Abra $URL — o código de instalação de 6 dígitos aparece no log
(~/.cache/media-server/media-server.log) ou na janela do instalador.

Abrir o navegador agora?"; then
    xdg-open "$URL" >/dev/null 2>&1 || true
fi
