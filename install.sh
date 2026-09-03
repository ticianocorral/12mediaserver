#!/usr/bin/env bash
# TicianoFlix — Instalador (Linux e macOS)
#
# Uso recomendado (nao precisa clonar nada antes):
#   curl -fsSL https://raw.githubusercontent.com/ticianocorral/TicianoFlix/main/install.sh | bash
#
# Tambem funciona rodado de dentro de um clone existente:
#   bash install.sh
#
# Compativel com bash 3.2 (o bash de sistema do macOS, que e quem roda o
# "curl | bash" ali em cima).
set -euo pipefail

REPO="${TICIANOFLIX_REPO:-ticianocorral/TicianoFlix}"
REF="${TICIANOFLIX_REF:-main}"
PORTA="${TICIANOFLIX_PORT:-9187}"

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

# ─── 1. Sistema operacional ─────────────────────────────
case "$(uname -s)" in
    Darwin) PLATAFORMA="macos" ;;
    Linux)  PLATAFORMA="linux" ;;
    *)
        erro "Este instalador cobre Linux e macOS."
        echo "  No Windows, baixe o projeto e rode install-windows.bat."
        exit 1
        ;;
esac
ok "Sistema: $PLATAFORMA"

# ─── 2. Onde fica o projeto ──────────────────────────────
# Rodando de um clone existente (bash install.sh dentro da pasta): usa esse
# diretorio. Rodando via "curl | bash" (o caminho de uma linha so): nao existe
# arquivo local nenhum — BASH_SOURCE fica vazio — entao baixa o projeto.
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ] \
   && [ -f "$(dirname "${BASH_SOURCE[0]}")/server.py" ]; then
    DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    ok "Rodando a partir de um clone existente: $DIR"
else
    DIR="${TICIANOFLIX_DIR:-$HOME/TicianoFlix}"
    info "Baixando o TicianoFlix (${REPO}@${REF})..."
    mkdir -p "$DIR"
    URL_TARBALL="https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"
    if ! curl -fsSL "$URL_TARBALL" | tar -xz --strip-components=1 -C "$DIR" 2>/tmp/ticianoflix-download.log; then
        erro "Não consegui baixar $URL_TARBALL"
        echo "  Isso costuma acontecer quando o repositório está privado no GitHub —"
        echo "  nesse caso baixe o .zip manualmente (autenticado) e rode 'bash install.sh'"
        echo "  de dentro da pasta extraída."
        exit 1
    fi
    ok "Projeto baixado em $DIR"
fi
if [ ! -f "$DIR/server.py" ]; then
    erro "server.py não encontrado em $DIR — download incompleto?"
    exit 1
fi
cd "$DIR"

# ─── 3. Python 3.9+ ──────────────────────────────────────
info "Verificando Python..."
PYTHON=""
for cand in python3 python3.13 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            PYTHON="$(command -v "$cand")"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    aviso "Python 3.9+ não encontrado."
    if [ "$PLATAFORMA" = "macos" ] && command -v brew >/dev/null 2>&1; then
        info "Instalando com Homebrew: brew install python"
        brew install python
        PYTHON="$(command -v python3 || true)"
    elif [ "$PLATAFORMA" = "linux" ]; then
        if command -v apt >/dev/null 2>&1; then
            info "Instalando com apt..."
            sudo apt update && sudo apt install -y python3
        elif command -v dnf >/dev/null 2>&1; then
            info "Instalando com dnf..."
            sudo dnf install -y python3
        elif command -v pacman >/dev/null 2>&1; then
            info "Instalando com pacman..."
            sudo pacman -S --noconfirm python
        fi
        PYTHON="$(command -v python3 || true)"
    fi
fi
if [ -z "$PYTHON" ]; then
    erro "Instale o Python 3.9+ e rode o instalador de novo."
    if [ "$PLATAFORMA" = "macos" ]; then
        echo "    - Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "    - Xcode CLT: xcode-select --install"
    else
        echo "    - Debian/Ubuntu: sudo apt install python3"
        echo "    - Fedora: sudo dnf install python3"
        echo "    - Arch: sudo pacman -S python"
    fi
    exit 1
