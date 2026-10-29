"""Gera os 12 avatares de perfil (static/avatars/a01.svg ... a12.svg).

Desenhos simples e chapados, na paleta do app: quadrado de cor com um emblema
retro por cima. Rode de novo se mudar algum desenho: python3 tools/gerar-avatares.py
"""
from pathlib import Path

CREME, GRAFITE, PRETO = "#efe6d0", "#2a2a2e", "#0e0e10"
VERM, AMBAR, VERDE, AZUL, ROXO = "#f02828", "#d9a441", "#4fb3a3", "#4a76c9", "#8a5fc4"

AVATARES = {
    # fita VHS
    "a01": (VERM, f'<rect x="18" y="30" width="60" height="38" rx="3" fill="{GRAFITE}"/>'
                  f'<rect x="26" y="36" width="44" height="18" rx="2" fill="{CREME}"/>'
                  f'<rect x="26" y="36" width="44" height="5" fill="#c0392b"/>'
                  f'<circle cx="36" cy="60" r="4" fill="{CREME}"/><circle cx="60" cy="60" r="4" fill="{CREME}"/>'),
    # balde de pipoca
    "a02": (AMBAR, f'<circle cx="34" cy="34" r="9" fill="{CREME}"/><circle cx="48" cy="28" r="10" fill="{CREME}"/>'
                   f'<circle cx="62" cy="34" r="9" fill="{CREME}"/>'
                   f'<path d="M24 40h48l-6 36H30z" fill="{CREME}"/>'
                   f'<path d="M34 40l2 36h-5zM48 40v36h-5zM62 40l-2 36h5z" fill="{VERM}"/>'),
    # claquete
    "a03": (GRAFITE, f'<rect x="20" y="40" width="56" height="34" rx="3" fill="{CREME}"/>'
                     f'<path d="M20 28l56-8 3 12-56 8z" fill="{PRETO}"/>'
                     f'<path d="M30 26l8 10M44 24l8 10M58 22l8 10" stroke="{CREME}" stroke-width="5"/>'
                     f'<rect x="28" y="50" width="30" height="4" fill="{PRETO}"/><rect x="28" y="60" width="20" height="4" fill="{PRETO}"/>'),
    # rolo de filme
    "a04": (VERDE, f'<circle cx="48" cy="48" r="28" fill="{PRETO}"/><circle cx="48" cy="48" r="6" fill="{VERDE}"/>'
                   f'<circle cx="48" cy="30" r="6" fill="{VERDE}"/><circle cx="48" cy="66" r="6" fill="{VERDE}"/>'
                   f'<circle cx="30" cy="48" r="6" fill="{VERDE}"/><circle cx="66" cy="48" r="6" fill="{VERDE}"/>'),
    # ingresso
    "a05": (ROXO, f'<path d="M14 32h68v10a6 6 0 0 0 0 12v10H14V54a6 6 0 0 0 0-12z" fill="{CREME}"/>'
                  f'<path d="M62 32v32" stroke="{ROXO}" stroke-width="3" stroke-dasharray="4 4"/>'
                  f'<rect x="22" y="42" width="30" height="5" fill="{GRAFITE}"/><rect x="22" y="52" width="22" height="5" fill="{GRAFITE}"/>'),
    # oculos 3D
    "a06": (CREME, f'<rect x="12" y="38" width="32" height="22" rx="3" fill="{VERM}"/>'
                   f'<rect x="52" y="38" width="32" height="22" rx="3" fill="{AZUL}"/>'
                   f'<path d="M44 46h8M12 44l-4-6M84 44l4-6" stroke="{PRETO}" stroke-width="4" stroke-linecap="square"/>'),
    # robo
    "a07": (AZUL, f'<rect x="22" y="30" width="52" height="44" rx="5" fill="{CREME}"/>'
                  f'<rect x="30" y="42" width="12" height="12" fill="{PRETO}"/><rect x="54" y="42" width="12" height="12" fill="{PRETO}"/>'
                  f'<rect x="34" y="62" width="28" height="5" fill="{PRETO}"/>'
                  f'<path d="M48 30V20" stroke="{CREME}" stroke-width="4"/><circle cx="48" cy="18" r="4" fill="{VERM}"/>'),
    # fantasma
    "a08": (GRAFITE, f'<path d="M24 74V46a24 24 0 0 1 48 0v28l-8-6-8 6-8-6-8 6-8-6z" fill="{CREME}"/>'
                     f'<circle cx="40" cy="46" r="5" fill="{PRETO}"/><circle cx="58" cy="46" r="5" fill="{PRETO}"/>'),
    # gato
    "a09": (AMBAR, f'<path d="M22 28l14 12h24l14-12v34a26 26 0 0 1-52 0z" fill="{GRAFITE}"/>'
                   f'<circle cx="38" cy="52" r="4" fill="{AMBAR}"/><circle cx="58" cy="52" r="4" fill="{AMBAR}"/>'
                   f'<path d="M44 62h8l-4 5z" fill="{VERM}"/>'),
    # foguete
    "a10": ("#243a6b", f'<path d="M48 14c14 12 16 32 12 46H36c-4-14-2-34 12-46z" fill="{CREME}"/>'
                   f'<circle cx="48" cy="38" r="7" fill="{AZUL}"/>'
                   f'<path d="M36 52l-12 14 14-2zM60 52l12 14-14-2z" fill="{VERM}"/>'
                   f'<path d="M42 64h12l-6 14z" fill="{AMBAR}"/>'),
    # estrela
    "a11": (VERM, f'<path d="M48 16l9 21 23 2-17 15 5 22-20-12-20 12 5-22-17-15 23-2z" fill="{AMBAR}"/>'),
    # TV
    "a12": (VERDE, f'<rect x="16" y="34" width="64" height="44" rx="5" fill="{GRAFITE}"/>'
                   f'<rect x="22" y="40" width="38" height="32" rx="3" fill="{CREME}"/>'
                   f'<circle cx="69" cy="48" r="4" fill="{VERM}"/><circle cx="69" cy="62" r="4" fill="{AMBAR}"/>'
                   f'<path d="M34 34l-10-14M62 34l10-14" stroke="{GRAFITE}" stroke-width="4"/>'),
}

destino = Path(__file__).resolve().parent.parent / "static" / "avatars"
destino.mkdir(parents=True, exist_ok=True)
for nome, (fundo, corpo) in AVATARES.items():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
           f'<rect width="96" height="96" fill="{fundo}"/>{corpo}</svg>\n')
    (destino / (nome + ".svg")).write_text(svg, encoding="utf-8")
print("%d avatares em %s" % (len(AVATARES), destino))
