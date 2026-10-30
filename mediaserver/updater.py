"""Atualizacao automatica do app empacotado no macOS.

De tempos em tempos consulta a ultima release do GitHub; se houver versao nova,
baixa o .dmg, confere o SHA-256 que o proprio GitHub publica para o arquivo,
troca o "Media Server.app" e reinicia o servidor (o LaunchAgent com KeepAlive
sobe o binario novo). A troca so reinicia quando nao ha ninguem assistindo.

So age no app empacotado (sys.frozen) no macOS: rodando do codigo-fonte ou em
outros sistemas nada acontece. Desliga com MEDIA_SERVER_AUTOUPDATE=0.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from . import __version__
from .config import PORT, env

REPO = env("REPO") or "ticianocorral/12mediaserver"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
APP_NOME = "Media Server.app"
INTERVALO = 6 * 3600     # entre consultas
ATRASO_INICIAL = 120     # deixa o servidor subir antes da primeira consulta
ESPERA_OCIOSO = 300      # entre tentativas de reiniciar enquanto alguem assiste
HOSTS_OK = ("github.com", "objects.githubusercontent.com",
            "release-assets.githubusercontent.com")


def _log(msg):
    print("[12:00 Media Server] Atualizador: %s" % msg, flush=True)


def _versao(texto):
    m = re.match(r"v?(\d+(?:\.\d+)*)", texto or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def _app_instalado():
    """Caminho do .app em execucao, ou None se nao for o app empacotado."""
    if not getattr(sys, "frozen", False) or sys.platform != "darwin":
        return None
    exe = os.path.realpath(sys.executable)
    marca = "/" + APP_NOME + "/"
    i = exe.find(marca)
    return exe[:i + len(marca) - 1] if i >= 0 else None


def _get(url, destino=None):
    host = urllib.parse.urlparse(url).hostname or ""
    if not url.startswith("https://") or not (
            host == "api.github.com" or host in HOSTS_OK):
        raise ValueError("endereco nao permitido: " + url)
    req = urllib.request.Request(url, headers={"User-Agent": "12-00-media-server"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if destino is None:
            return r.read()
        h = hashlib.sha256()
        with open(destino, "wb") as f:
            for bloco in iter(lambda: r.read(1 << 20), b""):
                f.write(bloco)
                h.update(bloco)
        return h.hexdigest()


def _release_nova():
    """(versao, url, sha256) da release mais nova para esta arquitetura, ou None."""
    dados = json.loads(_get(API))
    versao = dados.get("tag_name", "")
    if not _versao(versao) or _versao(versao) <= _versao(__version__):
        return None
    arq = "macOS-arm64.dmg" if platform.machine() == "arm64" else "macOS-x86_64.dmg"
    for a in dados.get("assets", []):
        if a.get("name", "").endswith(arq):
            digest = a.get("digest") or ""
            if not digest.startswith("sha256:"):
                _log("release %s sem SHA-256 publicado; ignorada" % versao)
                return None
            return versao, a["browser_download_url"], digest[7:]
    return None


def _instalar(dmg, app):
    """Troca o app instalado pelo do .dmg. Levanta excecao se algo falhar
    (e nesse caso o app antigo continua no lugar)."""
    pasta = os.path.dirname(app)
    novo = os.path.join(pasta, ".MediaServer-novo.app")
    velho = os.path.join(pasta, ".MediaServer-velho.app")
    montagem = tempfile.mkdtemp(prefix="ms-dmg-")
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noverify",
                    "-mountpoint", montagem, dmg], check=True, capture_output=True)
    try:
        shutil.rmtree(novo, ignore_errors=True)
        shutil.copytree(os.path.join(montagem, APP_NOME), novo, symlinks=True)
    finally:
        subprocess.run(["hdiutil", "detach", "-force", montagem], capture_output=True)
    try:
        subprocess.run(["codesign", "--verify", "--deep", novo],
                       check=True, capture_output=True)
        shutil.rmtree(velho, ignore_errors=True)
        os.rename(app, velho)
        try:
            os.rename(novo, app)
        except OSError:
            os.rename(velho, app)   # desfaz
            raise
    finally:
        shutil.rmtree(novo, ignore_errors=True)
    shutil.rmtree(velho, ignore_errors=True)


def _alguem_assistindo():
    """True se ha conexao ativa no servidor (player, TV, Chromecast)."""
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP:%d-%d" % (PORT, PORT + 1000),
             "-sTCP:ESTABLISHED", "-a", "-p", str(os.getpid())],
            capture_output=True, text=True, timeout=10).stdout
        return len(out.strip().splitlines()) > 1
    except Exception:
        return True   # na duvida, nao derruba


def _ciclo(app):
    nova = _release_nova()
    if not nova:
        return False
    versao, url, sha = nova
    _log("versao %s disponivel (atual %s); baixando..." % (versao, __version__))
    tmp = tempfile.mkdtemp(prefix="ms-update-")
    try:
        dmg = os.path.join(tmp, "app.dmg")
        if _get(url, dmg) != sha:
            _log("SHA-256 nao confere; descartado")
            return False
        _instalar(dmg, app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _log("versao %s instalada; reiniciando quando ninguem estiver assistindo" % versao)
    return True


def _laco():
    app = _app_instalado()
    time.sleep(ATRASO_INICIAL)
    while True:
        try:
            if _ciclo(app):
                while _alguem_assistindo():
                    time.sleep(ESPERA_OCIOSO)
                _log("reiniciando")
                from . import rclone
                rclone.shutdown()
                os._exit(0)   # o launchd (KeepAlive) sobe o binario novo
        except Exception as e:
            _log("falhou (%s); tenta de novo mais tarde" % e)
        time.sleep(INTERVALO)


def iniciar():
    if env("AUTOUPDATE", "1") == "0" or not _app_instalado():
        return
    threading.Thread(target=_laco, name="atualizador", daemon=True).start()
