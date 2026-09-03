"""Handler HTTP: roteamento, gate de autenticacao e streaming de midia."""

import http.server
import json
import os
import subprocess
import urllib.parse
import urllib.request
import urllib.error
import mimetypes
import threading
import sys
import hmac
import time
import shutil
import io
import zipfile
from pathlib import Path

from .config import (
    PROJECT_ROOT,
    PORT,
    LOGICAL_ROOT,
    RCLONE_BACKUP_REMOTE,
    BACKUP_FOLDER,
    RCLONE_SERVE_PORT,
    FRONTEND_PATH,
    DB_PATH,
    IMAGE_CACHE_DIR,
    SUBS_CACHE_DIR,
    CACHED_FILES_PATH,
    IMAGE_EXTENSIONS,
    MAX_RESTORE_BYTES,
    MAX_JSON_BODY_BYTES,
    WRITE_ROUTES,
    PUBLIC_PATHS,
    TOKEN_PATHS,
    ADMIN_PATHS,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
)
from .netsec import (
    host_allowed as _host_allowed,
    origin_allowed as _origin_allowed,
)
from .paths import rc_remote as _rc_remote, serve_path as _serve_path
from .db import (
    get_db,
    get_cache_time,
    is_cache_stale,
    get_cache_usage,
    log_notification as _log_notification,
    looks_like_ticianoflix_db as _looks_like_ticianoflix_db,
)
from .auth import (
    _setup_code_value,
    _auth_configured,
    _norm_username,
    _list_users,
    _create_user,
    _remove_user,
    _set_user_role,
    _set_user_password,
    _check_credentials,
    _revoke_all_sessions,
    _issue_session,
    _session_user,
    _issue_media_token,
    _valid_media_token,
    _login_blocked,
    _record_login_failure,
    _clear_login_failures,
)
from .templates import _login_page
from .netutil import _get_local_ip
from .rclone import (
    run_rclone_cmd,
    _vfs_segment_match,
    _mark_file_cached,
    _is_file_cached,
    _cached_files,
    _cached_files_lock,
    restart_rclone_serve,
    start_rclone_webgui,
    stop_rclone_webgui,
    get_rclone_status,
)
from . import scanner as _scanner
from . import sources as _sources
from . import scraper as _scraper
from . import branding as _branding
from .branding import NOME_PADRAO
from .nfo import _fetch_nfo_from_db
from .queries import (
    cached_list_directory, cached_movie_detail, cached_get_file_info,
    cached_search_files, cached_all_movies, cached_source_counts,
    cached_all_collections, cached_collection_movies,
    _find_poster_cached,
)

# Sentinela do cache de usuario por requisicao (ver _reset_request_state).
_UNSET = object()

# Progresso de download pro cache VFS: video_path -> {percent, status, ...}
_download_progress = {}
_download_progress_lock = threading.Lock()


# O mimetypes do Python nao conhece .webmanifest, e sem o tipo certo o
# navegador ignora o manifesto e nao oferece instalar o app.
mimetypes.add_type("application/manifest+json", ".webmanifest")