fi
PYVER="$($PYTHON --version 2>&1 | awk '{print $2}')"
ok "python3 encontrado: $PYTHON ($PYVER)"

# Google Drive e as fontes locais (HD externo, pendrive, pasta do computador)
# sao 100% opcionais e configuraveis pela propria interface, em Ajustes — nao
# ha nada para preparar aqui. O rclone so entra se e quando voce quiser o
# Drive; sem ele o servidor sobe igual.

# ─── 4. Diretórios de cache ──────────────────────────────
mkdir -p "$HOME/.cache/ticianoflix/images"
mkdir -p "$HOME/.cache/ticianoflix/subs"
ok "Diretórios de cache prontos (~/.cache/ticianoflix)"

if [ "$PLATAFORMA" = "macos" ]; then
    # ─── 5a. Wrapper nativo (nome legível no Activity Monitor) ──
    WRAPPER="$DIR/ticianoflix-server"
    if command -v clang >/dev/null 2>&1; then
        if [ ! -x "$WRAPPER" ] || [ "$DIR/ticianoflix-server.c" -nt "$WRAPPER" ]; then
            info "Compilando wrapper nativo (ticianoflix-server)..."
            clang -O2 -o "$WRAPPER" "$DIR/ticianoflix-server.c" && chmod +x "$WRAPPER" \
                && ok "Wrapper compilado" \
                || aviso "Falha ao compilar wrapper — usará python3 direto"
        else
            ok "Wrapper nativo: $WRAPPER"
        fi
    else
        aviso "clang não encontrado — usará python3 direto (sem nome legível)"
    fi

    # PATH completo para o rclone funcionar dentro do LaunchAgent, se e quando
    # voce configurar o Drive depois.
    BREW_PREFIX=""
    command -v brew >/dev/null 2>&1 && BREW_PREFIX="$(brew --prefix 2>/dev/null || true)"
    if [ -n "$BREW_PREFIX" ]; then
        LAUNCH_PATH="$BREW_PREFIX/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    else
        LAUNCH_PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    fi

    if [ -x "$WRAPPER" ]; then
        PROGRAM_ARGS="<string>$WRAPPER</string>"
    else
        PROGRAM_ARGS="<string>$PYTHON</string>
        <string>server.py</string>"
    fi

    LA_DIR="$HOME/Library/LaunchAgents"
    PLIST="$LA_DIR/com.ticianoflix.plist"
    mkdir -p "$LA_DIR"
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

    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    if ! launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then
        info "bootstrap falhou, tentando launchctl load (macOS antigo)..."
        launchctl load "$PLIST"
    fi
    sleep 2

    if launchctl list 2>/dev/null | grep -q "com.ticianoflix"; then
        ok "Serviço carregado e rodando"
    else
        aviso "Serviço não carregou. Veja o log: tail -50 ~/.cache/ticianoflix/ticianoflix.log"
    fi
else
    # ─── 5b. systemd (Linux) ─────────────────────────────
    SERVICE_DIR="$HOME/.config/systemd/user"
    SERVICE_FILE="$SERVICE_DIR/ticianoflix.service"
    mkdir -p "$SERVICE_DIR"
    cat > "$SERVICE_FILE" <<UNIT
[Unit]
Description=TicianoFlix
Documentation=https://github.com/${REPO}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$PYTHON server.py
WorkingDirectory=$DIR
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
ReadWritePaths=%h/.cache/ticianoflix
ReadWritePaths=%h/.cache/rclone

[Install]
WantedBy=default.target
UNIT
    ok "Serviço systemd criado em $SERVICE_FILE"

    systemctl --user daemon-reload
    systemctl --user enable ticianoflix.service
    systemctl --user restart ticianoflix.service 2>/dev/null || systemctl --user start ticianoflix.service
    loginctl enable-linger 2>/dev/null || true
    sleep 2

    if systemctl --user is-active --quiet ticianoflix.service; then
        ok "Serviço ativo"
    else
        aviso "Serviço não está ativo. Veja: journalctl --user -u ticianoflix -n 40 --no-pager"
    fi
