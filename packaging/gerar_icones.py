"""Gera os icones dos instaladores a partir do desenho do proprio app
(mediaserver/branding.py): PNGs, app.ico (Windows) e, no macOS, app.icns.

Uso: python3 packaging/gerar_icones.py <pasta-de-saida>
"""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# O branding grava icones em cache dentro do HOME; este script nao precisa disso.
from mediaserver import branding  # noqa: E402

COR = (0xF0, 0x28, 0x28)
TAMANHOS = (16, 32, 48, 64, 128, 256, 512)


def png(tamanho):
    return branding._codificar_png(branding._desenhar(tamanho, COR, True, 1.0), tamanho)


def ico(pngs):
    """ICO com PNGs dentro (aceito do Windows Vista em diante)."""
    itens = [(t, d) for t, d in pngs if t <= 256]
    cab = struct.pack("<HHH", 0, 1, len(itens))
    offset = 6 + 16 * len(itens)
    dirs, corpo = b"", b""
    for t, d in itens:
        dirs += struct.pack("<BBBBHHII", t % 256, t % 256, 0, 0, 1, 32, len(d), offset)
        offset += len(d)
        corpo += d
    return cab + dirs + corpo


def main(saida):
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    pngs = [(t, png(t)) for t in TAMANHOS]
    for t, d in pngs:
        (saida / ("icone-%d.png" % t)).write_bytes(d)
    (saida / "app.ico").write_bytes(ico(pngs))
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as tmp:
            conj = Path(tmp) / "app.iconset"
            conj.mkdir()
            nomes = {16: "icon_16x16", 32: "icon_32x32", 128: "icon_128x128",
                     256: "icon_256x256", 512: "icon_512x512"}
            for t, d in pngs:
                if t in nomes:
                    (conj / (nomes[t] + ".png")).write_bytes(d)
            # versoes @2x: reaproveita o proximo tamanho
            for t2, nome in ((32, "icon_16x16@2x"), (64, "icon_32x32@2x"),
                             (256, "icon_128x128@2x"), (512, "icon_256x256@2x")):
                (conj / (nome + ".png")).write_bytes(dict(pngs)[t2])
            subprocess.run(["iconutil", "-c", "icns", str(conj), "-o",
                            str(saida / "app.icns")], check=True)
    print("icones em", saida)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/icones")
