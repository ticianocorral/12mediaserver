"""Conta, perfis, sessoes e tokens de midia.

Um unico login (a conta da casa) e varios perfis, como num servico de
streaming: depois de entrar, cada pessoa escolhe o seu perfil. O perfil tem
nome, avatar, papel (admin / user), a marca de infantil e, se quiser, um PIN
de 4 numeros. Nao existe auto-cadastro: a conta e o primeiro perfil (admin)
nascem no primeiro boot, so com o codigo de instalacao impresso no log do
servidor.

A sessao e sem estado: o cookie carrega (conta, perfil, expiracao, epoca
global, epoca da conta, epoca do perfil) assinados por HMAC. As epocas
permitem derrubar todos os aparelhos (global), os da conta ou so os de um
perfil (quando o papel ou o PIN dele muda).

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
PIN_RE = re.compile(r"^[0-9]{4}$")
MAX_PERFIS = 6
AVATARES = tuple("a%02d" % i for i in range(1, 13))
GERENCIAR_SEGUNDOS = 10 * 60

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


def _auth_data():
    """Le auth.json no formato v3 (conta + perfis). Nao grava."""
    try:
        raw = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not raw:
        return None
    if raw.get("version") == 3:
        return raw
    return _v2_to_v3(raw)


def _novo_id():
    return secrets.token_hex(4)


def _v2_to_v3(raw):
    """Formato com varias contas vira conta unica + um perfil por conta antiga.
    A conta passa a ser o primeiro admin (e a senha dele); os demais ficam
    como perfis sem PIN."""
    users = raw.get("users") or {}
    if not users:
        return None
    ordem = sorted(users.items(), key=lambda kv: (kv[1].get("role") != "admin", kv[0]))
    nome_conta, u = ordem[0]
    now = int(time.time())
    conta = {k: u[k] for k in ("algo", "n", "r", "p", "iterations", "salt", "hash") if k in u}
    conta.update({"username": nome_conta, "epoch": int(u.get("epoch", now)),
                  "created": int(u.get("created", now))})
    perfis = {}
    for i, (nome, pu) in enumerate(ordem):
        pid = _novo_id()
        perfis[pid] = {
            "id": pid, "name": nome, "avatar": AVATARES[i % len(AVATARES)],
            "role": "admin" if pu.get("role") == "admin" else "user",
            "infantil": bool(pu.get("infantil")) and pu.get("role") != "admin",
            "pin": None, "epoch": now, "created": int(pu.get("created", now)),
        }
    return {"version": 3, "epoch": int(raw.get("epoch", now)),
            "account": conta, "profiles": perfis}


def _save_auth(data):
    with _auth_lock:
        AUTH_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            AUTH_PATH.chmod(0o600)
        except OSError:
            pass


def _migrate_auth_if_needed():
    """Persiste a conversao para o formato v3 uma unica vez, na subida."""
    try:
        raw = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if raw and raw.get("version") != 3:
        novo = _v2_to_v3(raw)
        if novo:
            _save_auth(novo)
            print("[12:00 Media Server] Contas migradas para conta unica + perfis.", flush=True)


def _auth_configured():
    d = _auth_data()
    return bool(d and d.get("account") and d.get("profiles"))


def _global_epoch():
    return int((_auth_data() or {}).get("epoch", 0))


def _next_epoch(current):
    """Epoca sempre crescente. So `int(time.time())` nao serve: duas operacoes
    no mesmo segundo produziriam o mesmo valor, e a sessao que deveria cair
    continuaria valida."""
    return max(int(current or 0) + 1, int(time.time()))


def _norm_username(name):
    return (name or "").strip().lower()


def _account(d=None):
    d = d if d is not None else _auth_data()
    return (d or {}).get("account")


def _perfil_publico(p):
    return {"id": p["id"], "name": p["name"], "avatar": p.get("avatar", AVATARES[0]),
            "role": p.get("role", "user"), "infantil": bool(p.get("infantil")),
            "hasPin": bool(p.get("pin"))}


def _list_profiles():
    d = _auth_data() or {}
    perfis = sorted((d.get("profiles") or {}).values(),
                    key=lambda p: (p.get("created", 0), p["name"].lower()))
    return [_perfil_publico(p) for p in perfis]


def _get_profile(pid):
    return ((_auth_data() or {}).get("profiles") or {}).get(pid or "")


def _admin_count(d):
    return sum(1 for p in (d.get("profiles") or {}).values() if p.get("role") == "admin")


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


def _password_problem(password):
    if len(password or "") < MIN_PASSWORD_LEN:
        return "A senha precisa ter pelo menos %d caracteres" % MIN_PASSWORD_LEN
    return None


def _username_problem(username):
    if not USERNAME_RE.match(_norm_username(username)):
        return ("O usuario deve ter de 2 a 32 caracteres, comecar com letra ou "
                "numero, e usar apenas letras, numeros, ponto, hifen ou _")
    return None


def _nome_perfil_problem(nome):
    nome = (nome or "").strip()
    if not 1 <= len(nome) <= 20:
        return "O nome do perfil deve ter de 1 a 20 caracteres"
    return None


def _create_account(username, password, profile_name=None):
    """Cria a conta unica e o primeiro perfil (admin). None = ok, ou o erro."""
    username = _norm_username(username)
    problem = _username_problem(username) or _password_problem(password)
    if problem:
        return None, problem
    nome = (profile_name or "").strip() or username
    problem = _nome_perfil_problem(nome)
    if problem:
        return None, problem
    with _auth_lock:
        if _auth_configured():
            return None, "A conta ja foi criada"
        now = int(time.time())
        pid = _novo_id()
        d = {"version": 3, "epoch": now,
             "account": {"username": username, **_novo_registro_senha(password),
                         "epoch": now, "created": now},
             "profiles": {pid: {"id": pid, "name": nome, "avatar": AVATARES[0],
                                "role": "admin", "infantil": False, "pin": None,
                                "epoch": now, "created": now}}}
        _save_auth(d)
    return pid, None


def _create_profile(name, avatar, infantil=False, role="user"):
    """Novo perfil. Devolve (perfil_publico, None) ou (None, erro)."""
    problem = _nome_perfil_problem(name)
    if problem:
        return None, problem
    with _auth_lock:
        d = _auth_data()
        if not d:
            return None, "Conta nao encontrada"
        perfis = d.setdefault("profiles", {})
        if len(perfis) >= MAX_PERFIS:
            return None, "Limite de %d perfis atingido" % MAX_PERFIS
        if any(p["name"].lower() == name.strip().lower() for p in perfis.values()):
            return None, "Ja existe um perfil com esse nome"
        role = "admin" if role == "admin" and not infantil else "user"
        now = int(time.time())
        pid = _novo_id()
        perfis[pid] = {"id": pid, "name": name.strip(),
                       "avatar": avatar if avatar in AVATARES else AVATARES[len(perfis) % len(AVATARES)],
                       "role": role, "infantil": bool(infantil) and role != "admin",
                       "pin": None, "epoch": now, "created": now}
        _save_auth(d)
        return _perfil_publico(perfis[pid]), None


def _update_profile(pid, name=None, avatar=None, infantil=None, role=None):
    """Edita um perfil. Mudar papel ou a marca de infantil derruba as sessoes
    dele (o aparelho volta ao seletor ja com o modo novo). None = ok."""
    with _auth_lock:
        d = _auth_data()
        p = ((d or {}).get("profiles") or {}).get(pid)
        if not p:
            return "Perfil nao encontrado"
        mudou_acesso = False
        if name is not None:
            problem = _nome_perfil_problem(name)
            if problem:
                return problem
            if any(o["id"] != pid and o["name"].lower() == name.strip().lower()
                   for o in d["profiles"].values()):
                return "Ja existe um perfil com esse nome"
            p["name"] = name.strip()
        if avatar is not None and avatar in AVATARES:
            p["avatar"] = avatar
        novo_role = p.get("role", "user") if role is None else ("admin" if role == "admin" else "user")
        novo_inf = bool(p.get("infantil")) if infantil is None else bool(infantil)
        if novo_inf:
            novo_role = "user"
        if p.get("role") == "admin" and novo_role != "admin" and _admin_count(d) <= 1:
            return "Precisa existir pelo menos um perfil administrador"
        if novo_role != p.get("role", "user") or novo_inf != bool(p.get("infantil")):
            mudou_acesso = True
        p["role"], p["infantil"] = novo_role, novo_inf
        if mudou_acesso:
            p["epoch"] = _next_epoch(p.get("epoch"))
        _save_auth(d)
    return None


def _delete_profile(pid):
    with _auth_lock:
        d = _auth_data()
        perfis = (d or {}).get("profiles") or {}
        if pid not in perfis:
            return "Perfil nao encontrado"
        if len(perfis) <= 1:
            return "A conta precisa ter pelo menos um perfil"
        if perfis[pid].get("role") == "admin" and _admin_count(d) <= 1:
            return "Nao da para remover o ultimo administrador"
        del perfis[pid]
        _save_auth(d)
    return None


def _pin_problem(pin):
    if not PIN_RE.match(pin or ""):
        return "O PIN deve ter exatamente 4 numeros"
    return None


def _set_pin(pid, pin):
    """Define (4 numeros) ou remove (pin=None) o PIN. Derruba as sessoes do
    perfil: quem estava dentro sem PIN precisa digitar o novo."""
    if pin is not None:
        problem = _pin_problem(pin)
        if problem:
            return problem
    with _auth_lock:
        d = _auth_data()
        p = ((d or {}).get("profiles") or {}).get(pid)
        if not p:
            return "Perfil nao encontrado"
        p["pin"] = _novo_registro_senha(pin) if pin is not None else None
        p["epoch"] = _next_epoch(p.get("epoch"))
        _save_auth(d)
    return None


def _pin_confere(pid, pin):
    p = _get_profile(pid)
    if not p or not p.get("pin"):
        return True
    if not PIN_RE.match(pin or ""):
        return False
    return _senha_confere(p["pin"], pin) is not None


def _check_credentials(username, password):
    """Confere o login da conta. Devolve {'username'} ou None."""
    conta = _account() or {}
    if not conta.get("hash") or _norm_username(username) != conta.get("username"):
        # Gasta o mesmo tempo de um hash real, para nao vazar se o usuario existe.
        _hash_password(password or "")
        return None
    formato = _senha_confere(conta, password or "")
    if not formato:
        return None
    if formato == "pbkdf2" and _scrypt_disponivel():
        _upgrade_hash(conta["username"], password or "")
    return {"username": conta["username"]}


def _upgrade_hash(username, password):
    """Troca o registro da senha da conta pelo formato atual sem mexer na epoca."""
    with _auth_lock:
        d = _auth_data()
        conta = (d or {}).get("account")
        if not conta or conta.get("username") != username:
            return
        for key in ("algo", "n", "r", "p", "iterations", "salt", "hash"):
            conta.pop(key, None)
        conta.update(_novo_registro_senha(password))
        _save_auth(d)


def _revoke_all_sessions():
    """Desloga todos os aparelhos."""
    with _auth_lock:
        d = _auth_data()
        if not d:
            return
        d["epoch"] = _next_epoch(d.get("epoch"))
        _save_auth(d)


def _set_account_password(password):
    problem = _password_problem(password)
    if problem:
        return problem
    with _auth_lock:
        d = _auth_data()
        conta = (d or {}).get("account")
        if not conta:
            return "Conta nao encontrada"
        for key in ("algo", "n", "r", "p", "iterations", "salt", "hash"):
            conta.pop(key, None)
        conta.update(_novo_registro_senha(password))
        conta["epoch"] = _next_epoch(conta.get("epoch"))
        _save_auth(d)
    return None


def _sign(msg):
    return hmac.new(_server_secret(), msg.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _issue_session(profile_id="", manage_until=0):
    conta = _account() or {}
    perfil = _get_profile(profile_id) or {}
    payload = {
        "u": conta.get("username", ""),
        "e": int(time.time()) + SESSION_MAX_AGE,
        "g": _global_epoch(),
        "p": int(conta.get("epoch", 0)),
        "pf": perfil.get("id", ""),
        "pe": int(perfil.get("epoch", 0)),
        "m": int(manage_until),
    }
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return raw + "." + _sign(raw)


def _session_info(token):
    """Le o cookie. Devolve {'account', 'profile', 'manage'} ou None.

    'profile' e o perfil escolhido (ja no formato publico) ou None enquanto a
    pessoa ainda esta no seletor. 'manage' vale quando a conta redigitou a
    senha ha pouco, liberando a edicao de perfis a partir do seletor."""
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
    conta = _account()
    if not conta or conta.get("username") != payload.get("u"):
        return None
    if int(payload.get("p", -1)) != int(conta.get("epoch", 0)):
        return None
    perfil = None
    pid = payload.get("pf") or ""
    if pid:
        p = _get_profile(pid)
        if not p or int(payload.get("pe", -1)) != int(p.get("epoch", 0)):
            return None
        perfil = p
    return {"account": conta["username"], "profile": perfil,
            "manage": float(payload.get("m", 0)) > time.time()}


def _session_user(token):
    """Compatibilidade com o resto do servidor: o 'usuario' da sessao e o
    perfil escolhido. None enquanto nao ha perfil."""
    info = _session_info(token)
    if not info or not info["profile"]:
        return None
    p = info["profile"]
    return {"id": p["id"], "username": p["name"], "name": p["name"],
            "role": p.get("role", "user"), "infantil": bool(p.get("infantil")),
            "avatar": p.get("avatar", AVATARES[0]), "hasPin": bool(p.get("pin"))}


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
