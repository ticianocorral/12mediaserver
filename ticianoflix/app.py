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
from .db import get_db, init_db, get_cache_time
from .auth import _setup_code_value, _migrate_auth_if_needed, _auth_configured
from .netutil import (
    _get_local_ip, _ensure_ssl_cert, start_https_server, find_free_port,
)
from .rclone import start_rclone_serve
from . import rclone as _rclone

# Sentinela do cache de usuario por requisicao (ver _reset_request_state).
from .handler import TicianoFlixHandler


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
        _rclone.shutdown()
        server.server_close()
        print("[TicianoFlix] Servidor parado.")


if __name__ == "__main__":
    main()
