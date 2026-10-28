#!/usr/bin/env bash
# 12:00 Media Server — compila o wrapper nativo do macOS.
# O wrapper dá nome legível ao processo no Activity Monitor / Login Items
# (em vez de "python3") e propaga sinais para o servidor python filho.
# Compatível com bash 3.2 (nativo do macOS).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/media-server.c"
BIN="$DIR/media-server"

if [ ! -f "$SRC" ]; then
    echo "✗ $SRC não encontrado. Rode este script dentro da pasta do 12:00 Media Server."
    exit 1
fi

if ! command -v clang >/dev/null 2>&1; then
    echo "✗ clang não encontrado. Instale as Command Line Tools: xcode-select --install"
    exit 1
fi

clang -O2 -o "$BIN" "$SRC"
chmod +x "$BIN"
echo "✓ Wrapper compilado: $BIN"
echo "  (processo aparecerá como 'media-server' no Monitor de Atividade)"
