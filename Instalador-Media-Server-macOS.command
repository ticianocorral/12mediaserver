#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  12:00 Media Server — Instalador visual para macOS
#
#  Diálogos nativos (AppleScript) + o instalador oficial
#  (install.sh) rodando na janela do Terminal, com a saída
#  colorida visível — a barra de progresso de verdade.
#
#  Uso: duplo clique no arquivo (ou: bash Instalador-Media-Server-macOS.command)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${MEDIA_SERVER_REPO:-ticianocorral/12mediaserver}"
REF="${MEDIA_SERVER_REF:-main}"

aviso() {
    osascript -e "display dialog \"$1\" with title \"12:00 Media Server\" buttons {\"Continuar\"} default button 1 with icon note" >/dev/null
}

# ── Boas-vindas ──────────────────────────────────────────────
if ! osascript -e 'display dialog "🎬 Bem-vindo ao 12:00 Media Server!

Seus filmes com cara de Netflix — self-hosted, leve e instantâneo.

O instalador vai:
  • verificar e instalar o rclone (se faltar)
  • instalar o app e o serviço que sobe com o login
  • abrir o navegador no final

 Continuar?" with title "12:00 Media Server — Instalador" buttons {"Cancelar", "Continuar"} default button 2 with icon note' 2>/dev/null | grep -q "Continuar"; then
    echo "Instalação cancelada."
    exit 0
fi

# ── Projeto ao lado ou baixar ────────────────────────────────
if [ ! -f "$DIR/install.sh" ]; then
    aviso "O instalador oficial (install.sh) não está junto deste arquivo. Vou baixá-lo do GitHub — se o repositório for privado, baixe o projeto e rode este arquivo de dentro da pasta."
    curl -fsSL "https://raw.githubusercontent.com/$REPO/$REF/install.sh" -o "$DIR/install.sh" \
        || { aviso "Não consegui baixar o install.sh (repositório privado?). Baixe o projeto e tente de novo."; exit 1; }
fi

# ── Instalar (saída visível no Terminal) ─────────────────────
clear 2>/dev/null || true
echo ""
echo "  🎬 12:00 Media Server — instalando..."
echo "  (esta janela mostra o progresso de verdade; pode deixar rodando)"
echo ""
chmod +x "$DIR/install.sh"
if ! bash "$DIR/install.sh"; then
    aviso "A instalação terminou com erro. Role a janela do Terminal para ver o que aconteceu — e rode de novo se quiser."
    exit 1
fi

# ── Encerramento ─────────────────────────────────────────────
RESPOSTA=$(osascript -e 'display dialog "✅ Instalação concluída!

O 12:00 Media Server já está rodando e vai iniciar junto com o Mac.

Abra http://localhost:9187 — o código de instalação de 6 dígitos
apareceu na janela do Terminal acima (e no log).

Abrir o navegador agora?" with title "12:00 Media Server — Instalador" buttons {"Depois", "Abrir"} default button 2 with icon note' 2>/dev/null | grep -o "Abrir\|Depois" || echo "")
if [ "$RESPOSTA" = "Abrir" ]; then
    open "http://localhost:9187"
fi
