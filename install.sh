#!/usr/bin/env bash
# 12:00 Media Server — Instalador (Linux e macOS)
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

REPO="${MEDIA_SERVER_REPO:-${TICIANOFLIX_REPO:-ticianocorral/TicianoFlix}}"
REF="${MEDIA_SERVER_REF:-${TICIANOFLIX_REF:-main}}"
PORTA="${MEDIA_SERVER_PORT:-${TICIANOFLIX_PORT:-9187}}"

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
echo -e "  ${CIANO}🎬 12:00 Media Server — Instalador${RESET}"
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
    DIR="${MEDIA_SERVER_DIR:-${TICIANOFLIX_DIR:-$HOME/Media-Server}}"
    # Instalacao de antes da troca de nome: leva a pasta pro nome novo.
    if [ ! -e "$DIR" ] && [ -d "$HOME/TicianoFlix" ] && [ -z "${MEDIA_SERVER_DIR:-${TICIANOFLIX_DIR:-}}" ]; then
        mv "$HOME/TicianoFlix" "$DIR" && ok "Pasta ~/TicianoFlix movida para $DIR"
    fi
    info "Baixando o 12:00 Media Server (${REPO}@${REF})..."
    mkdir -p "$DIR"
    URL_TARBALL="https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"
    if ! curl -fsSL "$URL_TARBALL" | tar -xz --strip-components=1 -C "$DIR" 2>/tmp/media-server-download.log; then
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
for cand in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9; do
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

# A nuvem (qualquer remote do rclone) e as fontes locais (HD externo,
# pendrive, pasta do computador) sao 100% opcionais e configuraveis pela
# propria interface, em Ajustes.

# ─── 4. rclone (motor da nuvem) ──────────────────────────
# O rclone e o que faz a nuvem funcionar. Instalar aqui deixa o
# botao "Conectar" de Ajustes > Nuvem pronto para uso. Sem sudo: baixa o
# binario oficial para ~/.local/bin, que o usuario enxerga sem senha. So cai no
# gerenciador de pacotes (com sudo) se o download direto falhar.
LOCAL_BIN="$HOME/.local/bin"
RCLONE_BIN="$(command -v rclone 2>/dev/null || true)"
if [ -z "$RCLONE_BIN" ] && [ -x "$LOCAL_BIN/rclone" ]; then
    RCLONE_BIN="$LOCAL_BIN/rclone"
fi

if [ -n "$RCLONE_BIN" ]; then
    ok "rclone ja instalado ($("$RCLONE_BIN" version 2>/dev/null | head -1 | awk '{print $2}' || echo '?'))"
else
    info "Instalando o rclone (motor da nuvem)..."
    case "$(uname -m)" in
        x86_64|amd64)  RCLONE_ARCH="amd64" ;;
        arm64|aarch64) RCLONE_ARCH="arm64" ;;
        armv7l|armv6l) RCLONE_ARCH="arm-v7" ;;
        *)             RCLONE_ARCH="" ;;
    esac
    if [ "$PLATAFORMA" = "macos" ]; then RCLONE_OS="osx"; else RCLONE_OS="linux"; fi
    # Base configuravel: mirrors e proxies de empresa nao precisam de sed no script.
    RCLONE_BASE="${MEDIA_SERVER_RCLONE_BASE:-${TICIANOFLIX_RCLONE_BASE:-https://downloads.rclone.org}}"

    if [ -n "$RCLONE_ARCH" ]; then
        TMP_RCLONE="$(mktemp -d)"
        if curl -fsSL "${RCLONE_BASE}/rclone-current-${RCLONE_OS}-${RCLONE_ARCH}.zip" \
                -o "$TMP_RCLONE/rclone.zip" 2>/dev/null; then
            mkdir -p "$LOCAL_BIN"
            # unzip nem sempre existe (Linux minimo). O zipfile do Python — que
            # ja foi verificado no passo anterior — da conta sem dependencia nova.
            if "$PYTHON" - "$TMP_RCLONE/rclone.zip" "$LOCAL_BIN/rclone" <<'PYRCLONE' 2>/dev/null
