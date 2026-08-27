"""IP local, certificado self-signed e escolha de porta."""

import datetime
import http.server
import os
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import HOST, PORT
from .procutil import _pids_on_port


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
