"""Constantes, caminhos e configuracao por ambiente.

Modulo folha: nao importa nada do proprio pacote.
"""

import os
from pathlib import Path


def env(nome, padrao=""):
    """Variavel de ambiente MEDIA_SERVER_<nome>."""
    return os.environ.get("MEDIA_SERVER_" + nome, padrao)

# ── Rede ─────────────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 9187
HTTPS_PORT_BASE = 9443

# O servidor continua ouvindo na LAN (Chromecast e celular precisam disso),
# mas so aceita requisicoes cujo Host seja local/privado e cujo Origin, quando
# presente, tambem seja. Isso preserva o uso domestico e fecha DNS rebinding —
# nesse ataque o Host e um dominio publico controlado por terceiros.
BIND_HOST = env("BIND", HOST)

# ── rclone ───────────────────────────────────────────────────
# A nuvem e qualquer remote rclone, escolhido pelo wizard da interface
# (veja nuvem.py): um remote ja existente na lista do rclone ou um novo
# criado por ali mesmo. O app grava a escolha no nuvem.json — o rclone.conf
# so e tocado quando o wizard cria um remote novo.
BACKUP_FOLDER = "Media Server Backups"
NOME_DB_BACKUP = "media-server.db"
PREFIXO_BACKUP = "media-server-backup-"
RCLONE_SERVE_PORT = 18082
RCLONE_WEBGUI_PORT = 5572

# Web GUI do rclone: desligada por padrao. Ela expoe a API de controle remoto
# do rclone, que da acesso total ao remote. Habilite com MEDIA_SERVER_RCLONE_GUI=1
# — nesse caso ela sobe apenas em 127.0.0.1, acessivel so do proprio computador.
RCLONE_GUI_ENABLED = env("RCLONE_GUI") == "1"

# Prefixo logico (hoje calculado em branding.logical_root(), a partir do nome
# escolhido na instalacao) que o DB e o frontend usam pra raiz da nuvem.
# Nao mora aqui porque config.py e modulo-folha e branding.py importa config —
# um LOGICAL_ROOT dinamico aqui criaria um ciclo de import.

# ── Fontes locais ────────────────────────────────────────────
# A nuvem deixou de ser a unica fonte: HD externo, pendrive e pastas do proprio
# computador entram no catalogo montados sob este prefixo logico, um nivel por
# fonte ("/Local/hd-externo/Terror/Alien (1979)/filme.mkv"). A nuvem continua em
# LOGICAL_ROOT, entao nenhum path ja gravado no banco muda de forma.
LOCAL_ROOT = "/Local"

# ── Caminhos ─────────────────────────────────────────────────
# A raiz do projeto e o diretorio acima do pacote: o index.html e os favicons
# ficam la, ao lado do server.py.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_PATH = PROJECT_ROOT / "index.html"

# Cache vai pro home do usuario (gravavel mesmo dentro de um AppImage).
CACHE_DIR = Path.home() / ".cache" / "media-server"
DB_PATH = CACHE_DIR / "media-server.db"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
SUBS_CACHE_DIR = CACHE_DIR / "subs"
CACHED_FILES_PATH = CACHE_DIR / "cached_files.json"
AUTH_PATH = CACHE_DIR / "auth.json"
# MP4s gerados pelo prepare.py para transmitir na TV (MKV/E-AC3 nao tocam
# no Chromecast nem no AirPlay). Regeneravel a qualquer momento — o nome do
# arquivo e o hash do path original, com um .json ao lado guardando a
# assinatura (mtime/tamanho) da fonte.
CAST_CACHE_DIR = CACHE_DIR / "cast"
# Fonte e configuracao, nao cache: fica fora do SQLite (como o auth.json) para
# que restaurar um backup feito em outra maquina nao importe caminhos que nao
# existem aqui.
SOURCES_PATH = CACHE_DIR / "sources.json"
# Mesmo raciocinio do sources.json: nome, cor e icone sao configuracao de
# exibicao, nao dado do acervo — nunca precisam entrar no SQLite nem viajam
# num backup do catalogo.
BRANDING_PATH = CACHE_DIR / "branding.json"
SECRET_PATH = CACHE_DIR / "secret.key"
# Conexão da nuvem feita pelo wizard da UI: qual remote rclone usar e a pasta
# de dentro dele onde mora o acervo. Segredos (quando o wizard cria um remote
# novo) ficam obscurecidos no rclone.conf; aqui fica so o endereço.
NUVEM_PATH = CACHE_DIR / "nuvem.json"
# A chave do TMDB e da pessoa que instalou, nunca do projeto: uma chave
# embutida no codigo publico ficaria exposta e todo mundo dividiria o mesmo
# limite de uso. Fica fora do SQLite pelo mesmo motivo do sources.json.
TMDB_KEY_PATH = CACHE_DIR / "tmdb.json"
# Historico das organizacoes (renomear/mover) de fontes locais, para desfazer.
ORGANIZAR_LOG_PATH = CACHE_DIR / "organizar-historico.json"

