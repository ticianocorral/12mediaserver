"""Consultas ao cache SQLite que servem o frontend."""

import json
import os
import re
import time
from pathlib import Path

from .config import (
    IMAGE_EXTENSIONS, LOGICAL_ROOT, SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS,
)
from .db import get_db, like_prefix
from .nfo import _fetch_nfo

def cached_list_directory(path):
    """List directory contents from cache."""
    conn = get_db()

    # Get folders
    folder_rows = conn.execute(
        "SELECT * FROM folders WHERE parent=? ORDER BY name",
        (path,)
    ).fetchall()

    # Get files
    file_rows = conn.execute(
        "SELECT * FROM files WHERE folder_path=? ORDER BY name",
        (path,)
    ).fetchall()

    conn.close()

    folders = []
    videos = []
    subtitles = []
    images = []

    for row in folder_rows:
        folders.append({
            "Path": row["path"].lstrip("/"),
            "Name": row["name"],
            "Size": 0,
            "MimeType": "inode/directory",
            "ModTime": row["mod_time"],
            "IsDir": True,
            "has_video": bool(row["has_video"]),
        })

    for row in file_rows:
        entry = {
            "Path": f"{row['folder_path'].lstrip('/')}/{row['name']}",
            "Name": row["name"],
            "Size": row["size"],
            "MimeType": row["mime_type"],
            "ModTime": row["mod_time"],
            "IsDir": False,
        }
        ft = row["file_type"]
        if ft == "video":
            # Find poster in same folder
            poster = _find_poster_cached(row["folder_path"])
            if poster:
                entry["poster"] = poster
            videos.append(entry)
        elif ft in ("poster", "fanart", "image"):
            images.append(entry)
        elif ft == "subtitle":
            subtitles.append(entry)

    return {
        "path": path,
        "folders": folders,
        "videos": videos,
        "subtitles": subtitles,
        "images": images,
    }


def cached_movie_detail(folder_path):
    """Get movie detail from SQLite cache (files + NFO metadata)."""
    conn = get_db()
    file_rows = conn.execute(
        "SELECT * FROM files WHERE folder_path=? ORDER BY name",
        (folder_path,)
    ).fetchall()
    conn.close()

    video = None
    poster = None
    fanart = None
    subtitle = None
    images = []

    for row in file_rows:
        entry = {
            "Path": f"{row['folder_path'].lstrip('/')}/{row['name']}",
            "Name": row["name"],
            "Size": row["size"],
            "MimeType": row["mime_type"],
            "ModTime": row["mod_time"],
            "IsDir": False,
            "ID": row["file_id"],
        }
        ft = row["file_type"]
        if ft == "video":
            video = entry
        elif ft == "poster":
            poster = entry
        elif ft == "fanart":
            fanart = entry
        elif ft == "subtitle":
            subtitle = entry
        elif ft == "image":
            images.append(entry)

    if not poster and images:
        poster = images.pop(0)
    if not fanart and images:
        fanart = images.pop(0)

    folder_name = folder_path.strip("/").split("/")[-1]
    year_match = re.search(r'\((\d{4})\)', folder_name)

    result = {
        "folder": folder_path,
        "title": folder_name,
        "year": year_match.group(1) if year_match else None,
        "video": video,
        "poster": poster,
        "fanart": fanart,
        "subtitle": subtitle,
        "images": images,
    }

    # Try to enrich with NFO metadata
    nfo = _fetch_nfo(folder_path)
    if nfo:
        # Use NFO title/year if available (cleaner than folder name)
        if nfo["title"]:
            result["title"] = nfo["title"]
        if nfo["year"]:
            result["year"] = nfo["year"]
        result["nfo"] = nfo

    # Colecao a que este filme pertence, se houver — vira um atalho na ficha.
    colecao = cached_collection_of(folder_path)
    if colecao:
        result["collection"] = colecao

    return result


def cached_get_file_info(file_path):
    """Get single file info from cache."""
    file_path = file_path.strip("/")
    # Determine folder path from file path
    parts = file_path.split("/")
    if len(parts) < 2:
        return None
    filename = parts[-1]
    folder_path = "/" + "/".join(parts[:-1])

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM files WHERE folder_path=? AND name=?",
        (folder_path, filename)
    ).fetchone()
    conn.close()

    if not row:
        return None

    result = {
        "Path": file_path,
        "Name": row["name"],
        "Size": row["size"],
        "MimeType": row["mime_type"],
        "ModTime": row["mod_time"],
        "IsDir": False,
        "ID": row["file_id"],
    }

    if row["file_type"] == "video":
        poster = _find_poster_cached(folder_path)
        if poster:
            result["poster"] = poster

    return result


