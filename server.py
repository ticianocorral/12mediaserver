#!/usr/bin/env python3
"""TicianoFlix — entrypoint.

O codigo vive no pacote ticianoflix/. Este arquivo continua na raiz porque
quatro coisas fixam este caminho: o ExecStart do systemd, o LaunchAgent do
macOS, o .bat do Windows e o wrapper nativo ticianoflix-server.c — mover o
arquivo quebraria instalacoes existentes.
"""

from ticianoflix.app import main

if __name__ == "__main__":
    main()
