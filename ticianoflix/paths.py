"""Fronteira de caminhos entre o app e o rclone.

O DB e o frontend sempre falam em paths logicos ("/TicianoFlix/Acao/Filme").
O rclone pode estar em dois modos:

  escopado  root_folder_id aponta pra pasta TicianoFlix, entao "gdrive:" JA e a
            pasta e o prefixo /TicianoFlix nao existe do lado dele
  raiz      modo antigo, "gdrive:" e a raiz do Drive e o prefixo e real

O modo e detectado lendo o rclone.conf uma vez, para que o mesmo codigo
funcione antes e depois de o usuario escopar o remote.
"""

import subprocess
import threading
from pathlib import Path

from .config import LOGICAL_ROOT, RCLONE_REMOTE

_remote_scoped = None
_remote_scoped_lock = threading.Lock()


def rclone_conf_path():
    """Caminho do rclone.conf, perguntado ao proprio rclone."""
    try:
        out = subprocess.run(["rclone", "config", "file"],
                             capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            line = line.strip()
            if line and not line.endswith(":"):
                return Path(line)
    except Exception:
        pass
    return Path.home() / ".config" / "rclone" / "rclone.conf"


def remote_is_scoped():
    """True quando o remote principal ja aponta direto pra pasta TicianoFlix."""
    global _remote_scoped
    with _remote_scoped_lock:
        if _remote_scoped is not None:
            return _remote_scoped
        scoped = False
        try:
            section = RCLONE_REMOTE.rstrip(":")
            current = None
            for raw in rclone_conf_path().read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1]
                elif current == section and line.startswith("root_folder_id"):
                    scoped = bool(line.split("=", 1)[1].strip())
        except Exception:
            scoped = False
        _remote_scoped = scoped
        return scoped


def read_remote_conf(section):
    """Campos de uma secao do rclone.conf, sem tokens nem segredos.

    Le o arquivo direto em vez de 'rclone config show' para nao arrastar o
    token pra dentro do processo — o que interessa aqui e so o escopo.
    """
    out = {}
    try:
        current = None
        for raw in rclone_conf_path().read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
            elif current == section and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k in ("scope", "root_folder_id", "client_id", "type"):
                    out[k] = v.strip()
    except Exception:
        pass
    return out


def _strip_logical_root(logical_path):
    p = "/" + str(logical_path).strip("/")
    if p == LOGICAL_ROOT:
        return ""
    if p.startswith(LOGICAL_ROOT + "/"):
        p = p[len(LOGICAL_ROOT):]
    return p.strip("/")


def rc(logical_path):
    """Path logico -> path relativo ao remote, sem barra inicial.

    "/TicianoFlix/Acao/Filme/x.mkv" -> "Acao/Filme/x.mkv"   (remote escopado)
                                    -> "TicianoFlix/Acao/Filme/x.mkv" (raiz)
    """
    if remote_is_scoped():
        return _strip_logical_root(logical_path)
    return ("/" + str(logical_path).strip("/")).strip("/")


def rc_remote(logical_path):
    """Path logico -> destino completo pro rclone ("gdrive:Acao/Filme/x.mkv")."""
    return RCLONE_REMOTE + rc(logical_path)


def serve_path(logical_path):
    """Path logico -> path dentro do 'rclone serve http'.

    O serve e sempre montado na pasta TicianoFlix (veja rclone.start_serve),
    entao aqui o prefixo logico sempre sai, independente do modo do remote.
    """
    return _strip_logical_root(logical_path)
