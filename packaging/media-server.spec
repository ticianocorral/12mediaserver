# -*- mode: python ; coding: utf-8 -*-
# Empacota o 12:00 Media Server com PyInstaller (pasta, nao arquivo unico: abre
# mais rapido e nao desempacota nada a cada subida).
#
# Variaveis de ambiente (preenchidas pelo workflow):
#   RCLONE_BIN   caminho do binario do rclone a embutir (pasta bin/ do pacote)
#   ICONES       pasta gerada por packaging/gerar_icones.py
#   VERSAO       versao do app (ex.: 1.26.0)
import os
import sys

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
VERSAO = os.environ.get("VERSAO", "0.0.0")
RCLONE = os.environ["RCLONE_BIN"]
ICONES = os.environ.get("ICONES", "")

datas = [
    (os.path.join(RAIZ, "index.html"), "."),
    (os.path.join(RAIZ, "favicon.svg"), "."),
    (os.path.join(RAIZ, "favicon.ico"), "."),
    (os.path.join(RAIZ, "static"), "static"),
]
binaries = [(RCLONE, "bin")]

a = Analysis(
    [os.path.join(RAIZ, "server.py")],
    pathex=[RAIZ],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["tkinter", "unittest", "pydoc"],
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    icone = os.path.join(ICONES, "app.ico")
elif sys.platform == "darwin":
    icone = os.path.join(ICONES, "app.icns")
else:
    icone = None
if icone and not os.path.exists(icone):
    icone = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="media-server",
    console=False,      # sem janela de console no Windows; o log vai para o arquivo
    icon=icone,
)
coll = COLLECT(exe, a.binaries, a.datas, name="media-server")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Media Server.app",
        icon=icone,
        bundle_identifier="com.mediaserver.app",
        info_plist={
            "CFBundleName": "Media Server",
            "CFBundleDisplayName": "12:00 Media Server",
            "CFBundleShortVersionString": VERSAO,
            "CFBundleVersion": VERSAO,
            "LSUIElement": True,   # servidor em segundo plano: sem icone no Dock
            "NSHighResolutionCapable": True,
        },
    )
