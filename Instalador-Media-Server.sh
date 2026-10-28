#!/bin/bash
# 12:00 Media Server — instalador visual para Linux.
# Abre um assistente no navegador; so precisa do Python 3.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    exec python3 instalador/instalador.py "$@"
fi

echo
echo "  Nao achei o Python 3. Instale com:  sudo apt install python3"
echo "  (Fedora: sudo dnf install python3) e rode este arquivo de novo."
echo
exit 1
