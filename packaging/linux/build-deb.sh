#!/usr/bin/env bash
# Monta o .deb a partir da pasta gerada pelo PyInstaller.
# Uso: build-deb.sh <pasta-dist/media-server> <versao> <saida-dir> <pasta-icones>
set -euo pipefail
ORIGEM="$1"; VERSAO="$2"; SAIDA="$3"; ICONES="$4"
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
PKG="$(mktemp -d)/media-server_${VERSAO}_amd64"

install -d "$PKG/DEBIAN" "$PKG/opt/media-server" "$PKG/usr/bin" \
    "$PKG/usr/share/applications" "$PKG/etc/xdg/autostart" \
    "$PKG/usr/share/icons/hicolor/scalable/apps" "$PKG/usr/share/icons/hicolor/512x512/apps"
cp -R "$ORIGEM"/. "$PKG/opt/media-server/"
ln -s /opt/media-server/media-server "$PKG/usr/bin/media-server"
cp "$RAIZ/favicon.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/media-server.svg"
cp "$ICONES/icone-512.png" "$PKG/usr/share/icons/hicolor/512x512/apps/media-server.png"

cat > "$PKG/usr/share/applications/media-server.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=12:00 Media Server
Comment=Seus filmes e series, num catalogo so seu
Exec=/opt/media-server/media-server
Icon=media-server
Terminal=false
Categories=AudioVideo;Video;Network;
DESK

# Inicio automatico do servidor ao entrar na sessao grafica.
cat > "$PKG/etc/xdg/autostart/media-server.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=12:00 Media Server (servidor)
Exec=/opt/media-server/media-server --servidor
Icon=media-server
Terminal=false
X-GNOME-Autostart-enabled=true
DESK

cat > "$PKG/DEBIAN/control" <<CTRL
Package: media-server
Version: ${VERSAO}
Section: video
Priority: optional
Architecture: amd64
Maintainer: 12:00 Media Server <noreply@users.noreply.github.com>
Description: 12:00 Media Server
 Servidor de filmes e series auto-hospedado: nuvem (rclone), HD externo e
 pendrive num catalogo no estilo streaming. Python e rclone embutidos.
CTRL

cat > "$PKG/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    pkill -f /opt/media-server/media-server 2>/dev/null || true
fi
exit 0
POSTRM
chmod 755 "$PKG/DEBIAN/postrm"

mkdir -p "$SAIDA"
dpkg-deb --root-owner-group --build "$PKG" "$SAIDA/12-00-media-server_${VERSAO}_amd64.deb"
