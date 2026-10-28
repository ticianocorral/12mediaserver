"""Fronteira de caminhos entre o app e o rclone.

O DB e o frontend sempre falam em paths logicos ("/Mediaflix/Acao/Filme") —
LOGICAL_ROOT e so um rotulo interno, nao o nome real de nada na nuvem de
ninguem. Qual remote usar (e a pasta de dentro dele) vem do nuvem.json,
escolhido pelo wizard da interface (veja nuvem.py), entao o prefixo logico
sempre sai na hora de falar com o rclone: renomear a marca no app nunca
muda nada do lado de la.
"""

import json
import subprocess
import threading
from pathlib import Path

from .config import BACKUP_FOLDER, BACKUP_FOLDER_LEGADO, NUVEM_PATH
from . import branding as _branding

_nuvem_cache_lock = threading.Lock()
_nuvem_cache = None


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


def _conexao():
    """(remote, pasta) cadastrados pelo wizard, com cache de processo."""
    global _nuvem_cache
    with _nuvem_cache_lock:
        if _nuvem_cache is not None:
            return _nuvem_cache
    try:
        data = json.loads(NUVEM_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    val = (str(data.get("remote") or "").strip(),
           str(data.get("pasta") or "").strip("/"))
    with _nuvem_cache_lock:
        _nuvem_cache = val
    return val


def reset_nuvem_cache():
    """Invalida a conexão em cache. Chamado pelo nuvem.py apos gravar/remover."""
    global _nuvem_cache
    with _nuvem_cache_lock:
        _nuvem_cache = None


def remote_atual():
    """Nome do remote em uso ("b2", "gdrive"...), ou vazio sem nuvem configurada."""
    return _conexao()[0]


def prefixo_nuvem():
    """Pasta de dentro do remote onde mora o acervo ("acervo/" ou "")."""
    pasta = _conexao()[1]
    return pasta + "/" if pasta else ""


def remote_configurado():
    """True quando o wizard cadastrou um remote e ele existe no rclone.conf.

    Le o arquivo em vez de chamar "rclone listremotes" porque isto roda na
    subida do servidor: um subprocesso a mais atrasaria o boot de todo mundo,
    inclusive de quem nunca configurou a nuvem.

    Na duvida devolve True. Se o rclone.conf existir mas nao der para ler —
    cifrado, por exemplo — e melhor tentar subir o serve e falhar do que
    negar a nuvem a quem tem um remote configurado.
    """
    remote = remote_atual()
    if not remote:
        return False
    caminho = rclone_conf_path()
    if not caminho.exists():
        return False
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError:
        return True
    secao = "[" + remote + "]"
    return any(linha.strip() == secao for linha in texto.splitlines())


def read_remote_conf(section):
    """Campos de uma secao do rclone.conf, sem segredos.

    Le o arquivo direto em vez de 'rclone config show' para nao arrastar
    segredo pra dentro do processo — o que interessa aqui e so identificar o
    remote (tipo e campos nao-sensiveis).
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
                if k in ("type", "account", "bucket", "remote"):
                    out[k] = v.strip()
    except Exception:
        pass
    return out


def destino_backup():
    """Destino raiz dos backups no remote conectado:
    "b2:acervo/Media Server Backups" (o handler acrescenta /arquivo.zip)."""
    destino = remote_atual() + ":" + prefixo_nuvem() + BACKUP_FOLDER
    return destino


def destinos_backup():
    """Pasta de backups atual e a de antes da troca de nome, nessa ordem: quem
    ja tinha backups na nuvem continua conseguindo restaurar."""
    base = remote_atual() + ":" + prefixo_nuvem()
    return [base + BACKUP_FOLDER, base + BACKUP_FOLDER_LEGADO]


def _strip_logical_root(logical_path):
    raiz = _branding.logical_root()
    p = "/" + str(logical_path).strip("/")
    if p == raiz:
        return ""
    if p.startswith(raiz + "/"):
        p = p[len(raiz):]
    return p.strip("/")


def rc(logical_path):
    """Path logico -> path relativo ao remote, sem barra inicial.

    "/Mediaflix/Acao/Filme/x.mkv" -> "Acao/Filme/x.mkv"

    O serve e o remote sempre apontam para a pasta cadastrada no wizard,
    entao o prefixo logico nunca existe do lado do rclone.
    """
    return _strip_logical_root(logical_path)


def rc_remote(logical_path):
    """Path logico -> destino completo pro rclone ("b2:acervo/Acao/...")."""
    return remote_atual() + ":" + prefixo_nuvem() + rc(logical_path)


def serve_path(logical_path):
    """Path logico -> path dentro do 'rclone serve http'.

    O serve e sempre montado na pasta cadastrada no wizard (veja
    rclone.start_serve), entao aqui o prefixo logico sempre sai.
    """
    return _strip_logical_root(logical_path)