def cached_search_files(query):
    """Search video files from cache (only videos, no poster/fanart dupes)."""
    conn = get_db()
    like = f"%{query}%"
    rows = conn.execute(
        """SELECT * FROM files
           WHERE name LIKE ?
           AND file_type = 'video'
           ORDER BY size DESC
           LIMIT 100""",
        (like,)
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        entry = {
            "Path": f"{row['folder_path'].lstrip('/')}/{row['name']}",
            "Name": row["name"],
            "Size": row["size"],
            "MimeType": row["mime_type"],
            "ModTime": row["mod_time"],
            "IsDir": False,
        }
        poster = _find_poster_cached(row["folder_path"])
        if poster:
            entry["poster"] = poster
        results.append(entry)
    return results


def cached_all_movies():
    """Return all movie folders sorted A-Z, with poster and title."""
    conn = get_db()
    rows = conn.execute(
        """SELECT f.*, m.title FROM folders f
           LEFT JOIN movie_meta m ON m.folder_path = f.path
           WHERE f.has_video = 1 AND f.depth >= 2
           ORDER BY m.title COLLATE NOCASE ASC, f.name COLLATE NOCASE ASC"""
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        folder_path = row["path"]
        poster = _find_poster_cached(folder_path)
        title = row["title"] or row["name"]
        results.append({
            "path": folder_path,
            "name": row["name"],
            "title": title,
            "poster": poster,
        })
    return results


def cached_collection_movies(name):
    """Os filmes de uma colecao, na ordem da saga.

    Ordena por ano — e o que resolve "Star Wars 1 2 3 4 5 6" sem exigir um
    campo de ordem manual, ja que o <set> do Kodi nao carrega ordem. Filme sem
    ano cai pro fim, com o nome da pasta como desempate.
    """
    conn = get_db()
    try:
        # NOCASE aqui tambem: o link pode vir com outra grafia.
        col = conn.execute(
            "SELECT id, name, overview FROM collections WHERE name = ? COLLATE NOCASE",
            (name,)).fetchone()
        if not col:
            return None
        rows = conn.execute(
            """SELECT f.path, f.name, m.title, m.year
               FROM movie_collections mc
               JOIN folders f ON f.path = mc.folder_path
               LEFT JOIN movie_meta m ON m.folder_path = f.path
               WHERE mc.collection_id = ?
               ORDER BY CASE WHEN m.year IS NULL OR m.year = '' THEN 1 ELSE 0 END,
                        CAST(m.year AS INTEGER) ASC,
                        f.name COLLATE NOCASE ASC""",
            (col["id"],)).fetchall()
    finally:
        conn.close()

    filmes = []
    for row in rows:
        filmes.append({
            "path": row["path"],
            "name": row["name"],
            "title": row["title"] or row["name"],
            "year": row["year"],
            "poster": _find_poster_cached(row["path"]),
        })
    return {"name": col["name"], "overview": col["overview"], "movies": filmes}


def cached_collection_of(folder_path):
    """A colecao a que um filme pertence, ou None. So o cabecalho — sem a
    lista de filmes, que a ficha do filme nao precisa carregar."""
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT c.name, c.overview, COUNT(mc2.folder_path) AS total
               FROM movie_collections mc
               JOIN collections c ON c.id = mc.collection_id
               JOIN movie_collections mc2 ON mc2.collection_id = c.id
               WHERE mc.folder_path = ?
               GROUP BY c.id""",
            (folder_path,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"name": row["name"], "overview": row["overview"], "total": row["total"]}


def cached_all_collections():
    """Todas as colecoes do acervo, com quantos filmes cada uma tem."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT c.name, c.overview, COUNT(mc.folder_path) AS total
               FROM collections c
               JOIN movie_collections mc ON mc.collection_id = c.id
               GROUP BY c.id
               ORDER BY c.name COLLATE NOCASE ASC""").fetchall()
    finally:
        conn.close()
    return [{"name": r["name"], "overview": r["overview"], "total": r["total"]}
            for r in rows]


def cached_source_counts(mount):
    """Quantos generos e filmes o catalogo tem sob um ponto de montagem."""
    like = like_prefix(mount)
    conn = get_db()
    try:
        genres = conn.execute(
            "SELECT COUNT(*) AS c FROM folders "
            "WHERE depth=1 AND has_video=1 AND path LIKE ? ESCAPE '\\'",
            (like,)).fetchone()["c"]
        movies = conn.execute(
            "SELECT COUNT(*) AS c FROM folders "
            "WHERE depth=2 AND has_video=1 AND path LIKE ? ESCAPE '\\'",
            (like,)).fetchone()["c"]
    finally:
        conn.close()
    return {"genres": genres, "movies": movies}


def _find_poster_cached(folder_path):
    """Find poster name from cache for a given folder."""
    conn = get_db()
    row = conn.execute(
        "SELECT name FROM files WHERE folder_path=? AND file_type='poster' LIMIT 1",
        (folder_path,)
    ).fetchone()
    conn.close()
    return row["name"] if row else None
