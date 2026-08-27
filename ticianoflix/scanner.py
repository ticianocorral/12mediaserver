"""Varredura do Google Drive e indexacao no SQLite.

O ciclo de vida do scan (claim, progresso, thread) mora aqui: antes o handler
HTTP manipulava as globais direto com `global _scan_in_progress`.
"""

import threading
import time
from pathlib import Path

from .config import (
    IMAGE_EXTENSIONS, LOGICAL_ROOT, SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS,
)
from .db import get_db, set_cache_time
from .paths import rc_remote as _rc_remote
from .nfo import _fetch_nfo_raw, _parse_nfo, _save_nfo_to_db
from .rclone import run_rclone_cmd

PROGRESS_ZERO = {
    "phase": "",           # listing_root | genres | movies | done | error
    "genre_current": "", "genre_index": 0, "genre_total": 0,
    "movie_current": "", "movie_index": 0, "movie_total": 0,
    "percent": 0,
}

_scan_in_progress = False


_scan_lock = threading.Lock()


# Scan progress tracking
_scan_progress = {
    "phase": "",           # "listing_root" | "genres" | "movies" | "done" | "error"
    "genre_current": "",
    "genre_index": 0,
    "genre_total": 0,
    "movie_current": "",
    "movie_index": 0,
    "movie_total": 0,
    "percent": 0,
}


_scan_progress_lock = threading.Lock()


def _remove_folder_tree(conn, path):
    """Remove a folder and everything under it (files, subfolders, NFO meta)."""
    conn.execute("DELETE FROM folders WHERE path=?", (path,))
    conn.execute("DELETE FROM folders WHERE parent LIKE ?", (path + '/%',))
    conn.execute("DELETE FROM files WHERE folder_path=? OR folder_path LIKE ?", (path, path + '/%'))
    conn.execute("DELETE FROM movie_meta WHERE folder_path=? OR folder_path LIKE ?", (path, path + '/%'))


