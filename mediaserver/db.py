"""Cache SQLite: conexoes, schema, metadados e uso em disco."""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from .config import DB_PATH, IMAGE_CACHE_DIR, SUBS_CACHE_DIR
from . import branding as _branding

_db_write_lock = threading.Lock()

SCHEMA = """
    CREATE TABLE IF NOT EXISTS cache_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS folders (
        path TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        parent TEXT NOT NULL DEFAULT '',
        is_media_server_root INTEGER NOT NULL DEFAULT 0,
        has_video INTEGER NOT NULL DEFAULT 0,
        depth INTEGER NOT NULL DEFAULT 0,
        mod_time TEXT NOT NULL DEFAULT '',
        tipo TEXT NOT NULL DEFAULT 'filme'
    );

    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_path TEXT NOT NULL,
        name TEXT NOT NULL,
        size INTEGER NOT NULL DEFAULT 0,
        mime_type TEXT,
        mod_time TEXT,
        file_id TEXT,
        extension TEXT NOT NULL DEFAULT '',
        file_type TEXT NOT NULL DEFAULT 'other',
        FOREIGN KEY (folder_path) REFERENCES folders(path)
    );

    CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_path);
    CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type);
    CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent);
    CREATE INDEX IF NOT EXISTS idx_folders_depth ON folders(depth);

    CREATE TABLE IF NOT EXISTS movie_meta (
        folder_path TEXT PRIMARY KEY,
        title TEXT,
        year TEXT,
        plot TEXT,
        rating TEXT,
        votes TEXT,
        genres TEXT,
        tagline TEXT,
        directors TEXT,
        writers TEXT,
        cast_list TEXT,
        video_info TEXT,
        audio_info TEXT,
        updated_at REAL NOT NULL DEFAULT 0
    );

    -- Progresso por perfil: cada perfil tem o seu "continuar assistindo" e os
    -- seus assistidos. Linha com position_seconds = 0 e "assistido".
    CREATE TABLE IF NOT EXISTS watch_progress (
        profile_id TEXT NOT NULL DEFAULT '',
        folder_path TEXT NOT NULL,
        position_seconds REAL NOT NULL DEFAULT 0,
        duration_seconds REAL NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (profile_id, folder_path)
    );

    -- Colecoes legadas, alimentadas pela tag <set> do NFO (tinyMediaManager).
    -- A tela de Coleções não usa mais estas tabelas: viram "colecoes" abaixo
    -- numa migração única e ficam só por compatibilidade de bancos antigos.
    CREATE TABLE IF NOT EXISTS collections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        overview TEXT
    );

    CREATE TABLE IF NOT EXISTS movie_collections (
        folder_path TEXT NOT NULL,
        collection_id INTEGER NOT NULL,
        PRIMARY KEY (folder_path, collection_id)
    );

    CREATE INDEX IF NOT EXISTS idx_movie_collections_col
        ON movie_collections(collection_id);

    -- Coleções do app: criadas e editadas na própria interface, sem NFO.
    -- capa é o folder_path do filme cujo pôster representa a coleção; um
    -- filme pode pertencer a várias coleções (colecoes_filmes é N:N).
    CREATE TABLE IF NOT EXISTS colecoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        descricao TEXT NOT NULL DEFAULT '',
        capa TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS colecoes_filmes (
        colecao_id INTEGER NOT NULL REFERENCES colecoes(id) ON DELETE CASCADE,
        folder_path TEXT NOT NULL,
        PRIMARY KEY (colecao_id, folder_path)
    );

    CREATE INDEX IF NOT EXISTS idx_colecoes_filmes_path
        ON colecoes_filmes(folder_path);

    -- Gêneros criados na interface, independentes de pasta. Um gênero pode
    -- receber filmes de qualquer fonte; o vínculo (generos_filmes.alvo) aponta
    -- para o folder_path do filme OU para o path completo do arquivo, no caso
    -- de filme solto (arquivo de vídeo direto na raiz da fonte).
    CREATE TABLE IF NOT EXISTS generos_app (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        created_at REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS generos_filmes (
        genero_id INTEGER NOT NULL REFERENCES generos_app(id) ON DELETE CASCADE,
        alvo TEXT NOT NULL,
        PRIMARY KEY (genero_id, alvo)
    );

    CREATE INDEX IF NOT EXISTS idx_generos_filmes_alvo
        ON generos_filmes(alvo);

    -- Filmes marcados para o perfil infantil (conta com "infantil" ligada).
    -- alvo = folder_path do filme, ou o path completo do arquivo, no caso de
    -- filme solto. Só o que está aqui aparece para o perfil infantil — e o
    -- resto fica bloqueado até no streaming.
    CREATE TABLE IF NOT EXISTS infantil_filmes (
        alvo TEXT PRIMARY KEY
    );
"""


