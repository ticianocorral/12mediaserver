#!/usr/bin/env bash
# TicianoFlix — compila o wrapper nativo do macOS.
# O wrapper dá nome legível ao processo no Activity Monitor / Login Items
# (em vez de "python3") e propaga sinais para o servidor python filho.
# Compatível com bash 3.2 (nativo do macOS).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/ticianoflix-server.c"
BIN="$DIR/ticianoflix-server"

if [ ! -f "$SRC" ]; then
    echo "✗ $SRC não encontrado. Rode este script dentro da pasta do TicianoFlix."
    exit 1
fi

if ! command -v clang >/dev/null 2>&1; then
    echo "✗ clang não encontrado. Instale as Command Line Tools: xcode-select --install"
    exit 1
fi

clang -O2 -o "$BIN" "$SRC"
chmod +x "$BIN"
echo "✓ Wrapper compilado: $BIN"
echo "  (processo aparecerá como 'ticianoflix-server' no Monitor de Atividade)"