import os, shutil, sys, zipfile
zf = zipfile.ZipFile(sys.argv[1])
dest = sys.argv[2]
for nome in zf.namelist():
    if nome.endswith("/rclone") and nome.count("/") == 1:
        with zf.open(nome) as origem, open(dest, "wb") as saida:
            shutil.copyfileobj(origem, saida)
        os.chmod(dest, 0o755)
        sys.exit(0)
sys.exit(1)
PYRCLONE
            then
                RCLONE_BIN="$LOCAL_BIN/rclone"
            fi
        fi
        rm -rf "${TMP_RCLONE:-}"
    fi

    if [ -z "$RCLONE_BIN" ]; then
        aviso "Download direto do rclone nao deu certo — tentando o gerenciador de pacotes."
        if [ "$PLATAFORMA" = "macos" ] && command -v brew >/dev/null 2>&1; then
            brew install rclone || true
        elif command -v apt >/dev/null 2>&1; then
            sudo apt update && sudo apt install -y rclone || true
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y rclone || true
        elif command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --noconfirm rclone || true
        fi
        RCLONE_BIN="$(command -v rclone 2>/dev/null || true)"
    fi

    if [ -n "$RCLONE_BIN" ]; then
        ok "rclone instalado: $("$RCLONE_BIN" version 2>/dev/null | head -1 | awk '{print $2}' || echo '?') ($RCLONE_BIN)"
        # So avisa do PATH quando o binario foi para ~/.local/bin: um rclone
        # vindo do brew/apt ja esta no PATH do terminal por definicao.
        if [ "$RCLONE_BIN" = "$LOCAL_BIN/rclone" ]; then
            case ":$PATH:" in
                *":$LOCAL_BIN:"*) : ;;
                *) aviso "Para o comando 'rclone' funcionar no seu terminal, adicione ~/.local/bin ao PATH."
                   aviso "O 12:00 Media Server ja enxerga o rclone sem isso — e so a linha de comando." ;;
            esac
        fi
    else
        aviso "Nao consegui instalar o rclone agora. A nuvem fica"
        aviso "indisponivel ate instalar — veja https://rclone.org/install/"
        aviso "Fontes locais (HD, pendrive, pastas) funcionam normalmente."
    fi
fi

# ─── 5. Diretórios de cache ──────────────────────────────
mkdir -p "$HOME/.cache/media-server/images"
mkdir -p "$HOME/.cache/media-server/subs"
ok "Diretórios de cache prontos (~/.cache/media-server)"

if [ "$PLATAFORMA" = "macos" ]; then
    # ─── 6a. Wrapper nativo (nome legível no Activity Monitor) ──
    WRAPPER="$DIR/media-server"
    if command -v clang >/dev/null 2>&1; then
        if [ ! -x "$WRAPPER" ] || [ "$DIR/media-server.c" -nt "$WRAPPER" ]; then
            info "Compilando wrapper nativo (media-server)..."
            clang -O2 -o "$WRAPPER" "$DIR/media-server.c" && chmod +x "$WRAPPER" \
                && ok "Wrapper compilado" \
                || aviso "Falha ao compilar wrapper — usará python3 direto"
        else
            ok "Wrapper nativo: $WRAPPER"
        fi
    else
        aviso "clang não encontrado — usará python3 direto (sem nome legível)"
    fi

    # PATH do serviço: o rclone tanto pode estar num prefixo do Homebrew quanto
    # no ~/.local/bin do passo 4 — os dois precisam estar aqui, senão o
    # LaunchAgent sobe sem enxergar o binário.
    BREW_PREFIX=""
    command -v brew >/dev/null 2>&1 && BREW_PREFIX="$(brew --prefix 2>/dev/null || true)"
    if [ -n "$BREW_PREFIX" ]; then
        LAUNCH_PATH="$HOME/.local/bin:$BREW_PREFIX/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    else
        LAUNCH_PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    fi

    if [ -x "$WRAPPER" ]; then
        PROGRAM_ARGS="<string>$WRAPPER</string>"
    else
        PROGRAM_ARGS="<string>$PYTHON</string>
        <string>server.py</string>"
    fi

    LA_DIR="$HOME/Library/LaunchAgents"
    # Servico de antes da troca de nome: para e remove, senao ele segue dono da porta.
    OLD_PLIST="$LA_DIR/com.ticianoflix.plist"
    if [ -f "$OLD_PLIST" ]; then
        launchctl bootout "gui/$(id -u)/com.ticianoflix" 2>/dev/null \
            || launchctl unload "$OLD_PLIST" 2>/dev/null || true
        rm -f "$OLD_PLIST"
        ok "Serviço antigo (com.ticianoflix) removido"
    fi
    PLIST="$LA_DIR/com.mediaserver.plist"
    mkdir -p "$LA_DIR"
    cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mediaserver</string>
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
    <string>$HOME/.cache/media-server/media-server.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.cache/media-server/media-server.log</string>
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

    if launchctl list 2>/dev/null | grep -q "com.mediaserver"; then
        ok "Serviço carregado e rodando"
    else
        aviso "Serviço não carregou. Veja o log: tail -50 ~/.cache/media-server/media-server.log"
    fi
