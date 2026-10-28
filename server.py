#!/usr/bin/env python3
"""12:00 Media Server — entrypoint.

O codigo vive no pacote mediaserver/. Este arquivo continua na raiz porque
quatro coisas fixam este caminho: o ExecStart do systemd, o LaunchAgent do
macOS, o .bat do Windows e o wrapper nativo media-server.c — mover o
arquivo quebraria instalacoes existentes.
"""

from mediaserver.app import main

if __name__ == "__main__":
    main()
