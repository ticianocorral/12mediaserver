"""Gera os icones de marca que nao vem do branding.py.

  favicon.svg / favicon.ico  so o "12" digital (7 segmentos), sem o videocassete;
                             copias em docs/assets e docs/press/assets.
  app da TV (APK)            banner (launcher da Android TV) e ic_launcher, a
                             partir do wordmark horizontal (static/wordmark.svg).

Uso: python3 tools/gerar_icones_marca.py   (requer Pillow)
"""
import io
import re
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
WORDMARK = (RAIZ / "static" / "wordmark.svg").read_text(encoding="utf-8")
RES = RAIZ / "tv" / "app" / "src" / "main" / "res"
SS = 4  # supersampling

FUNDO = "#0b0b0f"
ACESO, APAGADO = "#ff2a2a", "#3d0f12"
FONTE = "/System/Library/Fonts/Supplemental/Arial Black.ttf"

# Segmentos de um digito (x, y, w, h) num quadro 6x11 e os acesos de "1" e "2".
SEG = {"a": (1, 0, 4, 1), "b": (5, 1, 1, 4), "c": (5, 6, 1, 4), "d": (1, 10, 4, 1),
       "e": (0, 6, 1, 4), "f": (0, 1, 1, 4), "g": (1, 5, 4, 1)}
ACESOS = {"1": "bc", "2": "abdeg"}


# ── favicon: so o "12" ───────────────────────────────────────
def favicon_svg():
    esc, x0, y0, gap = 1.9, 2.7, 5.55, 8
    pecas = ['<rect width="32" height="32" rx="6" fill="#050505"/>']
    for i, dig in enumerate("12"):
        for nome, (x, y, w, h) in SEG.items():
            cor = ACESO if nome in ACESOS[dig] else APAGADO
            pecas.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="0.4" fill="%s"/>'
                         % (x0 + (i * gap + x) * esc, y0 + y * esc, w * esc, h * esc, cor))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">\n  '
            + "\n  ".join(pecas) + "\n</svg>\n")


def favicon_png(lado):
    k = lado * SS / 32
    img = Image.new("RGBA", (int(32 * k),) * 2, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, 32 * k - 1, 32 * k - 1], radius=6 * k, fill="#050505")
    esc, x0, y0, gap = 1.9, 2.7, 5.55, 8
    for i, dig in enumerate("12"):
        for nome, (x, y, w, h) in SEG.items():
            cor = ACESO if nome in ACESOS[dig] else APAGADO
            px, py = x0 + (i * gap + x) * esc, y0 + y * esc
            d.rounded_rectangle([px * k, py * k, (px + w * esc) * k, (py + h * esc) * k],
                                radius=0.4 * esc * k, fill=cor)
    return img.resize((lado, lado), Image.LANCZOS)


def favicon_ico(tamanhos=(16, 32, 48)):
    pngs = []
    for t in tamanhos:
        buf = io.BytesIO()
        favicon_png(t).save(buf, "PNG")
        pngs.append((t, buf.getvalue()))
    cab = struct.pack("<HHH", 0, 1, len(pngs))
    off = 6 + 16 * len(pngs)
    dirs, corpo = b"", b""
    for t, d in pngs:
        dirs += struct.pack("<BBBBHHII", t, t, 0, 0, 1, 32, len(d), off)
        off += len(d)
        corpo += d
    return cab + dirs + corpo


# ── wordmark horizontal (viewBox 124x25) ─────────────────────
def attrs(tag):
    return dict(re.findall(r'([\w-]+)="([^"]*)"', tag))


def desenhar_wordmark(largura):
    """Renderiza static/wordmark.svg na largura pedida, fundo transparente."""
    k = largura * SS / 124
    img = Image.new("RGBA", (int(124 * k), int(25 * k)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cores = {"on": ACESO, "off": APAGADO}
    corpo = WORDMARK.split("</style>", 1)[1]
    for m in re.finditer(r'<g transform="translate\(([\d.]+),([\d.]+)\) scale\(([\d.]+)\)">(.*?)</g>'
                         r'|<rect[^>]*/>|<text[^>]*>[^<]*</text>', corpo, re.S):
        if m.group(1):
            tx, ty, esc = float(m.group(1)), float(m.group(2)), float(m.group(3))
            for r in re.findall(r"<rect[^>]*/>", m.group(4)):
                a = attrs(r)
                x, y = tx + float(a["x"]) * esc, ty + float(a["y"]) * esc
                w, h = float(a["width"]) * esc, float(a["height"]) * esc
                d.rounded_rectangle([x * k, y * k, (x + w) * k, (y + h) * k],
                                    radius=float(a.get("rx", 0)) * esc * k, fill=cores[a["class"]])
            continue
        tag = m.group(0)
        a = attrs(tag)
        if tag.startswith("<rect"):
            x, y, w, h = (float(a[n]) for n in ("x", "y", "width", "height"))
            d.rectangle([x * k, y * k, (x + w) * k, (y + h) * k], fill=cores[a["class"]])
        else:
            txt = re.sub(r"<[^>]*>", "", tag)
            tam = float(a["font-size"])
            f = ImageFont.truetype(FONTE, int(tam * 1.0 * k))
            larg = float(a["textLength"])
            tmp = Image.new("RGBA", (int(d.textlength(txt, font=f)) + 2, int(tam * 1.6 * k)), (0, 0, 0, 0))
            ImageDraw.Draw(tmp).text((0, int(tam * 1.2 * k)), txt, font=f, fill=a["fill"], anchor="ls")
            tmp = tmp.resize((int(larg * k), tmp.height))
            img.alpha_composite(tmp, (int(float(a["x"]) * k), int((float(a["y"]) - tam * 1.2) * k)))
    return img.resize((largura, int(largura * 25 / 124)), Image.LANCZOS)


def salvar(img, caminho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img.save(caminho, optimize=True)


def banner(w=640, h=360):
    fundo = Image.new("RGBA", (w, h), FUNDO)
    logo = desenhar_wordmark(int(w * 0.8))
    fundo.alpha_composite(logo, ((w - logo.width) // 2, (h - logo.height) // 2))
    return fundo.convert("RGB")


def icone(lado):
    img = Image.new("RGBA", (lado, lado), FUNDO)
    logo = desenhar_wordmark(max(240, lado * 4))
    alvo = int(lado * 0.88)
    logo = logo.resize((alvo, max(1, int(alvo * logo.height / logo.width))), Image.LANCZOS)
    img.alpha_composite(logo, ((lado - logo.width) // 2, (lado - logo.height) // 2))
    return img


if __name__ == "__main__":
    svg = favicon_svg()
    for destino in (RAIZ, RAIZ / "docs" / "assets", RAIZ / "docs" / "press" / "assets"):
        (destino / "favicon.svg").write_text(svg, encoding="utf-8")
    (RAIZ / "favicon.ico").write_bytes(favicon_ico())

    salvar(banner(), RES / "drawable-xhdpi" / "banner.png")
    for pasta, lado in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        salvar(icone(lado), RES / f"mipmap-{pasta}" / "ic_launcher.png")
    print("ok")
