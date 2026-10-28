"""Validacao de Host e Origin.

Fecha DNS rebinding (Host publico apontando pro IP local) e leitura cross-site
(Origin de terceiro). Modulo folha: nao importa nada do proprio pacote.
"""

import ipaddress
import urllib.parse

# CGNAT (Tailscale): o ipaddress desta versao do Python nao marca a faixa
# como privada, entao ela fica explicita aqui.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _ip_local(h):
    """True/False para IP literal; None quando nao e IP (hostname).

    Antes isso era prefixo de string — qualquer dominio publico comecando
    com "fc"/"fd" ("fc-evil.com", "fdic.gov") passava como se fosse IPv6
    privado, derrubando o DNS rebinding que este modulo existe para fechar.
    """
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return None
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified:
        return True
    return isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT


def is_private_host(hostname):
    """True para nomes/IPs locais ou de rede privada."""
    if not hostname:
        return False
    h = hostname.strip().strip("[]").lower()
    if h == "localhost":
        return True
    if h.endswith((".local", ".localhost", ".lan", ".internal", ".home.arpa")):
        return True
    return _ip_local(h) is True


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
