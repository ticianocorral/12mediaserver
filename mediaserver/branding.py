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

NOME_PADRAO = "12:00 Media Server"
COR_PADRAO = "#f02828"
# O nome padrao tem ":" (nao vale em nome de pasta), entao a pasta real do
# acervo no HD/pendrive e na nuvem usa esta forma. Nomes escolhidos na
# instalacao ja nao podem ter ":" e viram a pasta como estao.
PASTA_PADRAO = "Media Server"

_RE_COR = re.compile(r"^#[0-9a-fA-F]{6}$")
# O nome vira pasta real na nuvem/HD/pendrive (ver pasta_biblioteca()), entao
# nao pode conter nada invalido em nome de arquivo em nenhum dos tres SOs.
_RE_NOME_INVALIDO = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

_lock = threading.Lock()
_cache = None


def _nome_valido(nome):
    nome = (nome or "").strip()
    if not (1 <= len(nome) <= 40):
        return False
    return not _RE_NOME_INVALIDO.search(nome)


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


def set(nome=None, cor=None):
    """Valida e grava so os campos fornecidos; o outro mantem o valor atual.
    Devolve (ok: bool, erro: str|None).

    Nome nunca e passado por quem edita a marca ja instalada (Ajustes so
    manda cor) — e essa omissao, e nao uma flag de "travado", que torna o
    nome imutavel depois da instalacao. So _handle_auth_setup passa nome,
    e so roda uma vez, antes de existir administrador."""
    global _cache
    atual = get()
    novo_nome = atual["nome"] if nome is None else (nome or "").strip()
    novo_cor = atual["cor"] if cor is None else (cor or "").strip()
    if nome is not None and novo_nome != NOME_PADRAO and not _nome_valido(novo_nome):
        return False, ("O nome precisa ter entre 1 e 40 caracteres e nao "
                       'pode conter \\ / : * ? " < > |')
    if cor is not None and not _cor_valida(novo_cor):
        return False, "A cor precisa ser hexadecimal, por exemplo #f02828"
    dados = {"nome": novo_nome, "cor": novo_cor.lower()}
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


def pasta_biblioteca():
    """Nome real da pasta da biblioteca (nuvem, HD, pendrive): o nome escolhido
    na instalacao, imutavel depois disso — ver set() e localfs.catalog_dir_name()."""
    nome = get()["nome"]
    return PASTA_PADRAO if nome == NOME_PADRAO else nome


def logical_root():
    """Prefixo logico usado no banco/rclone/frontend pra raiz do acervo no
    nuvem. Ver mediaserver/paths.py pra como isso vira (ou nao) pasta real."""
    return "/" + pasta_biblioteca()


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
# Zlib + struct, sem dependencia, e
# parametrizada pela cor escolhida e com cache em disco: gerar um PNG de 512px
# pixel a pixel com supersampling 4x nao e caro o bastante pra doer, mas nao ha
# razao pra refazer a cada requisicao quando a cor nao mudou.
#
# O desenho e o videocassete do logo, simplificado pra caber num quadrado:
# chassi cinza, etiqueta creme com faixa vermelha, e o display "12:00" de 7
# segmentos na cor da marca (segmentos apagados num tom bem escuro dela).
_AMOSTRAS = 4
_RAIO_SVG = 6
_FUNDO = (0x05, 0x05, 0x05)
# Troque ao mudar o desenho: entra no nome do arquivo em cache, entao PNGs de
# versoes anteriores deixam de ser servidos.
_VERSAO_ICONE = "v3"

# Segmentos a b c d e f g de um digito (x, y, largura, altura) num quadro 6x11,
# e quais acendem em cada digito de "12:00".
_SEG = {"a": (1, 0, 4, 1), "b": (5, 1, 1, 4), "c": (5, 6, 1, 4), "d": (1, 10, 4, 1),
        "e": (0, 6, 1, 4), "f": (0, 1, 1, 4), "g": (1, 5, 4, 1)}
_ACESOS = {1: "bc", 2: "abdeg", 0: "abcdef"}
# (digito, x) dentro do display, no quadro de 32 do icone
_DIGITOS = [(1, 4.7), (2, 7.3), (0, 10.9), (0, 13.5)]
_ESC_DIGITO = 0.36
_Y_DIGITO = 17.22
_DOIS_PONTOS = [(9.95, 18.4, 0.55, 0.55), (9.95, 19.9, 0.55, 0.55)]