def _bust_asset_cache(html):
    """Carimba os estaticos com o mtime do arquivo: /static/app.js?v=1787778.

    Eles sao servidos com max-age=3600. Sem isso, uma atualizacao do frontend
    so chegaria ao navegador uma hora depois — ou com refresh forcado. Usa o
    mtime, e nao a versao do app, para quebrar o cache sempre que o conteudo
    muda de fato, inclusive entre releases.
    """
    for asset in ("/static/app.js", "/static/styles.css",
                  "/static/tv.js", "/static/tv.css"):
        try:
            stamp = int((PROJECT_ROOT / asset.lstrip("/")).stat().st_mtime)
        except OSError:
            continue
        html = html.replace(f'"{asset}"', f'"{asset}?v={stamp}"')
    return html


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
        _clear_login_failures(ip)
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
        _clear_login_failures(ip)
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
        # Poster e fanart tambem saem por /api/stream, entao a TV precisa de um
        # token para cada um — senao a tela do Chromecast fica sem a arte.
        # Teto de 4: sao poster e fanart, nao uma galeria.
        extras = body.get("images")
        if isinstance(extras, list) and extras:
            out["imgs"] = {str(p): _issue_media_token(str(p))
                           for p in extras[:4] if p}
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

    def _media_token_ok(self):
        """True quando a requisicao traz um token de midia valido para o proprio
        arquivo que ela pede.

        E a credencial do Chromecast: ele busca a midia sozinho, sem cookie. O
        token e assinado por HMAC, vale para um arquivo so e expira em 12h; so
        e emitido por /api/cast-token, que exige sessao e Origin local.
        """
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in TOKEN_PATHS:
            return False
        params = urllib.parse.parse_qs(parsed.query)
        return _valid_media_token(params.get("path", [""])[0],
                                  params.get("t", [""])[0])

    def _security_gate(self):
        """Bloqueia DNS rebinding (Host publico) e leitura cross-site (Origin de
        terceiro). Chromecast e <video> nao mandam Origin e passam normalmente."""
        if not _host_allowed(self.headers.get("Host")):
            self._send_error("Host nao permitido", 403)
            return False
        if not _origin_allowed(self.headers.get("Origin")):
            # O receiver do Chromecast busca a faixa de legenda COM CORS — e
            # exigencia do Cast para faixas de texto — entao manda um Origin de
            # terceiro (ou "null"). O video passa porque elemento de midia nao
            # manda Origin; a legenda batia aqui e morria em 403.
            # Liberar so faz sentido porque nessas rotas quem autoriza e o token
            # por arquivo, nao a origem: o cookie de sessao e SameSite=Lax e nem
            # viaja numa requisicao cross-site.
            if not self._media_token_ok():
                self._send_error("Origem nao permitida", 403)
                return False
        return True

    def do_OPTIONS(self):
        """Preflight de CORS.

        O receiver do Chromecast faz um OPTIONS antes de buscar a legenda. Sem
        do_OPTIONS o BaseHTTPRequestHandler nem responde, e a faixa some sem
        erro visivel.
        """
        self._reset_request_state()
        if not _host_allowed(self.headers.get("Host")):
            self._send_error("Host nao permitido", 403)
            return
        origin = self.headers.get("Origin")
        if (urllib.parse.urlparse(self.path).path not in TOKEN_PATHS
                or not (_origin_allowed(origin) or self._media_token_ok())):
            self._send_error("Origem nao permitida", 403)
            return
        self.send_response(204)
        self._send_media_cors()
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

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
        download direto). Com Origin, ecoa se for local — ou se o token de midia
        autorizar, que e o caso da legenda buscada pelo receiver do Cast."""
        origin = self.headers.get("Origin")
        if not origin:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif _origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif self._media_token_ok():
            # "null" nao pode ser ecoado; vira "*", que aqui nao concede nada
            # alem do que o token assinado ja concedeu.
            self.send_header("Access-Control-Allow-Origin",
                             "*" if origin == "null" else origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Expose-Headers",
                         "Content-Length, Content-Range, Accept-Ranges")

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
        """Stream a file, escolhendo o caminho pela fonte dona do path."""
        ext = Path(path).suffix.lower()

        # Fonte local (HD externo, pendrive, disco): os bytes ja estao aqui —
        # nada de rclone, nada de cache intermediario.
        if _sources.is_local(path):
            self._stream_local(path)
            return
        if _sources.under_local_root(path):
            # Path de fonte local que nao existe mais. Nao pode escorregar pro
            # ramo do rclone: viraria um 502 sem sentido.
            self._send_error("Fonte local nao encontrada — ela foi removida?", 404)
            return

        # Small images: cache locally after first fetch
        if ext in IMAGE_EXTENSIONS:
            self._stream_image_cached(path)
            return

        # Videos and other files: proxy through rclone serve or fallback
        self._stream_video_direct(path)

    @staticmethod
    def _parse_range(range_header, size):
        """"bytes=inicio-fim" -> (inicio, fim) inclusivo, ou None se invalido.

        Cobre tambem a forma sufixo ("bytes=-500", os ultimos 500 bytes), que o
        <video> usa para ler o final do container antes de tocar um .mp4.
        """
        if not range_header or not range_header.startswith("bytes="):
            return None
        # Multiplos ranges numa requisicao exigiriam multipart/byteranges; o
        # player nunca pede isso, entao atendemos o primeiro.
        spec = range_header[len("bytes="):].split(",")[0].strip()
        first, sep, last = spec.partition("-")
        if not sep:
            return None
        try:
            if not first:
                n = int(last)
                if n <= 0:
                    return None
                start = max(0, size - n)
                end = size - 1
            else:
                start = int(first)
                end = int(last) if last else size - 1
        except ValueError:
            return None
        if start < 0 or start >= size or start > end:
            return None
        return start, min(end, size - 1)

    def _stream_local(self, path):
        """Serve um arquivo do disco com suporte a Range.

        O Range e o que faz o <video> conseguir pular no meio do filme: sem
        206 + Content-Range o player so consegue tocar do inicio.
        """
        real = _sources.local_real_path(path)
        if real is None:
            # Path fora da raiz da fonte (ou fonte inexistente). Nunca detalhar
            # o motivo: isso viraria uma sonda do sistema de arquivos.
            self._send_error("Forbidden", 403)
            return
        try:
            if not real.is_file():
                raise FileNotFoundError
            size = real.stat().st_size
        except OSError:
            self._send_error("Arquivo indisponivel — a fonte esta conectada?", 404)
            return

        ext = Path(path).suffix.lower()
        mime = self._guess_mime(path)
        range_header = self.headers.get("Range")
        start, end = 0, max(size - 1, 0)
        partial = False

        if range_header and size > 0:
            parsed = self._parse_range(range_header, size)
            if parsed is None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self._send_media_cors()
                self.end_headers()
                return
            start, end = parsed
            partial = True

        length = (end - start + 1) if size > 0 else 0

        self.send_response(206 if partial else 200)
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        if ext in IMAGE_EXTENSIONS:
            self.send_header("Cache-Control", "max-age=86400")
        self._send_media_cors()
        self.end_headers()

        try:
            with open(real, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    buf = f.read(min(65536, remaining))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    remaining -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass   # o player fechou ou pulou pra outro trecho
        except OSError as e:
            sys.stderr.write(f"[TicianoFlix] Falha lendo arquivo local: {e}\n")

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

    @staticmethod
    def _decode_subtitle(raw_bytes):
        """UTF-8 primeiro, latin-1 depois (encoding comum em SRT antigo)."""
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1")

    def _read_subtitle_text(self, path):
        """Texto bruto da legenda, buscado na fonte dona do path.

        Legenda de fonte local vem direto do disco — nao faz sentido copiar pro
        cache um arquivo que ja e local. A do Drive continua no rclone cat com
        cache em disco.
        """
        if _sources.is_local(path):
            real = _sources.local_real_path(path)
            if real is None or not real.is_file():
                return None
            try:
                return self._decode_subtitle(real.read_bytes())
            except OSError:
                return None

        cache_key = "sub_" + path.strip("/").replace("/", "_").replace(" ", "_")
        cache_path = SUBS_CACHE_DIR / cache_key
        try:
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

        try:
            result = subprocess.run(
                ["rclone", "cat", _rc_remote(path)],
                capture_output=True, timeout=30
            )
            if result.returncode != 0:
                return None
            raw = self._decode_subtitle(result.stdout)
        except Exception as e:
            sys.stderr.write(f"[TicianoFlix] Subtitle fetch failed: {e}\n")
            return None

        # Cache local (sempre UTF-8)
        try:
            cache_path.write_text(raw, encoding="utf-8")
        except Exception:
            pass
        return raw

    def _serve_subtitle(self, path):
        """Serve a subtitle file, converting SRT→VTT if needed."""
        if _sources.under_local_root(path) and not _sources.is_local(path):
            self._send_error("Fonte local nao encontrada — ela foi removida?", 404)
            return
        raw = self._read_subtitle_text(path)
        if raw is None:
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

        # Content-Length em BYTES, nao em caracteres: legenda com acento tem
        # mais bytes que caracteres em UTF-8 e chegava truncada no player.
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/vtt; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._send_media_cors()
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(payload)

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
        /static/../ — o que expunha server.py e o diretorio .git.

        A raiz vem do config, nao de Path(__file__): este modulo mora dentro do
        pacote, um nivel abaixo dos favicons."""
        project_root = PROJECT_ROOT
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

    # ── Fontes do catalogo (Drive + pastas locais) ──────────────

    def _source_payload(self, source):
        counts = cached_source_counts(source["mount"])
        payload = {
            "id": source["id"],
            "kind": source["kind"],
            "name": source["name"],
            "mount": source["mount"],
            "online": _sources.is_online(source),
            "genres": counts["genres"],
            "movies": counts["movies"],
        }
        # O caminho no disco so interessa a quem pode gerenciar fontes, e
        # descreve a maquina do servidor — nao vai pra sessao comum.
        if self._is_admin():
            payload["root"] = source["root"]
        return payload

    def _handle_sources_list(self):
        self._send_json({
            "sources": [self._source_payload(s) for s in _sources.list_sources()],
        })

    def _handle_sources_detect(self):
        """Volumes e pastas de midia sugeridos. So sugere — nao cadastra nada."""
        try:
            self._send_json({"candidates": _sources.detect_volumes()})
        except Exception as e:
            self._send_exception(e)

    def _handle_source_add(self):
        body = self._read_json_body() or {}
        source, err = _sources.add_source(body.get("name", ""), body.get("path", ""))
        if err:
            self._send_json({"status": "error", "error": err}, 400)
            return
        # Primeiro scan ja sai daqui: sem ele a fonte apareceria vazia.
        scan = _scanner.start_background_scan(source["id"])
        if scan == "already_scanning":
            # So existe uma vaga de scan por vez. Melhor dizer isso do que
            # deixar a fonte recem-criada parecendo vazia sem explicacao.
            message = ("Fonte adicionada. Ja havia um scan em andamento — "
                       "clique em Atualizar quando ele terminar.")
        else:
            message = "Fonte adicionada. Escaneando..."
        if source.get("descended"):
            # A raiz foi ancorada mais fundo: dizer qual, senao o usuario nao
            # entende por que o caminho mostrado nao e o que ele escolheu.
            message += f" Os filmes estao em {source['root']} — foi essa pasta que entrou."
        self._send_json({"status": "ok", "scan": scan, "message": message,
                         "source": self._source_payload(source)})

    def _handle_source_remove(self):
        body = self._read_json_body() or {}
        source_id = str(body.get("id", "")).strip()
        source = _sources.get_source(source_id)
        if not source or source["kind"] != "local":
            self._send_json({"status": "error",
                             "error": "Fonte local nao encontrada."}, 404)
            return
        _sources.remove_source(source_id)
        # O catalogo dela sai junto — senao ficariam filmes apontando pra
        # uma fonte que o app nao conhece mais.
        conn = get_db()
        try:
            _scanner._remove_folder_tree(conn, source["mount"])
            conn.commit()
        finally:
            conn.close()
        self._send_json({"status": "ok"})

    def _handle_scrape_apply(self):
        body = self._read_json_body() or {}
        folder_path = str(body.get("path", "")).strip()
        tmdb_id = body.get("tmdb_id")
        if not folder_path or not tmdb_id:
            self._send_json({"status": "error", "error": "Faltou path ou tmdb_id"}, 400)
            return
        try:
            tmdb_id = int(tmdb_id)
        except (TypeError, ValueError):
            self._send_json({"status": "error", "error": "tmdb_id invalido"}, 400)
            return
        ok, erro = _scraper.aplicar(folder_path, tmdb_id)
        if not ok:
            self._send_json({"status": "error", "error": erro}, 502)
            return
        self._send_json({"status": "ok"})

    def _handle_scrape_key_set(self):
        body = self._read_json_body() or {}
        _scraper.set_api_key(str(body.get("api_key", "")))
        self._send_json({"status": "ok", "configurado": _scraper.configurado()})

    def _handle_branding_set(self):
        body = self._read_json_body() or {}
        ok, err = _branding.set(body.get("nome", ""), body.get("cor", ""))
        if not ok:
            self._send_json({"status": "error", "error": err}, 400)
            return
        self._send_json({"status": "ok", "branding": _branding.get()})

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
            # Troca o nome de exibicao antes de servir: fazer isso por
            # JavaScript depois piscaria "TicianoFlix" por um instante a cada
            # carregamento, em qualquer instalacao que tenha escolhido outro
            # nome. So esse texto muda — CACHE_DIR, nome do banco e do
            # servico continuam fixos, de proposito (ver branding.py).
            html_content = html_content.replace(NOME_PADRAO, _branding.get()["nome"])
            # Inject HTTP base URL for Chromecast media streaming
            # (Chromecast doesn't trust self-signed certs, so media must use HTTP)
            html_content = html_content.replace(
                "</head>",
                f"<script>window.__HTTP_BASE__='http://{_get_local_ip()}:{PORT}';"
                f"window.__LOGICAL_ROOT__={json.dumps(LOGICAL_ROOT)};</script></head>",
                1
            )
            html_content = _bust_asset_cache(html_content)
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

        # Marca: manifest, CSS de cor e icones gerados na hora, na cor e nome
        # escolhidos. Publicos (ver PUBLIC_PATHS) porque o navegador os busca
        # fora da navegacao normal, sem cookie — inclusive antes do login.
        if path == "/manifest.webmanifest":
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(_branding.manifest_json().encode("utf-8"))
            return

        if path == "/branding.css":
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(_branding.css().encode("utf-8"))
            return

        if path.startswith("/icone-") and path.endswith(".png"):
            chave = path[len("/icone-"):-len(".png")]
            dados = _branding.icone_png(chave)
            if dados is None:
                self._send_error("Icone desconhecido", 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            # A cor entra no nome do arquivo em cache (branding.py); um icone
            # nunca fica desatualizado atras deste cache, so muda de URL.
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(dados)
            return

        # API: Marca atual (nome e cor) — admin, ver Ajustes > Aparencia
        if path == "/api/branding":
            self._send_json(_branding.get())
            return

        if path == "/api/branding/set":
            self._handle_branding_set()
            return

        # API: Refresh cache (escaneia todas as fontes, ou so uma)
        if path == "/api/refresh":
            source_id = params.get("source", [""])[0].strip() or None
            self._send_json({"status": _scanner.start_background_scan(source_id)})
            return

        # API: Fontes do catalogo
        if path == "/api/sources":
            self._handle_sources_list()
            return

        if path == "/api/sources/detect":
            self._handle_sources_detect()
            return

        if path == "/api/sources/add":
            self._handle_source_add()
            return

        if path == "/api/sources/remove":
            self._handle_source_remove()
            return

        # API: Metadados via TMDB (editor que substitui o tinyMediaManager)
        if path == "/api/scrape/status":
            pendentes, total = _scraper.listar_pendentes(limite=1)
            self._send_json({"configurado": _scraper.configurado(), "pendentes": total})
            return

        if path == "/api/scrape/pendentes":
            pendentes, total = _scraper.listar_pendentes()
            self._send_json({"pendentes": pendentes, "total": total})
            return

        if path == "/api/scrape/search":
            folder_path = params.get("path", [""])[0]
            query = params.get("q", [""])[0].strip() or None
            if not folder_path:
                self._send_error("Missing 'path' parameter", 400)
                return
            nome_pasta = folder_path.rstrip("/").rsplit("/", 1)[-1]
            candidatos, erro = _scraper.buscar_candidatos(nome_pasta, query)
            self._send_json({"candidatos": candidatos, "erro": erro})
            return

        if path == "/api/scrape/apply":
            self._handle_scrape_apply()
            return

        if path == "/api/scrape/key/set":
            self._handle_scrape_key_set()
            return

        # API: Scan progress
        if path == "/api/scan-progress":
            self._send_json(_scanner.get_progress())
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
            if _sources.is_local(folder_path):
                self._send_json({"status": "ok", "local": True,
                                 "message": "Filme em fonte local — ja disponivel offline."})
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
            # Arquivo em fonte local ja esta no disco: offline por definicao,
            # e o cache VFS do rclone nao tem nada a ver com ele.
            if _sources.is_local(file_path):
                self._send_json({"cached": True, "local": True})
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
            # Fonte local nao passa pelo cache VFS: apagar aqui seria apagar o
            # filme do HD do usuario.
            if _sources.is_local(folder_path):
                self._send_json(
                    {"status": "error",
                     "error": "Esse filme esta numa fonte local — nao ha cache a remover."},
                    400)
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
            wanted = params.get("source", [""])[0].strip()
            conn = get_db()
            genre_rows = conn.execute(
                "SELECT * FROM folders WHERE depth=1 AND has_video=1 ORDER BY name"
            ).fetchall()
            conn.close()

            all_sources = _sources.list_sources()
            folders = []
            for row in genre_rows:
                owner = _sources.resolve(row["path"])
                source_id = owner["id"] if owner else ""
                if wanted and source_id != wanted:
                    continue
                folders.append({
                    "Path": row["path"].lstrip("/"),
                    "Name": row["name"],
                    "Size": 0,
                    "MimeType": "inode/directory",
                    "ModTime": "",
                    "IsDir": True,
                    "has_video": True,
                    "source": source_id,
                })
            data = {
                "path": LOGICAL_ROOT,
                "folders": folders,
                # A home monta uma secao por fonte a partir daqui, numa
                # requisicao so — por isso as fontes vem junto dos generos.
                "sources": [
                    {"id": s["id"], "kind": s["kind"], "name": s["name"],
                     "online": _sources.is_online(s)}
                    for s in all_sources
                    if not wanted or s["id"] == wanted
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

            # Raiz -> raiz do Drive, sem depender do nome fixo em texto.
            if dir_path == "" or dir_path == "/":
                dir_path = LOGICAL_ROOT

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

        # API: Colecoes (Star Wars 1-6 e afins)
        if path == "/api/collections":
            self._send_json(cached_all_collections())
            return

        if path == "/api/collection":
            nome = params.get("name", [""])[0]
            if not nome:
                self._send_error("Missing 'name' parameter", 400)
                return
            data = cached_collection_movies(nome)
            if data is None:
                self._send_error("Colecao nao encontrada", 404)
                return
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











# ═══════════════════════════════════════════════
#  rclone management (serve, web GUI, status)
# ═══════════════════════════════════════════════
















