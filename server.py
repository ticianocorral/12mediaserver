#!/usr/bin/env python3
"""12:00 Media Server — entrypoint.

O codigo vive no pacote mediaserver/. Este arquivo continua na raiz porque
quatro coisas fixam este caminho: o ExecStart do systemd, o LaunchAgent do
macOS, o .bat do Windows e o wrapper nativo media-server.c — mover o
arquivo quebraria instalacoes existentes.

Empacotado (instaladores nativos, PyInstaller) o mesmo arquivo e o ponto de
entrada do executavel: ver mediaserver/desktop.py.
"""

import sys

if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        from mediaserver.desktop import iniciar
        iniciar()
    else:
        from mediaserver.app import main
        main()
