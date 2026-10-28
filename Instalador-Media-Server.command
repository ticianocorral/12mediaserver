#!/bin/bash
# 12:00 Media Server — instalador visual para macOS (duplo clique).
# Abre um assistente no navegador; so precisa do Python 3 (o do macOS serve).
cd "$(dirname "$0")" || exit 1

for PY in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do
    if command -v "$PY" >/dev/null 2>&1; then
        exec "$PY" instalador/instalador.py "$@"
    fi
done

echo
echo "  Nao achei o Python 3. Instale em https://www.python.org/downloads/"
echo "  (ou rode: xcode-select --install) e abra este arquivo de novo."
echo
read -r -p "  Enter para fechar..." _
