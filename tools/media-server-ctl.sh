#!/usr/bin/env bash
# 12:00 Media Server — controle pelo terminal (macOS).
#   media-server-ctl start | stop | restart | status | logs | remove [--yes] [--manter-dados]
# Compatível com bash 3.2 (nativo do macOS).
set -uo pipefail

ROTULO="com.mediaserver"
ROTULO_MDNS="com.mediaserver.mdns"
LA_DIR="$HOME/Library/LaunchAgents"
PLIST="$LA_DIR/$ROTULO.plist"
PLIST_MDNS="$LA_DIR/$ROTULO_MDNS.plist"
APP="/Applications/Media Server.app"
DADOS="$HOME/.cache/media-server"
LOG="$DADOS/media-server.log"
DOMINIO="gui/$(id -u)"

carregado() { launchctl print "$DOMINIO/$1" >/dev/null 2>&1; }

iniciar() {
    if [ ! -f "$PLIST" ]; then
        echo "✗ Serviço não instalado ($PLIST não existe). Rode o instalador."
        exit 1
    fi
    if carregado "$ROTULO"; then
        launchctl kickstart "$DOMINIO/$ROTULO" >/dev/null 2>&1
    else
        launchctl bootstrap "$DOMINIO" "$PLIST" || { echo "✗ Falha ao carregar o serviço"; exit 1; }
    fi
    [ -f "$PLIST_MDNS" ] && ! carregado "$ROTULO_MDNS" && launchctl bootstrap "$DOMINIO" "$PLIST_MDNS" 2>/dev/null
    sleep 2
    status
}

parar() {
    # bootout (não kill): com KeepAlive o launchd subiria o processo de novo.
    for r in "$ROTULO" "$ROTULO_MDNS"; do
        carregado "$r" && launchctl bootout "$DOMINIO/$r" 2>/dev/null
    done
    echo "✓ Servidor parado (volta a ligar no próximo login ou com: $(basename "$0") start)"
}

reiniciar() { parar; iniciar; }

status() {
    if ! carregado "$ROTULO"; then
        echo "● Parado (serviço não carregado)"
        return 1
    fi
    local pid
    pid="$(launchctl print "$DOMINIO/$ROTULO" 2>/dev/null | awk '/^[[:space:]]*pid = /{print $3; exit}')"
    if [ -n "$pid" ]; then
        echo "● Rodando (PID $pid)"
        lsof -a -p "$pid" -iTCP -sTCP:LISTEN -P -n 2>/dev/null | awk 'NR>1{print "  porta " $9}'
    else
        echo "● Serviço carregado, mas o processo não está de pé (caindo ao iniciar?)"
        echo "  Veja o log: $(basename "$0") logs"
        return 1
    fi
}

logs() { tail -n 60 -f "$LOG"; }

remover() {
    local sim=0 manter=0 a
    for a in "$@"; do
        case "$a" in
            --yes|-y) sim=1 ;;
            --manter-dados) manter=1 ;;
        esac
    done
    echo "Vai remover:"
    echo "  - serviço ($PLIST e o do mDNS)"
    echo "  - app ($APP)"
    [ "$manter" -eq 0 ] && echo "  - dados e cache ($DADOS: contas, progresso, fontes, banco)"
    if [ "$sim" -eq 0 ]; then
        printf "Confirma? [s/N] "
        read -r r
        case "$r" in s|S|sim|SIM) ;; *) echo "Cancelado."; exit 0 ;; esac
    fi
    parar >/dev/null
    rm -f "$PLIST" "$PLIST_MDNS"
    [ -d "$APP" ] && rm -rf "$APP"
    [ "$manter" -eq 0 ] && rm -rf "$DADOS"
    echo "✓ 12 Media Server removido."
}

case "${1:-}" in
    start)   iniciar ;;
    stop)    parar ;;
    restart) reiniciar ;;
    status)  status ;;
    logs)    logs ;;
    remove)  shift; remover "$@" ;;
    *)
        echo "Uso: $(basename "$0") {start|stop|restart|status|logs|remove [--yes] [--manter-dados]}"
        exit 1 ;;
esac