# Pecas fixas do videocassete (x, y, w, h, cor), no quadro de 32.
_CHASSI = (0x2A, 0x2A, 0x2E)
_PAINEL = (0x1A, 0x1A, 0x1D)
_CREME = (0xEF, 0xE6, 0xD0)
_FAIXA = (0xC0, 0x39, 0x2B)
_CINZA = (0x55, 0x55, 0x5C)
_PECAS = [
    (2, 9, 28, 14, _CHASSI),
    (3, 10, 26, 6.4, _PAINEL),
    (5, 10.6, 22, 5, _CREME),
    (5, 10.6, 22, 1.5, _FAIXA),
    (8, 13.4, 16, 0.9, _PAINEL),
    (4, 16.9, 11.6, 4.6, (0x04, 0x05, 0x04)),
    (17.4, 17.6, 2.6, 1, _CINZA), (20.6, 17.6, 2.6, 1, _CINZA),
    (17.4, 19.6, 2.6, 1, _CINZA), (20.6, 19.6, 2.6, 1, _CINZA),
    (24.2, 17.2, 4.2, 3.4, (0xE8, 0xE8, 0xE8)),
    (26.3, 17.2, 2.1, 3.4, _PAINEL),
]

# tamanho, arredondado (cantos vivos = icone comum; sem isso = maskable, que o
# Android recorta por cima), fator (encolhe o desenho pra caber na zona segura
# do maskable)
_ICONES = {
    "192": (192, True, 1.0),
    "512": (512, True, 1.0),
    "maskable-512": (512, False, 0.8),
    "apple-touch": (180, False, 1.0),
}


def _retangulos(tamanho, fator):
    """Lista (x, y, w, h, cor) em pixels, centralizada e escalada por fator.
    cor e uma tupla RGB ou as chaves "aceso" / "apagado" (cor da marca)."""
    esc = tamanho / 32
    centro = tamanho / 2
    rects = []

    def add(x, y, w, h, cor):
        rects.append((centro + (x * esc - centro) * fator,
                      centro + (y * esc - centro) * fator,
                      w * esc * fator, h * esc * fator, cor))

    for x, y, w, h, cor in _PECAS:
        add(x, y, w, h, cor)
    for digito, x0 in _DIGITOS:
        for nome, (sx, sy, sw, sh) in _SEG.items():
            add(x0 + sx * _ESC_DIGITO, _Y_DIGITO + sy * _ESC_DIGITO,
                sw * _ESC_DIGITO, sh * _ESC_DIGITO,
                "aceso" if nome in _ACESOS[digito] else "apagado")
    for x, y, w, h in _DOIS_PONTOS:
        add(x, y, w, h, "aceso")
    return rects


def _dentro_quadrado(px, py, lado_, raio):
    if raio <= 0:
        return 0 <= px <= lado_ and 0 <= py <= lado_
    cx = min(max(px, raio), lado_ - raio)
    cy = min(max(py, raio), lado_ - raio)
    return (px - cx) ** 2 + (py - cy) ** 2 <= raio * raio


def _desenhar(tamanho, cor_rgb, arredondado, fator):
    raio = (_RAIO_SVG / 32) * tamanho if arredondado else 0
    apagado = tuple(round(f + (c - f) * 0.2) for f, c in zip(_FUNDO, cor_rgb))
    rects = _retangulos(tamanho, fator)
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
                    cor = _FUNDO
                    # desenho de baixo pra cima: a ultima peca que cobre o ponto vence
                    for rx, ry, rw, rh, c in rects:
                        if rx <= px < rx + rw and ry <= py < ry + rh:
                            cor = cor_rgb if c == "aceso" else apagado if c == "apagado" else c
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
    tamanho, arredondado, fator = spec
    cor_hex = get()["cor"].lstrip("#")
    _ICONS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    caminho = _ICONS_CACHE_DIR / ("%s-%s-%s.png" % (chave, cor_hex, _VERSAO_ICONE))
    if caminho.exists():
        try:
            return caminho.read_bytes()
        except OSError:
            pass
    cor_rgb = tuple(int(cor_hex[i:i + 2], 16) for i in (0, 2, 4))
    dados = _codificar_png(
        _desenhar(tamanho, cor_rgb, arredondado, fator), tamanho)
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
        "background_color": "#0e0e10",
        "theme_color": "#0e0e10",
        "icons": [
            {"src": "/icone-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": "/icone-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": "/icone-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }, ensure_ascii=False, indent=2)
