#!/usr/bin/env bash
# Monta o .dmg a partir do "Media Server.app" gerado pelo PyInstaller.
# Uso: build-dmg.sh <pasta-dist> <versao> <arquitetura> <saida-dir>
set -euo pipefail
DIST="$1"; VERSAO="$2"; ARQ="$3"; SAIDA="$4"
APP="$DIST/Media Server.app"
[ -d "$APP" ] || { echo "nao achei $APP" >&2; exit 1; }

# Sem certificado da Apple o app vai assinado "ad hoc": abre depois de
# "clicar com o botao direito > Abrir" na primeira vez.
codesign --force --deep --sign - "$APP"

RAIZ_DMG="$(mktemp -d)"
cp -R "$APP" "$RAIZ_DMG/"
ln -s /Applications "$RAIZ_DMG/Applications"
cat > "$RAIZ_DMG/LEIA-ME.txt" <<TXT
12:00 Media Server

1. Arraste "Media Server" para a pasta Aplicativos.
2. Abra o app. Na primeira vez o macOS pode avisar que o desenvolvedor nao foi
   verificado: clique com o botao direito no app, escolha Abrir e confirme.
3. O navegador abre sozinho. Crie a conta (o codigo ja vem preenchido) e os perfis.

O servidor roda em segundo plano e inicia com o seu usuario.
Para desinstalar: apague o app e o arquivo ~/Library/LaunchAgents/com.mediaserver.plist
TXT
mkdir -p "$SAIDA"
hdiutil create -volname "Media Server" -srcfolder "$RAIZ_DMG" -ov -format UDZO \
    "$SAIDA/12-00-Media-Server-${VERSAO}-macOS-${ARQ}.dmg"
rm -rf "$RAIZ_DMG"
