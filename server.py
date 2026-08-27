#!/usr/bin/env python3
"""
TicianoFlix Server - Netflix-style Google Drive movie player powered by rclone
with SQLite caching for instant browsing.
"""

import http.server
import json
import os
import subprocess
import urllib.parse
import urllib.request
import urllib.error
import mimetypes
import socket
import ssl
import threading
import sys
import signal
import sqlite3
import base64
import hashlib
import hmac
import secrets
import re
import time
import shutil
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

HOST = "0.0.0.0"
PORT = 9187
HTTPS_PORT_BASE = 9443
RCLONE_REMOTE = "gdrive:"
# Remote separado só para o backup. O remote principal é somente-leitura
# (scope drive.readonly), então a escrita precisa de um token próprio com
# scope drive.file — que enxerga apenas arquivos criados pelo proprio app.
RCLONE_BACKUP_REMOTE = "gdrive_backup:"
BACKUP_FOLDER = "TicianoFlix Backups"
RCLONE_SERVE_PORT = 18082
# Pasta lógica que o DB e o frontend usam. Quando o remote esta escopado via
# root_folder_id, esse prefixo nao existe do lado do rclone — veja _rc().
LOGICAL_ROOT = "/TicianoFlix"
FRONTEND_PATH = Path(__file__).parent / "index.html"
# Cache goes to user's home (writable even inside AppImage)
_cache_home = Path.home() / ".cache" / "ticianoflix"
CACHE_DIR = _cache_home
DB_PATH = CACHE_DIR / "ticianoflix.db"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
SUBS_CACHE_DIR = CACHE_DIR / "subs"
CACHE_DIR.mkdir(exist_ok=True)
IMAGE_CACHE_DIR.mkdir(exist_ok=True)
SUBS_CACHE_DIR.mkdir(exist_ok=True)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


# ── Fronteira de paths com o rclone ──────────────────────────
# O DB e o frontend sempre falam em paths logicos ("/TicianoFlix/Acao/Filme").
# O rclone pode estar em dois modos:
#   escopado  — root_folder_id aponta pra pasta TicianoFlix, entao "gdrive:" JA
#               e a pasta e o prefixo /TicianoFlix nao existe do lado dele
#   raiz      — modo antigo, "gdrive:" e a raiz do Drive e o prefixo e real
# Detectamos lendo o rclone.conf uma vez, para que o mesmo codigo funcione
# antes e depois do usuario escopar o remote.
_remote_scoped = None
_remote_scoped_lock = threading.Lock()


def _rclone_conf_path():
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


def _remote_is_scoped():
    """True quando o remote principal ja aponta direto pra pasta TicianoFlix."""
    global _remote_scoped
    with _remote_scoped_lock:
        if _remote_scoped is not None:
            return _remote_scoped
        scoped = False
        try:
            section = RCLONE_REMOTE.rstrip(":")
            current = None
            for raw in _rclone_conf_path().read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1]
                elif current == section and line.startswith("root_folder_id"):
                    scoped = bool(line.split("=", 1)[1].strip())
        except Exception:
            scoped = False
        _remote_scoped = scoped
        return scoped


def _rc(logical_path):
    """Path logico -> path relativo ao remote, sem barra inicial.

    "/TicianoFlix/Acao/Filme/x.mkv" -> "Acao/Filme/x.mkv"   (remote escopado)
                                    -> "TicianoFlix/Acao/Filme/x.mkv" (raiz)
    """
    p = "/" + str(logical_path).strip("/")
    if _remote_is_scoped():
        if p == LOGICAL_ROOT:
            return ""
        if p.startswith(LOGICAL_ROOT + "/"):
            p = p[len(LOGICAL_ROOT):]
    return p.strip("/")


def _rc_remote(logical_path):
    """Path logico -> destino completo pro rclone ("gdrive:Acao/Filme/x.mkv")."""
    return RCLONE_REMOTE + _rc(logical_path)


def _serve_path(logical_path):
    """Path logico -> path dentro do 'rclone serve http'.

    O serve e sempre montado na pasta TicianoFlix (veja start_rclone_serve),
    entao aqui o prefixo logico sempre sai, independente do modo do remote.
    """
    p = "/" + str(logical_path).strip("/")
    if p == LOGICAL_ROOT:
        return ""
    if p.startswith(LOGICAL_ROOT + "/"):
        p = p[len(LOGICAL_ROOT):]
    return p.strip("/")

# ── Segurança de rede ────────────────────────────────────────
# O servidor continua ouvindo na LAN (Chromecast e celular precisam disso),
# mas só aceita requisições cujo Host seja local/privado e cujo Origin, quando
# presente, também seja. Isso preserva o uso doméstico e fecha DNS rebinding —
# nesse ataque o Host é um domínio público controlado por terceiros.
BIND_HOST = os.environ.get("TICIANOFLIX_BIND", HOST)

# Web GUI do rclone: desligada por padrão. Ela expõe a API de controle remoto
# do rclone, que dá acesso total ao Drive. Habilite com TICIANOFLIX_RCLONE_GUI=1
# — nesse caso ela sobe apenas em 127.0.0.1, acessível só do próprio computador.
RCLONE_GUI_ENABLED = os.environ.get("TICIANOFLIX_RCLONE_GUI", "") == "1"

MAX_RESTORE_BYTES = 512 * 1024 * 1024   # teto do zip de restore
MAX_JSON_BODY_BYTES = 64 * 1024         # teto de corpo JSON (ex.: /api/progress)
MAX_NFO_BYTES = 2 * 1024 * 1024         # teto de um arquivo .nfo

# Rotas que alteram estado: só respondem a POST com Origin local.
WRITE_ROUTES = frozenset({
    "/api/refresh", "/api/clear-cache", "/api/uncache",
    "/api/cache-download", "/api/backup/drive", "/api/restore/drive",
})


def _is_private_host(hostname):
    """True para nomes/IPs locais ou de rede privada."""
    if not hostname:
        return False
    h = hostname.strip().strip("[]").lower()
    if h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    if h.endswith((".local", ".localhost", ".lan", ".internal", ".home.arpa")):
        return True
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        a, b = int(parts[0]), int(parts[1])
        if a in (10, 127):
            return True
        if a == 192 and b == 168:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 169 and b == 254:
            return True
        if a == 100 and 64 <= b <= 127:   # CGNAT (Tailscale)
            return True
    if h.startswith(("fe80:", "fc", "fd")):
        return True
    return False


def _host_allowed(host_header):
    """Valida o header Host. Ausente = cliente HTTP/1.0 local."""
    if not host_header:
        return True
    h = host_header.strip()
    if h.startswith("["):                       # [::1]:8080
        h = h[1:h.index("]")] if "]" in h else h[1:]
    elif h.count(":") == 1:                     # host:porta
        h = h.split(":")[0]
    return _is_private_host(h)


def _origin_allowed(origin_header):
    """Origin ausente é aceito — Chromecast, <video> e navegação direta não mandam."""
    if not origin_header:
        return True
    if origin_header == "null":
        return False
    try:
        return _is_private_host(urllib.parse.urlparse(origin_header).hostname)
    except Exception:
        return False


def _looks_like_ticianoflix_db(raw):
    """Confere que o blob é um SQLite íntegro com o schema esperado antes de
    sobrescrever o banco real."""
    if not raw.startswith(b"SQLite format 3\x00"):
        return False
    import tempfile
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            f.write(raw)
            tmp = f.name
        conn = sqlite3.connect(tmp)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        return {"files", "folders"}.issubset(tables)
    except Exception:
        return False
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _vfs_segment_match(entry_str, needle):
    """Casa apenas em fronteira de componente de caminho. Impede que um
    fragmento curto ou vazio vire curinga e apague o cache inteiro."""
    n = needle.replace(os.sep, "/").strip("/")
    if not n:
        return False
    return ("/" + n + "/") in (entry_str.replace(os.sep, "/") + "/")


# ── Autenticacao ─────────────────────────────────────────────
# Contas com papeis (admin / user). Nao existe auto-cadastro: o primeiro
# admin e criado no primeiro boot, e so com o codigo de instalacao impresso
# no log do servidor. Depois disso, contas novas so pelo painel de admin.
#
# A sessao e sem estado: o cookie carrega (usuario, expiracao, epoca global,
# epoca do usuario) assinados por HMAC. Duas epocas permitem derrubar todos
# os aparelhos de uma vez (global) ou so os de uma pessoa (do usuario).
#
# O Chromecast nao manda cookie — para ele o servidor assina uma URL por
# arquivo (ver _issue_media_token).
AUTH_PATH = CACHE_DIR / "auth.json"
SECRET_PATH = CACHE_DIR / "secret.key"
SESSION_COOKIE = "tflix_session"
SESSION_MAX_AGE = 90 * 24 * 3600     # 90 dias por dispositivo
CAST_TOKEN_MAX_AGE = 12 * 3600       # cobre um filme inteiro com folga
MIN_PASSWORD_LEN = 8
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW = 15 * 60
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")

_auth_lock = threading.RLock()
_login_attempts = {}
_setup_code = None
_UNSET = object()

# Rotas alcancaveis sem sessao.
PUBLIC_PATHS = frozenset({
    "/login", "/favicon.ico", "/favicon.svg",
    "/api/auth/status", "/api/auth/login", "/api/auth/setup", "/api/auth/logout",
})
# Rotas que o Chromecast busca sozinho: liberadas por token assinado.
TOKEN_PATHS = frozenset({"/api/stream", "/api/subtitle"})
# Rotas restritas a administradores.
ADMIN_PATHS = frozenset({
    "/api/users", "/api/users/add", "/api/users/remove", "/api/users/role",
})


def _server_secret():
    """Chave HMAC persistida, para que reiniciar o servidor nao deslogue ninguem."""
    with _auth_lock:
        if SECRET_PATH.exists():
            raw = SECRET_PATH.read_bytes()
            if len(raw) >= 32:
                return raw
        raw = secrets.token_bytes(32)
        SECRET_PATH.write_bytes(raw)
        try:
            SECRET_PATH.chmod(0o600)
        except OSError:
            pass
        return raw


def _setup_code_value():
    """Codigo de 6 digitos exigido para criar o primeiro admin. Sorteado uma vez
    por execucao enquanto nao houver conta, e impresso no log do servidor —
    quem nao ve o terminal do computador nao consegue criar a conta inicial."""
    global _setup_code
    with _auth_lock:
        if _setup_code is None:
            _setup_code = "%06d" % secrets.randbelow(1000000)
        return _setup_code


def _v1_to_v2(raw):
    """Formato antigo (senha unica) vira uma conta de admin chamada 'admin'."""
    now = int(time.time())
    return {
        "version": 2,
        "epoch": int(raw.get("epoch", now)),
        "users": {
            "admin": {
                "role": "admin",
                "algo": "scrypt", "n": 16384, "r": 8, "p": 1,
                "salt": raw["salt"], "hash": raw["hash"],
                "epoch": int(raw.get("epoch", now)),
                "created": int(raw.get("created", now)),
            }
        },
    }


def _auth_data():
    """Le auth.json ja normalizado para o formato v2. Nao grava."""
    try:
        raw = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not raw:
        return None
    if "users" not in raw and raw.get("hash"):
        return _v1_to_v2(raw)
    return raw


def _save_auth(data):
    with _auth_lock:
        AUTH_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            AUTH_PATH.chmod(0o600)
        except OSError:
            pass


def _migrate_auth_if_needed():
    """Persiste a conversao v1 -> v2 uma unica vez, na subida do servidor."""
    try:
        raw = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if raw and "users" not in raw and raw.get("hash"):
        _save_auth(_v1_to_v2(raw))
        print("[TicianoFlix] Senha unica migrada para a conta 'admin'.", flush=True)


def _auth_configured():
    d = _auth_data()
    return bool(d and d.get("users"))


def _global_epoch():
    return int((_auth_data() or {}).get("epoch", 0))


def _next_epoch(current):
    """Epoca sempre crescente. So `int(time.time())` nao serve: duas operacoes
    no mesmo segundo produziriam o mesmo valor, e a sessao que deveria cair
    continuaria valida — trocar a senha nao derrubaria quem ja estava dentro."""
    return max(int(current or 0) + 1, int(time.time()))


def _norm_username(name):
    return (name or "").strip().lower()


def _get_user(username):
    d = _auth_data()
    if not d:
        return None
    return (d.get("users") or {}).get(_norm_username(username))


def _list_users():
    d = _auth_data() or {}
    return [
        {"username": name, "role": u.get("role", "user"), "created": u.get("created")}
        for name, u in sorted((d.get("users") or {}).items())
    ]


def _admin_count(d):
    return sum(1 for u in (d.get("users") or {}).values() if u.get("role") == "admin")


def _hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt=salt,
                              iterations=100000, dklen=32)
    return salt, dk


def _password_problem(password):
    if len(password or "") < MIN_PASSWORD_LEN:
        return "A senha precisa ter pelo menos %d caracteres" % MIN_PASSWORD_LEN
    return None


def _username_problem(username):
    if not USERNAME_RE.match(_norm_username(username)):
        return ("O usuario deve ter de 2 a 32 caracteres, comecar com letra ou "
                "numero, e usar apenas letras, numeros, ponto, hifen ou _")
    return None


def _create_user(username, password, role="user"):
    """Cria a conta. Devolve None em sucesso ou a mensagem de erro."""
    username = _norm_username(username)
    problem = _username_problem(username) or _password_problem(password)
    if problem:
        return problem
    with _auth_lock:
        d = _auth_data() or {"version": 2, "epoch": int(time.time()), "users": {}}
        if username in (d.get("users") or {}):
            return "Ja existe uma conta com esse nome"
        salt, dk = _hash_password(password)
        now = int(time.time())
        d.setdefault("users", {})[username] = {
            "role": "admin" if role == "admin" else "user",
            "algo": "scrypt", "n": 16384, "r": 8, "p": 1,
            "salt": salt.hex(), "hash": dk.hex(),
            "epoch": now, "created": now,
        }
        _save_auth(d)
    return None


