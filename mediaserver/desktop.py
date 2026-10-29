"""Modo desktop do app empacotado (instaladores nativos).

O instalador deixa um unico executavel. Ele tem dois jeitos de subir:

  --servidor   roda o servidor (e o que o inicio automatico executa; sem
               janela, com a saida indo para o arquivo de log);
  (sem args)   e o que o atalho do usuario abre: garante que o servidor esteja
               de pe e abre o navegador na pagina do app. Se o servidor ja
               estiver rodando, so abre o navegador.

Rodando do codigo-fonte (python3 server.py) nada disto entra em cena: o
comportamento de sempre continua.
"""

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from .config import CACHE_DIR, PORT, env

NOME = "12:00 Media Server"
ROTULO_MAC = "com.mediaserver"


def _porta():
    try:
        return int(env("PORT") or PORT)
    except ValueError:
        return PORT


def _url():
    return "http://localhost:%d" % _porta()


def servidor_responde(timeout=1.5):
    try:
        urllib.request.urlopen(_url() + "/api/auth/status", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True   # respondeu (mesmo um erro): ha servidor ali
    except Exception:
        return False


def _redirecionar_saida():
    """Sem console (Windows/macOS empacotados) print() falharia: manda tudo
    para o log, o mesmo arquivo que o servico de antes usava."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(CACHE_DIR / "media-server.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = log
    sys.stderr = log


def _iniciar_servidor_desacoplado():
    """Sobe o servidor num processo proprio, que sobrevive ao launcher."""
    cmd = [sys.executable, "--servidor"]
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
        subprocess.Popen(cmd, creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(cmd, start_new_session=True, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def _registrar_inicio_mac():
    """macOS: LaunchAgent (inicia no login e reinicia se cair). Devolve True
    quando o launchd assumiu o servidor."""
    from pathlib import Path
    import plistlib
    la = Path.home() / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    plist = la / (ROTULO_MAC + ".plist")
    dados = {
        "Label": ROTULO_MAC,
        "ProgramArguments": [sys.executable, "--servidor"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
    }
    try:
        atual = plistlib.loads(plist.read_bytes()) if plist.exists() else None
    except Exception:
        atual = None
    if atual == dados:
        return True   # ja registrado e igual: o launchd ja cuida dele
    plist.write_bytes(plistlib.dumps(dados))
    uid = str(os.getuid())
    subprocess.run(["launchctl", "bootout", "gui/%s/%s" % (uid, ROTULO_MAC)],
                   capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", "gui/" + uid, str(plist)],
                       capture_output=True)
    return r.returncode == 0


def abrir():
    """Atalho do usuario: garante o servidor e abre o navegador."""
    if not servidor_responde():
        usou_launchd = sys.platform == "darwin" and _registrar_inicio_mac()
        if not usou_launchd:
            _iniciar_servidor_desacoplado()
        for _ in range(60):
            if servidor_responde():
                break
            time.sleep(0.5)
    webbrowser.open(_url())


def iniciar():
    """Ponto de entrada do executavel empacotado."""
    if "--servidor" in sys.argv[1:]:
        _redirecionar_saida()
        from .app import main
        main()
        return
    abrir()
