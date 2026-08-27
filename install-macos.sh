#!/usr/bin/env bash
# TicianoFlix — Instalador para macOS (LaunchAgent)
# Uso: bash install-macos.sh
# Compatível com bash 3.2 (o bash nativo do macOS).
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
echo -e "  ${CIANO}🎬 TicianoFlix — Instalador macOS${RESET}"
echo -e "  ${CIANO}══════════════════════════════════${RESET}"
echo ""

# ─── 1. Verificar diretório do projeto ──────────────────
if [ ! -f "$DIR/server.py" ]; then
    erro "server.py não encontrado em $DIR"
    echo "  Execute este script dentro da pasta do TicianoFlix."
    exit 1
fi
ok "Diretório do projeto: $DIR"

# ─── 2. Python 3.10+ ────────────────────────────────────
info "Verificando Python..."
PYTHON=""
for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$cand" ]; then
        PYTHON="$cand"
        break
    fi
done
if [ -z "$PYTHON" ] && command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
fi
if [ -z "$PYTHON" ]; then
    aviso "python3 não encontrado."
    if command -v brew >/dev/null 2>&1; then
        info "Instalando Python com Homebrew..."
        brew install python
        PYTHON="/opt/homebrew/bin/python3"
        [ -x "$PYTHON" ] || PYTHON="/usr/local/bin/python3"
    else
        erro "Instale o Python 3.10+ e rode o instalador de novo."
        echo "    - Homebrew:  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "    - Site:      https://www.python.org/downloads/macos/"
        echo "    - Xcode:     xcode-select --install (inclui /usr/bin/python3)"
        exit 1
    fi
fi
PYVER="$($PYTHON --version 2>&1 | awk '{print $2}')"
ok "python3 encontrado: $PYTHON ($PYVER)"

# ─── 3. rclone ──────────────────────────────────────────
info "Verificando rclone..."
if command -v rclone >/dev/null 2>&1; then
    ok "rclone encontrado: $(rclone version | head -1)"
else
    aviso "rclone não instalado."
    if command -v brew >/dev/null 2>&1; then
        info "Instalando com Homebrew: brew install rclone"
        brew install rclone
    else
        info "Instalando script oficial rclone..."
        curl -s https://rclone.org/install.sh | sudo bash
    fi
    ok "rclone instalado: $(rclone version | head -1)"
fi
RCLONE_BIN="$(command -v rclone)"

# ─── 4. Remote gdrive: ──────────────────────────────────
info "Verificando remote 'gdrive:'..."
if rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
    ok "Remote gdrive: já configurado"
else
    aviso "Remote 'gdrive:' não configurado."
    echo "  Configure depois pelo botão ☁️ rclone dentro do TicianoFlix"
    echo "  (ou rode 'rclone config' manualmente)."
fi

# ─── 4b. Acesso ao Drive (privilegio minimo) ────────────
if rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
    SCOPE="$(rclone config show gdrive 2>/dev/null | sed -n 's/^scope[[:space:]]*=[[:space:]]*//p')"
    ROOTID="$(rclone config show gdrive 2>/dev/null | sed -n 's/^root_folder_id[[:space:]]*=[[:space:]]*//p')"
    if [ "$SCOPE" = "drive.readonly" ] && [ -n "$ROOTID" ]; then
        ok "Acesso ao Drive já está no mínimo (só leitura, só a pasta TicianoFlix)"
    else
        echo
        aviso "O remote 'gdrive:' alcança MAIS do que o TicianoFlix precisa."
        echo "  Escopo atual: ${SCOPE:-drive} — isso permite ler e apagar arquivos"
        echo "  em todo o seu Google Drive, não só na pasta TicianoFlix."
        echo
        echo "  O script setup-rclone-seguro.sh reduz isso ao mínimo. Ele abre o"
        echo "  navegador para você reautorizar (é o Google que aplica o limite)."
        echo
        printf "  Reduzir agora? [S/n] "
        read -r RESP </dev/tty || RESP="n"
        case "$RESP" in
            [Nn]*) aviso "Pulado. Rode depois: ./setup-rclone-seguro.sh" ;;
            *) "$DIR/setup-rclone-seguro.sh" || aviso "Falhou. Rode depois: ./setup-rclone-seguro.sh" ;;
        esac
    fi
