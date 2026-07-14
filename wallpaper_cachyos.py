#!/usr/bin/env python3
"""
Wallpaper CachyOS — Comandos Essenciais
Design premium dark mode com gradientes, glow, cards e grid organizado.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os, math

# ─── COMANDOS ───────────────────────────────────────────────────────────
comandos = [
    ("SISTEMA",     "", [
        "pacman -Syu           # Atualizar tudo",
        "pacman -S <pkg>       # Instalar pacote",
        "pacman -Rns <pkg>     # Remover pacote",
        "pacman -Qe            # Pacotes explícitos",
        "pacman -Ss <termo>    # Buscar pacote",
        "paru -Syu             # AUR + Arch + CachyOS",
        "cachyos-settings      # Centro de controle",
    ]),
    ("DESEMPENHO",  "⚡", [
        "cpupower frequency-set -g performance",
        "cpupower frequency-set -g schedutil",
        "systemd-analyze blame",
        "systemd-analyze critical-chain",
    ]),
    ("KERNEL",      "🐧", [
        "uname -r              # Kernel atual",
        "pacman -Q linux-cachyos",
        "mkinitcpio -P         # Rebuild initramfs",
    ]),
    ("PACOTE / AUR","󰏗", [
        "paru -S <pkg>         # Instalar (AUR+repo)",
        "paru -Qdt             # Órfãos",
        "paru -Sc              # Limpar cache",
        "paru -G <pkg>         # Baixar PKGBUILD",
    ]),
    ("REDE",        "󰤨", [
        "ip a                  # Interfaces",
        "ping -c 4 1.1.1.1     # Teste de rede",
        "iwctl                 # Wi-Fi (IWD)",
        "nmcli                 # NetworkManager",
    ]),
    ("MONITOR",     "󰻠", [
        "btop                  # Monitor interativo",
        "htop                  # Processos",
        "fastfetch             # Info do sistema",
        "nvtop                 # GPU monitor",
    ]),
    ("GPU",         "󰢮", [
        "nvidia-smi            # NVIDIA stats",
        "radeontop             # AMD stats",
        "glxinfo | grep OpenGL",
        "vulkaninfo --summary",
    ]),
    ("ARMAZENAMENTO","󰋊", [
        "df -h                 # Discos",
        "lsblk                 # Partições",
        "fdisk -l              # Tabela de partições",
        "du -sh * | sort -h    # Pastas pesadas",
    ]),
]

# ─── PALETA ─────────────────────────────────────────────────────────────
BG_TOP      = "#0f1419"
BG_BOTTOM   = "#010409"
ACCENT      = "#f0883e"  # Laranja CachyOS
ACCENT2     = "#58a6ff"  # Azul
GREEN       = "#3fb950"
RED         = "#ff7b72"
WHITE       = "#e6edf3"
GRAY        = "#8b949e"
DARK_CARD   = "#151c26"
BORDER      = "#1e2a3a"
BORDER_HL   = "#f0883e"
TITLE_C     = "#f0b37e"  # Laranja claro pro título

def font(tamanho, bold=False):
    """Carrega JetBrains Mono com fallback."""
    nomes = [
        f"JetBrainsMono-{'Bold' if bold else 'Regular'}.ttf",
        f"FiraCode-{'Bold' if bold else 'Regular'}.ttf",
    ]
    dirs = [
        "/usr/share/fonts/TTF",
        "/usr/share/fonts/JetBrainsMono/ttf",
        "/usr/share/fonts/fira-code",
    ]
    for nome in nomes:
        for d in dirs:
            p = os.path.join(d, nome)
            if os.path.exists(p):
                return ImageFont.truetype(p, tamanho)
    try:
        return ImageFont.truetype("DejaVuSansMono.ttf", tamanho)
    except Exception:
        return ImageFont.load_default()

def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """Retângulo arredondado."""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

def draw_cmd_line(draw, x, y, cmd, font_cmd, col_w):
    """Desenha uma linha de comando com prompt colorido e comentário cinza."""
    prompt = "# "
    cor_prompt = GREEN

    # Determina prompt pelo prefixo
    root_cmds = ("pacman","paru","cpupower","systemd-analyze","mkinitcpio",
                 "nvidia","radeontop","fdisk","glxinfo","vulkaninfo","iwctl")
    if cmd.lstrip().startswith(root_cmds):
        prompt, cor_prompt = "# ", GREEN
    else:
        prompt, cor_prompt = "$ ", RED

    # Separa comando e comentário
    if "  # " in cmd:
        cmd_txt, comment = cmd.split("  # ", 1)
        comment = "# " + comment.strip()
    else:
        cmd_txt, comment = cmd.strip(), ""

    pw = draw.textlength(prompt, font=font_cmd)
    cw = draw.textlength(cmd_txt.strip(), font=font_cmd)
    max_w = col_w - 12

    if pw + cw + 30 > max_w:  # não cabe — pula comentário
        draw.text((x, y), prompt + cmd_txt.strip(), fill=cor_prompt if False else WHITE, font=font_cmd)
        return

    draw.text((x, y), prompt, fill=cor_prompt, font=font_cmd)
    draw.text((x + pw, y), cmd_txt.strip(), fill=WHITE, font=font_cmd)
    if comment:
        cx = x + pw + cw + 6
        draw.text((cx, y), comment, fill=GRAY, font=font_cmd)

def generate(largura, altura, path):
    img = Image.new("RGB", (largura, altura))
    draw = ImageDraw.Draw(img)

    # ─── GRADIENTE DE FUNDO ──────────────────────────────────────────
    for y in range(altura):
        t = y / altura
        r = int(15 * (1 - t) + 1 * t)
        g = int(20 * (1 - t) + 4 * t)
        b = int(25 * (1 - t) + 9 * t)
        ImageDraw.Draw(img).line([(0, y), (largura, y)], fill=(r, g, b))

    # ─── GRADE SUTIL ─────────────────────────────────────────────────
    draw_s = ImageDraw.Draw(img)
    grid_alpha = 3
    for x in range(0, largura, 60):
        draw_s.line([(x, 0), (x, altura)], fill=(255, 255, 255, grid_alpha))
    for y in range(0, altura, 60):
        draw_s.line([(0, y), (largura, y)], fill=(255, 255, 255, grid_alpha))

    # ─── FONTES ──────────────────────────────────────────────────────
    fs_title   = max(32, int(altura * 0.036))
    fs_cat     = max(15, int(altura * 0.019))
    fs_cmd     = max(13, int(altura * 0.0145))
    fs_small   = max(10, int(altura * 0.012))
    fs_footer  = max(11, int(altura * 0.012))

    ft_title   = font(fs_title, bold=True)
    ft_cat     = font(fs_cat, bold=True)
    ft_cmd     = font(fs_cmd)
    ft_small   = font(fs_small)
    ft_footer  = font(fs_footer)

    # ─── LAYOUT ──────────────────────────────────────────────────────
    margin_x = int(largura * 0.04)
    margin_y = int(altura * 0.05)
    n_cols   = 4 if largura >= 3440 else 3
    gap_col  = int(largura * 0.008)
    gap_row  = int(altura * 0.014)

    # ─── HEADER ──────────────────────────────────────────────────────
    # Logo / Ícone
    logo_text = ""  # Arch logo placeholder
    try:
        logo_font = font(int(altura * 0.055))
    except:
        logo_font = ft_title

    # Título principal
    x_title = margin_x
    y_title = margin_y

    # Badge "CACHYOS"
    badge_w = draw.textlength(" CACHYOS ", font=ft_title) + 24
    badge_h = fs_title + 16
    badge_x = x_title
    badge_y = y_title
    draw_rounded_rect(draw, (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                      radius=8, fill="#1d2d44", outline=ACCENT, width=1)
    draw.text((badge_x + 12, badge_y + 8), "CACHYOS", fill=TITLE_C, font=ft_title)

    # Subtítulo
    sub = "COMANDOS ESSENCIAIS"
    sub_x = badge_x + badge_w + 20
    sub_y = badge_y + 6
    draw.text((sub_x, sub_y), sub, fill=ACCENT2, font=ft_cat)

    # Linha decorativa
    line_y = badge_y + badge_h + int(altura * 0.02)
    grad_steps = 60
    for i in range(grad_steps):
        t = i / grad_steps
        r = int(240 * (1 - t) + 15 * t)
        g = int(131 * (1 - t) + 20 * t)
        b = int(62 * (1 - t) + 25 * t)
        x1 = margin_x + i * (largura - 2 * margin_x) // grad_steps
        x2 = margin_x + (i + 1) * (largura - 2 * margin_x) // grad_steps
        draw.rectangle([x1, line_y, x2, line_y + 2], fill=(r, g, b))

    # ─── COLUNAS ─────────────────────────────────────────────────────
    col_w = (largura - 2 * margin_x - (n_cols - 1) * gap_col) // n_cols
    cats_per_col = math.ceil(len(comandos) / n_cols)

    col_groups = []
    for c in range(n_cols):
        s = c * cats_per_col
        e = min(s + cats_per_col, len(comandos))
        col_groups.append(comandos[s:e])

    card_pad_x = 8
    card_pad_y_top = 8
    card_pad_y_bot = 10
    y_start = line_y + int(altura * 0.028)

    for ci, group in enumerate(col_groups):
        x = margin_x + ci * (col_w + gap_col)
        y = y_start

        for cat_name, icon, cmds in group:
            # ── CARD ─────────────────────────────────────────────────
            # Altura do card = cabeçalho + linhas
            n_lines = len(cmds)
            cmd_h = fs_cmd + int(altura * 0.0055)
            card_h = (card_pad_y_top + fs_cat + 8 + n_lines * cmd_h + card_pad_y_bot)
            card_x1 = x
            card_y1 = y
            card_x2 = x + col_w - 4
            card_y2 = y + card_h

            # Sombra do card (cópia escura deslocada)
            shadow_offset = 3
            draw_rounded_rect(draw,
                (card_x1 + shadow_offset, card_y1 + shadow_offset,
                 card_x2 + shadow_offset, card_y2 + shadow_offset),
                radius=10, fill="#080c12")

            # Card fill
            draw_rounded_rect(draw, (card_x1, card_y1, card_x2, card_y2),
                              radius=10, fill=DARK_CARD, outline=BORDER, width=1)

            # Barra lateral colorida no card
            bar_w = 3
            bar_color = ACCENT if ci % 2 == 0 else ACCENT2
            draw_rounded_rect(draw,
                (card_x1 + 2, card_y1 + 12, card_x1 + 2 + bar_w, card_y2 - 12),
                radius=2, fill=bar_color)

            # Ícone + nome da categoria
            icon_text = f"{icon}  {cat_name}"
            ix = card_x1 + card_pad_x + 10
            iy = card_y1 + card_pad_y_top
            draw.text((ix, iy), icon_text, fill=ACCENT, font=ft_cat)

            # Linha separadora interna
            sep_y = iy + fs_cat + 8
            for i in range(50):
                t = i / 50
                x1 = card_x1 + 12 + i * (col_w - 24) // 50
                r = int(240 * (1 - t) + 21 * t)
                g = int(131 * (1 - t) + 42 * t)
                b = int(62 * (1 - t) + 58 * t)
                draw.rectangle([x1, sep_y, x1 + (col_w - 24) // 50 + 1, sep_y + 1], fill=(r, g, b))

            # Comandos
            cy = sep_y + 6
            inner_pad = 8
            for cmd in cmds:
                draw_cmd_line(draw, card_x1 + inner_pad + 4, cy, cmd, ft_cmd, col_w - inner_pad)
                cy += cmd_h

            y += card_h + gap_row

    # ─── FOOTER ──────────────────────────────────────────────────────
    footer = "CachyOS  •  Linux-cachyOS  •  Arch Linux  •  Feito com  por Ticiano"
    fw = draw.textlength(footer, font=ft_footer)
    fx = (largura - fw) // 2
    fy = altura - int(altura * 0.04)
    draw.text((fx, fy), footer, fill=GRAY, font=ft_footer)

    # ─── SALVAR ──────────────────────────────────────────────────────
    img.save(path, "PNG", optimize=True)
    print(f"✓ {path}  ({largura}×{altura})")


# ─── MAIN ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    out = os.path.expanduser("~/Imagens/Wallpapers")
    os.makedirs(out, exist_ok=True)

    generate(1920, 1080, os.path.join(out, "cachyos_commands_fhd.png"))
    generate(3440, 1440, os.path.join(out, "cachyos_commands_ultrawide.png"))
    print("\nPronto! 🎉")
