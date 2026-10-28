"""Descoberta e encerramento de processos por porta.

macOS e Linux: lsof primeiro, fuser como reserva. No macOS o fuser existe mas
nao aceita a sintaxe "porta/tcp" — sai com codigo 0 e stdout vazio, entao nao
serve sozinho.
"""

import subprocess
from pathlib import Path


def _pids_on_port(port):
    """PIDs ouvindo em 'port'. lsof primeiro (macOS e Linux), fuser como
    reserva — no macOS o fuser existe mas nao aceita a sintaxe 'porta/tcp',
    entao ele sai com codigo 0 e stdout vazio e nao serve sozinho."""
    try:
        out = subprocess.run(["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5)
        pids = [p for p in out.stdout.split() if p.strip().isdigit()]
        if pids:
            return pids
    except Exception:
        pass
    try:
        out = subprocess.run(["fuser", f"{port}/tcp"],
                             capture_output=True, text=True, timeout=5)
        return [p for p in out.stdout.split() if p.strip().isdigit()]
    except Exception:
        return []


def _proc_cmdline(pid):
    """Linha de comando de um PID. Usa /proc no Linux e 'ps' no macOS/BSD."""
    proc_file = Path(f"/proc/{pid}/cmdline")
    if proc_file.exists():
        try:
            return " ".join(proc_file.read_text().split("\0"))
        except Exception:
            return ""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except Exception:
        return ""