def _remove_user(username, acting):
    username = _norm_username(username)
    with _auth_lock:
        d = _auth_data()
        if not d or username not in (d.get("users") or {}):
            return "Conta nao encontrada"
        if username == _norm_username(acting):
            return "Voce nao pode remover a propria conta"
        if d["users"][username].get("role") == "admin" and _admin_count(d) <= 1:
            return "Nao da para remover o ultimo administrador"
        del d["users"][username]
        _save_auth(d)
    return None


def _set_user_role(username, role, acting):
    username = _norm_username(username)
    role = "admin" if role == "admin" else "user"
    with _auth_lock:
        d = _auth_data()
        if not d or username not in (d.get("users") or {}):
            return "Conta nao encontrada"
        user = d["users"][username]
        if user.get("role") == "admin" and role != "admin" and _admin_count(d) <= 1:
            return "Nao da para rebaixar o ultimo administrador"
        if username == _norm_username(acting) and role != "admin":
            return "Voce nao pode tirar o proprio acesso de administrador"
        user["role"] = role
        # Trocar o papel invalida as sessoes daquela conta.
        user["epoch"] = _next_epoch(user.get("epoch"))
        _save_auth(d)
    return None


def _set_user_password(username, password):
    username = _norm_username(username)
    problem = _password_problem(password)
    if problem:
        return problem
    with _auth_lock:
        d = _auth_data()
        if not d or username not in (d.get("users") or {}):
            return "Conta nao encontrada"
        salt, dk = _hash_password(password)
        user = d["users"][username]
        user["salt"], user["hash"] = salt.hex(), dk.hex()
        # Trocar a senha derruba as sessoes daquela conta.
        user["epoch"] = _next_epoch(user.get("epoch"))
        _save_auth(d)
    return None


def _check_credentials(username, password):
    user = _get_user(username)
    if not user or not user.get("hash"):
        # Gasta o mesmo tempo de um hash real, para nao vazar quais contas existem.
        _hash_password(password or "")
        return None
    try:
        salt = bytes.fromhex(user["salt"])
        _, dk = _hash_password(password or "", salt)
        if hmac.compare_digest(dk.hex(), user["hash"]):
            return {"username": _norm_username(username),
                    "role": user.get("role", "user")}
    except Exception:
        pass
    return None


def _revoke_all_sessions():
    """Desloga todos os aparelhos de todas as contas."""
    with _auth_lock:
        d = _auth_data()
        if not d:
            return
        d["epoch"] = _next_epoch(d.get("epoch"))
        _save_auth(d)


def _revoke_user_sessions(username):
    username = _norm_username(username)
    with _auth_lock:
        d = _auth_data()
        if not d or username not in (d.get("users") or {}):
            return
        d["users"][username]["epoch"] = _next_epoch(
            d["users"][username].get("epoch"))
        _save_auth(d)


def _sign(msg):
    return hmac.new(_server_secret(), msg.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _issue_session(username):
    user = _get_user(username) or {}
    payload = {
        "u": _norm_username(username),
        "e": int(time.time()) + SESSION_MAX_AGE,
        "g": _global_epoch(),
        "p": int(user.get("epoch", 0)),
    }
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return raw + "." + _sign(raw)


def _session_user(token):
    """Devolve {'username','role'} da sessao, ou None."""
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(raw)):
        return None
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        return None
    if float(payload.get("e", 0)) < time.time():
        return None
    if int(payload.get("g", -1)) != _global_epoch():
        return None
    user = _get_user(payload.get("u", ""))
    if not user:
        return None
    if int(payload.get("p", -1)) != int(user.get("epoch", 0)):
        return None
    return {"username": _norm_username(payload["u"]),
            "role": user.get("role", "user")}


def _issue_media_token(media_path):
    exp = int(time.time()) + CAST_TOKEN_MAX_AGE
    return "%d.%s" % (exp, _sign("m|%s|%d" % (media_path, exp)))


def _valid_media_token(media_path, token):
    if not token or not media_path:
        return False
    try:
        exp_s, sig = token.split(".")
        exp = int(exp_s)
    except Exception:
        return False
    if exp < time.time():
        return False
    return hmac.compare_digest(sig, _sign("m|%s|%d" % (media_path, exp)))


def _login_blocked(ip):
    now = time.time()
    hits = [t for t in _login_attempts.get(ip, []) if t > now - LOGIN_WINDOW]
    _login_attempts[ip] = hits
    return len(hits) >= LOGIN_MAX_ATTEMPTS


def _record_login_failure(ip):
    _login_attempts.setdefault(ip, []).append(time.time())


def _login_page(setup=False):
    """Tela de entrada. Em modo setup cria o primeiro administrador, e exige o
    codigo impresso no log do servidor — assim quem esta na rede mas nao tem
    acesso ao computador nao consegue tomar a conta inicial."""
    if setup:
        heading = "Criar o administrador"
        sub = ("Primeiro acesso. O codigo de 6 digitos aparece no terminal onde "
               "o TicianoFlix esta rodando.")
        action = "/api/auth/setup"
        button = "Criar conta e entrar"
        extra_top = (
            '<label for="code">Codigo de instalacao</label>'
            '<input id="code" type="text" inputmode="numeric" pattern="[0-9]{6}" '
            'maxlength="6" autocomplete="off" required placeholder="000000">')
        extra_bottom = (
            '<label for="confirm">Repita a senha</label>'
            '<input id="confirm" type="password" autocomplete="new-password" '
            'required minlength="%d">' % MIN_PASSWORD_LEN)
        hint = ("Depois disso nao existe auto-cadastro: contas novas so pelo "
                "painel de administracao.")
        autocomplete = "new-password"
    else:
        heading = "Entrar"
        sub = "Use a conta que o administrador criou para voce."
        action = "/api/auth/login"
        button = "Entrar"
        extra_top = ""
        extra_bottom = ""
        hint = ("Esqueceu a senha? Peca a um administrador para redefinir. "
                "Se ninguem mais tiver acesso, apague "
                "<code>~/.cache/ticianoflix/auth.json</code> no computador e o "
                "primeiro acesso volta.")
        autocomplete = "current-password"

    page = """<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>TicianoFlix</title>
<link rel="icon" href="/favicon.svg">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 24px;
    background: radial-gradient(1200px 600px at 50% -10%, #2a1114 0%, #0b0b0d 60%);
    color: #f2f2f4;
    font-family: Roboto, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .card {
    width: 100%; max-width: 390px; background: rgba(20,20,23,.92);
    border: 1px solid #2a2a30; border-radius: 14px; padding: 34px 30px 30px;
    box-shadow: 0 24px 60px -20px rgba(0,0,0,.8);
  }
  .brand { font-size: 26px; font-weight: 800; letter-spacing: -.02em; margin: 0; color: #e50914; }
  h1 { font-size: 19px; font-weight: 600; margin: 18px 0 6px; }
  p.sub { margin: 0 0 22px; font-size: 14px; line-height: 1.5; color: #a0a0aa; }
  label {
    display: block; font-size: 12px; text-transform: uppercase;
    letter-spacing: .08em; color: #8b8b95; margin: 0 0 6px;
  }
  input {
    width: 100%; padding: 12px 13px; margin-bottom: 16px; font-size: 15px;
    color: #f2f2f4; background: #141418; border: 1px solid #33333c;
    border-radius: 8px; font-family: inherit;
  }
  #code { letter-spacing: .5em; font-family: ui-monospace, Menlo, monospace; text-align: center; }
  input:focus { outline: none; border-color: #e50914; box-shadow: 0 0 0 3px rgba(229,9,20,.18); }
  button {
    width: 100%; padding: 12px; font-size: 15px; font-weight: 600; color: #fff;
    background: #e50914; border: 0; border-radius: 8px; cursor: pointer; font-family: inherit;
  }
  button:hover { background: #f6121d; }
  button:disabled { opacity: .6; cursor: default; }
  .msg { margin: 14px 0 0; padding: 10px 12px; border-radius: 8px; font-size: 13.5px; line-height: 1.45; display: none; }
  .msg.err { display: block; background: #2c1214; color: #f5a19b; border: 1px solid #55211f; }
  .msg.ok  { display: block; background: #10241a; color: #7fce9f; border: 1px solid #1f4a33; }
  .hint { margin: 20px 0 0; font-size: 12px; line-height: 1.55; color: #6e6e78; }
  .hint code { color: #9a9aa4; }
</style>
</head><body>
  <form class="card" id="form" autocomplete="on">
    <div class="brand">TicianoFlix</div>
    <h1>__HEADING__</h1>
    <p class="sub">__SUB__</p>
    __EXTRA_TOP__
    <label for="username">Usuario</label>
    <input id="username" type="text" autocomplete="username" required
           autocapitalize="none" spellcheck="false" autofocus>
    <label for="password">Senha</label>
    <input id="password" type="password" autocomplete="__AC__" required minlength="__MIN__">
    __EXTRA_BOTTOM__
    <button id="btn" type="submit">__BUTTON__</button>
    <div class="msg" id="msg"></div>
    <p class="hint">__HINT__</p>
  </form>
<script>
  var form = document.getElementById('form');
  var msg = document.getElementById('msg');
  var btn = document.getElementById('btn');
  function show(text, kind) { msg.textContent = text; msg.className = 'msg ' + kind; }
  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var body = {
      username: document.getElementById('username').value.trim().toLowerCase(),
      password: document.getElementById('password').value
    };
    var confirmEl = document.getElementById('confirm');
    if (confirmEl && body.password !== confirmEl.value) {
      show('As senhas nao conferem.', 'err'); return;
    }
    if (body.password.length < __MIN__) {
      show('A senha precisa ter pelo menos __MIN__ caracteres.', 'err'); return;
    }
    var codeEl = document.getElementById('code');
    if (codeEl) body.code = codeEl.value.trim();
    btn.disabled = true;
    try {
      var res = await fetch('__ACTION__', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      var data = await res.json().catch(function () { return {}; });
      if (res.ok && data.status === 'ok') {
        show('Tudo certo, entrando...', 'ok');
        window.location.replace('/');
        return;
      }
      show(data.error || 'Nao foi possivel entrar.', 'err');
    } catch (e) {
      show('Falha de conexao com o servidor.', 'err');
    }
    btn.disabled = false;
  });
</script>
</body></html>"""
    for token, value in (
        ("__HEADING__", heading), ("__SUB__", sub), ("__ACTION__", action),
        ("__BUTTON__", button), ("__EXTRA_TOP__", extra_top),
        ("__EXTRA_BOTTOM__", extra_bottom), ("__HINT__", hint),
        ("__AC__", autocomplete), ("__MIN__", str(MIN_PASSWORD_LEN)),
    ):
        page = page.replace(token, value)
    return page


rclone_server_proc = None
rclone_webgui_proc = None
_webgui_credentials = {"user": "", "pass": ""}
_webgui_lock = threading.Lock()
_rclone_serve_lock = threading.Lock()
RCLONE_WEBGUI_PORT = 5572
_db_lock = threading.Lock()
_scan_in_progress = False
_scan_lock = threading.Lock()

# Scan progress tracking
_scan_progress = {
    "phase": "",           # "listing_root" | "genres" | "movies" | "done" | "error"
    "genre_current": "",
    "genre_index": 0,
    "genre_total": 0,
    "movie_current": "",
    "movie_index": 0,
    "movie_total": 0,
    "percent": 0,
}
_scan_progress_lock = threading.Lock()

# Set of fully-cached file paths (persisted as JSON)
CACHED_FILES_PATH = CACHE_DIR / "cached_files.json"
_cached_files_lock = threading.Lock()
_cached_files = set()

def _norm_cache_path(file_path):
    """Normalize a file path for cache bookkeeping.

    Streaming marks files with the URL path (leading slash); the cache manager
    and manual downloads build paths without it. Normalize to a single canonical
    form (no leading/trailing slashes) so lookups always match.
    """
    return "/".join(part for part in str(file_path).split("/") if part)

# Download progress tracking
_download_progress = {}  # video_path -> {"percent": int, "status": str, "total": int, "downloaded": int}
_download_progress_lock = threading.Lock()
if CACHED_FILES_PATH.exists():
    try:
        _cached_files = set(_norm_cache_path(p) for p in json.loads(CACHED_FILES_PATH.read_text()))
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


# ═══════════════════════════════════════════════
#  SQLite Cache
# ═══════════════════════════════════════════════

