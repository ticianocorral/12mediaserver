"""Constantes, caminhos e configuracao por ambiente.

Modulo folha: nao importa nada do proprio pacote.
"""

import os
from pathlib import Path

# ── Rede ─────────────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 9187
HTTPS_PORT_BASE = 9443

# O servidor continua ouvindo na LAN (Chromecast e celular precisam disso),
# mas so aceita requisicoes cujo Host seja local/privado e cujo Origin, quando
# presente, tambem seja. Isso preserva o uso domestico e fecha DNS rebinding —
# nesse ataque o Host e um dominio publico controlado por terceiros.
BIND_HOST = os.environ.get("TICIANOFLIX_BIND", HOST)

# ── rclone ───────────────────────────────────────────────────
RCLONE_REMOTE = "gdrive:"
# Remote separado so para o backup. O remote principal e somente-leitura
# (scope drive.readonly), entao a escrita precisa de um token proprio com
# scope drive.file — que enxerga apenas arquivos criados pelo proprio app.
RCLONE_BACKUP_REMOTE = "gdrive_backup:"
BACKUP_FOLDER = "TicianoFlix Backups"
RCLONE_SERVE_PORT = 18082
RCLONE_WEBGUI_PORT = 5572

# Web GUI do rclone: desligada por padrao. Ela expoe a API de controle remoto
# do rclone, que da acesso total ao Drive. Habilite com TICIANOFLIX_RCLONE_GUI=1
# — nesse caso ela sobe apenas em 127.0.0.1, acessivel so do proprio computador.
RCLONE_GUI_ENABLED = os.environ.get("TICIANOFLIX_RCLONE_GUI", "") == "1"

# Pasta logica que o DB e o frontend usam. Quando o remote esta escopado via
# root_folder_id, esse prefixo nao existe do lado do rclone — veja paths._rc().
#
# O nome e neutro de proposito: e a pasta que a pessoa precisa criar no
# proprio Google Drive, entao carregar a marca aqui vazaria "TicianoFlix" pro
# Drive de qualquer um que instalasse com outro nome. LOGICAL_ROOT_LEGADO e so
# para a migracao de quem ja tinha o app antigo — db.py reescreve o prefixo
# gravado uma unica vez (ver _migrar_prefixo_marca).
LOGICAL_ROOT = "/Mediaflix"
LOGICAL_ROOT_LEGADO = "/TicianoFlix"

# ── Fontes locais ────────────────────────────────────────────
# O Drive deixou de ser a unica fonte: HD externo, pendrive e pastas do proprio
# computador entram no catalogo montados sob este prefixo logico, um nivel por
# fonte ("/Local/hd-externo/Terror/Alien (1979)/filme.mkv"). O Drive continua em
# LOGICAL_ROOT, entao nenhum path ja gravado no banco muda de forma.
LOCAL_ROOT = "/Local"

# ── Caminhos ─────────────────────────────────────────────────
# A raiz do projeto e o diretorio acima do pacote: o index.html e os favicons
# ficam la, ao lado do server.py.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_PATH = PROJECT_ROOT / "index.html"

# Cache vai pro home do usuario (gravavel mesmo dentro de um AppImage).
CACHE_DIR = Path.home() / ".cache" / "ticianoflix"
DB_PATH = CACHE_DIR / "ticianoflix.db"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
SUBS_CACHE_DIR = CACHE_DIR / "subs"
CACHED_FILES_PATH = CACHE_DIR / "cached_files.json"
AUTH_PATH = CACHE_DIR / "auth.json"
# Fonte e configuracao, nao cache: fica fora do SQLite (como o auth.json) para
# que restaurar um backup feito em outra maquina nao importe caminhos que nao
# existem aqui.
SOURCES_PATH = CACHE_DIR / "sources.json"
# A chave do TMDB e da pessoa que instalou, nunca do projeto: uma chave
# embutida no codigo publico ficaria exposta e todo mundo dividiria o mesmo
# limite de uso. Fica fora do SQLite pelo mesmo motivo do sources.json.
TMDB_KEY_PATH = CACHE_DIR / "tmdb.json"
# Mesmo raciocinio do sources.json: nome, cor e icone sao configuracao de
# exibicao, nao dado do acervo — nunca precisam entrar no SQLite nem viajam
# num backup do catalogo.
BRANDING_PATH = CACHE_DIR / "branding.json"
SECRET_PATH = CACHE_DIR / "secret.key"

for _d in (CACHE_DIR, IMAGE_CACHE_DIR, SUBS_CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Tipos de arquivo ─────────────────────────────────────────
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
                    ".m4v", ".mpg", ".mpeg"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

# ── Limites de corpo ─────────────────────────────────────────
MAX_RESTORE_BYTES = 512 * 1024 * 1024   # teto do zip de restore
MAX_JSON_BODY_BYTES = 64 * 1024         # teto de corpo JSON (ex.: /api/progress)
MAX_NFO_BYTES = 2 * 1024 * 1024         # teto de um arquivo .nfo

# ── Rotas ────────────────────────────────────────────────────
# Rotas que alteram estado: so respondem a POST com Origin local.
WRITE_ROUTES = frozenset({
    "/api/refresh", "/api/clear-cache", "/api/uncache",
    "/api/cache-download", "/api/backup/drive", "/api/restore/drive",
    "/api/sources/add", "/api/sources/remove", "/api/branding/set",
    "/api/scrape/apply", "/api/scrape/key/set",
})

# Rotas alcancaveis sem sessao.
#
# O manifest, o CSS de marca e os icones entram aqui porque o navegador os
# busca fora da navegacao normal, sem mandar o cookie: se respondessem 401 o
# celular nao ofereceria instalar o app, e a pagina de login (que roda antes
# de qualquer sessao existir) ficaria sem a cor e o icone escolhidos. Sao
# lista exata, nao prefixo — o resto de /static/ continua exigindo sessao.
PUBLIC_PATHS = frozenset({
    "/login", "/favicon.ico", "/favicon.svg",
    "/api/auth/status", "/api/auth/login", "/api/auth/setup", "/api/auth/logout",
    "/manifest.webmanifest", "/branding.css",
    "/icone-192.png", "/icone-512.png",
    "/icone-maskable-512.png", "/icone-apple-touch.png",
})

# Rotas que o Chromecast busca sozinho: liberadas por token assinado.
TOKEN_PATHS = frozenset({"/api/stream", "/api/subtitle"})

# Rotas restritas a administradores.
# Apontar o servidor para uma pasta do computador expoe aquele diretorio na LAN
# para qualquer conta logada: cadastrar e remover fonte e decisao de admin.
ADMIN_PATHS = frozenset({
    "/api/users", "/api/users/add", "/api/users/remove", "/api/users/role",
    "/api/sources/add", "/api/sources/remove", "/api/sources/detect",
    "/api/scrape/status", "/api/scrape/pendentes", "/api/scrape/search",
    "/api/scrape/apply", "/api/scrape/key/set",
    "/api/branding", "/api/branding/set",
})

# ── Sessao e contas ──────────────────────────────────────────
SESSION_COOKIE = "tflix_session"
SESSION_MAX_AGE = 90 * 24 * 3600     # 90 dias por dispositivo
CAST_TOKEN_MAX_AGE = 12 * 3600       # cobre um filme inteiro com folga
MIN_PASSWORD_LEN = 8
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW = 15 * 60
