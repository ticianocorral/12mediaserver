"""Tudo que fala com o rclone: comandos, cache VFS e o processo do serve.

O `rclone serve http` e montado sempre na pasta TicianoFlix, nunca na raiz do
Drive — veja start_rclone_serve. Combinado com --read-only, a porta local nao
le nem escreve nada fora do catalogo.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .config import (
    CACHED_FILES_PATH, LOGICAL_ROOT, RCLONE_GUI_ENABLED,
    RCLONE_SERVE_PORT, RCLONE_WEBGUI_PORT,
)
from .paths import rc_remote as _rc_remote, read_remote_conf
from .procutil import _pids_on_port, _proc_cmdline

rclone_server_proc = None


rclone_webgui_proc = None


_webgui_credentials = {"user": "", "pass": ""}


_webgui_lock = threading.Lock()


_rclone_serve_lock = threading.Lock()


# Conjunto de arquivos 100% cacheados no VFS (persistido em JSON).
_cached_files_lock = threading.Lock()


_cached_files = set()


def _vfs_segment_match(entry_str, needle):
    """Casa apenas em fronteira de componente de caminho. Impede que um
    fragmento curto ou vazio vire curinga e apague o cache inteiro."""
    n = needle.replace(os.sep, "/").strip("/")
    if not n:
        return False
    return ("/" + n + "/") in (entry_str.replace(os.sep, "/") + "/")


def _norm_cache_path(file_path):
    """Normalize a file path for cache bookkeeping.

    Streaming marks files with the URL path (leading slash); the cache manager
    and manual downloads build paths without it. Normalize to a single canonical
    form (no leading/trailing slashes) so lookups always match.
    """
    return "/".join(part for part in str(file_path).split("/") if part)


# Rehidrata o conjunto do disco na carga do modulo.
if CACHED_FILES_PATH.exists():
    try:
        _cached_files = set(
            _norm_cache_path(p) for p in json.loads(CACHED_FILES_PATH.read_text()))
    except Exception:
        _cached_files = set()


def _mark_file_cached(file_path):
    """Register a file as fully cached in rclone VFS.
    Batches writes to disk — at most one write per 5 seconds."""
    file_path = _norm_cache_path(file_path)
    with _cached_files_lock:
        _cached_files.add(file_path)
    # Batch write: persist at most once per 5s
    _schedule_cached_files_save()


_save_timer = None


_save_timer_lock = threading.Lock()


def _schedule_cached_files_save():
    global _save_timer
    with _save_timer_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        _save_timer = threading.Timer(5.0, _flush_cached_files)
        _save_timer.daemon = True
        _save_timer.start()


def _flush_cached_files():
    """Persist the cached_files set to disk."""
    with _cached_files_lock:
        CACHED_FILES_PATH.write_text(json.dumps(list(_cached_files)))


def _is_file_cached(file_path):
    file_path = _norm_cache_path(file_path)
    with _cached_files_lock:
        return file_path in _cached_files


def run_rclone_cmd(args, timeout=60):
    """Run an rclone command and return parsed JSON output."""
    cmd = ["rclone"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        if result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"output": result.stdout.strip()}
        return {"output": ""}
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out"}
    except FileNotFoundError:
        return {"error": "rclone not found. Please install rclone."}


def list_directory_raw(path):
    """List directory contents via rclone lsjson (uncached)."""
    return run_rclone_cmd(["lsjson", _rc_remote(path)])


def _urlopen_ok(url, timeout=2):
    """True se a URL responder HTTP sem erro."""
    try:
        import urllib.request as _ur
        _ur.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def _kill_rclone_on_port(port):
    """Best-effort: mata processos rclone ouvindo em 'port'.

    So mata se a linha de comando do PID mencionar rclone — nunca derruba um
    processo alheio que por acaso esteja na porta."""
    for pid in _pids_on_port(port):
        try:
            if "rclone" in _proc_cmdline(pid):
                os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass


def start_rclone_serve():
    """Garante que o 'rclone serve http' esteja rodando na porta 18082.

    Retorna o Popen se este processo iniciou, "external" se já havia um
    servidor respondendo com o Drive acessível, ou None em caso de falha.
    """
    global rclone_server_proc
    with _rclone_serve_lock:
        # Já temos um processo vivo iniciado por nós?
        if rclone_server_proc is not None and rclone_server_proc.poll() is None:
            return rclone_server_proc

        # Já existe um serve respondendo (ex.: iniciado externamente)?
        try:
            import urllib.request as ureq_check
            ureq_check.urlopen(f"http://localhost:{RCLONE_SERVE_PORT}/", timeout=2)
            try:
                ureq_check.urlopen(f"http://localhost:{RCLONE_SERVE_PORT}/?format=json", timeout=5)
                print(f"[TicianoFlix] rclone serve already running on localhost:{RCLONE_SERVE_PORT}", flush=True)
                return "external"
            except Exception:
                print(f"[TicianoFlix] rclone serve responde mas o Drive está inacessível — tentando reiniciar", flush=True)
                _kill_rclone_on_port(RCLONE_SERVE_PORT)
                time.sleep(1)
        except Exception:
            pass

        try:
            proc = subprocess.Popen(
                # Montado na pasta TicianoFlix, nunca na raiz do Drive: mesmo
                # com o remote ainda apontando pra raiz, o serve so expoe o
                # catalogo. Combinado com --read-only, a porta 18082 nao le
                # nem escreve nada fora dali.
                ["rclone", "serve", "http", _rc_remote(LOGICAL_ROOT),
                 "--addr", f"127.0.0.1:{RCLONE_SERVE_PORT}",
                 "--read-only",
                 "--drive-chunk-size", "128M",
                 "--buffer-size", "512M",
                 "--vfs-cache-mode", "full",
                 "--vfs-cache-max-age", "720h",
                 "--vfs-read-chunk-size", "4M",
                 "--vfs-read-chunk-size-limit", "off",
                 "--vfs-read-ahead", "512M",
                 "--log-level", "ERROR"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            rclone_server_proc = proc
            print(f"[TicianoFlix] Starting rclone serve http on localhost:{RCLONE_SERVE_PORT}...", end=" ", flush=True)

            # Wait for rclone serve to be ready (up to 25s — cold start pode
            # demorar enquanto o rclone inicializa o VFS e conecta no Drive)
            for _ in range(25):
                time.sleep(1)
                if _urlopen_ok(f"http://localhost:{RCLONE_SERVE_PORT}/", timeout=2):
                    print("ready!", flush=True)
                    break
            else:
                print("timed out, streams may use fallback", flush=True)
            return proc
        except FileNotFoundError:
            print("[TicianoFlix] WARNING: rclone not found, streams will use fallback method", flush=True)
            return None
        except Exception as e:
            print(f"[TicianoFlix] WARNING: could not start rclone serve: {e}", flush=True)
            return None


def restart_rclone_serve():
    """Mata o serve atual (se houver) e sobe um novo. Usado após configurar o remote."""
    global rclone_server_proc
    if rclone_server_proc is not None and rclone_server_proc.poll() is None:
        try:
            rclone_server_proc.terminate()
            rclone_server_proc.wait(timeout=5)
        except Exception:
            try:
                rclone_server_proc.kill()
            except Exception:
                pass
    rclone_server_proc = None
    _kill_rclone_on_port(RCLONE_SERVE_PORT)
    time.sleep(1)

    proc = start_rclone_serve()
    if proc is None:
        return {"status": "error", "error": "Não foi possível iniciar o rclone serve (rclone está instalado?)."}
    return {"status": "ok", "serve_running": True, "external": proc == "external"}


def start_rclone_webgui():
    """Sobe o 'rclone rcd --rc-web-gui' (configurador oficial do rclone) na porta 5572."""
    global rclone_webgui_proc
    if not RCLONE_GUI_ENABLED:
        return {"status": "error", "error": (
            "Configurador desativado por padrao. Inicie o TicianoFlix com "
            "TICIANOFLIX_RCLONE_GUI=1 e abra pelo proprio computador.")}
    with _webgui_lock:
        if rclone_webgui_proc is not None and rclone_webgui_proc.poll() is None:
            return {
                "status": "ok", "running": True, "local_only": True,
                "url": f"http://127.0.0.1:{RCLONE_WEBGUI_PORT}/",
            }
        # Sem usuario/senha: a GUI so escuta em 127.0.0.1, entao nao ha
        # credencial para vazar por HTTP.
        _webgui_credentials["user"] = ""
        _webgui_credentials["pass"] = ""
        try:
            proc = subprocess.Popen(
                ["rclone", "rcd",
                 "--rc-web-gui",
                 "--rc-web-gui-no-open-browser",
                 "--rc-addr", f"127.0.0.1:{RCLONE_WEBGUI_PORT}",
                 "--rc-no-auth"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return {"status": "error", "error": "rclone não está instalado."}
        rclone_webgui_proc = proc

        # Espera o rcd responder (primeira execução pode baixar os assets da GUI)
        for _ in range(40):
            time.sleep(0.5)
            if proc.poll() is not None:
                break
            if _urlopen_ok(f"http://127.0.0.1:{RCLONE_WEBGUI_PORT}/", timeout=2):
                break
        if proc.poll() is not None:
            return {"status": "error", "error": f"rclone rcd encerrou com código {proc.returncode}."}
        return {
            "status": "ok", "running": True, "local_only": True,
            "url": f"http://127.0.0.1:{RCLONE_WEBGUI_PORT}/",
        }


def stop_rclone_webgui():
    """Encerra o rclone rcd (web GUI), se estiver rodando."""
    global rclone_webgui_proc
    with _webgui_lock:
        if rclone_webgui_proc is not None and rclone_webgui_proc.poll() is None:
            try:
                rclone_webgui_proc.terminate()
                rclone_webgui_proc.wait(timeout=5)
            except Exception:
                try:
                    rclone_webgui_proc.kill()
                except Exception:
                    pass
        rclone_webgui_proc = None
    return {"status": "ok", "running": False}


def audit_drive_access():
    """Quanto do Google Drive o TicianoFlix alcanca hoje.

    Por padrao o `rclone config` cria o remote com scope "drive": leitura E
    escrita no Drive inteiro. O app so precisa ler uma pasta. Isto e o que o
    painel usa para avisar quando o acesso esta mais largo que o necessario.
    """
    main = read_remote_conf("gdrive")
    backup = read_remote_conf("gdrive_backup")
    scope = main.get("scope", "")
    somente_leitura = scope in ("drive.readonly", "drive.metadata.readonly")
    escopado = bool(main.get("root_folder_id"))

    if not main:
        nivel, resumo = "desconhecido", "Nao foi possivel ler o rclone.conf."
    elif somente_leitura and escopado:
        nivel, resumo = "ok", "Acesso minimo: so leitura, so a pasta TicianoFlix."
    elif somente_leitura:
        nivel, resumo = "atencao", ("So leitura, mas enxerga o Drive inteiro. "
                                    "Falta escopar na pasta TicianoFlix.")
    elif escopado:
        nivel, resumo = "atencao", ("Limitado a pasta TicianoFlix, mas ainda "
                                    "pode ESCREVER nela.")
    else:
        nivel, resumo = "risco", ("O TicianoFlix pode LER E APAGAR qualquer "
                                  "arquivo do seu Google Drive.")

    return {
        "nivel": nivel,                    # ok | atencao | risco | desconhecido
        "resumo": resumo,
        "scope": scope or None,
        "somente_leitura": somente_leitura,
        "escopado": escopado,
        "backup_remote": bool(backup),
        "backup_scope": backup.get("scope"),
        # O client_id compartilhado do rclone esta sendo aposentado em 2026.
        "backup_client_proprio": bool(backup.get("client_id")),
        "comando": "./setup-rclone-seguro.sh",
    }


def get_rclone_status():
    """Status completo do rclone para o modal da UI."""
    status = {
        "installed": False,
        "version": None,
        "remote_configured": False,
        "remote_ok": False,
        "remote_error": None,
        "serve_running": False,
        "webgui": {"running": False, "port": RCLONE_WEBGUI_PORT,
                   "enabled": RCLONE_GUI_ENABLED},
    }
    # Instalado? Versão?
    try:
        res = subprocess.run(["rclone", "version"], capture_output=True, text=True, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            status["installed"] = True
            status["version"] = res.stdout.strip().splitlines()[0]
    except Exception:
        pass

    if not status["installed"]:
        return status

    # Remote gdrive: configurado?
    try:
        res = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True, timeout=15)
        remotes = res.stdout.strip().splitlines()
        status["remote_configured"] = "gdrive:" in remotes
    except Exception:
        status["remote_error"] = "Falha ao listar remotes"

    # Remote acessível (autenticação OK)?
    if status["remote_configured"]:
        try:
            res = subprocess.run(["rclone", "lsd", "gdrive:", "--max-depth", "1"],
                                 capture_output=True, text=True, timeout=20)
            status["remote_ok"] = res.returncode == 0
            if not status["remote_ok"]:
                lines = [l for l in res.stderr.strip().splitlines() if l.strip()]
                status["remote_error"] = lines[-1] if lines else "Falha na conexão"
        except subprocess.TimeoutExpired:
            status["remote_error"] = "Timeout ao testar conexão"
        except Exception as e:
            status["remote_error"] = str(e)

    # Quanto do Drive o app alcanca?
    status["acesso"] = audit_drive_access()

    # Serve de streaming ativo?
    status["serve_running"] = _urlopen_ok(f"http://localhost:{RCLONE_SERVE_PORT}/", timeout=2)

    # Web GUI ativa?
    if rclone_webgui_proc is not None:
        status["webgui"]["running"] = rclone_webgui_proc.poll() is None
        if status["webgui"]["running"]:
            status["webgui"]["url"] = f"http://127.0.0.1:{RCLONE_WEBGUI_PORT}/"
            status["webgui"]["local_only"] = True
    return status


def shutdown():
    """Encerra os processos do rclone que subimos. Chamado no fim do main().

    Vive aqui, e nao no server.py, porque start_rclone_serve rebinda estes
    nomes via `global` — quem importasse os handles ficaria com o valor de
    antes do serve subir.
    """
    global rclone_server_proc, rclone_webgui_proc
    if rclone_server_proc is not None and hasattr(rclone_server_proc, "poll") \
            and rclone_server_proc.poll() is None:
        rclone_server_proc.terminate()
        try:
            rclone_server_proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            rclone_server_proc.kill()
            rclone_server_proc.wait(timeout=1)
    if rclone_webgui_proc is not None and rclone_webgui_proc.poll() is None:
        rclone_webgui_proc.terminate()