def get_db():
    """Get a thread-local database connection with write serialization."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


_db_write_lock = threading.Lock()

def get_db_write():
    """Get a connection for writes, serialized via _db_write_lock."""
    conn = get_db()
    return conn, _db_write_lock


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS folders (
            path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent TEXT NOT NULL DEFAULT '',
            is_ticianoflix_root INTEGER NOT NULL DEFAULT 0,
            has_video INTEGER NOT NULL DEFAULT 0,
            depth INTEGER NOT NULL DEFAULT 0,
            mod_time TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path TEXT NOT NULL,
            name TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 0,
            mime_type TEXT,
            mod_time TEXT,
            file_id TEXT,
            extension TEXT NOT NULL DEFAULT '',
            file_type TEXT NOT NULL DEFAULT 'other',
            FOREIGN KEY (folder_path) REFERENCES folders(path)
        );

        CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_path);
        CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type);
        CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent);
        CREATE INDEX IF NOT EXISTS idx_folders_depth ON folders(depth);

        CREATE TABLE IF NOT EXISTS movie_meta (
            folder_path TEXT PRIMARY KEY,
            title TEXT,
            year TEXT,
            plot TEXT,
            rating TEXT,
            votes TEXT,
            genres TEXT,
            tagline TEXT,
            directors TEXT,
            writers TEXT,
            cast_list TEXT,
            video_info TEXT,
            audio_info TEXT,
            updated_at REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS watch_progress (
            folder_path TEXT PRIMARY KEY,
            position_seconds REAL NOT NULL DEFAULT 0,
            duration_seconds REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0
        );
    """)
    # Migration: add mod_time column if missing (existing databases)
    try:
        conn.execute("ALTER TABLE folders ADD COLUMN mod_time TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    conn.close()


def get_cache_time():
    """Get last cache update timestamp."""
    conn = get_db()
    cursor = conn.execute("SELECT value FROM cache_meta WHERE key='last_updated'")
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else None


def set_cache_time():
    """Set cache update timestamp."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('last_updated', ?)",
        (str(int(time.time())),)
    )
    conn.commit()
    conn.close()


def is_cache_stale():
    """Check if cache needs refresh (older than 1 hour)."""
    t = get_cache_time()
    if not t:
        return True
    return (int(time.time()) - int(t)) > 3600


def _log_notification(level, message):
    """Log a notification to the DB for user-facing display."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)",
            (f"notification_{int(time.time())}", json.dumps({"level": level, "message": message, "time": time.time()}))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_cache_usage():
    """Return disk usage of caches in human-readable bytes."""
    total = 0
    details = {}
    for label, path in [
        ("images", IMAGE_CACHE_DIR),
        ("subs", SUBS_CACHE_DIR),
        ("vfs", Path.home() / ".cache" / "rclone" / "vfs"),
        ("db", DB_PATH),
    ]:
        p = Path(path)
        size = 0
        if p.is_file():
            size = p.stat().st_size
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    size += f.stat().st_size
        details[label] = size
        total += size
    return {"total": total, "details": details}



# ═══════════════════════════════════════════════
#  Drive Scanner
# ═══════════════════════════════════════════════

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


def _remove_folder_tree(conn, path):
    """Remove a folder and everything under it (files, subfolders, NFO meta)."""
    conn.execute("DELETE FROM folders WHERE path=?", (path,))
    conn.execute("DELETE FROM folders WHERE parent LIKE ?", (path + '/%',))
    conn.execute("DELETE FROM files WHERE folder_path=? OR folder_path LIKE ?", (path, path + '/%'))
    conn.execute("DELETE FROM movie_meta WHERE folder_path=? OR folder_path LIKE ?", (path, path + '/%'))


def scan_drive():
    """
    Incremental scan of the TicianoFlix drive structure using a SINGLE
    recursive rclone lsjson of the whole tree, then diffing against the DB:
    - New/changed movies (file set or file size/modtime differs) are re-indexed
      and their NFO is re-fetched.
    - Unchanged movies are left completely untouched (no rclone calls, no DB writes).
    - Folders/files that disappeared from the Drive are removed.
    """
    global _scan_progress
    print("[TicianoFlix] Scanning Google Drive (incremental)...", flush=True)
    start = time.time()

    with _scan_progress_lock:
        _scan_progress["phase"] = "listing_root"
        _scan_progress["percent"] = 0

    conn = get_db()
    stats = {"added": 0, "changed": 0, "removed": 0, "unchanged": 0}

    # Single recursive listing of the whole TicianoFlix tree (--fast-list uses
    # the Drive files.list API, ~10x faster than walking the tree per directory)
    tree = run_rclone_cmd(["lsjson", "--recursive", "--fast-list",
                           _rc_remote(LOGICAL_ROOT)])
    if not isinstance(tree, list):
        print(f"[TicianoFlix] Failed to list TicianoFlix: {tree}", flush=True)
        with _scan_progress_lock:
            _scan_progress["phase"] = "error"
        conn.close()
        return False

    root_path = "/TicianoFlix"
    conn.execute(
        "INSERT OR REPLACE INTO folders (path, name, parent, is_ticianoflix_root, depth) VALUES (?, ?, '', 1, 0)",
        (root_path, "TicianoFlix")
    )

    # Build in-memory tree: dirs by full path, files grouped by parent folder
    dirs = {}
    files_by_parent = {}
    for e in tree:
        rel = e.get("Path", "")
        full = f"{root_path}/{rel}" if rel else root_path
        if e.get("IsDir"):
            dirs[full] = e
        else:
            parent = full.rsplit("/", 1)[0]
            files_by_parent.setdefault(parent, {})[e.get("Name", "")] = e

    genre_dirs = {p: e for p, e in dirs.items() if p.count("/") == 2}
    movie_dirs = {p: e for p, e in dirs.items() if p.count("/") == 3}

    # DB state
    db_genres = {r["path"] for r in conn.execute("SELECT path FROM folders WHERE depth=1").fetchall()}
    db_movies = {r["path"]: r for r in conn.execute(
        "SELECT path, name, mod_time, has_video FROM folders WHERE depth=2").fetchall()}
    db_files = {}
    for r in conn.execute("SELECT folder_path, name, size, mod_time FROM files").fetchall():
        db_files[(r["folder_path"], r["name"])] = r

    # Remove genres that no longer exist on the Drive
    removed_prefixes = []
    for p in db_genres - set(genre_dirs):
        _remove_folder_tree(conn, p)
        removed_prefixes.append(p)
        stats["removed"] += 1

    # Remove movies that no longer exist (skip ones already removed with their genre)
    for p in set(db_movies) - set(movie_dirs):
        if any(p.startswith(rp + "/") for rp in removed_prefixes):
            continue
        _remove_folder_tree(conn, p)
        stats["removed"] += 1

    # Direct files at the TicianoFlix root: upsert + prune deleted
    root_live = files_by_parent.get(root_path, {})
    for name, fe in root_live.items():
        _index_file(conn, root_path, fe)
    for (fp, name) in list(db_files):
        if fp == root_path and name not in root_live:
            conn.execute("DELETE FROM files WHERE folder_path=? AND name=?", (fp, name))

    total_genres = len(genre_dirs)
    with _scan_progress_lock:
        _scan_progress["phase"] = "genres"
        _scan_progress["genre_total"] = total_genres

    for gi, (genre_path, genre_entry) in enumerate(sorted(genre_dirs.items())):
        genre_name = genre_entry.get("Name", "")

        with _scan_progress_lock:
            _scan_progress["genre_index"] = gi + 1
            _scan_progress["genre_current"] = genre_name
            _scan_progress["percent"] = int((gi / total_genres) * 100) if total_genres else 0

        conn.execute(
            "INSERT OR REPLACE INTO folders (path, name, parent, depth, mod_time) VALUES (?, ?, ?, 1, ?)",
            (genre_path, genre_name, root_path, genre_entry.get("ModTime", ""))
        )

        # Direct files in genre folder (unstructured): upsert + prune deleted
        has_direct_video = False
        live_genre_files = files_by_parent.get(genre_path, {})
        for name, fe in live_genre_files.items():
            if Path(name).suffix.lower() in VIDEO_EXTENSIONS:
                has_direct_video = True
            _index_file(conn, genre_path, fe)
        for (fp, name) in list(db_files):
            if fp == genre_path and name not in live_genre_files:
                conn.execute("DELETE FROM files WHERE folder_path=? AND name=?", (fp, name))

        # Movies under this genre
        for movie_path in sorted(m for m in movie_dirs if m.startswith(genre_path + "/")):
            movie_entry = movie_dirs[movie_path]
            movie_name = movie_entry.get("Name", "")
            live_movie_files = files_by_parent.get(movie_path, {})
            prev = db_movies.get(movie_path)

            # File-level change detection: name set + size/modtime of each file
            new = prev is None
            changed = new
            if not changed:
                db_keys = {name for (fp, name) in db_files if fp == movie_path}
                live_keys = set(live_movie_files)
                if db_keys != live_keys:
                    changed = True
                else:
                    for name in live_keys:
                        fe = live_movie_files[name]
                        dr = db_files[(movie_path, name)]
                        if fe.get("Size", 0) != dr["size"] or fe.get("ModTime", "") != dr["mod_time"]:
                            changed = True
                            break

            if prev is not None and not changed:
                # Unchanged: keep the folder row (preserve has_video), touch nothing else
                conn.execute(
                    "INSERT INTO folders (path, name, parent, depth, mod_time, has_video) "
                    "VALUES (?, ?, ?, 2, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET mod_time=excluded.mod_time",
                    (movie_path, movie_name, genre_path, movie_entry.get("ModTime", ""), prev["has_video"])
                )
                stats["unchanged"] += 1
                continue

            # New or changed: rebuild folder contents from the same listing
            conn.execute(
                "INSERT OR REPLACE INTO folders (path, name, parent, depth, mod_time) VALUES (?, ?, ?, 2, ?)",
                (movie_path, movie_name, genre_path, movie_entry.get("ModTime", ""))
            )

            with _scan_progress_lock:
                _scan_progress["movie_index"] += 1
                _scan_progress["movie_current"] = movie_name

            conn.execute("DELETE FROM files WHERE folder_path=?", (movie_path,))
            for name, fe in live_movie_files.items():
                _index_file(conn, movie_path, fe)

            if any(Path(n).suffix.lower() in VIDEO_EXTENSIONS for n in live_movie_files):
                conn.execute(
                    "UPDATE folders SET has_video=1 WHERE path=?",
                    (movie_path,)
                )

                # NFO only for new/changed movies AND only if the folder really
                # has one (avoids a slow rclone cat on a missing file)
                if any(n.lower().endswith(".nfo") for n in live_movie_files):
                    nfo_raw = _fetch_nfo_raw(movie_path)
                    if nfo_raw:
                        nfo_data = _parse_nfo(nfo_raw)
                        if nfo_data:
                            _save_nfo_to_db(conn, movie_path, nfo_data)

            if new:
                stats["added"] += 1
            else:
                stats["changed"] += 1

        # Mark genre as having content if any movie folder has video
        genre_has_video = conn.execute(
            "SELECT COUNT(*) as c FROM folders WHERE parent=? AND has_video=1",
            (genre_path,)
        ).fetchone()["c"]

        if has_direct_video:
            genre_has_video = genre_has_video + 1

        if genre_has_video > 0:
            conn.execute(
                "UPDATE folders SET has_video=1 WHERE path=?",
                (genre_path,)
            )

    conn.commit()

    # Mark ticianoflix root
    total_genres = conn.execute("SELECT COUNT(*) as c FROM folders WHERE depth=1").fetchone()["c"]
    total_movies = conn.execute("SELECT COUNT(*) as c FROM folders WHERE has_video=1 AND depth=2").fetchone()["c"]
    total_files = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
    conn.close()

    set_cache_time()

    elapsed = time.time() - start
    print(
        f"[TicianoFlix] Scan complete: {total_genres} genres, {total_movies} movies, {total_files} files "
        f"in {elapsed:.1f}s (+{stats['added']} novos, ~{stats['changed']} alterados, -{stats['removed']} removidos, "
        f"{stats['unchanged']} inalterados)",
        flush=True
    )

    with _scan_progress_lock:
        _scan_progress["phase"] = "done"
        _scan_progress["percent"] = 100

    return True


def _index_file(conn, folder_path, item):
    """Index a single file into the database."""
    name = item.get("Name", "")
    ext = Path(name).suffix.lower()
    size = item.get("Size", 0)
    mime = item.get("MimeType", "")
    mod_time = item.get("ModTime", "")
    file_id = item.get("ID", "")

    # Determine file type
    if ext in VIDEO_EXTENSIONS:
        file_type = "video"
    elif ext in SUBTITLE_EXTENSIONS:
        file_type = "subtitle"
    elif ext in IMAGE_EXTENSIONS:
        stem = Path(name).stem.lower()
        if stem in ("poster", "capa", "cover", "folder"):
            file_type = "poster"
        elif stem in ("fanart", "background", "backdrop", "banner"):
            file_type = "fanart"
        else:
            file_type = "image"
    else:
        file_type = "other"

    conn.execute(
        """INSERT OR REPLACE INTO files
           (folder_path, name, size, mime_type, mod_time, file_id, extension, file_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (folder_path, name, size, mime, mod_time, file_id, ext, file_type)
    )


# ═══════════════════════════════════════════════
#  Cached Queries
# ═══════════════════════════════════════════════

def cached_list_directory(path):
    """List directory contents from cache."""
    conn = get_db()

    # Get folders
    folder_rows = conn.execute(
        "SELECT * FROM folders WHERE parent=? ORDER BY name",
        (path,)
    ).fetchall()

    # Get files
    file_rows = conn.execute(
        "SELECT * FROM files WHERE folder_path=? ORDER BY name",
        (path,)
    ).fetchall()

    conn.close()

    folders = []
    videos = []
    subtitles = []
    images = []

    for row in folder_rows:
        folders.append({
            "Path": row["path"].lstrip("/"),
            "Name": row["name"],
            "Size": 0,
            "MimeType": "inode/directory",
            "ModTime": row["mod_time"],
            "IsDir": True,
            "has_video": bool(row["has_video"]),
        })

    for row in file_rows:
        entry = {
            "Path": f"{row['folder_path'].lstrip('/')}/{row['name']}",
            "Name": row["name"],
            "Size": row["size"],
            "MimeType": row["mime_type"],
            "ModTime": row["mod_time"],
            "IsDir": False,
        }
        ft = row["file_type"]
        if ft == "video":
            # Find poster in same folder
            poster = _find_poster_cached(row["folder_path"])
            if poster:
                entry["poster"] = poster
            videos.append(entry)
        elif ft in ("poster", "fanart", "image"):
            images.append(entry)
        elif ft == "subtitle":
            subtitles.append(entry)

    return {
        "path": path,
        "folders": folders,
        "videos": videos,
        "subtitles": subtitles,
        "images": images,
    }


def _parse_nfo(xml_text):
    """Parse Kodi-style NFO XML into a dict of metadata."""
    # NFOs legitimos nao declaram entidades. Recusar <!ENTITY fecha o vetor de
    # bomba XML (billion laughs) do ElementTree sem dependencia externa.
    if xml_text and "<!ENTITY" in xml_text.upper():
        sys.stderr.write("[TicianoFlix] NFO recusado: declara entidades XML\n")
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    def text(tag):
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else None

    def texts(tag):
        return [el.text.strip() for el in root.findall(tag) if el.text]

    def rating_info():
        """Extract rating value + votes from <ratings><rating>."""
        r = root.find("ratings/rating")
        if r is not None:
            val = r.findtext("value", "").strip()
            votes = r.findtext("votes", "").strip()
            return val, votes
        return text("rating"), None

    rating_val, rating_votes = rating_info()

    # Actors
    actors = []
    for actor in root.findall("actor"):
        name = actor.findtext("name", "").strip()
        role = actor.findtext("role", "").strip()
        thumb = actor.findtext("thumb", "").strip()
        if name:
            actors.append({"name": name, "role": role, "thumb": thumb})

    # Directors / Writers / Producers
    directors = texts("director")
    writers = texts("credits")

    # NFO can have <streamdetails> with video/audio info
    video_info = {}
    v = root.find("fileinfo/streamdetails/video")
    if v is not None:
        for child in v:
            video_info[child.tag] = child.text.strip() if child.text else ""

    audio_info = {}
    for a in root.findall("fileinfo/streamdetails/audio"):
        for child in a:
            audio_info[child.tag] = child.text.strip() if child.text else ""

    return {
        "title": text("title"),
        "originaltitle": text("originaltitle"),
        "year": text("year"),
        "plot": text("plot"),
        "outline": text("outline"),
        "tagline": text("tagline"),
        "runtime": text("runtime"),
        "mpaa": text("mpaa"),
        "country": texts("country"),
        "premiered": text("premiered"),
        "rating": rating_val,
        "votes": rating_votes,
        "genres": texts("genre"),
        "studios": texts("studio"),
        "directors": directors,
        "writers": writers,
        "tags": texts("tag"),
        "actors": actors,
        "video_info": video_info,
        "audio_info": audio_info,
        "source": text("source"),
    }


def _fetch_nfo_raw(folder_path):
    """Fetch NFO XML text for a movie folder via rclone. No caching."""
    nfo_path = f"{folder_path.strip('/')}/{folder_path.strip('/').split('/')[-1]}.nfo"
    remote_path = _rc_remote(nfo_path)
    try:
        result = subprocess.run(
            ["rclone", "cat", remote_path],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None
        if len(result.stdout) > MAX_NFO_BYTES:
            sys.stderr.write("[TicianoFlix] NFO ignorado (acima de %d bytes): %s\n"
                             % (MAX_NFO_BYTES, nfo_path))
            return None
        return result.stdout
    except Exception:
        return None


def _save_nfo_to_db(conn, folder_path, nfo_data):
    """Save parsed NFO metadata into movie_meta table."""
    conn.execute("""INSERT OR REPLACE INTO movie_meta
        (folder_path, title, year, plot, rating, votes, genres, tagline,
         directors, writers, cast_list, video_info, audio_info, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        folder_path,
        nfo_data.get("title"),
        nfo_data.get("year"),
        nfo_data.get("plot"),
        nfo_data.get("rating"),
        nfo_data.get("votes"),
        json.dumps(nfo_data.get("genres", []), ensure_ascii=False),
        nfo_data.get("tagline"),
        json.dumps(nfo_data.get("directors", []), ensure_ascii=False),
        json.dumps(nfo_data.get("writers", []), ensure_ascii=False),
        json.dumps(nfo_data.get("actors", []), ensure_ascii=False),
        json.dumps(nfo_data.get("video_info", {}), ensure_ascii=False),
        json.dumps(nfo_data.get("audio_info", {}), ensure_ascii=False),
        time.time(),
    ))


def _fetch_nfo_from_db(folder_path):
    """Read parsed NFO metadata from movie_meta table."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM movie_meta WHERE folder_path=?", (folder_path,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "title": row["title"],
        "year": row["year"],
        "plot": row["plot"],
        "rating": row["rating"],
        "votes": row["votes"],
        "genres": json.loads(row["genres"]) if row["genres"] else [],
        "tagline": row["tagline"],
        "directors": json.loads(row["directors"]) if row["directors"] else [],
        "writers": json.loads(row["writers"]) if row["writers"] else [],
        "actors": json.loads(row["cast_list"]) if row["cast_list"] else [],
        "video_info": json.loads(row["video_info"]) if row["video_info"] else {},
        "audio_info": json.loads(row["audio_info"]) if row["audio_info"] else {},
    }


def _fetch_nfo(folder_path):
    """Fetch and parse NFO metadata. Tries DB first, then downloads via rclone."""
    # Try DB cache first
    from_db = _fetch_nfo_from_db(folder_path)
    if from_db:
        return from_db

    # Fallback: fetch via rclone
    nfo_path = f"{folder_path.strip('/')}/{folder_path.strip('/').split('/')[-1]}.nfo"
    remote_path = _rc_remote(nfo_path)
    try:
        result = subprocess.run(
            ["rclone", "cat", remote_path],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None
        parsed = _parse_nfo(result.stdout)
        if parsed:
            # Save to DB for next time
            conn = get_db()
            try:
                _save_nfo_to_db(conn, folder_path, parsed)
                conn.commit()
            finally:
                conn.close()
        return parsed
    except Exception:
        return None


def cached_movie_detail(folder_path):
    """Get movie detail from SQLite cache (files + NFO metadata)."""
    conn = get_db()
    file_rows = conn.execute(
        "SELECT * FROM files WHERE folder_path=? ORDER BY name",
        (folder_path,)
    ).fetchall()
    conn.close()

    video = None
    poster = None
    fanart = None
    subtitle = None
    images = []

    for row in file_rows:
        entry = {
            "Path": f"{row['folder_path'].lstrip('/')}/{row['name']}",
            "Name": row["name"],
            "Size": row["size"],
            "MimeType": row["mime_type"],
            "ModTime": row["mod_time"],
            "IsDir": False,
            "ID": row["file_id"],
        }
        ft = row["file_type"]
        if ft == "video":
            video = entry
        elif ft == "poster":
            poster = entry
        elif ft == "fanart":
            fanart = entry
        elif ft == "subtitle":
            subtitle = entry
        elif ft == "image":
            images.append(entry)

    if not poster and images:
        poster = images.pop(0)
    if not fanart and images:
        fanart = images.pop(0)

    folder_name = folder_path.strip("/").split("/")[-1]
    year_match = re.search(r'\((\d{4})\)', folder_name)

    result = {
        "folder": folder_path,
        "title": folder_name,
        "year": year_match.group(1) if year_match else None,
        "video": video,
        "poster": poster,
        "fanart": fanart,
        "subtitle": subtitle,
        "images": images,
    }

    # Try to enrich with NFO metadata
    nfo = _fetch_nfo(folder_path)
    if nfo:
        # Use NFO title/year if available (cleaner than folder name)
        if nfo["title"]:
            result["title"] = nfo["title"]
        if nfo["year"]:
            result["year"] = nfo["year"]
        result["nfo"] = nfo

    return result


def cached_get_file_info(file_path):
    """Get single file info from cache."""
    file_path = file_path.strip("/")
    # Determine folder path from file path
    parts = file_path.split("/")
    if len(parts) < 2:
        return None
    filename = parts[-1]
    folder_path = "/" + "/".join(parts[:-1])

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM files WHERE folder_path=? AND name=?",
        (folder_path, filename)
    ).fetchone()
    conn.close()

    if not row:
        return None

    result = {
        "Path": file_path,
        "Name": row["name"],
        "Size": row["size"],
        "MimeType": row["mime_type"],
        "ModTime": row["mod_time"],
        "IsDir": False,
        "ID": row["file_id"],
    }

    if row["file_type"] == "video":
        poster = _find_poster_cached(folder_path)
        if poster:
            result["poster"] = poster

    return result


def cached_search_files(query):
    """Search video files from cache (only videos, no poster/fanart dupes)."""
    conn = get_db()
    like = f"%{query}%"
    rows = conn.execute(
        """SELECT * FROM files
           WHERE name LIKE ?
           AND file_type = 'video'
           ORDER BY size DESC
           LIMIT 100""",
        (like,)
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        entry = {
            "Path": f"{row['folder_path'].lstrip('/')}/{row['name']}",
            "Name": row["name"],
            "Size": row["size"],
            "MimeType": row["mime_type"],
            "ModTime": row["mod_time"],
            "IsDir": False,
        }
        poster = _find_poster_cached(row["folder_path"])
        if poster:
            entry["poster"] = poster
        results.append(entry)
    return results


def cached_all_movies():
    """Return all movie folders sorted A-Z, with poster and title."""
    conn = get_db()
    rows = conn.execute(
        """SELECT f.*, m.title FROM folders f
           LEFT JOIN movie_meta m ON m.folder_path = f.path
           WHERE f.has_video = 1 AND f.depth >= 2
           ORDER BY m.title COLLATE NOCASE ASC, f.name COLLATE NOCASE ASC"""
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        folder_path = row["path"]
        poster = _find_poster_cached(folder_path)
        title = row["title"] or row["name"]
        results.append({
            "path": folder_path,
            "name": row["name"],
            "title": title,
            "poster": poster,
        })
    return results


def _find_poster_cached(folder_path):
    """Find poster name from cache for a given folder."""
    conn = get_db()
    row = conn.execute(
        "SELECT name FROM files WHERE folder_path=? AND file_type='poster' LIMIT 1",
        (folder_path,)
    ).fetchone()
    conn.close()
    return row["name"] if row else None


# ═══════════════════════════════════════════════
#  HTTP Handler
# ═══════════════════════════════════════════════

class TicianoFlixHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        sys.stderr.write(f"[TicianoFlix] {args[0]} {args[1]} {args[2]}\n")

    def _reset_request_state(self):
        """A instancia do handler e reaproveitada em conexoes keep-alive —
        sem isso, cookies e usuario vazariam de uma requisicao para a seguinte."""
        self._pending_cookies = []
        self._user_cache = _UNSET

    def _cookies(self):
        jar = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                jar[k.strip()] = v.strip()
        return jar

    def _current_user(self):
        if getattr(self, "_user_cache", _UNSET) is _UNSET:
            self._user_cache = _session_user(self._cookies().get(SESSION_COOKIE))
        return self._user_cache

    def _has_session(self):
        return self._current_user() is not None

    def _is_admin(self):
        user = self._current_user()
        return bool(user and user.get("role") == "admin")

    def _wants_html(self):
        return "text/html" in (self.headers.get("Accept") or "")

    def _client_ip(self):
        return self.client_address[0] if self.client_address else "?"

    def _queue_cookie(self, value):
        self._pending_cookies = list(getattr(self, "_pending_cookies", [])) + [value]

    def _start_session(self, username):
        self._user_cache = _UNSET
        self._queue_cookie("%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax"
                           % (SESSION_COOKIE, _issue_session(username), SESSION_MAX_AGE))

    def _auth_gate(self, path, params):
        """Decide quem entra. O Chromecast nao manda cookie — para ele o acesso
        vem de um token assinado por arquivo, emitido por /api/cast-token."""
        if not _auth_configured():
            # Primeiro acesso: so a criacao do administrador responde.
            if path in ("/api/auth/setup", "/api/auth/status",
                        "/favicon.ico", "/favicon.svg"):
                return True
            if path in ("/", "/index.html", "/login") or self._wants_html():
                self._send_html(_login_page(setup=True))
                return False
            self._send_json({"status": "error", "error": "setup_required"}, 401)
            return False

        if path in PUBLIC_PATHS:
            return True

        if self._has_session():
            if path in ADMIN_PATHS and not self._is_admin():
                self._send_json(
                    {"status": "error", "error": "Apenas administradores"}, 403)
                return False
            return True

        if path in TOKEN_PATHS and _valid_media_token(
                params.get("path", [""])[0], params.get("t", [""])[0]):
            return True

        if self._wants_html():
            self._send_html(_login_page(setup=False))
            return False
        self._send_json({"status": "error", "error": "auth_required"}, 401)
        return False

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0 or length > MAX_JSON_BODY_BYTES:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return None

    # ── Entrada ──────────────────────────────────────────────
    def _handle_auth_setup(self):
        if _auth_configured():
            self._send_json({"status": "error",
                             "error": "O administrador ja foi criado"}, 409)
            return
        ip = self._client_ip()
        if _login_blocked(ip):
            self._send_json({"status": "error", "error":
                             "Muitas tentativas. Espere alguns minutos."}, 429)
            return
        body = self._read_json_body() or {}
        if not hmac.compare_digest(str(body.get("code", "")).strip(),
                                   _setup_code_value()):
            _record_login_failure(ip)
            sys.stderr.write("[TicianoFlix] codigo de instalacao errado de %s\n" % ip)
            self._send_json({"status": "error", "error":
                             "Codigo de instalacao incorreto. Ele aparece no "
                             "terminal onde o TicianoFlix esta rodando."}, 403)
            return
        username = str(body.get("username", ""))
        problem = _create_user(username, str(body.get("password", "")), role="admin")
        if problem:
            self._send_json({"status": "error", "error": problem}, 400)
            return
        _login_attempts.pop(ip, None)
        self._start_session(username)
        print("[TicianoFlix] Administrador '%s' criado." % _norm_username(username),
              flush=True)
        self._send_json({"status": "ok"})

    def _handle_auth_login(self):
        ip = self._client_ip()
        if _login_blocked(ip):
            self._send_json({"status": "error", "error":
                             "Muitas tentativas. Espere alguns minutos."}, 429)
            return
        body = self._read_json_body() or {}
        username = str(body.get("username", ""))
        user = _check_credentials(username, str(body.get("password", "")))
        if not user:
            _record_login_failure(ip)
            sys.stderr.write("[TicianoFlix] login recusado para '%s' de %s\n"
                             % (_norm_username(username), ip))
            # Mensagem unica: nao revela se a conta existe.
            self._send_json({"status": "error",
                             "error": "Usuario ou senha incorretos"}, 401)
            return
        _login_attempts.pop(ip, None)
        self._start_session(user["username"])
        self._send_json({"status": "ok", "user": user})

    def _handle_auth_logout(self, everywhere=False):
        if everywhere:
            _revoke_all_sessions()
        self._queue_cookie("%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
                           % SESSION_COOKIE)
        self._send_json({"status": "ok"})

    def _handle_cast_token(self):
        """Assina URLs para o Chromecast, que busca a midia sem cookie."""
        body = self._read_json_body() or {}
        media_path = str(body.get("path", ""))
        if not media_path:
            self._send_json({"status": "error", "error": "Missing path"}, 400)
            return
        out = {"status": "ok", "t": _issue_media_token(media_path)}
        subtitle = str(body.get("subtitle", ""))
        if subtitle:
            out["sub"] = _issue_media_token(subtitle)
        self._send_json(out)

    # ── Painel de administracao ──────────────────────────────
    def _handle_users_list(self):
        me = self._current_user() or {}
        self._send_json({"status": "ok", "me": me.get("username"),
                         "users": _list_users()})

    def _handle_user_add(self):
        body = self._read_json_body() or {}
        problem = _create_user(str(body.get("username", "")),
                               str(body.get("password", "")),
                               role=str(body.get("role", "user")))
        if problem:
            self._send_json({"status": "error", "error": problem}, 400)
            return
        self._send_json({"status": "ok", "users": _list_users()})

    def _handle_user_remove(self):
        body = self._read_json_body() or {}
        me = (self._current_user() or {}).get("username", "")
        problem = _remove_user(str(body.get("username", "")), me)
        if problem:
            self._send_json({"status": "error", "error": problem}, 400)
            return
        self._send_json({"status": "ok", "users": _list_users()})

    def _handle_user_role(self):
        body = self._read_json_body() or {}
        me = (self._current_user() or {}).get("username", "")
        problem = _set_user_role(str(body.get("username", "")),
                                 str(body.get("role", "user")), me)
        if problem:
            self._send_json({"status": "error", "error": problem}, 400)
            return
        self._send_json({"status": "ok", "users": _list_users()})

    def _handle_user_password(self):
        """Admin redefine a senha de qualquer conta; cada um troca a propria."""
        body = self._read_json_body() or {}
        me = self._current_user() or {}
        target = _norm_username(str(body.get("username", "")) or me.get("username", ""))
        if target != me.get("username") and me.get("role") != "admin":
            self._send_json({"status": "error",
                             "error": "Apenas administradores"}, 403)
            return
        problem = _set_user_password(target, str(body.get("password", "")))
        if problem:
            self._send_json({"status": "error", "error": problem}, 400)
            return
        # Trocar a propria senha derruba as outras sessoes: renova a atual.
        if target == me.get("username"):
            self._start_session(target)
        self._send_json({"status": "ok"})

    def _security_gate(self):
        """Bloqueia DNS rebinding (Host publico) e leitura cross-site (Origin de
        terceiro). Chromecast e <video> nao mandam Origin e passam normalmente."""
        if not _host_allowed(self.headers.get("Host")):
            self._send_error("Host nao permitido", 403)
            return False
        if not _origin_allowed(self.headers.get("Origin")):
            self._send_error("Origem nao permitida", 403)
            return False
        return True

    def _require_write_origin(self):
        """Operacoes que alteram estado exigem Origin local explicito — e o que
        impede CSRF disparado por <img> ou <form> a partir de qualquer site."""
        origin = self.headers.get("Origin")
        if not origin or not _origin_allowed(origin):
            self._send_json(
                {"status": "error", "error": "Origem invalida para operacao de escrita"}, 403)
            return False
        return True

    def _send_media_cors(self):
        """CORS restrito: '*' apenas quando nao ha Origin (Chromecast, <video>,
        download direto). Com Origin, ecoa somente se for local."""
        origin = self.headers.get("Origin")
        if not origin:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif _origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send_exception(self, e, status=500):
        """Detalhe completo no log do servidor, mensagem generica para o cliente."""
        sys.stderr.write("[TicianoFlix] %s: %r\n" % (self.path, e))
        self._send_json({"status": "error", "error": "Erro interno — veja o log do servidor"}, status)

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        for cookie in getattr(self, "_pending_cookies", ()):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send_html(self, content, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for cookie in getattr(self, "_pending_cookies", ()):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _send_error(self, msg, status=500):
        self._send_json({"error": msg}, status)

    def _stream_file(self, path):
        """Stream a file. Images are cached locally; videos go through rclone proxy."""
        ext = Path(path).suffix.lower()

        # Small images: cache locally after first fetch
        if ext in IMAGE_EXTENSIONS:
            self._stream_image_cached(path)
            return

        # Videos and other files: proxy through rclone serve or fallback
        self._stream_video_direct(path)

    def _stream_image_cached(self, path):
        """Stream an image file, caching it locally on first access."""
        cache_key = path.strip("/").replace("/", "_")
        cache_path = IMAGE_CACHE_DIR / cache_key

        # Serve from local cache if available
        if cache_path.exists():
            mime, _ = mimetypes.guess_type(str(cache_path))
            if mime is None:
                mime = "image/jpeg"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(cache_path.stat().st_size))
            self.send_header("Cache-Control", "max-age=86400")
            self._send_media_cors()
            self.end_headers()
            with open(cache_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            return

        # Not cached yet — download via rclone proxy with retry
        safe_path = urllib.parse.quote(_serve_path(path), safe="/")
        rclone_url = f"http://localhost:{RCLONE_SERVE_PORT}/{safe_path}"

        # Retry up to 3 times with 0.5s delay (rclone serve may still be starting)
        last_error = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(rclone_url, method="GET")
                resp = urllib.request.urlopen(req, timeout=60)

                data = resp.read()
                mime = resp.headers.get("Content-Type", "image/jpeg")

                # Save to local cache
                try:
                    with open(cache_path, "wb") as f:
                        f.write(data)
                    sys.stderr.write(f"[TicianoFlix] Cached image: {cache_key} ({len(data)}B)\n")
                except Exception as e:
                    sys.stderr.write(f"[TicianoFlix] Cache write failed: {e}\n")

                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self._send_media_cors()
                self.end_headers()
                self.wfile.write(data)
                return
            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(0.5)
                    continue

        # All retries failed — fallback to direct
        sys.stderr.write(f"[TicianoFlix] Image cache proxy failed after retries: {last_error}\n")
        self._stream_file_direct(path)

    def _stream_video_direct(self, path):
        """Stream video directly via rclone HTTP serve, proxying through same server.
        Uses http.client + shutil.copyfileobj for zero-buffer streaming."""
        safe_path = urllib.parse.quote(_serve_path(path), safe="/")
        range_header = self.headers.get("Range")
        mime = self._guess_mime(path)

        import http.client
        try:
            conn = http.client.HTTPConnection("localhost", RCLONE_SERVE_PORT, timeout=60)
            conn.request("GET", "/" + safe_path, headers={"Range": range_header} if range_header else {})
            resp = conn.getresponse()

            status = resp.status
            cl = resp.getheader("Content-Length")
            cr = resp.getheader("Content-Range")

            # Se rclone devolveu erro, não repassa o body — retorna erro limpo
            if status in (404, 500, 502, 503):
                resp.read()
                resp.close()
                conn.close()
                sys.stderr.write(f"[TicianoFlix] rclone error {status} for {path}\n")
                self._send_error("Video not available from storage", 502)
                return

            if status == 206:
                self.send_response(206)
                if cr:
                    self.send_header("Content-Range", cr)
            else:
                self.send_response(200)

            if cl:
                self.send_header("Content-Length", cl)
            self.send_header("Content-Type", mime)
            self.send_header("Accept-Ranges", "bytes")
            self._send_media_cors()
            self.end_headers()

            # Stream direto do socket do rclone pro socket do browser
            shutil.copyfileobj(resp, self.wfile, 65536)
            resp.close()
            conn.close()

            # Mark as VFS-cached if range covered the last byte
            if status == 206 and range_header:
                try:
                    file_info = cached_get_file_info(path)
                    file_size = file_info.get("Size", 0) if file_info else 0
                    if file_size > 0:
                        range_match = range_header.replace("bytes=", "").split("-")
                        range_end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else None
                        if range_end is not None and range_end >= file_size - 1:
                            _mark_file_cached(path)
                except Exception:
                    pass
        except Exception as e:
            sys.stderr.write(f"[ERROR] Video stream failed: {e}\n")
            self._stream_file_direct(path)

    def _stream_file_direct(self, path):
        """Fallback: stream directly via rclone cat (original method)."""
        remote_path = _rc_remote(path)

        file_info = cached_get_file_info(path)
        file_size = file_info.get("Size", 0) if file_info else 0

        range_header = self.headers.get("Range")
        start = 0
        end = file_size - 1 if file_size > 0 else None
        chunk_size = 10 * 1024 * 1024

        if range_header:
            range_match = range_header.replace("bytes=", "").split("-")
            try:
                start = int(range_match[0]) if range_match[0] else 0
                if len(range_match) > 1 and range_match[1]:
                    end = int(range_match[1])
                    chunk_size = end - start + 1
                else:
                    end = min(start + chunk_size, file_size - 1) if file_size > 0 else start + chunk_size
                    chunk_size = end - start + 1
            except (ValueError, IndexError):
                pass
        else:
            end = min(chunk_size - 1, file_size - 1) if file_size > 0 else chunk_size - 1
            chunk_size = end + 1

        cat_cmd = ["rclone", "cat"]
        if start > 0:
            cat_cmd.extend(["--offset", str(start)])
        cat_cmd.extend(["--count", str(chunk_size)])
        cat_cmd.append(remote_path)

        mime = self._guess_mime(path)

        if range_header:
            self.send_response(206)
            content_range = f"bytes {start}-{end}/{file_size}" if file_size > 0 else f"bytes {start}-{end}/*"
            self.send_header("Content-Range", content_range)
            self.send_header("Content-Length", str(chunk_size))
            self.send_header("Accept-Ranges", "bytes")
            self._send_media_cors()
            self.send_header("Content-Type", mime)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(chunk_size))
            self.send_header("Accept-Ranges", "bytes")
            self._send_media_cors()
            self.send_header("Content-Type", mime)
            self.end_headers()

        try:
            proc = subprocess.Popen(cat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            remaining = chunk_size
            while remaining > 0:
                buf = proc.stdout.read(min(65536, remaining))
                if not buf:
                    break
                self.wfile.write(buf)
                remaining -= len(buf)
            proc.stdout.close()
            proc.wait(timeout=10)
            # If range covers the last byte of the file, the whole file is cached by rclone
            if proc.returncode == 0 and file_size > 0 and end is not None and end >= file_size - 1:
                _mark_file_cached(path)
        except Exception as e:
            sys.stderr.write(f"[ERROR] Direct stream failed: {e}\n")

    def _serve_subtitle(self, path):
        """Serve a subtitle file, converting SRT→VTT if needed.
        Caches locally on first fetch for speed."""
        cache_key = "sub_" + path.strip("/").replace("/", "_").replace(" ", "_")
        cache_path = SUBS_CACHE_DIR / cache_key

        # Try local cache first
        try:
            if cache_path.exists():
                raw = cache_path.read_text(encoding="utf-8", errors="replace")
            else:
                raise FileNotFoundError
        except (OSError, FileNotFoundError):
            # Fetch via rclone cat
            remote_path = _rc_remote(path)
            try:
                result = subprocess.run(
                    ["rclone", "cat", remote_path],
                    capture_output=True, timeout=30
                )
                if result.returncode != 0:
                    self._send_error("Subtitle not found", 404)
                    return
                # Tenta UTF-8 primeiro, fallback pra latin-1 (comum em SRT)
                raw_bytes = result.stdout
                try:
                    raw = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    raw = raw_bytes.decode("latin-1")
                # Cache local (sempre UTF-8)
                try:
                    cache_path.write_text(raw, encoding="utf-8")
                except Exception:
                    pass
            except Exception as e:
                sys.stderr.write(f"[TicianoFlix] Subtitle fetch failed: {e}\n")
                self._send_error("Subtitle not found", 404)
                return

        ext = Path(path).suffix.lower()

        # SRT → WebVTT conversion (browsers don't support SRT natively)
        if ext == ".srt":
            # Normalize line endings (CRLF de SRTs de Windows)
            text = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("\n")
            lines = text.split("\n")
            # Cabeçalho WEBVTT SEMPRE seguido de linha em branco — parsers
            # estritos (receiver do Chromecast) rejeitam o arquivo sem ela
            vtt = ["WEBVTT", ""]
            for line in lines:
                # SRT: 00:00:10,500 --> 00:00:13,000
                # VTT: 00:00:10.500 --> 00:00:13.000
                if "-->" in line:
                    line = line.replace(",", ".")
                vtt.append(line)
            body = "\n".join(vtt)
        else:
            # VTT/ASS already supported or passed through
            body = raw

        self.send_response(200)
        self.send_header("Content-Type", "text/vtt; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_media_cors()
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _guess_mime(self, path):
        """Guess MIME type for a file."""
        mime, _ = mimetypes.guess_type(path)
        if mime:
            return mime
        ext = Path(path).suffix.lower()
        MIME_MAP = {
            ".mp4": "video/mp4",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".wmv": "video/x-ms-wmv",
            ".flv": "video/x-flv",
            ".m4v": "video/mp4",
            ".mpg": "video/mpeg",
            ".mpeg": "video/mpeg",
            ".ts": "video/mp2t",
            ".3gp": "video/3gpp",
            ".ogg": "video/ogg",
        }
        return MIME_MAP.get(ext, "application/octet-stream")

    def _serve_file(self, path):
        """Serve arquivo estatico. Ancorado numa allowlist: apenas os favicons da
        raiz e o conteudo de static/. Antes a raiz inteira era alcancavel via
        /static/../ — o que expunha server.py e o diretorio .git."""
        project_root = Path(__file__).parent.resolve()
        rel = path.lstrip("/")
        if rel in ("favicon.ico", "favicon.svg"):
            base = project_root
        elif rel.startswith("static/"):
            base = (project_root / "static").resolve()
            rel = rel[len("static/"):]
        else:
            self._send_error("Forbidden", 403)
            return
        try:
            requested = (base / rel).resolve()
            requested.relative_to(base)
        except (ValueError, RuntimeError):
            self._send_error("Forbidden", 403)
            return
        if not requested.exists() or not requested.is_file():
            self._send_error("File not found", 404)
            return
        mime, _ = mimetypes.guess_type(str(requested))
        if mime is None:
            mime = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(requested.stat().st_size))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        with open(requested, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def _generate_backup_zip(self):
        """Generate backup zip to a temporary file. Returns path to temp file."""
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                db_path = Path(DB_PATH)
                if db_path.exists():
                    z.write(db_path, "ticianoflix.db")
                img_dir = Path(IMAGE_CACHE_DIR)
                if img_dir.exists():
                    for f in sorted(img_dir.iterdir()):
                        if f.is_file():
                            z.write(f, f"images/{f.name}")
                subs_dir = Path(SUBS_CACHE_DIR)
                if subs_dir.exists():
                    for f in sorted(subs_dir.iterdir()):
                        if f.is_file():
                            z.write(f, f"subs/{f.name}")
            tmp.close()
            return tmp.name
        except Exception:
            tmp.close()
            os.unlink(tmp.name)
            raise

    def _serve_backup(self):
        """Generate and serve a zip backup of DB + images + subs (streamed)."""
        import tempfile
        zip_path = None
        try:
            zip_path = self._generate_backup_zip()
            zip_size = os.path.getsize(zip_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="ticianoflix-backup.zip"')
            self.send_header("Content-Length", str(zip_size))
            self._send_media_cors()
            self.end_headers()
            with open(zip_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        except Exception as e:
            sys.stderr.write(f"[TicianoFlix] Backup failed: {e}\n")
            self._send_error("Failed to generate backup")
        finally:
            if zip_path and os.path.exists(zip_path):
                try:
                    os.unlink(zip_path)
                except Exception:
                    pass

    def _backup_to_drive(self):
        """Gera o zip e sobe pro Drive usando o remote de escrita.

        O remote principal e somente-leitura; so este caminho escreve, e ele
        usa um token com scope drive.file — que enxerga exclusivamente os
        arquivos criados pelo proprio TicianoFlix."""
        zip_path = None
        try:
            zip_path = self._generate_backup_zip()
            filename = f"ticianoflix-backup-{time.strftime('%Y-%m-%d')}.zip"
            remote_path = f"{RCLONE_BACKUP_REMOTE}{BACKUP_FOLDER}/{filename}"

            with open(zip_path, "rb") as f:
                data = f.read()

            proc = subprocess.run(
                ["rclone", "rcat", remote_path],
                input=data,
                capture_output=True,
                timeout=120
            )
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace").strip()
                if "didn't find section in config file" in err:
                    return {"ok": False, "error":
                            "O remote de backup nao esta configurado. "
                            "Rode: ./setup-rclone-seguro.sh"}
                return {"ok": False, "error": f"rclone failed: {err}"}

            return {"ok": True, "path": f"{BACKUP_FOLDER}/{filename}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if zip_path and os.path.exists(zip_path):
                try:
                    os.unlink(zip_path)
                except Exception:
                    pass

    def _handle_restore_from_drive(self):
        """Find latest backup zip in Drive, download and restore."""
        try:
            # Lista pelo remote de backup: com scope drive.file ele so enxerga
            # os arquivos que o proprio TicianoFlix criou.
            result = run_rclone_cmd(
                ["lsjson", f"{RCLONE_BACKUP_REMOTE}{BACKUP_FOLDER}"])
            if not isinstance(result, list):
                self._send_error(
                    "Nao foi possivel listar os backups. O remote de backup "
                    "esta configurado? Rode: ./setup-rclone-seguro.sh")
                return

            zips = [f for f in result if f.get("Name", "").startswith("ticianoflix-backup-") and f.get("Name", "").endswith(".zip")]
            if not zips:
                self._send_error("Nenhum backup encontrado no Google Drive")
                return

            # Get most recent by ModTime
            zips.sort(key=lambda f: f.get("ModTime", ""), reverse=True)
            latest = zips[0]
            name = latest["Name"]

            self._send_json({"status": "downloading", "file": name})

            # Download in background thread
            def _do_restore():
                try:
                    remote = f"{RCLONE_BACKUP_REMOTE}{BACKUP_FOLDER}/{name}"
                    proc = subprocess.run(
                        ["rclone", "cat", remote],
                        capture_output=True, timeout=120
                    )
                    if proc.returncode != 0:
                        msg = f"Falha ao baixar backup: {proc.stderr.decode(errors='replace')}"
                        print(f"[TicianoFlix] {msg}", flush=True)
                        # Log to DB for user to see on next refresh
                        _log_notification("error", msg)
                        return

                    buf = io.BytesIO(proc.stdout)
                    with zipfile.ZipFile(buf, "r") as z:
                        names = z.namelist()
                        if "ticianoflix.db" not in names:
                            msg = "Backup zip não contém ticianoflix.db"
                            print(f"[TicianoFlix] {msg}", flush=True)
                            _log_notification("error", msg)
                            return
                        db_path = Path(DB_PATH)
                        if db_path.exists():
                            shutil.copy2(db_path, db_path.with_suffix(".db.bak"))
                        db_path.write_bytes(z.read("ticianoflix.db"))
                        img_dir = Path(IMAGE_CACHE_DIR)
                        img_dir.mkdir(exist_ok=True)
                        for n in names:
                            if n.startswith("images/") and not n.endswith("/"):
                                (img_dir / Path(n).name).write_bytes(z.read(n))
                        subs_dir = Path(SUBS_CACHE_DIR)
                        subs_dir.mkdir(exist_ok=True)
                        for n in names:
                            if n.startswith("subs/") and not n.endswith("/"):
                                (subs_dir / Path(n).name).write_bytes(z.read(n))
                    msg = f"Backup restaurado com sucesso: {name}"
                    print(f"[TicianoFlix] {msg}", flush=True)
                    _log_notification("success", msg)
                except Exception as e:
                    msg = f"Falha ao restaurar do Drive: {e}"
                    print(f"[TicianoFlix] {msg}", flush=True)
                    _log_notification("error", msg)

            threading.Thread(target=_do_restore, daemon=True).start()

        except Exception as e:
            self._send_error(f"Falha ao restaurar do Drive: {e}")

    def do_POST(self):
        self._reset_request_state()
        if not self._security_gate():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if not self._require_write_origin():
            return

        # Login e criacao de senha vem antes do gate — sao a porta de entrada.
        if path == "/api/auth/setup":
            self._handle_auth_setup()
            return

        if path == "/api/auth/login":
            self._handle_auth_login()
            return

        if not self._auth_gate(path, urllib.parse.parse_qs(parsed.query)):
            return

        if path == "/api/auth/logout":
            self._handle_auth_logout(
                everywhere=(self._read_json_body() or {}).get("everywhere", False))
            return

        if path == "/api/cast-token":
            self._handle_cast_token()
            return

        if path == "/api/users/add":
            self._handle_user_add()
            return

        if path == "/api/users/remove":
            self._handle_user_remove()
            return

        if path == "/api/users/role":
            self._handle_user_role()
            return

        if path == "/api/users/password":
            self._handle_user_password()
            return

        # Rotas que antes eram GET e alteravam estado (scan, cache, restore).
        # O corpo do handler continua em do_GET; aqui so liberamos a execucao.
        if path in WRITE_ROUTES:
            self._write_ok = True
            try:
                self.do_GET()
            finally:
                self._write_ok = False
            return

        if path == "/api/restore":
            self._handle_restore()
            return

        if path == "/api/progress":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len == 0:
                    self._send_json({"status": "error", "error": "Empty body"}, 400)
                    return
                if content_len > MAX_JSON_BODY_BYTES:
                    self._send_json({"status": "error", "error": "Corpo grande demais"}, 413)
                    return
                raw = self.rfile.read(content_len)
                body = json.loads(raw)
                folder_path = body.get("path", "").strip()
                position = float(body.get("position", 0))
                duration = float(body.get("duration", 0))
                if not folder_path:
                    self._send_json({"status": "error", "error": "Missing path"}, 400)
                    return
                conn = get_db()
                conn.execute(
                    "INSERT OR REPLACE INTO watch_progress (folder_path, position_seconds, duration_seconds, updated_at) VALUES (?, ?, ?, ?)",
                    (folder_path, position, duration, time.time())
                )
                conn.commit()
                conn.close()
                self._send_json({"status": "ok"})
            except Exception as e:
                self._send_exception(e)
            return

        if path == "/api/rclone/webgui/start":
            self._send_json(start_rclone_webgui())
            return

        if path == "/api/rclone/webgui/stop":
            self._send_json(stop_rclone_webgui())
            return

        if path == "/api/rclone/serve/restart":
            self._send_json(restart_rclone_serve())
            return

        self._send_error("Not found", 404)

    def _handle_restore(self):
        """Restore backup from uploaded zip file."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0:
                self._send_error("Empty request", 400)
                return
            if content_len > MAX_RESTORE_BYTES:
                self._send_error("Backup grande demais", 413)
                return
            data = self.rfile.read(content_len)
            buf = io.BytesIO(data)
            with zipfile.ZipFile(buf, "r") as z:
                names = z.namelist()
                if "ticianoflix.db" not in names:
                    self._send_error("Backup must contain ticianoflix.db", 400)
                    return
                if z.getinfo("ticianoflix.db").file_size > MAX_RESTORE_BYTES:
                    self._send_error("Banco do backup grande demais", 413)
                    return
                db_bytes = z.read("ticianoflix.db")
                if not _looks_like_ticianoflix_db(db_bytes):
                    self._send_error(
                        "O arquivo nao e um banco valido do TicianoFlix", 400)
                    return
                db_path = Path(DB_PATH)
                if db_path.exists():
                    shutil.copy2(db_path, db_path.with_suffix(".db.bak"))
                db_path.write_bytes(db_bytes)
                img_dir = Path(IMAGE_CACHE_DIR)
                img_dir.mkdir(exist_ok=True)
                for name in names:
                    if name.startswith("images/") and not name.endswith("/"):
                        (img_dir / Path(name).name).write_bytes(z.read(name))
                subs_dir = Path(SUBS_CACHE_DIR)
                subs_dir.mkdir(exist_ok=True)
                for name in names:
                    if name.startswith("subs/") and not name.endswith("/"):
                        (subs_dir / Path(name).name).write_bytes(z.read(name))
            self._send_json({"status": "ok", "message": "Backup restaurado com sucesso"})
        except Exception as e:
            sys.stderr.write("[TicianoFlix] restore falhou: %r\n" % (e,))
            self._send_error("Falha ao restaurar o backup")

    def do_GET(self):
        self._reset_request_state()
        if not self._security_gate():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if not self._auth_gate(path, params):
            return

        if path == "/login":
            if self._has_session():
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            self._send_html(_login_page(setup=not _auth_configured()))
            return

        if path == "/api/auth/status":
            user = self._current_user()
            self._send_json({"configured": _auth_configured(),
                             "authenticated": user is not None,
                             "user": user})
            return

        if path == "/api/users":
            self._handle_users_list()
            return

        # Rotas de escrita chegam aqui apenas quando redespachadas por do_POST.
        if path in WRITE_ROUTES and not getattr(self, "_write_ok", False):
            self._send_json(
                {"status": "error", "error": "Use POST para esta operacao"}, 405)
            return

        # Serve frontend
        if path == "/" or path == "/index.html":
            html_content = FRONTEND_PATH.read_text(encoding="utf-8") if FRONTEND_PATH.exists() else "<h1>TicianoFlix</h1><p>Frontend not found.</p>"
            # Inject HTTP base URL for Chromecast media streaming
            # (Chromecast doesn't trust self-signed certs, so media must use HTTP)
            html_content = html_content.replace(
                "</head>",
                f"<script>window.__HTTP_BASE__='http://{_get_local_ip()}:{PORT}';</script></head>",
                1
            )
            self._send_html(html_content)
            return

        # Favicon (serve from project root)
        if path == "/favicon.ico" or path == "/favicon.svg":
            self._serve_file(path)
            return

        # Static files
        if path.startswith("/static/"):
            self._serve_file(path)
            return

        # API: Refresh cache (scan drive)
        if path == "/api/refresh":
            global _scan_in_progress, _scan_progress
            with _scan_lock:
                if _scan_in_progress:
                    self._send_json({"status": "already_scanning"})
                    return
                _scan_in_progress = True

            def scan_wrapper():
                global _scan_in_progress, _scan_progress
                try:
                    scan_drive()
                except Exception as e:
                    with _scan_progress_lock:
                        _scan_progress["phase"] = "error"
                    print(f"[TicianoFlix] Scan error: {e}", flush=True)
                finally:
                    with _scan_lock:
                        _scan_in_progress = False

            # Reset progress
            with _scan_progress_lock:
                _scan_progress = {
                    "phase": "",
                    "genre_current": "",
                    "genre_index": 0,
                    "genre_total": 0,
                    "movie_current": "",
                    "movie_index": 0,
                    "movie_total": 0,
                    "percent": 0,
                }

            self._send_json({"status": "scanning"})
            threading.Thread(target=scan_wrapper, daemon=True).start()
            return

        # API: Scan progress
        if path == "/api/scan-progress":
            with _scan_progress_lock:
                self._send_json(dict(_scan_progress))
            return

        # API: Download backup (.zip)
        if path == "/api/backup":
            self._serve_backup()
            return

        # API: Backup to Drive (salva em ~/Downloads/ + serve)
        if path == "/api/backup/local":
            db_path = DB_PATH
            if not db_path.exists():
                self._send_error("Database not found", 404)
                return

            downloads = Path.home() / "Downloads"
            downloads.mkdir(exist_ok=True)
            today = time.strftime("%Y-%m-%d")
            backup_name = f"ticianoflix-backup-{today}.db"
            backup_path = downloads / backup_name

            try:
                import shutil as _shutil
                _shutil.copy2(db_path, backup_path)
                saved_path = str(backup_path)
            except Exception:
                saved_path = str(db_path)

            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{backup_name}"')
            self.send_header("Content-Length", str(db_path.stat().st_size))
            self._send_media_cors()
            self.send_header("X-Backup-Path", saved_path)
            self.end_headers()
            with open(db_path, "rb") as f:
                self.wfile.write(f.read())
            return

        # API: Backup to Google Drive
        if path == "/api/backup/drive":
            result = self._backup_to_drive()
            if result["ok"]:
                self._send_json({"status": "ok", "path": result["path"]})
            else:
                self._send_json({"status": "error", "error": result["error"]}, 500)
            return

        # API: Restore backup from Google Drive
        if path == "/api/restore/drive":
            self._handle_restore_from_drive()
            return

        # API: Cache manager — returns all movies with cached status
        if path == "/api/cache-manager":
            try:
                movies = cached_all_movies()
                result = []
                for m in movies:
                    folder_path = m["path"]
                    cached = False
                    # Check if any video file in this folder is cached
                    conn_ck = get_db()
                    rows_ck = conn_ck.execute(
                        "SELECT name FROM files WHERE folder_path=? AND file_type='video' LIMIT 1",
                        (folder_path,)
                    ).fetchall()
                    if not rows_ck:
                        rows_ck = conn_ck.execute(
                            "SELECT name FROM files WHERE folder_path=? AND file_type='video' LIMIT 1",
                            (folder_path.strip("/"),)
                        ).fetchall()
                    conn_ck.close()
                    for row_ck in rows_ck:
                        file_path = folder_path.strip("/") + "/" + row_ck["name"]
                        if _is_file_cached(file_path):
                            cached = True
                            break
                    result.append({
                        "path": folder_path,
                        "name": m["name"],
                        "title": m["title"],
                        "poster": m["poster"],
                        "cached": cached,
                    })
                self._send_json(result)
            except Exception as e:
                self._send_exception(e)
            return

        # API: Download a movie file to cache (forces VFS caching in background)
        if path == "/api/cache-download":
            folder_path = params.get("path", [""])[0]
            if not folder_path:
                self._send_json({"status": "error", "error": "Missing path"}, 400)
                return
            try:
                # Find the video file for this folder
                conn = get_db()
                row = conn.execute(
                    "SELECT name FROM files WHERE folder_path=? AND file_type='video' LIMIT 1",
                    (folder_path,)
                ).fetchone()
                conn.close()
                if not row:
                    # Try without leading slash
                    conn2 = get_db()
                    row2 = conn2.execute(
                        "SELECT name FROM files WHERE folder_path=? AND file_type='video' LIMIT 1",
                        (folder_path.strip("/"),)
                    ).fetchone()
                    conn2.close()
                    if not row2:
                        self._send_json({"status": "error", "error": "No video found"}, 404)
                        return
                    row = row2
                video_name = row["name"]
                video_path = folder_path.strip("/") + "/" + video_name

                # Check if already cached
                if _is_file_cached(video_path):
                    self._send_json({"status": "already_cached", "path": video_path})
                    return

                # Start background download (forces VFS caching via rclone serve HTTP)
                def _do_cache_download(file_path, total_bytes):
                    try:
                        print(f"[TicianoFlix] Cache download starting: {file_path} ({total_bytes}B)", flush=True)

                        with _download_progress_lock:
                            _download_progress[file_path] = {"percent": 0, "status": "downloading", "total": total_bytes, "downloaded": 0}

                        if total_bytes <= 0:
                            # Can't track progress without size, just mark as cached
                            _mark_file_cached(file_path)
                            with _download_progress_lock:
                                _download_progress[file_path] = {"percent": 100, "status": "done"}
                            print(f"[TicianoFlix] Cache marked (no size info): {file_path}", flush=True)
                            return

                        # Use HTTP range requests against rclone serve to force VFS caching
                        safe_url_path = urllib.parse.quote(_serve_path(file_path), safe="/")
                        rclone_url = f"http://localhost:{RCLONE_SERVE_PORT}/{safe_url_path}"
                        CHUNK = 5 * 1024 * 1024  # 5MB chunks (same as frontend)
                        downloaded = 0

                        while downloaded < total_bytes:
                            end = min(downloaded + CHUNK - 1, total_bytes - 1)
                            range_hdr = f"bytes={downloaded}-{end}"
                            try:
                                req = urllib.request.Request(rclone_url, method="GET")
                                req.add_header("Range", range_hdr)
                                with urllib.request.urlopen(req, timeout=120) as resp:
                                    while True:
                                        buf = resp.read(65536)
                                        if not buf:
                                            break
                                        downloaded += len(buf)
                                        pct = min(99, int((downloaded / total_bytes) * 100))
                                        with _download_progress_lock:
                                            _download_progress[file_path] = {
                                                "percent": pct, "status": "downloading",
                                                "total": total_bytes, "downloaded": downloaded
                                            }
                            except Exception as chunk_err:
                                print(f"[TicianoFlix] Cache chunk error at {downloaded}: {chunk_err}", flush=True)
                                # Retry once
                                try:
                                    req2 = urllib.request.Request(rclone_url, method="GET")
                                    req2.add_header("Range", range_hdr)
                                    with urllib.request.urlopen(req2, timeout=120) as resp2:
                                        while True:
                                            buf = resp2.read(65536)
                                            if not buf:
                                                break
                                            downloaded += len(buf)
                                            pct = min(99, int((downloaded / total_bytes) * 100))
                                            with _download_progress_lock:
                                                _download_progress[file_path] = {
                                                    "percent": pct, "status": "downloading",
                                                    "total": total_bytes, "downloaded": downloaded
                                                }
                                except Exception:
                                    raise

                        # Mark as fully cached
                        _mark_file_cached(file_path)
                        with _download_progress_lock:
                            _download_progress[file_path] = {"percent": 100, "status": "done"}
                        print(f"[TicianoFlix] Cache download complete: {file_path}", flush=True)
                    except Exception as e:
                        print(f"[TicianoFlix] Cache download error: {e}", flush=True)
                        with _download_progress_lock:
                            _download_progress[file_path] = {"percent": 0, "status": "error"}

                # Get file size first (needed for progress tracking)
                file_size = 0
                # Prefer DB size (fastest, most reliable)
                try:
                    conn_sz = get_db()
                    row_sz = conn_sz.execute(
                        "SELECT size FROM files WHERE folder_path=? AND file_type='video' LIMIT 1",
                        (folder_path.strip("/"),)
                    ).fetchone()
                    if not row_sz:
                        row_sz = conn_sz.execute(
                            "SELECT size FROM files WHERE folder_path=? AND file_type='video' LIMIT 1",
                            (folder_path,)
                        ).fetchone()
                    conn_sz.close()
                    if row_sz and row_sz["size"] > 0:
                        file_size = row_sz["size"]
                except Exception:
                    pass

                t = threading.Thread(target=_do_cache_download, args=(video_path, file_size), daemon=True)
                t.start()
                self._send_json({"status": "started", "path": video_path, "name": video_name, "size": file_size})
            except Exception as e:
                self._send_exception(e)
            return

        # API: Download progress for a video being cached
        if path == "/api/cache-download-progress":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_json({"percent": 0, "status": "unknown"})
                return
            with _download_progress_lock:
                prog = dict(_download_progress.get(file_path, {"percent": 0, "status": "unknown"}))
            self._send_json(prog)
            return

        # API: Check if file is fully cached in rclone VFS
        if path == "/api/check-cached":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_json({"cached": False})
                return
            self._send_json({"cached": _is_file_cached(file_path)})
            return

        # API: Clear all caches (VFS, DB cache markers)
        if path == "/api/clear-cache":
            try:
                import shutil as sh
                # Clear VFS cache (downloaded videos)
                vfs_cache = Path.home() / ".cache" / "rclone" / "vfs"
                if vfs_cache.exists():
                    for entry in vfs_cache.iterdir():
                        if entry.is_dir():
                            sh.rmtree(entry)
                # Clear cached files list
                global _cached_files
                with _cached_files_lock:
                    _cached_files.clear()
                    if CACHED_FILES_PATH.exists():
                        CACHED_FILES_PATH.unlink()
                # Clear DB cache timestamps
                conn = get_db()
                conn.execute("DELETE FROM cache_meta")
                conn.commit()
                conn.close()
                self._send_json({"status": "ok"})
            except Exception as e:
                self._send_exception(e)
            return

        # API: Remove single movie from VFS cache
        if path == "/api/uncache":
            folder_path = params.get("path", [""])[0]
            if not folder_path:
                self._send_json({"status": "error", "error": "Missing path"}, 400)
                return
            # Um caminho vazio ou minusculo casaria com todo o cache VFS.
            if len(folder_path.strip("/")) < 2 or folder_path.strip("/") in (".", ".."):
                self._send_json({"status": "error", "error": "Caminho invalido"}, 400)
                return
            try:
                # Get the video file name from the database directly
                video_name = ""
                try:
                    conn = get_db()
                    folder = folder_path.strip("/")
                    cur = conn.execute(
                        "SELECT name FROM files WHERE folder_path = ? AND extension IN ('.mp4','.mkv','.avi','.mov','.webm') LIMIT 1",
                        (folder,)
                    )
                    row = cur.fetchone()
                    if row:
                        video_name = row[0]
                    conn.close()
                except Exception:
                    pass
                
                # Remove from cached_files list
                with _cached_files_lock:
                    to_remove = {p for p in _cached_files if folder_path.strip("/") in p}
                    _cached_files -= to_remove
                    CACHED_FILES_PATH.write_text(json.dumps(list(_cached_files)))

                # Remove VFS cache files from rclone cache directory
                vfs_cache = Path.home() / ".cache" / "rclone" / "vfs"
                if vfs_cache.exists():
                    removed = 0
                    # rclone VFS cache stores files under gdrive{hash}/<full remote path>
                    # Search recursively for any file/dir containing the folder path
                    folder_stripped = folder_path.strip("/")
                    for entry in vfs_cache.rglob("*"):
                        if entry.is_file():
                            if _vfs_segment_match(str(entry), folder_stripped):
                                entry.unlink()
                                removed += 1
                        elif entry.is_dir() and _vfs_segment_match(str(entry), folder_stripped):
                            import shutil
                            shutil.rmtree(entry, ignore_errors=True)
                            removed += 1
                    # Also try matching just the folder name (last path component)
                    folder_last = folder_stripped.split("/")[-1]
                    for entry in vfs_cache.rglob("*"):
                        if entry.is_file() and _vfs_segment_match(str(entry), folder_last):
                            # Check if it's a parent match (not already deleted)
                            if entry.exists():
                                entry.unlink()
                                removed += 1
                    if removed > 0:
                        print(f"[TicianoFlix] Removed {removed} VFS cache entries for {folder_path}", flush=True)
                    else:
                        # Fallback: clear entire VFS cache for this folder path using simple hash search
                        for entry in vfs_cache.iterdir():
                            if entry.is_dir():
                                for cached_file in entry.rglob("*"):
                                    if cached_file.is_file():
                                        cached_str = str(cached_file)
                                        _flat = folder_path.strip("/").replace("/", "_")
                                        if len(_flat) >= 2 and _flat in cached_str:
                                            cached_file.unlink()
                                            removed += 1
                        if removed > 0:
                            print(f"[TicianoFlix] Removed {removed} VFS cache entries (deep) for {folder_path}", flush=True)

                self._send_json({"status": "ok"})
            except Exception as e:
                self._send_exception(e)
            return

        # API: Cache status
        if path == "/api/cache-status":
            cache_time = get_cache_time()
            stale = is_cache_stale()
            usage = get_cache_usage()
            conn = get_db()
            genres = conn.execute("SELECT COUNT(*) as c FROM folders WHERE depth=1").fetchone()["c"]
            movies = conn.execute("SELECT COUNT(*) as c FROM folders WHERE has_video=1 AND depth=2").fetchone()["c"]
            files = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
            conn.close()
            self._send_json({
                "cached": cache_time is not None,
                "last_updated": cache_time,
                "stale": stale,
                "genres": genres,
                "movies": movies,
                "files": files,
                "usage": usage,
            })
            return

        # API: List genres with content (from cache)
        if path == "/api/genres":
            conn = get_db()
            genre_rows = conn.execute(
                "SELECT * FROM folders WHERE depth=1 AND has_video=1 ORDER BY name"
            ).fetchall()
            conn.close()
            data = {
                "path": "/TicianoFlix",
                "folders": [
                    {
                        "Path": row["path"].lstrip("/"),
                        "Name": row["name"],
                        "Size": 0,
                        "MimeType": "inode/directory",
                        "ModTime": "",
                        "IsDir": True,
                        "has_video": True,
                    }
                    for row in genre_rows
                ],
                "videos": [],
                "subtitles": [],
                "images": [],
            }
            self._send_json(data)
            return

        # API: Recent movies sorted by creation time (from cache)
        if path == "/api/recent-movies":
            conn = get_db()
            limit = 50
            try:
                limit = min(int(params.get("limit", ["50"])[0]), 200)
            except (ValueError, IndexError):
                pass
            movie_rows = conn.execute(
                """SELECT * FROM folders
                   WHERE depth=2 AND has_video=1
                   ORDER BY mod_time DESC, name ASC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            conn.close()

            movies = []
            for row in movie_rows:
                movie_path = row["path"]
                poster = _find_poster_cached(movie_path)
                nfo = _fetch_nfo_from_db(movie_path)
                title = None
                if nfo and nfo.get("title"):
                    title = nfo["title"]
                movies.append({
                    "path": movie_path,
                    "name": row["name"],
                    "mod_time": row["mod_time"],
                    "poster": poster,
                    "title": title,
                })
            self._send_json(movies)
            return

        # API: Continue watching — movies with saved progress
        if path == "/api/continue-watching":
            conn = get_db()
            rows = conn.execute(
                """SELECT p.*, f.name FROM watch_progress p
                   LEFT JOIN folders f ON f.path = p.folder_path
                   WHERE p.position_seconds > 0
                   ORDER BY p.updated_at DESC
                   LIMIT 20"""
            ).fetchall()
            conn.close()
            result = []
            for row in rows:
                folder_path = row["folder_path"]
                poster = _find_poster_cached(folder_path)
                nfo = _fetch_nfo_from_db(folder_path)
                title = None
                if nfo and nfo.get("title"):
                    title = nfo["title"]
                result.append({
                    "path": folder_path,
                    "name": row["name"] or folder_path.strip("/").split("/")[-1],
                    "position": row["position_seconds"],
                    "duration": row["duration_seconds"],
                    "poster": poster,
                    "title": title,
                })
            self._send_json(result)
            return

        # API: Get progress for a single movie
        if path == "/api/progress":
            folder_path = params.get("path", [""])[0]
            if not folder_path:
                self._send_json({"position": 0, "duration": 0})
                return
            conn = get_db()
            row = conn.execute(
                "SELECT * FROM watch_progress WHERE folder_path=?",
                (folder_path,)
            ).fetchone()
            conn.close()
            if row:
                self._send_json({
                    "position": row["position_seconds"],
                    "duration": row["duration_seconds"],
                })
            else:
                self._send_json({"position": 0, "duration": 0})
            return

        # API: List directory (from cache)
        if path == "/api/list":
            dir_path = params.get("path", [""])[0]

            # On root, auto-redirect to TicianoFlix
            if dir_path == "" or dir_path == "/":
                dir_path = "/TicianoFlix"

            data = cached_list_directory(dir_path)
            if data is None:
                self._send_error("Path not found in cache", 404)
                return

            # Ensure empty lists for missing keys
            data.setdefault("folders", [])
            data.setdefault("videos", [])
            data.setdefault("subtitles", [])
            data.setdefault("images", [])

            # No auto-scan — user must click refresh manually
            # If cache is empty, just show whatever we have (will be empty)

            self._send_json(data)
            return

        # API: Movie detail (from cache)
        if path == "/api/movie-detail":
            folder_path = params.get("path", [""])[0]
            if not folder_path:
                self._send_error("Missing 'path' parameter", 400)
                return

            data = cached_movie_detail(folder_path)
            self._send_json(data)
            return

        # API: Search (from cache)
        if path == "/api/search":
            query = params.get("q", [""])[0]
            if not query:
                self._send_error("Missing 'q' parameter", 400)
                return
            results = cached_search_files(query)
            self._send_json({"results": results})
            return

        # API: All movies A-Z (from cache)
        if path == "/api/all-movies":
            results = cached_all_movies()
            self._send_json(results)
            return

        # API: Stream (live from rclone)
        if path == "/api/stream":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_error("Missing 'path' parameter", 400)
                return
            self._stream_file(file_path)
            return

        # API: Subtitle (serve as WebVTT for browser)
        if path == "/api/subtitle":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_error("Missing 'path' parameter", 400)
                return
            self._serve_subtitle(file_path)
            return

        # API: File info (from cache)
        if path == "/api/info":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_error("Missing 'path' parameter", 400)
                return
            item = cached_get_file_info(file_path)
            if item:
                self._send_json(item)
            else:
                self._send_error("File not found", 404)
            return

        # API: rclone status (instalação, remote gdrive, streaming, web UI)
        if path == "/api/rclone/status":
            self._send_json(get_rclone_status())
            return

        # Fallback 404
        self._send_error("Not found", 404)


# ──────────────────────────────────────────────
#  SSL / HTTPS (self-signed cert for Chromecast)
# ──────────────────────────────────────────────

def _get_local_ip():
    """Get the local network IP address for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        # Doesn't actually connect — just used to determine the preferred local IP
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    return HOST


def _ensure_ssl_cert(cert_dir, local_ip):
    """Generate a locally-trusted SSL cert using mkcert (preferred) or openssl.

    mkcert creates a CA-trusted certificate — required by the Cast SDK
    (self-signed certs are rejected even with correct SAN).
    Regenerates if the IP changes.
    Returns (cert_path, key_path) or (None, None) on failure.
    """
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"

    # Check if existing cert is still valid for this IP
    if cert_path.exists() and key_path.exists():
        try:
            existing = subprocess.run(
                ["openssl", "x509", "-in", str(cert_path), "-noout", "-text"],
                check=True, capture_output=True, timeout=10, text=True,
            )
            if local_ip in existing.stdout:
                return cert_path, key_path
            print(f"[TicianoFlix] IP changed ({local_ip}), regenerating SSL cert...", flush=True)
            cert_path.unlink(missing_ok=True)
            key_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Prefer mkcert (CA-trusted = Cast SDK works)
    mkcert = subprocess.run(["which", "mkcert"], capture_output=True, text=True, timeout=5)
    if mkcert.returncode == 0:
        print("[TicianoFlix] Generating CA-trusted SSL certificate via mkcert...", flush=True)
        try:
            subprocess.run(
                ["mkcert", "-key-file", str(key_path), "-cert-file", str(cert_path),
                 "localhost", local_ip, "ticianoflix.local"],
                check=True, capture_output=True, timeout=15,
            )
            key_path.chmod(0o600)
            print(f"[TicianoFlix] mkcert cert created: {cert_path}", flush=True)
            return cert_path, key_path
        except Exception as e:
            print(f"[TicianoFlix] mkcert failed ({e}), falling back to openssl...", flush=True)

    # Fallback: openssl self-signed (Cast SDK may not work)
    print("[TicianoFlix] Generating self-signed SSL certificate via openssl...", flush=True)
    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(key_path),
                "-out", str(cert_path),
                "-days", "3650",
                "-nodes",
                "-subj", "/CN=TicianoFlix",
                "-addext", f"subjectAltName=DNS:localhost,DNS:ticianoflix.local,IP:{local_ip}",
            ],
            check=True, capture_output=True, timeout=15,
        )
        key_path.chmod(0o600)
        print(f"[TicianoFlix] Self-signed cert created: {cert_path}", flush=True)
        return cert_path, key_path
    except Exception as e:
        print(f"[TicianoFlix] WARNING: Could not generate SSL cert: {e}", flush=True)
        print("[TicianoFlix] Chromecast discovery will require HTTPS.", flush=True)
        return None, None


