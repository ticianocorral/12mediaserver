"""IP local, certificado self-signed e escolha de porta."""

import datetime
import http.server
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import HOST, PORT, env
from .procutil import _pids_on_port


# Porta HTTPS ativa neste processo — o handler injeta ela no HTML autenticado
# (window.__NET__) para as instrucoes "Instalar no celular" no desktop. Fica
# None ate o servidor HTTPS subir (ver start_https_server).
ACTIVE_HTTPS_PORT = None


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


def _local_hostnames():
    """Nomes DNS (.local) que o certificado deve cobrir, além do IP.

    No macOS o Bonjour resolve "<LocalHostName>.local" (ex.:
    Mac-mini-de-Ticiano.local) — endereço estável para celulares e TVs,
    ao contrário do IP, que muda quando o roteador troca. "media-server.local"
    fica incluído para quem renomear o Mac com esse nome.
    """
    nomes = ["media-server.local"]

    def _qualificado(nome):
        nome = (nome or "").strip()
        if not nome or " " in nome:
            return None
        return nome if "." in nome else nome + ".local"

    try:
        res = subprocess.run(["scutil", "--get", "LocalHostName"],
                             capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            nomes.append(_qualificado(res.stdout))
    except Exception:
        pass

    try:
        nomes.append(_qualificado(socket.gethostname()))
    except Exception:
        pass

    unicos = []
    for n in nomes:
        if n and n not in unicos:
            unicos.append(n)
    return unicos


def _primary_local_hostname():
    """O melhor nome .local para as instrucoes de instalacao no celular.

    O nome Bonjour real da maquina (ex.: Mac-mini-de-Ticiano.local) resolve
    sozinho no iPhone e no Android 12+; "media-server.local" so resolve se o
    Mac tiver sido renomeado para isso — fica como ultimo recurso.
    """
    for nome in _local_hostnames():
        if nome != "media-server.local":
            return nome
    return "media-server.local"


def _ensure_ssl_cert(cert_dir, local_ip):
    """Generate a locally-trusted SSL cert using mkcert (preferred) or openssl.

    mkcert creates a CA-trusted certificate — required by the Cast SDK
    (self-signed certs are rejected even with correct SAN).
    Regenerates if the IP or any .local hostname is missing from the cert.
    Returns (cert_path, key_path) or (None, None) on failure.
    """
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"

    hostnames = ["localhost", *_local_hostnames()]
    # Tokens exatos como o openssl mostra na seção Subject Alternative Name
    required = [f"DNS:{n}" for n in hostnames] + [f"IP Address:{local_ip}"]

    # Check if existing cert still covers this IP and the hostnames
    if cert_path.exists() and key_path.exists():
        try:
            existing = subprocess.run(
                ["openssl", "x509", "-in", str(cert_path), "-noout", "-text"],
                check=True, capture_output=True, timeout=10, text=True,
            )
            missing = [t for t in required if t not in existing.stdout]
            if not missing:
                return cert_path, key_path
            print(f"[12:00 Media Server] SSL cert outdated (missing {', '.join(missing)}), "
                  f"regenerating...", flush=True)
            cert_path.unlink(missing_ok=True)
            key_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Prefer mkcert (CA-trusted = Cast SDK works)
    if shutil.which("mkcert"):
        print("[12:00 Media Server] Generating CA-trusted SSL certificate via mkcert...", flush=True)
        try:
            subprocess.run(
                ["mkcert", "-key-file", str(key_path), "-cert-file", str(cert_path),
                 *hostnames, local_ip],
                check=True, capture_output=True, timeout=15,
            )
            key_path.chmod(0o600)
            print(f"[12:00 Media Server] mkcert cert created: {cert_path}", flush=True)
            return cert_path, key_path
        except Exception as e:
            print(f"[12:00 Media Server] mkcert failed ({e}), falling back to openssl...", flush=True)

    # Fallback: openssl self-signed (Cast SDK may not work)
    print("[12:00 Media Server] Generating self-signed SSL certificate via openssl...", flush=True)
    san = ",".join([f"DNS:{n}" for n in hostnames] + [f"IP:{local_ip}"])
    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(key_path),
                "-out", str(cert_path),
                "-days", "3650",
                "-nodes",
                "-subj", "/CN=Media Server",
                "-addext", f"subjectAltName={san}",
            ],
            check=True, capture_output=True, timeout=15,
        )
        key_path.chmod(0o600)
        print(f"[12:00 Media Server] Self-signed cert created: {cert_path}", flush=True)
        return cert_path, key_path
    except Exception as e:
        print(f"[12:00 Media Server] WARNING: Could not generate SSL cert: {e}", flush=True)
        print("[12:00 Media Server] Chromecast discovery will require HTTPS.", flush=True)
        return None, None


def mkcert_root_ca_path():
    """Caminho do rootCA.pem do mkcert — a CA que assina o cert do app.

    E o arquivo que celulares instalam (iOS/Android) para o navegador confiar
    no HTTPS local sem aviso de certificado. So o certificado publico e
    distribuido: a chave (rootCA-key.pem) nunca deve sair do computador.
    Devolve None se o mkcert nao estiver instalado ou a CA nao existir.
    """
    candidatos = []
    env_caroot = os.environ.get("CAROOT")
    if env_caroot:
        candidatos.append(Path(env_caroot))
    try:
        res = subprocess.run(["mkcert", "-CAROOT"],
                             capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            candidatos.append(Path(res.stdout.strip()))
    except Exception:
        pass
    candidatos.append(Path.home() / "Library" / "Application Support" / "mkcert")
    for base in candidatos:
        ca = base / "rootCA.pem"
        if ca.is_file():
            return ca
    return None


def start_https_server(handler_class, host, https_port, cert_path, key_path):
    """Start an HTTPS server on a daemon thread wrapping the same handler.

    Returns the server object (for cleanup) or None on failure.
    """
    global ACTIVE_HTTPS_PORT
    try:
        import ssl as _ssl
        httpd = http.server.ThreadingHTTPServer((host, https_port), handler_class)
        httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        ACTIVE_HTTPS_PORT = https_port
        print(f"[12:00 Media Server] HTTPS on https://localhost:{https_port}", flush=True)
        return httpd
    except Exception as e:
        print(f"[12:00 Media Server] WARNING: Could not start HTTPS server: {e}", flush=True)
        print("[12:00 Media Server] Continuing with HTTP only.", flush=True)
        return None


def active_https_port():
    """Porta do HTTPS em execucao — None se ele nao subiu."""
    return ACTIVE_HTTPS_PORT


def find_free_port():
    """Sempre usa PORT. Se ocupada, mata a instância anterior."""
    env_port = env("PORT") or None
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
        print(f"[12:00 Media Server] Porta {port} ocupada por {', '.join(pids) or '?'}. "
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
            print(f"[12:00 Media Server] ERRO: Porta {port} ainda está ocupada. Saia a instância anterior com: pkill -9 -f 'python.*server.py'", flush=True)
            sys.exit(1)
