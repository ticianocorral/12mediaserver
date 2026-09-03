"""Marca configuravel: nome, cor e icone do app.

Principio: nome de exibicao e mutavel; identidade de armazenamento e fixa.
Trocar a marca aqui nunca move nem apaga dado nenhum — CACHE_DIR, o nome do
banco, o rotulo do servico continuam os mesmos de sempre, porque amarrar os
dois seria o pior tipo de acidente: renomear o app e "perder" a biblioteca.

Persistido em CACHE_DIR/branding.json, fora do SQLite pelo mesmo motivo do
sources.json: e configuracao, nao cache — restaurar um backup feito em outra
maquina nao deve importar o nome/cor de la.

Modulo folha: importa so o config.
"""

import json
import os
import re
import struct
import threading
import zlib
from pathlib import Path

from .config import BRANDING_PATH, CACHE_DIR

NOME_PADRAO = "TicianoFlix"
COR_PADRAO = "#e50914"

_RE_COR = re.compile(r"^#[0-9a-fA-F]{6}$")

_lock = threading.Lock()
_cache = None


def _nome_valido(nome):
    nome = (nome or "").strip()
    return 1 <= len(nome) <= 40


def _cor_valida(cor):
    return bool(_RE_COR.match(cor or ""))


def get():
    """Marca atual. Nunca falha — sem arquivo ou com arquivo invalido, cai
    no padrao neutro em vez de quebrar a pagina."""
    global _cache
    with _lock:
        if _cache is not None:
            return dict(_cache)
        dados = {"nome": NOME_PADRAO, "cor": COR_PADRAO}
        try:
            bruto = json.loads(BRANDING_PATH.read_text(encoding="utf-8"))
            if isinstance(bruto, dict):
                if _nome_valido(bruto.get("nome")):
                    dados["nome"] = bruto["nome"].strip()
                if _cor_valida(bruto.get("cor")):
                    dados["cor"] = bruto["cor"].lower()
        except (OSError, ValueError):
            pass
        _cache = dados
        return dict(dados)


def set(nome, cor):
    """Valida e grava. Devolve (ok: bool, erro: str|None)."""
    global _cache
    nome = (nome or "").strip()
    cor = (cor or "").strip()
    if not _nome_valido(nome):
        return False, "O nome precisa ter entre 1 e 40 caracteres"
    if not _cor_valida(cor):
        return False, "A cor precisa ser hexadecimal, por exemplo #e50914"
    dados = {"nome": nome, "cor": cor.lower()}
    tmp = BRANDING_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, BRANDING_PATH)
    try:
        os.chmod(BRANDING_PATH, 0o600)
    except OSError:
        pass
    with _lock:
        _cache = dados
        # O cache de icones fica preso ao nome do arquivo (tamanho+cor), entao
        # trocar a cor por si so ja gera um caminho novo — nao ha nada pra
        # invalidar ali. So o cache em memoria da marca precisa ser derrubado,
        # e ja foi, na linha acima.
    return True, None


def _clarear(cor_hex, fator=0.15):
    """Mistura a cor com branco — usado no estado :hover do botao primario."""
    r = int(cor_hex[1:3], 16)
    g = int(cor_hex[3:5], 16)
    b = int(cor_hex[5:7], 16)
    r = round(r + (255 - r) * fator)
    g = round(g + (255 - g) * fator)
    b = round(b + (255 - b) * fator)
    return "#%02x%02x%02x" % (r, g, b)


def css():
    """Variaveis de CSS que sobrescrevem o vermelho padrao do styles.css.
    Carregado depois dele no <head>, entao a mesma especificidade em :root
    basta pra vencer a cascata."""
    marca = get()
    cor = marca["cor"]
    hover = _clarear(cor)
    return ":root{--primary:%s;--primary-hover:%s;--accent:%s;}" % (cor, hover, cor)


# ── Icones ────────────────────────────────────────────────────
# Mesma tecnica do tools/gerar-icones.py (zlib + struct, sem dependencia), mas
# parametrizada pela cor escolhida e com cache em disco: gerar um PNG de 512px
# pixel a pixel com supersampling 4x nao e caro o bastante pra doer, mas nao ha
# razao pra refazer a cada requisicao quando a cor nao mudou.
_AMOSTRAS = 4
_TRI = [(12, 8), (12, 24), (26, 16)]  # mesmas coordenadas do favicon.svg
_RAIO_SVG = 6

