#!/usr/bin/env bash
# TicianoFlix — Instalador do servidor como serviço systemd
# Uso: bash install.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

# ─── Cores ──────────────────────────────────────────────
VERDE='\033[0;32m'
AMARELO='\033[1;33m'
VERMELHO='\033[0;31m'
CIANO='\033[0;36m'
RESET='\033[0m'
ok()   { echo -e "  ${VERDE}✓${RESET} $1"; }
info() { echo -e "  ${CIANO}→${RESET} $1"; }
aviso(){ echo -e "  ${AMARELO}⚠${RESET} $1"; }
erro() { echo -e "  ${VERMELHO}✗${RESET} $1"; }

echo ""
echo -e "  ${CIANO}🎬 TicianoFlix — Instalador${RESET}"
echo -e "  ${CIANO}═══════════════════════════${RESET}"
echo ""

# ─── 1. Verificar diretório do projeto ──────────────────
if [ ! -f "$DIR/server.py" ]; then
    erro "server.py não encontrado em $DIR"
    echo "  Execute este script dentro da pasta do TicianoFlix."
    exit 1
fi
ok "Diretório do projeto: $DIR"

# ─── 2. Rclone ──────────────────────────────────────────
info "Verificando rclone..."
if command -v rclone &>/dev/null; then
    ok "rclone encontrado: $(rclone version | head -1)"
else
    aviso "rclone não instalado."
    if command -v pacman &>/dev/null; then
        info "Instalando com pacman..."
        sudo pacman -S --noconfirm rclone
    elif command -v apt &>/dev/null; then
        info "Instalando com apt..."
        sudo apt update && sudo apt install -y rclone
    else
        info "Instalando script oficial rclone..."
        curl -s https://rclone.org/install.sh | sudo bash
    fi
    ok "rclone instalado: $(rclone version | head -1)"
fi

# ─── 3. Remote gdrive: ──────────────────────────────────
info "Verificando remote 'gdrive:'..."
if rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
    ok "Remote gdrive: já configurado"
else
    aviso "Remote 'gdrive:' não encontrado."
    echo ""
    echo -e "  ${AMARELO}⚠ Configure o Google Drive:${RESET}"
    echo "    rclone config"
    echo ""
    echo "  Siga o assistente para criar um remote chamado 'gdrive'"
    echo "  com escopo 'drive' (acesso completo) ou 'drive.file'."
    echo "  Depois execute este instalador novamente."
    echo ""
    # Tenta iniciar o config interativamente
    if [ -t 0 ]; then
        read -p "  Iniciar rclone config agora? (s/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Ss]$ ]]; then
            rclone config
        fi
    fi
    # Verifica de novo
    if ! rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
        erro "Remote gdrive: não configurado. Execute 'rclone config' manualmente e rode o instalador de novo."
        exit 1
    fi
    ok "Remote gdrive: configurado"
fi

# ─── 4. Symlink (evita espaços no path do systemd) ──────
SYMLINK="$HOME/TicianoFlix"
if [ -L "$SYMLINK" ]; then
    ok "Symlink ~/TicianoFlix já existe"
elif [ -d "$SYMLINK" ]; then
    aviso "~/TicianoFlix já existe como diretório — removendo pra criar symlink"
    rmdir "$SYMLINK" 2>/dev/null || {
        erro "~/TicianoFlix existe e não é vazio. Remova manualmente."
        exit 1
    }
    ln -sf "$DIR" "$SYMLINK"
    ok "Symlink ~/TicianoFlix criado"
else
    ln -sf "$DIR" "$SYMLINK"
    ok "Symlink ~/TicianoFlix criado"
fi

# ─── 5. Diretórios de cache ─────────────────────────────
mkdir -p "$HOME/.cache/ticianoflix"
mkdir -p "$HOME/.cache/ticianoflix/images"
mkdir -p "$HOME/.cache/rclone"
ok "Diretórios de cache prontos"

# ─── 6. Serviço systemd ─────────────────────────────────
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/ticianoflix.service"
mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_FILE" << UNIT
[Unit]
Description=TicianoFlix - Netflix-style Google Drive movie player
Documentation=https://github.com/ticiano/ticianoflix
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 server.py
WorkingDirectory=%h/TicianoFlix
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
MemoryDenyWriteExecute=false
ReadWritePaths=%h/.cache/ticianoflix
ReadWritePaths=%h/.cache/rclone

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
ok "Serviço systemd criado em $SERVICE_FILE"

# ─── 7. Habilitar e iniciar ─────────────────────────────
systemctl --user enable ticianoflix.service
systemctl --user restart ticianoflix.service 2>/dev/null || true
sleep 3

# ─── 8. Linger (rodar mesmo sem login) ──────────────────
loginctl enable-linger 2>/dev/null || true
ok "Linger ativado (serviço persiste após logout)"

# ─── 9. Verificar ───────────────────────────────────────
if systemctl --user is-active --quiet ticianoflix.service; then
    PORT=$(ss -tlnp 2>/dev/null | grep python | awk '{print $4}' | grep -oP '\d+$' || echo "8080")
    echo ""
    echo -e "  ${VERDE}╔══════════════════════════════════════════════╗${RESET}"
    echo -e "  ${VERDE}║        Instalação concluída! 🎉             ║${RESET}"
    echo -e "  ${VERDE}║                                              ║${RESET}"
    echo -e "  ${VERDE}║  🌐 http://localhost:${PORT}                     ║${RESET}"
    echo -e "  ${VERDE}║                                              ║${RESET}"
    echo -e "  ${VERDE}║  📋 systemctl --user status ticianoflix      ║${RESET}"
    echo -e "  ${VERDE}║  📋 journalctl --user -u ticianoflix -f     ║${RESET}"
    echo -e "  ${VERDE}╚══════════════════════════════════════════════╝${RESET}"
    echo ""
else
    echo ""
    aviso "Serviço não está ativo. Verifique os logs:"
    echo "  journalctl --user -u ticianoflix.service --no-pager -n 20"
    echo ""
    systemctl --user status ticianoflix.service --no-pager 2>&1 || true
fi

# ─── 10. Aviso sobre o rclone config ────────────────────
if rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
    :
else
    aviso "Lembre-se de configurar o remote gdrive: com 'rclone config'"
fi

echo -e "  ${CIANO}Feito!${RESET}"
echo ""
