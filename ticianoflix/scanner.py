"""Varredura das fontes e indexacao no SQLite.

O motor (`_index_tree`) e um so: ele recebe a arvore ja listada, no formato do
`rclone lsjson`, e a reconcilia com o banco. Quem muda e o modo de obter a
arvore — `rclone lsjson` para o Drive, `os.scandir` para HD externo, pendrive e
pastas do computador.

O ciclo de vida do scan (claim, progresso, thread) mora aqui: antes o handler
HTTP manipulava as globais direto com `global _scan_in_progress`.
"""

import threading
import time
from pathlib import Path

from .config import (
    IMAGE_EXTENSIONS, LOCAL_ROOT, LOGICAL_ROOT, SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from .db import get_db, like_prefix as _like_prefix, log_notification, set_cache_time
from .paths import rc_remote as _rc_remote
from .nfo import (
    _fetch_nfo_raw, _parse_nfo, _prune_empty_collections, _save_collection_to_db,
    _save_nfo_to_db,
)
from .rclone import run_rclone_cmd
from . import localfs as _localfs
from . import sources as _sources

PROGRESS_ZERO = {
    "phase": "",           # listing_root | genres | movies | done | error
    "source_current": "", "source_index": 0, "source_total": 0,
    "genre_current": "", "genre_index": 0, "genre_total": 0,
    "movie_current": "", "movie_index": 0, "movie_total": 0,
    "percent": 0,
}

_scan_in_progress = False


_scan_lock = threading.Lock()


# Scan progress tracking
_scan_progress = dict(PROGRESS_ZERO)


_scan_progress_lock = threading.Lock()


def _remove_folder_tree(conn, path):
    """Remove a folder and everything under it (files, subfolders, NFO meta)."""
    like = _like_prefix(path)
    conn.execute("DELETE FROM folders WHERE path=?", (path,))
    conn.execute("DELETE FROM folders WHERE path LIKE ? ESCAPE '\\'", (like,))
    conn.execute(
        "DELETE FROM files WHERE folder_path=? OR folder_path LIKE ? ESCAPE '\\'",
        (path, like))
    conn.execute(
        "DELETE FROM movie_meta WHERE folder_path=? OR folder_path LIKE ? ESCAPE '\\'",
        (path, like))
    conn.execute(
        "DELETE FROM movie_collections WHERE folder_path=? OR folder_path LIKE ? ESCAPE '\\'",
        (path, like))


def _set_progress(**fields):
    with _scan_progress_lock:
        _scan_progress.update(fields)


def _index_tree(conn, root_path, root_name, entries,
                progress_base=0.0, progress_span=1.0):
    """Reconcilia uma arvore ja listada com o banco.

    `entries` vem no formato do `rclone lsjson`: Path relativo a raiz, Name,
    Size, ModTime, IsDir, MimeType, ID. A estrutura esperada e a mesma para toda
    fonte — Raiz/Genero/Filme (ano)/arquivos.

    Regras que valem para as duas fontes:
      - filme novo ou alterado (conjunto de arquivos, tamanho ou mtime) e
        reindexado e tem o NFO relido;
      - filme inalterado nao gera nenhuma escrita;
      - pasta que sumiu da fonte sai do banco.

    Toda consulta de estado e escopada por `root_path`: sem isso o scan do Drive
    apagaria o catalogo do HD externo, e vice-versa.
    """
    stats = {"added": 0, "changed": 0, "removed": 0, "unchanged": 0}
    like_root = _like_prefix(root_path)
    # /TicianoFlix tem 1 barra, /Local/hd-externo tem 2: a profundidade e sempre
    # relativa a raiz da fonte, nunca absoluta.
    root_depth = root_path.count("/")

    conn.execute(
        "INSERT OR REPLACE INTO folders "
        "(path, name, parent, is_ticianoflix_root, depth) VALUES (?, ?, '', 1, 0)",
        (root_path, root_name)
    )

    # Build in-memory tree: dirs by full path, files grouped by parent folder
    dirs = {}
    files_by_parent = {}
    for e in entries:
        rel = e.get("Path", "")
        full = f"{root_path}/{rel}" if rel else root_path
        if e.get("IsDir"):
            dirs[full] = e
        else:
            parent = full.rsplit("/", 1)[0]
            files_by_parent.setdefault(parent, {})[e.get("Name", "")] = e

    genre_dirs = {p: e for p, e in dirs.items() if p.count("/") == root_depth + 1}
    movie_dirs = {p: e for p, e in dirs.items() if p.count("/") == root_depth + 2}

    # DB state — apenas o que pertence a esta fonte
    db_genres = {r["path"] for r in conn.execute(
        "SELECT path FROM folders WHERE depth=1 AND path LIKE ? ESCAPE '\\'",
        (like_root,)).fetchall()}
    db_movies = {r["path"]: r for r in conn.execute(
        "SELECT path, name, mod_time, has_video FROM folders "
        "WHERE depth=2 AND path LIKE ? ESCAPE '\\'", (like_root,)).fetchall()}
    db_files = {}
    for r in conn.execute(
            "SELECT folder_path, name, size, mod_time FROM files "
            "WHERE folder_path=? OR folder_path LIKE ? ESCAPE '\\'",
            (root_path, like_root)).fetchall():
        db_files[(r["folder_path"], r["name"])] = r

    # Remove genres that no longer exist in the source
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

    # Direct files at the source root: upsert + prune deleted
    root_live = files_by_parent.get(root_path, {})
    for name, fe in root_live.items():
        _index_file(conn, root_path, fe)
    for (fp, name) in list(db_files):
        if fp == root_path and name not in root_live:
            conn.execute("DELETE FROM files WHERE folder_path=? AND name=?", (fp, name))

    total_genres = len(genre_dirs)
    _set_progress(phase="genres", genre_total=total_genres)

    for gi, (genre_path, genre_entry) in enumerate(sorted(genre_dirs.items())):
        genre_name = genre_entry.get("Name", "")

        frac = (gi / total_genres) if total_genres else 1.0
        _set_progress(
            genre_index=gi + 1,
            genre_current=genre_name,
            percent=int((progress_base + frac * progress_span) * 100),
        )

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
                # has one (avoids a slow fetch on a missing file)
                nfo_data = None
                if any(n.lower().endswith(".nfo") for n in live_movie_files):
                    nfo_raw = _fetch_nfo_raw(movie_path)
                    if nfo_raw:
                        nfo_data = _parse_nfo(nfo_raw)
                        if nfo_data:
                            _save_nfo_to_db(conn, movie_path, nfo_data)

                # A colecao sai do mesmo NFO que acabou de ser lido — nao custa
                # varredura nenhuma a mais. Fica FORA do if do NFO de proposito:
                # com nfo_data None a funcao desfaz o vinculo, que e o correto
                # quando o .nfo foi apagado do filme. Dentro do if, o vinculo
                # antigo ficaria orfao.
                _save_collection_to_db(conn, movie_path, nfo_data)

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

    _prune_empty_collections(conn)
    return stats


def _report(label, root_path, stats, elapsed, conn):
    like_root = _like_prefix(root_path)
    genres = conn.execute(
        "SELECT COUNT(*) as c FROM folders WHERE depth=1 AND path LIKE ? ESCAPE '\\'",
        (like_root,)).fetchone()["c"]
    movies = conn.execute(
        "SELECT COUNT(*) as c FROM folders WHERE depth=2 AND has_video=1 "
        "AND path LIKE ? ESCAPE '\\'", (like_root,)).fetchone()["c"]
    print(
        f"[TicianoFlix] {label}: {genres} generos, {movies} filmes em {elapsed:.1f}s "
        f"(+{stats['added']} novos, ~{stats['changed']} alterados, "
        f"-{stats['removed']} removidos, {stats['unchanged']} inalterados)",
        flush=True
    )


def scan_drive(progress_base=0.0, progress_span=1.0):
    """Varredura incremental do Google Drive via uma unica listagem recursiva."""
    print("[TicianoFlix] Escaneando o Google Drive (incremental)...", flush=True)
    start = time.time()
    _set_progress(phase="listing_root", source_current="Google Drive")

    # --fast-list usa a API files.list do Drive, ~10x mais rapido que andar
    # diretorio por diretorio
    tree = run_rclone_cmd(["lsjson", "--recursive", "--fast-list",
                           _rc_remote(LOGICAL_ROOT)])
    if not isinstance(tree, list):
        print(f"[TicianoFlix] Falha ao listar o Drive: {tree}", flush=True)
        log_notification("error", "Nao foi possivel listar o Google Drive.")
        return False

    conn = get_db()
    try:
        stats = _index_tree(conn, LOGICAL_ROOT, "TicianoFlix", tree,
                            progress_base, progress_span)
        conn.commit()
        _report("Google Drive", LOGICAL_ROOT, stats, time.time() - start, conn)
    finally:
        conn.close()
    return True


def scan_source(source, progress_base=0.0, progress_span=1.0):
    """Varredura incremental de uma fonte local (HD externo, pendrive, pasta).

    Se o volume nao estiver montado, a fonte e pulada por inteiro — sem podar
    nada. Escanear com o pendrive fora nao pode apagar o catalogo dele.
    """
    name = source["name"]
    if not _sources.is_online(source):
        print(f"[TicianoFlix] Fonte '{name}' offline ({source['root']}) — "
              f"catalogo preservado, nada foi escaneado.", flush=True)
        log_notification(
            "warning",
            f"A fonte \"{name}\" esta desconectada. O catalogo dela foi mantido.")
        return False

    print(f"[TicianoFlix] Escaneando '{name}' ({source['root']})...", flush=True)
    start = time.time()
    _set_progress(phase="listing_root", source_current=name)

    entries = _localfs.list_tree(source["root"])

    conn = get_db()
    try:
        stats = _index_tree(conn, source["mount"], name, entries,
                            progress_base, progress_span)
        conn.commit()
        _report(name, source["mount"], stats, time.time() - start, conn)
    finally:
        conn.close()
    return True


def prune_orphan_sources():
    """Apaga arvores sob /Local/ que nao pertencem a nenhuma fonte cadastrada.

    Restaurar um backup feito em outra maquina traz as pastas locais dela junto;
    sem esta poda elas ficariam no catalogo apontando pra lugar nenhum.
    """
    known = {s["mount"] for s in _sources.local_sources()}
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT path FROM folders WHERE depth=0 AND path LIKE ? ESCAPE '\\'",
            (_like_prefix(LOCAL_ROOT),)).fetchall()
        orphans = [r["path"] for r in rows if r["path"] not in known]
        for path in orphans:
            _remove_folder_tree(conn, path)
            print(f"[TicianoFlix] Removida do catalogo a fonte desconhecida {path}",
                  flush=True)
        if orphans:
            conn.commit()
        return len(orphans)
    finally:
        conn.close()


def scan_all(source_id=None):
    """Escaneia o Drive e as fontes locais. `source_id` limita a uma delas."""
    prune_orphan_sources()

    targets = _sources.list_sources()
    if source_id:
        targets = [s for s in targets if s["id"] == source_id]
    if not targets:
        _set_progress(phase="error")
        return False

    total = len(targets)
    span = 1.0 / total
    any_ok = False
    for i, source in enumerate(targets):
        _set_progress(source_index=i + 1, source_total=total,
                      source_current=source["name"])
        base = i * span
        if source["kind"] == "drive":
            ok = scan_drive(base, span)
        else:
            ok = scan_source(source, base, span)
        any_ok = any_ok or ok

    if not any_ok:
        _set_progress(phase="error")
        return False

    set_cache_time()
    _set_progress(phase="done", percent=100)
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


def start_background_scan(source_id=None):
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
            scan_all(source_id)
        except Exception as e:
            _set_progress(phase="error")
            print(f"[TicianoFlix] Scan error: {e}", flush=True)
        finally:
            with _scan_lock:
                _scan_in_progress = False

    with _scan_progress_lock:
        _scan_progress = dict(PROGRESS_ZERO)

    threading.Thread(target=_run, daemon=True).start()
    return "scanning"
