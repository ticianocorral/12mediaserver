"""Cache SQLite: conexoes, schema, metadados e uso em disco."""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from .config import DB_PATH, IMAGE_CACHE_DIR, SUBS_CACHE_DIR

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
        is_ticianoflix_root INTEGER NOT NULL DEFAULT 0,
        has_video INTEGER NOT NULL DEFAULT 0,
        depth INTEGER NOT NULL DEFAULT 0,
        mod_time TEXT NOT NULL DEFAULT ''
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

    CREATE TABLE IF NOT EXISTS watch_progress (
        folder_path TEXT PRIMARY KEY,
        position_seconds REAL NOT NULL DEFAULT 0,
        duration_seconds REAL NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL DEFAULT 0
    );
"""


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
    # Migracao: bancos antigos nao tem folders.mod_time.
    try:
        conn.execute(
            "ALTER TABLE folders ADD COLUMN mod_time TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # coluna ja existe
    conn.commit()
    conn.close()


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
            for f in p.rglob("*"):
                if f.is_file():
                    size += f.stat().st_size
        details[label] = size
        total += size
    return {"total": total, "details": details}


def looks_like_ticianoflix_db(raw):
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