def start_https_server(handler_class, host, https_port, cert_path, key_path):
    """Start an HTTPS server on a daemon thread wrapping the same handler.

    Returns the server object (for cleanup) or None on failure.
    """
    try:
        import ssl as _ssl
        httpd = http.server.ThreadingHTTPServer((host, https_port), handler_class)
        httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"[TicianoFlix] HTTPS on https://localhost:{https_port}", flush=True)
        return httpd
    except Exception as e:
        print(f"[TicianoFlix] WARNING: Could not start HTTPS server: {e}", flush=True)
        print("[TicianoFlix] Continuing with HTTP only.", flush=True)
        return None


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


def find_free_port():
    """Sempre usa PORT. Se ocupada, mata a instância anterior."""
    env_port = os.environ.get("TICIANOFLIX_PORT")
    if env_port:
        return int(env_port)

    port = PORT
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, port))
        s.close()
        return port
    except OSError:
        pids = _pids_on_port(port)
        me = str(os.getpid())
        pids = [p for p in pids if p != me]
        print(f"[TicianoFlix] Porta {port} ocupada por {', '.join(pids) or '?'}. "
              f"Matando instância anterior...", flush=True)
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass

        time.sleep(1)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, port))
            s.close()
            return port
        except OSError:
            print(f"[TicianoFlix] ERRO: Porta {port} ainda está ocupada. Saia a instância anterior com: pkill -9 -f 'python.*server.py'", flush=True)
            sys.exit(1)