else
    # ─── 6b. systemd (Linux) ─────────────────────────────
    SERVICE_DIR="$HOME/.config/systemd/user"
    SERVICE_FILE="$SERVICE_DIR/media-server.service"
    # Servico de antes da troca de nome: para e remove.
    if [ -f "$SERVICE_DIR/ticianoflix.service" ]; then
        systemctl --user disable --now ticianoflix.service 2>/dev/null || true
        rm -f "$SERVICE_DIR/ticianoflix.service"
        ok "Serviço antigo (ticianoflix) removido"
    fi
    mkdir -p "$SERVICE_DIR"
    cat > "$SERVICE_FILE" <<UNIT
[Unit]
Description=12:00 Media Server
Documentation=https://github.com/${REPO}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$PYTHON server.py
WorkingDirectory=$DIR
# O rclone vem do ~/.local/bin (passo 4) ou do sistema; sem isto o PATH do
# serviço pode não incluir o ~/.local/bin e a nuvem ficaria invisível.
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
ReadWritePaths=%h/.cache/media-server
ReadWritePaths=%h/.cache/rclone
# O cadastro da nuvem (Ajustes > Nuvem) grava os remotes no rclone.conf via
# "rclone config create" — sem esta linha a gravação falharia com o home
# somente-leitura acima.
ReadWritePaths=%h/.config/rclone

[Install]
WantedBy=default.target
UNIT
    ok "Serviço systemd criado em $SERVICE_FILE"

    systemctl --user daemon-reload
    systemctl --user enable media-server.service
    systemctl --user restart media-server.service 2>/dev/null || systemctl --user start media-server.service
    loginctl enable-linger 2>/dev/null || true
    sleep 2

    if systemctl --user is-active --quiet media-server.service; then
        ok "Serviço ativo"
    else
        aviso "Serviço não está ativo. Veja: journalctl --user -u media-server -n 40 --no-pager"
    fi
fi

# ─── 7. Esperar o servidor e mostrar o código de instalação ──
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
        echo "  tail -50 ~/.cache/media-server/media-server.log"
    else
        echo "  journalctl --user -u media-server -n 50 --no-pager"
    fi
else
    ok "Servidor no ar em $URL"
    STATUS_JSON="$(curl -fsS "http://localhost:${PORTA}/api/auth/status" 2>/dev/null || true)"
    if echo "$STATUS_JSON" | grep -q '"configured": *true'; then
        ok "Conta já configurada — é só abrir e entrar."
    else
        LOG="$HOME/.cache/media-server/media-server.log"
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
    echo -e "  ${VERDE}║${RESET}  🔄 launchctl kickstart -k gui/\$(id -u)/com.mediaserver"
    echo -e "  ${VERDE}║${RESET}  📋 tail -f ~/.cache/media-server/media-server.log"
else
    echo -e "  ${VERDE}║${RESET}  🔄 systemctl --user restart media-server"
    echo -e "  ${VERDE}║${RESET}  📋 journalctl --user -u media-server -f"
fi
echo -e "  ${VERDE}╚══════════════════════════════════════════════╝${RESET}"
echo ""
if [ "$PLATAFORMA" = "macos" ]; then
    aviso "Se o macOS perguntar sobre conexões de entrada, permita — é o servidor na rede local."
fi

# ─── 8. Abrir o navegador ────────────────────────────────
if [ -n "$RESPONDEU" ]; then
    if [ "$PLATAFORMA" = "macos" ]; then
        open "$URL" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 || true
    fi
fi