# Perfil da requisicao em andamento. Cada requisicao roda numa thread propria
# (ThreadingHTTPServer): o handler grava aqui quem esta logado e as consultas
# de progresso filtram por isso, sem passar o perfil por todas as assinaturas.
_contexto = threading.local()


def set_perfil_atual(profile_id):
    _contexto.perfil = profile_id or ""


def perfil_atual():
    return getattr(_contexto, "perfil", "")


def like_prefix(path):
    """Prefixo para `LIKE ? ESCAPE '\\'`, com os curingas do LIKE neutralizados.

    Sem isso uma pasta chamada "Alien_1979" casaria com "Alien-1979" — o `_` e
    curinga de um caractere no LIKE, e uma remocao de subarvore levaria junto a
    pasta vizinha.
    """
    escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "/%"


def get_db():
    """Conexao nova, ja com WAL e busy_timeout."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_db_write():
    """Conexao para escrita, com o lock que serializa os writers."""
    return get_db(), _db_write_lock


def init_db():
    """Cria as tabelas se ainda nao existirem."""
    conn = get_db()
    conn.executescript(SCHEMA)
    # Migracao: bancos antigos nao tem folders.mod_time nem folders.tipo.
    try:
        conn.execute(
            "ALTER TABLE folders ADD COLUMN mod_time TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # coluna ja existe
    try:
        conn.execute(
            "ALTER TABLE folders ADD COLUMN tipo TEXT NOT NULL DEFAULT 'filme'")
    except sqlite3.OperationalError:
        pass  # coluna ja existe
    # Migracao: a tabela files nao tinha chave por (pasta, arquivo) e rescans
    # acumulavam linhas duplicadas — episodios apareciam dobrados na serie.
    # Deduplica (fica a linha mais antiga) e trava o reinci­dio com indice
    # unico; o _index_file usa INSERT OR REPLACE, entao passa a substituir.
    conn.execute(
        "DELETE FROM files WHERE id NOT IN "
        "(SELECT MIN(id) FROM files GROUP BY folder_path, name)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_files_unico "
        "ON files(folder_path, name)")
    _migrar_progresso_por_perfil(conn)
    _migrar_prefixo_marca(conn)
    _migrar_colecoes_nfo(conn)
    conn.commit()
    conn.close()


# Tabelas que guardam path logico, e a coluna onde ele mora em cada uma. Fixo
# e interno — nunca vem de entrada externa — entao formatar nome de
# tabela/coluna direto na string e seguro aqui.
#
# folders.parent guarda o path logico do pai (mesma natureza de folders.path)
# — faltou na primeira versao desta migracao, e por isso o gatilho abaixo
# usa uma chave de cache_meta nova ('v2'): quem ja rodou a v1 tem path
# migrado mas parent com o prefixo antigo sobrando, e precisa rodar de novo.
_TABELAS_COM_PATH = (
    ("folders", "path"),
    ("folders", "parent"),
    ("files", "folder_path"),
    ("movie_meta", "folder_path"),
    ("watch_progress", "folder_path"),
    ("movie_collections", "folder_path"),
    ("colecoes_filmes", "folder_path"),
    ("colecoes", "capa"),
    ("generos_filmes", "alvo"),
    ("infantil_filmes", "alvo"),
)


def _migrar_colecoes_nfo(conn):
    """Importa as colecoes vindas de NFO (<set> do tinyMediaManager), uma vez.

    A tela de Coleções passou a ser gerenciada pelo app (criar, editar, capa),
    sem ler NFO nenhum. Bancos que ja tinham conjuntos etiquetados no
    tinyMediaManager nao podem perder isso: na primeira subida com esta versao,
    cada colecao antiga vira uma colecao do app com os mesmos filmes — a capa
    sai do cartaz do filme mais antigo do conjunto, como a tela fazia antes.

    Roda uma unica vez (cache_meta); colecoes novas do usuario nunca voltam
    aqui, e as tabelas antigas ficam no banco so como registro historico.
    """
    row = conn.execute(
        "SELECT value FROM cache_meta WHERE key='colecoes_app_v1'").fetchone()
    if row:
        return
    antigas = conn.execute(
        """SELECT c.id, c.name, c.overview FROM collections c
           JOIN movie_collections mc ON mc.collection_id = c.id
           GROUP BY c.id""").fetchall()
    for antiga in antigas:
        cur = conn.execute(
            "INSERT INTO colecoes (nome, descricao, capa, created_at) "
            "VALUES (?, ?, '', ?)",
            (antiga["name"], antiga["overview"] or "", time.time()))
        nova_id = cur.lastrowid
        conn.execute(
            "INSERT OR IGNORE INTO colecoes_filmes (colecao_id, folder_path) "
            "SELECT ?, folder_path FROM movie_collections WHERE collection_id=?",
            (nova_id, antiga["id"]))
        # Capa inicial: cartaz do filme mais antigo do conjunto (mesma regra
        # que a tela usava como fallback antes de existir capa escolhida).
        primeiro = conn.execute(
            """SELECT cf.folder_path FROM colecoes_filmes cf
               JOIN folders f ON f.path = cf.folder_path
               LEFT JOIN movie_meta m ON m.folder_path = f.path
               WHERE cf.colecao_id = ?
               ORDER BY CASE WHEN m.year IS NULL OR m.year = '' THEN 1 ELSE 0 END,
                        CAST(m.year AS INTEGER) ASC, f.name COLLATE NOCASE ASC
               LIMIT 1""", (nova_id,)).fetchone()
        if primeiro:
            conn.execute("UPDATE colecoes SET capa=? WHERE id=?",
                         (primeiro["folder_path"], nova_id))
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta (key, value) "
        "VALUES ('colecoes_app_v1', ?)", (str(time.time()),))


def _migrar_progresso_por_perfil(conn):
    """Bancos de antes dos perfis tinham watch_progress com a chave so no
    folder_path. Reconstroi a tabela com profile_id; as linhas antigas ficam
    com profile_id='' e sao adotadas pelo primeiro perfil (ver
    adotar_progresso_orfao)."""
    colunas = {r[1] for r in conn.execute("PRAGMA table_info(watch_progress)")}
    if not colunas or "profile_id" in colunas:
        return
    conn.executescript("""
        ALTER TABLE watch_progress RENAME TO watch_progress_antiga;
        CREATE TABLE watch_progress (
            profile_id TEXT NOT NULL DEFAULT '',
            folder_path TEXT NOT NULL,
            position_seconds REAL NOT NULL DEFAULT 0,
            duration_seconds REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (profile_id, folder_path)
        );
        INSERT INTO watch_progress (profile_id, folder_path, position_seconds,
                                    duration_seconds, updated_at)
            SELECT '', folder_path, position_seconds, duration_seconds, updated_at
            FROM watch_progress_antiga;
        DROP TABLE watch_progress_antiga;
    """)


def adotar_progresso_orfao(profile_id):
    """Passa o progresso sem dono (de antes dos perfis) para este perfil."""
    conn = get_db()
    try:
        conn.execute("UPDATE OR IGNORE watch_progress SET profile_id=? "
                     "WHERE profile_id=''", (profile_id,))
        conn.commit()
    finally:
        conn.close()


def apagar_progresso_do_perfil(profile_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM watch_progress WHERE profile_id=?", (profile_id,))
        conn.commit()
    finally:
        conn.close()


def _migrar_prefixo_marca(conn):
    """Reescreve o prefixo logico anterior para o atual (branding.logical_root(),
    hoje o nome escolhido na instalacao), nas tabelas/colunas que guardam path
    logico.

    Sem isto, um rescan ate reconstroi folders/files sozinho, mas PERDERIA o
    progresso de exibicao e os vinculos de colecao, que sao indexados pelo
    path exato — trocar so o nome de exibicao (branding) nunca bastaria aqui,
    porque o path logico gravado no banco e uma identidade fixa, nao mutavel.

    folders.parent ficando com o prefixo antigo (mesmo com folders.path ja
    migrado) quebra a contagem de has_video por genero no proximo scan — o
    "WHERE parent=?" do scanner para de bater, e o genero some da tela mesmo
    com os filmes intactos no banco. Root_path='' (a raiz) nunca casa com o
    prefixo antigo, entao fica de fora do UPDATE sem precisar de caso especial.

    O prefixo anterior nao e mais um valor fixo no codigo: como o nome agora
    pode mudar de uma versao pra outra (era generico, virou o nome escolhido
    na instalacao), o "de onde migrar" tem que vir do que ficou gravado da
    ultima vez (cache_meta), e, sem essa chave (banco novo), so registra o prefixo atual. Gatilho unico, no mesmo idioma que o
    scanner ja usa pro backfill de NFO (meta_version): se o prefixo anterior
    ja bate com o atual, nao ha nada a fazer.
    """
    logical_root = _branding.logical_root()
    row = conn.execute(
        "SELECT value FROM cache_meta WHERE key='logical_root_migrado_v2'").fetchone()
    if row is None:
        # Banco novo: nada a migrar, so registra o prefixo atual.
        conn.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('logical_root_migrado_v2', ?)",
            (logical_root,))
        return
    prefixo_antigo = row["value"]
    if prefixo_antigo == logical_root:
        return
    prefixo_like = like_prefix(prefixo_antigo)
    tamanho_antigo = len(prefixo_antigo) + 1  # +1: substr e 1-indexado
    for tabela, coluna in _TABELAS_COM_PATH:
        conn.execute(
            f"UPDATE {tabela} SET {coluna} = ? || substr({coluna}, ?) "
            f"WHERE {coluna} = ? OR {coluna} LIKE ? ESCAPE '\\'",
            (logical_root, tamanho_antigo, prefixo_antigo, prefixo_like),
        )
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('logical_root_migrado_v2', ?)",
        (logical_root,),
    )


def get_cache_time():
    """Timestamp do ultimo scan, ou None."""
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM cache_meta WHERE key='last_updated'").fetchone()
    conn.close()
    return row["value"] if row else None


def set_cache_time():
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('last_updated', ?)",
        (str(int(time.time())),))
    conn.commit()
    conn.close()


def is_cache_stale():
    """True se o cache tem mais de uma hora."""
    t = get_cache_time()
    if not t:
        return True
    return (int(time.time()) - int(t)) > 3600


def log_notification(level, message):
    """Grava um aviso para o frontend mostrar no proximo refresh."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)",
            (f"notification_{int(time.time())}",
             json.dumps({"level": level, "message": message, "time": time.time()})))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _tamanho_arvore(p):
    """Soma dos arquivos da árvore, via scandir.

    O rglob + is_file + stat anterior fazia dois stats por arquivo — e o
    /api/cache-status é consultado em laço pela interface. DirEntry já traz
    o tipo; o stat só acontece para tamanho.
    """
    total = 0
    pilha = [p]
    while pilha:
        try:
            with os.scandir(pilha.pop()) as it:
                for entrada in it:
                    try:
                        if entrada.is_dir(follow_symlinks=False):
                            pilha.append(entrada.path)
                        elif entrada.is_file(follow_symlinks=False):
                            total += entrada.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def get_cache_usage():
    """Uso em disco de cada cache, em bytes."""
    total = 0
    details = {}
    for label, path in [
        ("images", IMAGE_CACHE_DIR),
        ("subs", SUBS_CACHE_DIR),
        ("vfs", Path.home() / ".cache" / "rclone" / "vfs"),
        ("db", DB_PATH),
    ]:
        p = Path(path)
        size = 0
        if p.is_file():
            size = p.stat().st_size
        elif p.is_dir():
            size = _tamanho_arvore(p)
        details[label] = size
        total += size
    return {"total": total, "details": details}


def looks_like_media_server_db(raw):
    """Confere que o blob e um SQLite integro com o schema esperado antes de
    sobrescrever o banco real."""
    if not raw.startswith(b"SQLite format 3\x00"):
        return False
    import tempfile
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            f.write(raw)
            tmp = f.name
        conn = sqlite3.connect(tmp)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        return {"files", "folders"}.issubset(tables)
    except Exception:
        return False
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
