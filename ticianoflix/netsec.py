"""Validacao de Host e Origin.

Fecha DNS rebinding (Host publico apontando pro IP local) e leitura cross-site
(Origin de terceiro). Modulo folha: nao importa nada do proprio pacote.
"""

import urllib.parse


def is_private_host(hostname):
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


def host_allowed(host_header):
    """Valida o header Host. Ausente = cliente HTTP/1.0 local."""
    if not host_header:
        return True
    h = host_header.strip()
    if h.startswith("["):                       # [::1]:9187
        h = h[1:h.index("]")] if "]" in h else h[1:]
    elif h.count(":") == 1:                     # host:porta
        h = h.split(":")[0]
    return is_private_host(h)


def origin_allowed(origin_header):
    """Origin ausente e aceito — Chromecast, <video> e navegacao direta nao mandam."""
    if not origin_header:
        return True
    if origin_header == "null":
        return False
    try:
        return is_private_host(urllib.parse.urlparse(origin_header).hostname)
    except Exception:
        return False
