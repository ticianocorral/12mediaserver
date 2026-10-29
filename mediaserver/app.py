"""Composicao e ciclo de vida do servidor."""

import http.server
import os
import socket
import signal
import time

from .config import (
    HOST,
    HTTPS_PORT_BASE,
    BIND_HOST,
    RCLONE_SERVE_PORT,
    CACHE_DIR,
    DB_PATH,
)
from .db import get_db, init_db, get_cache_time, adotar_progresso_orfao
from .auth import _setup_code_value, _migrate_auth_if_needed, _auth_configured, _list_profiles
from .netutil import (
    _get_local_ip, _ensure_ssl_cert, start_https_server, find_free_port,
)
from .rclone import ensure_rclone_in_path, start_rclone_serve
from . import rclone as _rclone
from . import sources as _sources
from . import scanner as _scanner
from .paths import remote_atual, remote_configurado

# Sentinela do cache de usuario por requisicao (ver _reset_request_state).
from .handler import MediaServerHandler


def _rotacionar_log():
    """O launchd segura stdout/stderr abertos no mesmo arquivo desde a subida
    do processo — sem rotacao o log so cresce (ja passou de 3 MB). Copytruncate:
    guarda a versao anterior em .1 e zera o original; renomear nao serve — o fd
    aberto continuaria escrevendo no arquivo ja rotacionado."""
    log = CACHE_DIR / "media-server.log"
    try:
        if not (log.exists() and log.stat().st_size >= 1024 * 1024):
            return
        (CACHE_DIR / "media-server.log.1").write_bytes(log.read_bytes())
        log.write_bytes(b"")
    except OSError:
        pass


def _adotar_progresso_antigo():
    """Progresso de antes dos perfis (profile_id vazio) passa para o primeiro
    administrador, para ninguem perder o "continuar assistindo"."""
    perfis = [p for p in _list_profiles() if p["role"] == "admin"]
    if perfis:
        adotar_progresso_orfao(perfis[0]["id"])


def main():
    _rotacionar_log()
    # Initialize database
    init_db()
    _migrate_auth_if_needed()
    _adotar_progresso_antigo()
    db_path_abs = DB_PATH.resolve()

    # O rclone pode estar em ~/.local/bin (instalado pelo install.sh) fora do
    # PATH do processo — resolve antes de qualquer subprocesso do rclone.
    ensure_rclone_in_path()

    # Start rclone serve http (persistent connection = much faster streams)
    start_rclone_serve()

    # Um backup restaurado de outra maquina traz as pastas locais dela junto.
    # Sem esta poda elas ficariam no catalogo apontando pra lugar nenhum.
    try:
        _scanner.prune_orphan_sources()
    except Exception as e:
        print(f"[12:00 Media Server] Falha ao podar fontes orfas: {e}", flush=True)

    # O mesmo para a nuvem: desconfigurada, o catalogo remoto antigo nao sairia
    # nunca — o scan incremental nao visita fonte que deixou de existir.
    try:
        _scanner.prune_unconfigured_cloud()
    except Exception as e:
        print(f"[12:00 Media Server] Falha ao podar catalogo da nuvem: {e}", flush=True)

    # No auto-scan on startup — user must click refresh manually
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) as c FROM folders").fetchone()["c"]
    conn.close()

    if count == 0:
        print("[12:00 Media Server] Cache vazio. Clique em 🔄 (Atualizar) para escanear as fontes.", flush=True)
    else:
        cache_age = ""
        t = get_cache_time()
        if t:
            age_mins = (int(time.time()) - int(t)) // 60
            cache_age = f" (cached {age_mins}m ago)"
        print(f"[12:00 Media Server] Cache loaded from {db_path_abs}{cache_age}", flush=True)

    port = find_free_port()
    server = http.server.ThreadingHTTPServer((BIND_HOST, port), MediaServerHandler)
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
                MediaServerHandler, BIND_HOST, https_port, cert_path, key_path
            )

    # Build banner
    banner = f"""
╔══════════════════════════════════════════════╗
║            12:00 Media Server                ║
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
    local = _sources.local_sources()
    if local:
        online = sum(1 for s in local if _sources.is_online(s))
        fontes = f"{len(local)} local(is), {online} conectada(s)"
    else:
        fontes = "nenhuma cadastrada"
    # Nuvem é opcional: mostra o remote conectado ou o lembrete de configurar.
    if remote_configurado():
        linha_nuvem = f"☁️  Nuvem: {remote_atual()} (cache + http)"
    else:
        linha_nuvem = "☁️  Nuvem nao configurada (Ajustes > Nuvem)"
    banner += f"""
║  {linha_nuvem:<44}║
║  💽 Fontes locais: {fontes:<27}║
║                                              ║
║  ⚡ /api/refresh - rescan do acervo           ║
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
        print("\n[12:00 Media Server] Desligando...")
        os._exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGHUP, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _rclone.shutdown()
        server.server_close()
        print("[12:00 Media Server] Servidor parado.")


if __name__ == "__main__":
    main()