def scan_drive():
    """
    Incremental scan of the TicianoFlix drive structure using a SINGLE
    recursive rclone lsjson of the whole tree, then diffing against the DB:
    - New/changed movies (file set or file size/modtime differs) are re-indexed
      and their NFO is re-fetched.
    - Unchanged movies are left completely untouched (no rclone calls, no DB writes).
    - Folders/files that disappeared from the Drive are removed.
    """
    global _scan_progress
    print("[TicianoFlix] Scanning Google Drive (incremental)...", flush=True)
    start = time.time()

    with _scan_progress_lock:
        _scan_progress["phase"] = "listing_root"
        _scan_progress["percent"] = 0

    conn = get_db()
    stats = {"added": 0, "changed": 0, "removed": 0, "unchanged": 0}

    # Single recursive listing of the whole TicianoFlix tree (--fast-list uses
    # the Drive files.list API, ~10x faster than walking the tree per directory)
    tree = run_rclone_cmd(["lsjson", "--recursive", "--fast-list",
                           _rc_remote(LOGICAL_ROOT)])
    if not isinstance(tree, list):
        print(f"[TicianoFlix] Failed to list TicianoFlix: {tree}", flush=True)
        with _scan_progress_lock:
            _scan_progress["phase"] = "error"
        conn.close()
        return False

    root_path = "/TicianoFlix"
    conn.execute(
        "INSERT OR REPLACE INTO folders (path, name, parent, is_ticianoflix_root, depth) VALUES (?, ?, '', 1, 0)",
        (root_path, "TicianoFlix")
    )

    # Build in-memory tree: dirs by full path, files grouped by parent folder
    dirs = {}
    files_by_parent = {}
    for e in tree:
        rel = e.get("Path", "")
        full = f"{root_path}/{rel}" if rel else root_path
        if e.get("IsDir"):
            dirs[full] = e
        else:
            parent = full.rsplit("/", 1)[0]
            files_by_parent.setdefault(parent, {})[e.get("Name", "")] = e

    genre_dirs = {p: e for p, e in dirs.items() if p.count("/") == 2}
    movie_dirs = {p: e for p, e in dirs.items() if p.count("/") == 3}

    # DB state
    db_genres = {r["path"] for r in conn.execute("SELECT path FROM folders WHERE depth=1").fetchall()}
    db_movies = {r["path"]: r for r in conn.execute(
        "SELECT path, name, mod_time, has_video FROM folders WHERE depth=2").fetchall()}
    db_files = {}
    for r in conn.execute("SELECT folder_path, name, size, mod_time FROM files").fetchall():
        db_files[(r["folder_path"], r["name"])] = r

    # Remove genres that no longer exist on the Drive
    removed_prefixes = []
    for p in db_genres - set(genre_dirs):
        _remove_folder_tree(conn, p)
        removed_prefixes.append(p)
        stats["removed"] += 1

    # Remove movies that no longer exist (skip ones already removed with their genre)
    for p in set(db_movies) - set(movie_dirs):
        if any(p.startswith(rp + "/") for rp in removed_prefixes):
            continue
        _remove_folder_tree(conn, p)
        stats["removed"] += 1

    # Direct files at the TicianoFlix root: upsert + prune deleted
    root_live = files_by_parent.get(root_path, {})
    for name, fe in root_live.items():
        _index_file(conn, root_path, fe)
    for (fp, name) in list(db_files):
        if fp == root_path and name not in root_live:
            conn.execute("DELETE FROM files WHERE folder_path=? AND name=?", (fp, name))

    total_genres = len(genre_dirs)
    with _scan_progress_lock:
        _scan_progress["phase"] = "genres"
        _scan_progress["genre_total"] = total_genres

    for gi, (genre_path, genre_entry) in enumerate(sorted(genre_dirs.items())):
        genre_name = genre_entry.get("Name", "")

        with _scan_progress_lock:
            _scan_progress["genre_index"] = gi + 1
            _scan_progress["genre_current"] = genre_name
            _scan_progress["percent"] = int((gi / total_genres) * 100) if total_genres else 0

        conn.execute(
            "INSERT OR REPLACE INTO folders (path, name, parent, depth, mod_time) VALUES (?, ?, ?, 1, ?)",
            (genre_path, genre_name, root_path, genre_entry.get("ModTime", ""))
        )

        # Direct files in genre folder (unstructured): upsert + prune deleted
        has_direct_video = False
        live_genre_files = files_by_parent.get(genre_path, {})
        for name, fe in live_genre_files.items():
            if Path(name).suffix.lower() in VIDEO_EXTENSIONS:
                has_direct_video = True
            _index_file(conn, genre_path, fe)
        for (fp, name) in list(db_files):
            if fp == genre_path and name not in live_genre_files:
                conn.execute("DELETE FROM files WHERE folder_path=? AND name=?", (fp, name))

        # Movies under this genre
        for movie_path in sorted(m for m in movie_dirs if m.startswith(genre_path + "/")):
            movie_entry = movie_dirs[movie_path]
            movie_name = movie_entry.get("Name", "")
            live_movie_files = files_by_parent.get(movie_path, {})
            prev = db_movies.get(movie_path)

            # File-level change detection: name set + size/modtime of each file
            new = prev is None
            changed = new
            if not changed:
                db_keys = {name for (fp, name) in db_files if fp == movie_path}
                live_keys = set(live_movie_files)
                if db_keys != live_keys:
                    changed = True
                else:
                    for name in live_keys:
                        fe = live_movie_files[name]
                        dr = db_files[(movie_path, name)]
                        if fe.get("Size", 0) != dr["size"] or fe.get("ModTime", "") != dr["mod_time"]:
                            changed = True
                            break

            if prev is not None and not changed:
                # Unchanged: keep the folder row (preserve has_video), touch nothing else
                conn.execute(
                    "INSERT INTO folders (path, name, parent, depth, mod_time, has_video) "
                    "VALUES (?, ?, ?, 2, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET mod_time=excluded.mod_time",
                    (movie_path, movie_name, genre_path, movie_entry.get("ModTime", ""), prev["has_video"])
                )
                stats["unchanged"] += 1
                continue

            # New or changed: rebuild folder contents from the same listing
            conn.execute(
                "INSERT OR REPLACE INTO folders (path, name, parent, depth, mod_time) VALUES (?, ?, ?, 2, ?)",
                (movie_path, movie_name, genre_path, movie_entry.get("ModTime", ""))
            )

            with _scan_progress_lock:
                _scan_progress["movie_index"] += 1
                _scan_progress["movie_current"] = movie_name

            conn.execute("DELETE FROM files WHERE folder_path=?", (movie_path,))
            for name, fe in live_movie_files.items():
                _index_file(conn, movie_path, fe)

            if any(Path(n).suffix.lower() in VIDEO_EXTENSIONS for n in live_movie_files):
                conn.execute(
                    "UPDATE folders SET has_video=1 WHERE path=?",
                    (movie_path,)
                )

                # NFO only for new/changed movies AND only if the folder really
                # has one (avoids a slow rclone cat on a missing file)
                if any(n.lower().endswith(".nfo") for n in live_movie_files):
                    nfo_raw = _fetch_nfo_raw(movie_path)
                    if nfo_raw:
                        nfo_data = _parse_nfo(nfo_raw)
                        if nfo_data:
                            _save_nfo_to_db(conn, movie_path, nfo_data)

            if new:
                stats["added"] += 1
            else:
                stats["changed"] += 1

        # Mark genre as having content if any movie folder has video
        genre_has_video = conn.execute(
            "SELECT COUNT(*) as c FROM folders WHERE parent=? AND has_video=1",
            (genre_path,)
        ).fetchone()["c"]

        if has_direct_video:
            genre_has_video = genre_has_video + 1

        if genre_has_video > 0:
            conn.execute(
                "UPDATE folders SET has_video=1 WHERE path=?",
                (genre_path,)
            )

    conn.commit()

    # Mark ticianoflix root
    total_genres = conn.execute("SELECT COUNT(*) as c FROM folders WHERE depth=1").fetchone()["c"]
    total_movies = conn.execute("SELECT COUNT(*) as c FROM folders WHERE has_video=1 AND depth=2").fetchone()["c"]
    total_files = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
    conn.close()

    set_cache_time()

    elapsed = time.time() - start
    print(
        f"[TicianoFlix] Scan complete: {total_genres} genres, {total_movies} movies, {total_files} files "
        f"in {elapsed:.1f}s (+{stats['added']} novos, ~{stats['changed']} alterados, -{stats['removed']} removidos, "
        f"{stats['unchanged']} inalterados)",
        flush=True
    )

    with _scan_progress_lock:
        _scan_progress["phase"] = "done"
        _scan_progress["percent"] = 100

    return True