# ═══════════════════════════════════════════════
#  rclone management (serve, web GUI, status)
# ═══════════════════════════════════════════════

def _urlopen_ok(url, timeout=2):
    """True se a URL responder HTTP sem erro."""
    try:
        import urllib.request as _ur
        _ur.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


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

    # Serve de streaming ativo?
    status["serve_running"] = _urlopen_ok(f"http://localhost:{RCLONE_SERVE_PORT}/", timeout=2)

    # Web GUI ativa?
    if rclone_webgui_proc is not None:
        status["webgui"]["running"] = rclone_webgui_proc.poll() is None
        if status["webgui"]["running"]:
            status["webgui"]["url"] = f"http://127.0.0.1:{RCLONE_WEBGUI_PORT}/"
            status["webgui"]["local_only"] = True
    return status


def main():
    # Initialize database
    init_db()
    _migrate_auth_if_needed()
    db_path_abs = DB_PATH.resolve()

    # Start rclone serve http (persistent connection = much faster streams)
    start_rclone_serve()

    # No auto-scan on startup — user must click refresh manually
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) as c FROM folders").fetchone()["c"]
    conn.close()

    if count == 0:
        print("[TicianoFlix] Cache vazio. Clique em 🔄 (Atualizar) para escanear o Google Drive.", flush=True)
    else:
        cache_age = ""
        t = get_cache_time()
        if t:
            age_mins = (int(time.time()) - int(t)) // 60
            cache_age = f" (cached {age_mins}m ago)"
        print(f"[TicianoFlix] Cache loaded from {db_path_abs}{cache_age}", flush=True)

    port = find_free_port()
    server = http.server.ThreadingHTTPServer((BIND_HOST, port), TicianoFlixHandler)
    server.timeout = 0.5
    # Permite reuso imediato da porta ao reiniciar
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # ── HTTPS (self-signed cert para Chromecast) ──
    local_ip = _get_local_ip()
    https_server = None
    https_port = None
    cert_path, key_path = _ensure_ssl_cert(CACHE_DIR, local_ip)
    if cert_path and key_path:
        # Try base HTTPS port, fallback to a free port
        https_port = HTTPS_PORT_BASE
        s_test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s_test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s_test.bind((HOST, https_port))
            s_test.close()
        except OSError:
            # Port busy — find any free port starting from HTTPS_PORT_BASE
            https_port = None
            for hp in range(HTTPS_PORT_BASE, HTTPS_PORT_BASE + 100):
                try:
                    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s2.bind((HOST, hp))
                    s2.close()
                    https_port = hp
                    break
                except OSError:
                    continue
        if https_port:
            https_server = start_https_server(
                TicianoFlixHandler, BIND_HOST, https_port, cert_path, key_path
            )

    # Build banner
    banner = f"""
╔══════════════════════════════════════════════╗
║            TicianoFlix Server                ║
║                                              ║
║  🌐 http://localhost:{port}                     ║
║  🌐 http://{local_ip}:{port}                     ║"""
    if https_server:
        banner += f"""
║  🔒 https://localhost:{https_port}  (Cast/HTTPS)   ║
║  🔒 https://{local_ip}:{https_port} (LAN - Chromecast)║"""
    else:
        banner += """
║                                              ║"""
    banner += f"""
║  📁 Google Drive via rclone (cached + http)  ║
║                                              ║
║  ⚡ /api/refresh - rescan drive               ║
║  🚀 rclone proxy on localhost:{RCLONE_SERVE_PORT}        ║
╚══════════════════════════════════════════════╝
    """
    print(banner)
    if not _auth_configured():
        print("  " + "─" * 46, flush=True)
        print("  PRIMEIRO ACESSO — crie a conta de administrador", flush=True)
        print("  Codigo de instalacao: %s" % _setup_code_value(), flush=True)
        print("  Abra o endereco acima e informe esse codigo.", flush=True)
        print("  " + "─" * 46 + "\n", flush=True)

    # Shutdown imediato — não espera threads de stream terminarem
    def shutdown(sig, frame):
        print("\n[TicianoFlix] Desligando...")
        os._exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGHUP, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if rclone_server_proc is not None and rclone_server_proc.poll() is None:
            rclone_server_proc.terminate()
            try:
                rclone_server_proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                rclone_server_proc.kill()
                rclone_server_proc.wait(timeout=1)
        if rclone_webgui_proc is not None and rclone_webgui_proc.poll() is None:
            rclone_webgui_proc.terminate()
        server.server_close()
        print("[TicianoFlix] Servidor parado.")


if __name__ == "__main__":
    main()
