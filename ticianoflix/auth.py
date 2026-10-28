"""Contas, sessoes e tokens de midia.

Contas com papeis (admin / user). Nao existe auto-cadastro: o primeiro admin e
criado no primeiro boot, e so com o codigo de instalacao impresso no log do
servidor. Depois disso, contas novas so pelo painel de admin.

A sessao e sem estado: o cookie carrega (usuario, expiracao, epoca global,
epoca do usuario) assinados por HMAC. Duas epocas permitem derrubar todos os
aparelhos de uma vez (global) ou so os de uma pessoa (do usuario).

O Chromecast nao manda cookie — para ele o servidor assina uma URL por arquivo
(ver issue_media_token).
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

from .config import (
    AUTH_PATH, SECRET_PATH, SESSION_MAX_AGE, CAST_TOKEN_MAX_AGE,
    MIN_PASSWORD_LEN, LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW,
)

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")

_auth_lock = threading.RLock()
_login_attempts = {}
_setup_code = None
_UNSET = object()


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
                # O formato antigo guardava PBKDF2; agora o rotulo conta a verdade.
                "algo": "pbkdf2_sha256", "iterations": 100000,
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
        {"username": name, "role": u.get("role", "user"),
         "infantil": bool(u.get("infantil")), "created": u.get("created")}
        for name, u in sorted((d.get("users") or {}).items())
    ]


def _admin_count(d):
    return sum(1 for u in (d.get("users") or {}).values() if u.get("role") == "admin")


def _hash_password(password, salt=None):
    """PBKDF2 legado — o algoritmo real de todas as senhas ate o upgrade para
    scrypt. Continua aqui para conferir os registros antigos."""
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt=salt,
                              iterations=100000, dklen=32)
    return salt, dk


# O scrypt depende do OpenSSL do interpretador: o Python 3.9 da Apple nao
# expoe hashlib.scrypt (LibreSSL antigo), o do Homebrew expoe. A escolha e
# por disponibilidade, e cada registro grava o que foi usado de verdade — nos
# registros antigos o rotulo "scrypt" mentia (guardavam PBKDF2).
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 16384, 8, 1
_scrypt_ok = None


def _scrypt_disponivel():
    global _scrypt_ok
    if _scrypt_ok is None:
        try:
            hashlib.scrypt(b"probe", salt=b"0123456789abcdef",
                           n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=16)
            _scrypt_ok = True
        except Exception:
            _scrypt_ok = False
    return _scrypt_ok


def _novo_registro_senha(password):
    """Campos de senha para um registro novo, no KDF que este interpretador
    tem — rotulo e parametros contando a verdade."""
    if _scrypt_disponivel():
        salt = secrets.token_bytes(16)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
        return {"algo": "scrypt", "n": _SCRYPT_N, "r": _SCRYPT_R,
                "p": _SCRYPT_P, "salt": salt.hex(), "hash": dk.hex()}
    salt, dk = _hash_password(password)
    return {"algo": "pbkdf2_sha256", "iterations": 100000,
            "salt": salt.hex(), "hash": dk.hex()}


def _senha_confere(user, password):
    """Confere a senha e devolve o formato que bateu ('scrypt' ou 'pbkdf2').

    Registros antigos dizem 'scrypt' mas guardam PBKDF2 — por isso o formato
    declarado e tentado primeiro e o PBKDF2 entra como segundo teste. Quem
    entra por esse caminho ganha registro novo no login (ver _check_credentials).
    """
    try:
        salt = bytes.fromhex(user["salt"])
        esperado = user["hash"]
        if user.get("algo") == "scrypt" and _scrypt_disponivel():
            try:
                dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                    n=int(user.get("n") or _SCRYPT_N),
                                    r=int(user.get("r") or _SCRYPT_R),
                                    p=int(user.get("p") or _SCRYPT_P),
                                    dklen=32)
                if hmac.compare_digest(dk.hex(), esperado):
                    return "scrypt"
            except Exception:
                pass
        _, dk = _hash_password(password, salt)
        if hmac.compare_digest(dk.hex(), esperado):
            return "pbkdf2"
    except Exception:
        pass
    return None


def _upgrade_hash(username, password):
    """Troca o registro da senha pelo formato atual sem mexer na epoca — o
    login ja concedido continua valido; so o hash melhora."""
    with _auth_lock:
        d = _auth_data()
        if not d or username not in (d.get("users") or {}):
            return
        user = d["users"][username]
        for key in ("algo", "n", "r", "p", "iterations", "salt", "hash"):
            user.pop(key, None)
        user.update(_novo_registro_senha(password))
        _save_auth(d)


def _password_problem(password):
    if len(password or "") < MIN_PASSWORD_LEN:
        return "A senha precisa ter pelo menos %d caracteres" % MIN_PASSWORD_LEN
    return None


def _username_problem(username):
    if not USERNAME_RE.match(_norm_username(username)):
        return ("O usuario deve ter de 2 a 32 caracteres, comecar com letra ou "
                "numero, e usar apenas letras, numeros, ponto, hifen ou _")
    return None


def _create_user(username, password, role="user", infantil=False):
    """Cria a conta. Devolve None em sucesso ou a mensagem de erro."""
    username = _norm_username(username)
    problem = _username_problem(username) or _password_problem(password)
    if problem:
        return problem
    with _auth_lock:
        d = _auth_data() or {"version": 2, "epoch": int(time.time()), "users": {}}
        if username in (d.get("users") or {}):
            return "Ja existe uma conta com esse nome"
        now = int(time.time())
        registro = _novo_registro_senha(password)
        d.setdefault("users", {})[username] = {
            "role": "admin" if role == "admin" else "user",
            "infantil": bool(infantil) and role != "admin",
            **registro,
            "epoch": now, "created": now,
        }
        _save_auth(d)
    return None


def _set_user_infantil(username, infantil, acting):
    """Liga/desliga o perfil infantil de uma conta.

    Revoga as sessões da conta (mesmo mecanismo da troca de papel): o
    dispositivo da criança volta ao login e a sessão já reflete o modo novo.
    """
    username = _norm_username(username)
    acting = _norm_username(acting)
    with _auth_lock:
        d = _auth_data()
        if not d or username not in (d.get("users") or {}):
            return "Conta não encontrada"
        if username == acting:
            return "Não dá para mudar o seu próprio perfil"
        if d["users"][username].get("role") == "admin":
            return "Perfil infantil não se aplica a administradores"
        d["users"][username]["infantil"] = bool(infantil)
        d["users"][username]["epoch"] = _next_epoch(
            d["users"][username].get("epoch"))
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
        user = d["users"][username]
        for key in ("algo", "n", "r", "p", "iterations", "salt", "hash"):
            user.pop(key, None)
        user.update(_novo_registro_senha(password))
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
    formato = _senha_confere(user, password or "")
    if not formato:
        return None
    username = _norm_username(username)
    if formato == "pbkdf2" and _scrypt_disponivel():
        # Registro antigo (ou com rotulo mentiroso): reaproveita a senha ja
        # conferida para gravar no formato atual, sem derrubar sessao nenhuma.
        _upgrade_hash(username, password or "")
    return {"username": username, "role": user.get("role", "user")}


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
            "role": user.get("role", "user"),
            "infantil": bool(user.get("infantil"))}


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


def _clear_login_failures(ip):
    """Zera o rate limit do IP apos uma entrada bem-sucedida."""
    _login_attempts.pop(ip, None)
