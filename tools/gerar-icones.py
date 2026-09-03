"""Gera os PNGs do app a partir da mesma forma do favicon.svg.

So biblioteca padrao (zlib + struct): o projeto nao tem dependencias e nao vale
criar uma so para desenhar um triangulo. Supersampling 4x da o antialias.
"""
import struct, zlib, sys
from pathlib import Path

VERMELHO = (0xE5, 0x09, 0x14)
BRANCO = (0xFF, 0xFF, 0xFF)
AMOSTRAS = 4

# mesmas coordenadas do favicon.svg, num quadro de 32
TRI = [(12, 8), (12, 24), (26, 16)]
RAIO_SVG = 6


def dentro_triangulo(px, py, tri):
    def lado(a, b, p):
        return (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0])
    d1 = lado(tri[0], tri[1], (px, py))
    d2 = lado(tri[1], tri[2], (px, py))
    d3 = lado(tri[2], tri[0], (px, py))
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def dentro_quadrado(px, py, lado_, raio):
    if raio <= 0:
        return 0 <= px <= lado_ and 0 <= py <= lado_
    cx = min(max(px, raio), lado_ - raio)
    cy = min(max(py, raio), lado_ - raio)
    return (px-cx)**2 + (py-cy)**2 <= raio*raio


def gerar(tamanho, arredondado, fator, centralizar=False):
    """fator encolhe o triangulo em torno do centro (zona segura do maskable).

    centralizar move o triangulo para o meio exato: a forma do favicon nao e
    simetrica (a ponta vai ate 26 e a base fica em 12), entao sem isso ele fica
    visivelmente deslocado — o que so incomoda no icone maskable, que o Android
    ainda recorta por cima.
    """
    raio = (RAIO_SVG/32)*tamanho if arredondado else 0
    esc = tamanho/32
    centro = tamanho/2
    tri = [(centro + (x*esc-centro)*fator, centro + (y*esc-centro)*fator)
           for x, y in TRI]
    if centralizar:
        dx = centro - (min(p[0] for p in tri) + max(p[0] for p in tri))/2
        dy = centro - (min(p[1] for p in tri) + max(p[1] for p in tri))/2
        tri = [(x+dx, y+dy) for x, y in tri]
    linhas = []
    for y in range(tamanho):
        linha = bytearray()
        for x in range(tamanho):
            r = g = b = a = 0
            for sy in range(AMOSTRAS):
                for sx in range(AMOSTRAS):
                    px = x + (sx+0.5)/AMOSTRAS
                    py = y + (sy+0.5)/AMOSTRAS
                    if not dentro_quadrado(px, py, tamanho, raio):
                        continue
                    cor = BRANCO if dentro_triangulo(px, py, tri) else VERMELHO
                    r += cor[0]; g += cor[1]; b += cor[2]; a += 255
            n = AMOSTRAS*AMOSTRAS
            linha += bytes((r//n, g//n, b//n, a//n))
        linhas.append(bytes(linha))
    return linhas


def escrever_png(caminho, linhas, tamanho):
    cru = b"".join(b"\x00" + l for l in linhas)
    def chunk(tipo, dados):
        c = struct.pack(">I", len(dados)) + tipo + dados
        return c + struct.pack(">I", zlib.crc32(tipo + dados) & 0xffffffff)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", tamanho, tamanho, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(cru, 9))
           + chunk(b"IEND", b""))
    Path(caminho).write_bytes(png)
    return len(png)


destino = Path(sys.argv[1])
destino.mkdir(parents=True, exist_ok=True)
alvos = [
    # 192 e 512 mantem a geometria exata do favicon.svg, para o icone do app
    # ser reconhecivelmente o mesmo do site
    ("icon-192.png", 192, True, 1.0, False),
    ("icon-512.png", 512, True, 1.0, False),
    # maskable: o Android recorta as bordas, entao o play encolhe para caber na
    # zona segura de 80% e vai para o centro exato
    ("icon-maskable-512.png", 512, False, 0.62, True),
    # iOS aplica a propria mascara: o icone precisa ser quadrado cheio
    ("apple-touch-icon.png", 180, False, 1.0, False),
]
for nome, tam, arred, fator, centro_exato in alvos:
    n = escrever_png(destino/nome, gerar(tam, arred, fator, centro_exato), tam)
    print(f"  {nome:24} {tam}x{tam}  {n/1024:.1f} KB")