def _index_file(conn, folder_path, item):
    """Index a single file into the database."""
    name = item.get("Name", "")
    ext = Path(name).suffix.lower()
    size = item.get("Size", 0)
    mime = item.get("MimeType", "")
    mod_time = item.get("ModTime", "")
    file_id = item.get("ID", "")

    # Determine file type
    if ext in VIDEO_EXTENSIONS:
        file_type = "video"
    elif ext in SUBTITLE_EXTENSIONS:
        file_type = "subtitle"
    elif ext in IMAGE_EXTENSIONS:
        stem = Path(name).stem.lower()
        if stem in ("poster", "capa", "cover", "folder"):
            file_type = "poster"
        elif stem in ("fanart", "background", "backdrop", "banner"):
            file_type = "fanart"
        else:
            file_type = "image"
    else:
        file_type = "other"

    conn.execute(
        """INSERT OR REPLACE INTO files
           (folder_path, name, size, mime_type, mod_time, file_id, extension, file_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (folder_path, name, size, mime, mod_time, file_id, ext, file_type)
    )


def is_scanning():
    with _scan_lock:
        return _scan_in_progress


def get_progress():
    """Copia do progresso atual — o dict vivo nao vaza pra fora do modulo."""
    with _scan_progress_lock:
        return dict(_scan_progress)


def start_background_scan():
    """Reivindica a vaga do scan e dispara a thread.

    Devolve "scanning" ou "already_scanning". Antes isso morava no handler
    HTTP, que mexia em _scan_in_progress e _scan_progress com `global`.
    """
    global _scan_in_progress, _scan_progress
    with _scan_lock:
        if _scan_in_progress:
            return "already_scanning"
        _scan_in_progress = True

    def _run():
        global _scan_in_progress
        try:
            scan_drive()
        except Exception as e:
            with _scan_progress_lock:
                _scan_progress["phase"] = "error"
            print(f"[TicianoFlix] Scan error: {e}", flush=True)
        finally:
            with _scan_lock:
                _scan_in_progress = False

    with _scan_progress_lock:
        _scan_progress = dict(PROGRESS_ZERO)

    threading.Thread(target=_run, daemon=True).start()
    return "scanning"
