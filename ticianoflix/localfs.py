"""Listagem de uma pasta local no mesmo formato do `rclone lsjson`.

O motor de indexacao do scanner nasceu lendo a saida do rclone. Em vez de
duplica-lo para o disco, esta camada fina devolve entradas com as mesmas chaves
(Path, Name, Size, ModTime, IsDir, MimeType, ID) — assim HD externo, pendrive e
pasta do computador passam pelo mesmo diff incremental que o Drive.
"""

import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path

# Teto de profundidade relativa a raiz da fonte. A estrutura util e
# Genero/Filme/arquivo (3 niveis); o resto e rede de seguranca contra uma pasta
# escolhida por engano com uma arvore gigante.
MAX_DEPTH = 6

# Lixo de sistema que aparece em pendrive e HD externo formatado em qualquer SO.
SKIP_NAMES = {
    ".Trashes", ".Trash", ".Spotlight-V100", ".fseventsd", ".TemporaryItems",
    ".DocumentRevisions-V100", ".DS_Store", ".AppleDouble", "@eaDir",
    "System Volume Information", "$RECYCLE.BIN", "RECYCLER",
    "lost+found", "#recycle",
}


def _mod_time(st):
    """mtime em RFC3339 UTC.

    O scanner detecta mudanca comparando esta string com a gravada no banco,
    entao o que importa e ser estavel entre dois scans do mesmo arquivo.
    """
    try:
        return datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(
            timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return ""


def _skip(name):
    return name in SKIP_NAMES or name.startswith(".")


def list_tree(root):
    """Varre `root` e devolve as entradas em formato lsjson.

    Nao segue symlink de diretorio (evita loop e vazamento pra fora da fonte) e
    ignora o que nao consegue ler, em vez de abortar a varredura inteira.
    """
    root = Path(root)
    entries = []
    # Pilha em vez de recursao: uma arvore funda nao derruba o scan.
    stack = [(root, "", 0)]
    while stack:
        current, rel_prefix, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                children = sorted(it, key=lambda e: e.name)
        except (OSError, PermissionError):
            continue

        for entry in children:
            name = entry.name
            if _skip(name):
                continue
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            if is_dir:
                entries.append({
                    "Path": rel,
                    "Name": name,
                    "Size": -1,
                    "MimeType": "inode/directory",
                    "ModTime": _mod_time(st),
                    "IsDir": True,
                    "ID": "",
                })
                if depth + 1 < MAX_DEPTH:
                    stack.append((Path(entry.path), rel, depth + 1))
                continue

            if entry.is_symlink():
                # Arquivo apontando pra fora da fonte burlaria o confinamento
                # de sources.local_real_path na hora de servir.
                continue

            mime, _ = mimetypes.guess_type(name)
            entries.append({
                "Path": rel,
                "Name": name,
                "Size": st.st_size,
                "MimeType": mime or "application/octet-stream",
                "ModTime": _mod_time(st),
                "IsDir": False,
                "ID": "",
            })
    return entries


def read_bytes(path, max_bytes):
    """Le no maximo max_bytes de um arquivo local. None se falhar ou estourar."""
    try:
        p = Path(path)
        if p.stat().st_size > max_bytes:
            return None
        with open(p, "rb") as f:
            return f.read(max_bytes + 1)
    except OSError:
        return None