# tamanho, arredondado (cantos vivos = icone comum; sem isso = maskable, que o
# Android recorta por cima), fator (encolhe o triangulo pra caber na zona
# segura do maskable), centralizar (o triangulo do favicon nao e simetrico —
# so importa recentralizar quando ele ja foi encolhido)
_ICONES = {
    "192": (192, True, 1.0, False),
    "512": (512, True, 1.0, False),
    "maskable-512": (512, False, 0.62, True),
    "apple-touch": (180, False, 1.0, False),
}


def _dentro_triangulo(px, py, tri):
    def lado(a, b, p):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    d1 = lado(tri[0], tri[1], (px, py))
    d2 = lado(tri[1], tri[2], (px, py))
    d3 = lado(tri[2], tri[0], (px, py))
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def _dentro_quadrado(px, py, lado_, raio):
    if raio <= 0:
        return 0 <= px <= lado_ and 0 <= py <= lado_
    cx = min(max(px, raio), lado_ - raio)
    cy = min(max(py, raio), lado_ - raio)
    return (px - cx) ** 2 + (py - cy) ** 2 <= raio * raio


def _desenhar(tamanho, cor_rgb, arredondado, fator, centralizar):
    raio = (_RAIO_SVG / 32) * tamanho if arredondado else 0
    esc = tamanho / 32
    centro = tamanho / 2
    tri = [(centro + (x * esc - centro) * fator, centro + (y * esc - centro) * fator)
           for x, y in _TRI]
    if centralizar:
        dx = centro - (min(p[0] for p in tri) + max(p[0] for p in tri)) / 2
        dy = centro - (min(p[1] for p in tri) + max(p[1] for p in tri)) / 2
        tri = [(x + dx, y + dy) for x, y in tri]
    branco = (0xFF, 0xFF, 0xFF)
    linhas = []
    for y in range(tamanho):
        linha = bytearray()
        for x in range(tamanho):
            r = g = b = a = 0
            for sy in range(_AMOSTRAS):
                for sx in range(_AMOSTRAS):
                    px = x + (sx + 0.5) / _AMOSTRAS
                    py = y + (sy + 0.5) / _AMOSTRAS
                    if not _dentro_quadrado(px, py, tamanho, raio):
                        continue
                    cor = branco if _dentro_triangulo(px, py, tri) else cor_rgb
                    r += cor[0]; g += cor[1]; b += cor[2]; a += 255
            n = _AMOSTRAS * _AMOSTRAS
            linha += bytes((r // n, g // n, b // n, a // n))
        linhas.append(bytes(linha))
    return linhas


def _codificar_png(linhas, tamanho):
    cru = b"".join(b"\x00" + l for l in linhas)

    def chunk(tipo, dados):
        c = struct.pack(">I", len(dados)) + tipo + dados
        return c + struct.pack(">I", zlib.crc32(tipo + dados) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", tamanho, tamanho, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(cru, 9))
            + chunk(b"IEND", b""))


_ICONS_CACHE_DIR = CACHE_DIR / "branding-icons"


def icone_png(chave):
    """Bytes do PNG pra uma das chaves de _ICONES, na cor da marca atual.
    Devolve None para chave desconhecida — o handler responde 404."""
    spec = _ICONES.get(chave)
    if spec is None:
        return None
    tamanho, arredondado, fator, centralizar = spec
    cor_hex = get()["cor"].lstrip("#")
    _ICONS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    caminho = _ICONS_CACHE_DIR / ("%s-%s.png" % (chave, cor_hex))
    if caminho.exists():
        try:
            return caminho.read_bytes()
        except OSError:
            pass
    cor_rgb = tuple(int(cor_hex[i:i + 2], 16) for i in (0, 2, 4))
    dados = _codificar_png(
        _desenhar(tamanho, cor_rgb, arredondado, fator, centralizar), tamanho)
    try:
        tmp = caminho.with_suffix(".tmp")
        tmp.write_bytes(dados)
        os.replace(tmp, caminho)
    except OSError:
        pass
    return dados


def manifest_json():
    """Conteudo do manifest.webmanifest, com o nome escolhido."""
    marca = get()
    return json.dumps({
        "name": marca["nome"],
        "short_name": marca["nome"],
        "description": "Seu acervo de filmes, na sua rede.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#141414",
        "theme_color": "#141414",
        "icons": [
            {"src": "/icone-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": "/icone-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": "/icone-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }, ensure_ascii=False, indent=2)