fi

# ─── 6. Esperar o servidor e mostrar o código de instalação ──
info "Aguardando o servidor responder em localhost:${PORTA}..."
RESPONDEU=""
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://localhost:${PORTA}/api/auth/status" 2>/dev/null; then
        RESPONDEU="1"
        break
    fi
    sleep 1
done

URL="http://localhost:${PORTA}"
if [ -z "$RESPONDEU" ]; then
    aviso "O servidor não respondeu em 30s. Veja o log:"
    if [ "$PLATAFORMA" = "macos" ]; then
        echo "  tail -50 ~/.cache/ticianoflix/ticianoflix.log"
    else
        echo "  journalctl --user -u ticianoflix -n 50 --no-pager"
    fi
else
    ok "Servidor no ar em $URL"
    STATUS_JSON="$(curl -fsS "http://localhost:${PORTA}/api/auth/status" 2>/dev/null || true)"
    if echo "$STATUS_JSON" | grep -q '"configured": *true'; then
        ok "Conta já configurada — é só abrir e entrar."
    else
        LOG="$HOME/.cache/ticianoflix/ticianoflix.log"
        CODIGO=""
        for _ in $(seq 1 10); do
            # "|| true" no pipe inteiro, nao so no grep: sob "set -e -o pipefail",
            # o grep BSD do macOS devolve exit 2 (nao 1) quando o arquivo ainda
            # nao existe, e pipefail propaga isso mesmo com o awk tendo saida 0
            # no fim do cano — o "$(...)" abortava o script inteiro bem aqui,
            # antes de qualquer mensagem de erro aparecer. Reproduzido e
            # confirmado num teste isolado antes deste ajuste.
            CODIGO="$(grep -o 'Codigo de instalacao: [0-9]\{6\}' "$LOG" 2>/dev/null | tail -1 | awk '{print $NF}' || true)"
            if [ -n "$CODIGO" ]; then
                break
            fi
            sleep 1
        done
        if [ -n "$CODIGO" ]; then
            echo ""
            echo -e "  ${VERDE}╔════════════════════════════════════════╗${RESET}"
            printf "  ${VERDE}║${RESET}  Código de instalação: ${CIANO}%-6s${RESET}          ${VERDE}║${RESET}\n" "$CODIGO"
            echo -e "  ${VERDE}╚════════════════════════════════════════╝${RESET}"
            echo "  Abra o endereço abaixo e informe esse código para criar a conta admin."
        else
            aviso "Não achei o código de instalação no log."
        fi
    fi
fi

echo ""
echo -e "  ${VERDE}╔══════════════════════════════════════════════╗${RESET}"
echo -e "  ${VERDE}║        Instalação concluída! 🎉               ║${RESET}"
echo -e "  ${VERDE}║                                                ║${RESET}"
printf   "  ${VERDE}║${RESET}  🌐 %-42s${VERDE}║${RESET}\n" "$URL"
echo -e "  ${VERDE}║                                                ║${RESET}"
if [ "$PLATAFORMA" = "macos" ]; then
    echo -e "  ${VERDE}║${RESET}  🔄 launchctl kickstart -k gui/\$(id -u)/com.ticianoflix"
    echo -e "  ${VERDE}║${RESET}  📋 tail -f ~/.cache/ticianoflix/ticianoflix.log"
else
    echo -e "  ${VERDE}║${RESET}  🔄 systemctl --user restart ticianoflix"
    echo -e "  ${VERDE}║${RESET}  📋 journalctl --user -u ticianoflix -f"
fi
echo -e "  ${VERDE}╚══════════════════════════════════════════════╝${RESET}"
echo ""
if [ "$PLATAFORMA" = "macos" ]; then
    aviso "Se o macOS perguntar sobre conexões de entrada, permita — é o servidor na rede local."
fi

# ─── 7. Abrir o navegador ────────────────────────────────
if [ -n "$RESPONDEU" ]; then
    if [ "$PLATAFORMA" = "macos" ]; then
        open "$URL" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 || true
    fi
fi
