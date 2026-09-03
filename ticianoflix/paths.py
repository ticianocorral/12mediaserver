"""Fronteira de caminhos entre o app e o rclone.

O DB e o frontend sempre falam em paths logicos ("/Mediaflix/Acao/Filme") —
LOGICAL_ROOT e so um rotulo interno, nao o nome real de nada no Drive de
ninguem. O rclone pode estar em dois modos:

  escopado  root_folder_id aponta direto pra pasta do acervo, entao "gdrive:"
            JA e a pasta e o prefixo logico nao existe do lado dele —
            LOGICAL_ROOT pode mudar de nome livremente, sem afetar nada aqui
  raiz      modo antigo (anterior a LOGICAL_ROOT virar rotulo neutro),
            "gdrive:" e a raiz do Drive e o prefixo tem que ser o nome real
            da pasta, que e sempre LOGICAL_ROOT_LEGADO — quem esta neste modo
            configurou o rclone antes desta mudanca, entao a pasta real no
            Drive dele nunca foi renomeada

O modo e detectado lendo o rclone.conf uma vez, para que o mesmo codigo
funcione antes e depois de o usuario escopar o remote.
"""

import subprocess
import threading
from pathlib import Path

from .config import LOGICAL_ROOT, LOGICAL_ROOT_LEGADO, RCLONE_REMOTE

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


def remote_configurado():
    """True quando o remote principal existe no rclone.conf.

    Le o arquivo em vez de chamar "rclone listremotes" porque isto roda na
    subida do servidor: um subprocesso a mais atrasaria o boot de todo mundo,
    inclusive de quem nunca vai usar o Drive.

    Na duvida devolve True. Se o rclone.conf existir mas nao der para ler —
    cifrado, por exemplo — e melhor tentar subir o serve e falhar do que negar
    o Drive a quem tem um configurado.
    """
    caminho = rclone_conf_path()
    if not caminho.exists():
        return False
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError:
        return True
    secao = "[" + RCLONE_REMOTE.rstrip(":") + "]"
    return any(linha.strip() == secao for linha in texto.splitlines())


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

    "/Mediaflix/Acao/Filme/x.mkv" -> "Acao/Filme/x.mkv"             (remote escopado)
                                   -> "TicianoFlix/Acao/Filme/x.mkv" (raiz, legado)

    O modo raiz e sempre de quem configurou o rclone antes de LOGICAL_ROOT
    virar um rotulo neutro — a pasta real no Google Drive dele continua com
    o nome antigo, entao e LOGICAL_ROOT_LEGADO que tem que ir pro remote, nao
    o rotulo novo (senao o rclone procura uma pasta "Mediaflix" que nunca
    existiu no Drive de ninguem). O instalador atual so cria remote escopado
    (setup-rclone-seguro.sh), entao ninguem novo cai neste ramo.
    """
    if remote_is_scoped():
        return _strip_logical_root(logical_path)
    resto = _strip_logical_root(logical_path)
    raiz_real = LOGICAL_ROOT_LEGADO.strip("/")
    return raiz_real + ("/" + resto if resto else "")


def rc_remote(logical_path):
    """Path logico -> destino completo pro rclone ("gdrive:Acao/Filme/x.mkv")."""
    return RCLONE_REMOTE + rc(logical_path)


def serve_path(logical_path):
    """Path logico -> path dentro do 'rclone serve http'.

    O serve e sempre montado na pasta TicianoFlix (veja rclone.start_serve),
    entao aqui o prefixo logico sempre sai, independente do modo do remote.
    """
    return _strip_logical_root(logical_path)