for _d in (CACHE_DIR, IMAGE_CACHE_DIR, SUBS_CACHE_DIR, CAST_CACHE_DIR):
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
    "/api/cache-download", "/api/backup/b2", "/api/restore/b2",
    "/api/sources/add", "/api/sources/remove", "/api/branding/set",
    "/api/nuvem/conectar", "/api/nuvem/desconectar", "/api/rclone/wizard",
    "/api/infantil/marcar",
    "/api/colecoes/create", "/api/colecoes/update", "/api/colecoes/delete",
    "/api/generos/create", "/api/generos/delete", "/api/generos/atribuir",
    "/api/generos/renomear", "/api/watched",
    "/api/scrape/apply", "/api/scrape/key/set",
    "/api/organizar/aplicar", "/api/organizar/desfazer",
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
    # CA local (mkcert): o celular novo baixa pelo http:// antes de ter
    # sessao (senao vira ovo e galinha com o aviso de certificado). E so o
    # certificado publico da CA — a chave fica no computador.
    "/ca.crt",
})

# Rotas do seletor de perfis: alcancaveis com a conta logada mesmo antes de
# escolher o perfil (cada uma confere por conta propria o que pode fazer).
ACCOUNT_PATHS = frozenset({
    "/perfis", "/api/profiles", "/api/profiles/select", "/api/profiles/leave",
    "/api/profiles/unlock", "/api/profiles/save", "/api/profiles/pin",
    "/api/profiles/delete", "/api/auth/status", "/api/auth/logout",
    "/api/auth/login", "/branding.css",
})

# Rotas que o Chromecast busca sozinho: liberadas por token assinado.
# /api/prepared e servido com o token do path ORIGINAL — o receptor nao
# conhece o arquivo convertido; o mapeamento mora no prepare.py.
TOKEN_PATHS = frozenset({"/api/stream", "/api/subtitle", "/api/prepared"})

# Rotas restritas a administradores.
# Apontar o servidor para uma pasta do computador expoe aquele diretorio na LAN
# para qualquer conta logada: cadastrar e remover fonte e decisao de admin.
ADMIN_PATHS = frozenset({
    "/api/sources/add", "/api/sources/remove", "/api/sources/detect",
    "/api/branding", "/api/branding/set",
    "/api/nuvem/conectar", "/api/nuvem/desconectar", "/api/nuvem/status",
    "/api/rclone/remotes", "/api/rclone/providers", "/api/rclone/wizard",
    # Backup/restore mexem no banco e no cache inteiros (ate sobrescrever o
    # catalogo com um zip qualquer): sao decisao de administrador, como
    # apontar as fontes.
    "/api/backup", "/api/backup/local", "/api/backup/b2",
    "/api/restore", "/api/restore/b2",
    "/api/infantil/marcar",
    "/api/colecoes/create", "/api/colecoes/update", "/api/colecoes/delete",
    "/api/generos/create", "/api/generos/delete", "/api/generos/atribuir",
    "/api/generos/renomear",
    "/api/scrape/status", "/api/scrape/pendentes", "/api/scrape/search",
    "/api/scrape/apply", "/api/scrape/key/set",
    "/api/organizar/itens", "/api/organizar/buscar", "/api/organizar/aplicar",
    "/api/organizar/desfazer", "/api/organizar/historico",
})

# ── Sessao e contas ──────────────────────────────────────────
SESSION_COOKIE = "ms_session"
SESSION_MAX_AGE = 90 * 24 * 3600     # 90 dias por dispositivo
CAST_TOKEN_MAX_AGE = 12 * 3600       # cobre um filme inteiro com folga
MIN_PASSWORD_LEN = 8
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW = 15 * 60