fi

# ─── 5. Diretórios de cache ─────────────────────────────
mkdir -p "$HOME/.cache/ticianoflix/images"
mkdir -p "$HOME/.cache/ticianoflix/subs"
mkdir -p "$HOME/.cache/rclone"
ok "Diretórios de cache prontos (~/.cache/ticianoflix)"

# ─── 6. Wrapper nativo (nome legível no Activity Monitor) ──
WRAPPER="$DIR/ticianoflix-server"
if [ ! -x "$WRAPPER" ] || [ "$DIR/ticianoflix-server.c" -nt "$WRAPPER" ]; then
    info "Compilando wrapper nativo (ticianoflix-server)..."
    if command -v clang >/dev/null 2>&1; then
        clang -O2 -o "$WRAPPER" "$DIR/ticianoflix-server.c" && chmod +x "$WRAPPER" \
            && ok "Wrapper compilado" \
            || aviso "Falha ao compilar wrapper — usará python3 direto"
    else
        aviso "clang não encontrado — usará python3 direto (sem nome legível)"
    fi
else
    ok "Wrapper nativo: $WRAPPER"
fi

# ─── 7. LaunchAgent ─────────────────────────────────────
LA_DIR="$HOME/Library/LaunchAgents"
PLIST="$LA_DIR/com.ticianoflix.plist"
mkdir -p "$LA_DIR"

# PATH completo para o rclone funcionar dentro do LaunchAgent
BREW_PREFIX=""
if command -v brew >/dev/null 2>&1; then
    BREW_PREFIX="$(brew --prefix 2>/dev/null || true)"
fi
if [ -n "$BREW_PREFIX" ]; then
    LAUNCH_PATH="$BREW_PREFIX/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
else
    LAUNCH_PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
fi

# Programa a executar: wrapper nativo (nome legível) ou python3 direto (fallback)
if [ -x "$WRAPPER" ]; then
    PROGRAM_ARGS="<string>$WRAPPER</string>"
else
    PROGRAM_ARGS="<string>$PYTHON</string>
        <string>server.py</string>"
fi

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ticianoflix</string>
    <key>ProgramArguments</key>
    <array>
        $PROGRAM_ARGS
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$LAUNCH_PATH</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$HOME/.cache/ticianoflix/ticianoflix.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.cache/ticianoflix/ticianoflix.log</string>
</dict>
</plist>
PLIST_EOF
ok "LaunchAgent criado em $PLIST"

# ─── 7. Carregar o serviço ──────────────────────────────
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
if ! launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then
    info "bootstrap falhou, tentando launchctl load (macOS antigo)..."
    launchctl load "$PLIST"
fi
sleep 2

# ─── 8. Verificar ───────────────────────────────────────
if launchctl list 2>/dev/null | grep -q "com.ticianoflix"; then
    ok "Serviço carregado e rodando"
else
    aviso "Serviço não carregou. Veja o log:"
    echo "  tail -50 ~/.cache/ticianoflix/ticianoflix.log"
fi

echo ""
echo -e "  ${VERDE}╔══════════════════════════════════════════════╗${RESET}"
echo -e "  ${VERDE}║        Instalação concluída! 🎉             ║${RESET}"
echo -e "  ${VERDE}║                                              ║${RESET}"
echo -e "  ${VERDE}║  🌐 http://localhost:8080                     ║${RESET}"
echo -e "  ${VERDE}║                                              ║${RESET}"
echo -e "  ${VERDE}║  🔄 launchctl kickstart gui/\$(id -u)/com.ticianoflix  ║${RESET}"
echo -e "  ${VERDE}║  🛑 launchctl bootout gui/\$(id -u)/com.ticianoflix   ║${RESET}"
echo -e "  ${VERDE}║  📋 tail -f ~/.cache/ticianoflix/ticianoflix.log   ║${RESET}"
echo -e "  ${VERDE}╚══════════════════════════════════════════════╝${RESET}"
echo ""
aviso "Se o macOS perguntar sobre conexões de entrada, permita (o servidor escuta na porta 8080)."
aviso "Para Chromecast/HTTPS (porta 8443), instale o mkcert: brew install mkcert && mkcert -install"
echo ""
