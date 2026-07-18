#!/usr/bin/env python3
"""
TicianoFlix Server - Netflix-style Google Drive movie player powered by rclone
with SQLite caching for instant browsing.
"""

import http.server
import json
import os
import subprocess
import urllib.parse
import urllib.request
import urllib.error
import mimetypes
import socket
import threading
import sys
import signal
import sqlite3
import re
import time
import shutil
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8080
RCLONE_REMOTE = "gdrive:"
RCLONE_SERVE_PORT = 18082
FRONTEND_PATH = Path(__file__).parent / "index.html"
# Cache goes to user's home (writable even inside AppImage)
_cache_home = Path.home() / ".cache" / "ticianoflix"
CACHE_DIR = _cache_home
DB_PATH = CACHE_DIR / "ticianoflix.db"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
SUBS_CACHE_DIR = CACHE_DIR / "subs"
CACHE_DIR.mkdir(exist_ok=True)
IMAGE_CACHE_DIR.mkdir(exist_ok=True)
SUBS_CACHE_DIR.mkdir(exist_ok=True)

POSTER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

rclone_server_proc = None
_db_lock = threading.Lock()
_scan_in_progress = False
_scan_lock = threading.Lock()

# Set of fully-cached file paths (persisted as JSON)
CACHED_FILES_PATH = CACHE_DIR / "cached_files.json"
_cached_files_lock = threading.Lock()
_cached_files = set()
if CACHED_FILES_PATH.exists():
    try:
        _cached_files = set(json.loads(CACHED_FILES_PATH.read_text()))
    except Exception:
        _cached_files = set()

def _mark_file_cached(file_path):
    """Register a file as fully cached in rclone VFS."""
    with _cached_files_lock:
        _cached_files.add(file_path)
        CACHED_FILES_PATH.write_text(json.dumps(list(_cached_files)))

def _is_file_cached(file_path):
    with _cached_files_lock:
        return file_path in _cached_files


# ═══════════════════════════════════════════════
#  SQLite Cache
# ═══════════════════════════════════════════════

def get_db():
    """Get a thread-local database connection."""
    with _db_lock:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
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
            depth INTEGER NOT NULL DEFAULT 0
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
    """)
    conn.commit()
    conn.close()


def get_cache_time():
    """Get last cache update timestamp."""
    conn = get_db()
    cursor = conn.execute("SELECT value FROM cache_meta WHERE key='last_updated'")
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else None


def set_cache_time():
    """Set cache update timestamp."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('last_updated', ?)",
        (str(int(time.time())),)
    )
    conn.commit()
    conn.close()


def is_cache_stale():
    """Check if cache needs refresh (older than 1 hour)."""
    t = get_cache_time()
    if not t:
        return True
    return (int(time.time()) - int(t)) > 3600


# ═══════════════════════════════════════════════
#  Drive Scanner
# ═══════════════════════════════════════════════

def run_rclone_cmd(args, timeout=60):
    """Run an rclone command and return parsed JSON output."""
    cmd = ["rclone"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        if result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"output": result.stdout.strip()}
        return {"output": ""}
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out"}
    except FileNotFoundError:
        return {"error": "rclone not found. Please install rclone."}


def list_directory_raw(path):
    """List directory contents via rclone lsjson (uncached)."""
    remote_path = RCLONE_REMOTE + path
    return run_rclone_cmd(["lsjson", remote_path])


def scan_drive():
    """
    Full scan of the TicianoFlix drive structure.
    1. List TicianoFlix root (genres)
    2. For each genre, list its contents
    3. For each movie folder, list its contents
    """
    print("[TicianoFlix] Scanning Google Drive...", flush=True)
    start = time.time()

    conn = get_db()

    # Clear old data
    conn.execute("DELETE FROM files")
    conn.execute("DELETE FROM folders")

    # Step 1: Check if TicianoFlix folder exists
    root_data = list_directory_raw("")
    if isinstance(root_data, dict) and "error" in root_data:
        print(f"[TicianoFlix] ERROR: {root_data['error']}", flush=True)
        conn.close()
        return False

    # Find TicianoFlix folder
    ticianoflix_path = ""
    if isinstance(root_data, list):
        for item in root_data:
            if item.get("IsDir") and item.get("Name") == "TicianoFlix":
                ticianoflix_path = "/TicianoFlix"
                conn.execute(
                    "INSERT OR REPLACE INTO folders (path, name, parent, is_ticianoflix_root, depth) VALUES (?, ?, '', 1, 0)",
                    (ticianoflix_path, "TicianoFlix")
                )
                break

    if not ticianoflix_path:
        print("[TicianoFlix] TicianoFlix folder not found in drive root!", flush=True)
        conn.commit()
        conn.close()
        return False

    # Step 2: List genres (inside TicianoFlix)
    genres = list_directory_raw(ticianoflix_path)
    if not isinstance(genres, list):
        print(f"[TicianoFlix] Failed to list genres: {genres}", flush=True)
        conn.commit()
        conn.close()
        return False

    for genre_item in genres:
        if not genre_item.get("IsDir"):
            continue

        genre_name = genre_item.get("Name", "")
        genre_path = f"{ticianoflix_path}/{genre_name}"
        genre_stripped = genre_path.lstrip("/")  # for rclone

        conn.execute(
            "INSERT OR REPLACE INTO folders (path, name, parent, depth) VALUES (?, ?, ?, 1)",
            (genre_path, genre_name, ticianoflix_path)
        )

        # Step 3: List movie folders inside genre
        movie_items = list_directory_raw(f"/{genre_stripped}")
        if not isinstance(movie_items, list):
            continue

        # Check for direct video files (unstructured)
        has_direct_video = False
        for item in movie_items:
            if not item.get("IsDir"):
                ext = Path(item.get("Name", "")).suffix.lower()
                if ext in VIDEO_EXTENSIONS:
                    has_direct_video = True
                # Index all files in genre root
                _index_file(conn, genre_path, item)

        for item in movie_items:
            if not item.get("IsDir"):
                continue

            movie_name = item.get("Name", "")
            movie_path = f"{genre_path}/{movie_name}"
            movie_stripped = movie_path.lstrip("/")

            conn.execute(
                "INSERT OR REPLACE INTO folders (path, name, parent, depth) VALUES (?, ?, ?, 2)",
                (movie_path, movie_name, genre_path)
            )

            # Step 4: List movie folder contents
            movie_contents = list_directory_raw(f"/{movie_stripped}")
            if not isinstance(movie_contents, list):
                continue

            has_video = False
            for file_item in movie_contents:
                if file_item.get("IsDir"):
                    continue
                fname = file_item.get("Name", "")
                ext = Path(fname).suffix.lower()
                if ext in VIDEO_EXTENSIONS:
                    has_video = True
                _index_file(conn, movie_path, file_item)

            if has_video:
                conn.execute(
                    "UPDATE folders SET has_video=1 WHERE path=?",
                    (movie_path,)
                )

                # Parse NFO and save metadata to DB
                nfo_raw = _fetch_nfo_raw(movie_path)
                if nfo_raw:
                    nfo_data = _parse_nfo(nfo_raw)
                    if nfo_data:
                        _save_nfo_to_db(conn, movie_path, nfo_data)

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

    # Also index any files directly in TicianoFlix root
    for item in genres:
        if not item.get("IsDir"):
            _index_file(conn, ticianoflix_path, item)

    conn.commit()

    # Mark ticianoflix root
    total_genres = conn.execute("SELECT COUNT(*) as c FROM folders WHERE depth=1").fetchone()["c"]
    total_movies = conn.execute("SELECT COUNT(*) as c FROM folders WHERE has_video=1 AND depth=2").fetchone()["c"]
    total_files = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
    conn.close()

    set_cache_time()

    elapsed = time.time() - start
    print(f"[TicianoFlix] Scan complete: {total_genres} genres, {total_movies} movies, {total_files} files in {elapsed:.1f}s", flush=True)
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


# ═══════════════════════════════════════════════
#  Cached Queries
# ═══════════════════════════════════════════════

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
            "ModTime": "",
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




def _parse_nfo(xml_text):
    """Parse Kodi-style NFO XML into a dict of metadata."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    def text(tag):
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else None

    def texts(tag):
        return [el.text.strip() for el in root.findall(tag) if el.text]

    def rating_info():
        """Extract rating value + votes from <ratings><rating>."""
        r = root.find("ratings/rating")
        if r is not None:
            val = r.findtext("value", "").strip()
            votes = r.findtext("votes", "").strip()
            return val, votes
        return text("rating"), None

    rating_val, rating_votes = rating_info()

    # Actors
    actors = []
    for actor in root.findall("actor"):
        name = actor.findtext("name", "").strip()
        role = actor.findtext("role", "").strip()
        thumb = actor.findtext("thumb", "").strip()
        if name:
            actors.append({"name": name, "role": role, "thumb": thumb})

    # Directors / Writers / Producers
    directors = texts("director")
    writers = texts("credits")

    # NFO can have <streamdetails> with video/audio info
    video_info = {}
    v = root.find("fileinfo/streamdetails/video")
    if v is not None:
        for child in v:
            video_info[child.tag] = child.text.strip() if child.text else ""

    audio_info = {}
    for a in root.findall("fileinfo/streamdetails/audio"):
        for child in a:
            audio_info[child.tag] = child.text.strip() if child.text else ""

    return {
        "title": text("title"),
        "originaltitle": text("originaltitle"),
        "year": text("year"),
        "plot": text("plot"),
        "outline": text("outline"),
        "tagline": text("tagline"),
        "runtime": text("runtime"),
        "mpaa": text("mpaa"),
        "country": texts("country"),
        "premiered": text("premiered"),
        "rating": rating_val,
        "votes": rating_votes,
        "genres": texts("genre"),
        "studios": texts("studio"),
        "directors": directors,
        "writers": writers,
        "tags": texts("tag"),
        "actors": actors,
        "video_info": video_info,
        "audio_info": audio_info,
        "source": text("source"),
    }


def _fetch_nfo_raw(folder_path):
    """Fetch NFO XML text for a movie folder via rclone. No caching."""
    nfo_path = f"{folder_path.strip('/')}/{folder_path.strip('/').split('/')[-1]}.nfo"
    remote_path = RCLONE_REMOTE + nfo_path
    try:
        result = subprocess.run(
            ["rclone", "cat", remote_path],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


def _save_nfo_to_db(conn, folder_path, nfo_data):
    """Save parsed NFO metadata into movie_meta table."""
    import json
    conn.execute("""INSERT OR REPLACE INTO movie_meta
        (folder_path, title, year, plot, rating, votes, genres, tagline,
         directors, writers, cast_list, video_info, audio_info, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        folder_path,
        nfo_data.get("title"),
        nfo_data.get("year"),
        nfo_data.get("plot"),
        nfo_data.get("rating"),
        nfo_data.get("votes"),
        json.dumps(nfo_data.get("genres", []), ensure_ascii=False),
        nfo_data.get("tagline"),
        json.dumps(nfo_data.get("directors", []), ensure_ascii=False),
        json.dumps(nfo_data.get("writers", []), ensure_ascii=False),
        json.dumps(nfo_data.get("actors", []), ensure_ascii=False),
        json.dumps(nfo_data.get("video_info", {}), ensure_ascii=False),
        json.dumps(nfo_data.get("audio_info", {}), ensure_ascii=False),
        time.time(),
    ))


def _fetch_nfo_from_db(folder_path):
    """Read parsed NFO metadata from movie_meta table."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM movie_meta WHERE folder_path=?", (folder_path,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    import json
    return {
        "title": row["title"],
        "year": row["year"],
        "plot": row["plot"],
        "rating": row["rating"],
        "votes": row["votes"],
        "genres": json.loads(row["genres"]) if row["genres"] else [],
        "tagline": row["tagline"],
        "directors": json.loads(row["directors"]) if row["directors"] else [],
        "writers": json.loads(row["writers"]) if row["writers"] else [],
        "actors": json.loads(row["cast_list"]) if row["cast_list"] else [],
        "video_info": json.loads(row["video_info"]) if row["video_info"] else {},
        "audio_info": json.loads(row["audio_info"]) if row["audio_info"] else {},
    }


def _fetch_nfo(folder_path):
    """Fetch and parse NFO metadata. Tries DB first, then downloads via rclone."""
    # Try DB cache first
    from_db = _fetch_nfo_from_db(folder_path)
    if from_db:
        return from_db

    # Fallback: fetch via rclone
    nfo_path = f"{folder_path.strip('/')}/{folder_path.strip('/').split('/')[-1]}.nfo"
    remote_path = RCLONE_REMOTE + nfo_path
    try:
        result = subprocess.run(
            ["rclone", "cat", remote_path],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None
        parsed = _parse_nfo(result.stdout)
        if parsed:
            # Save to DB for next time
            conn = get_db()
            try:
                _save_nfo_to_db(conn, folder_path, parsed)
                conn.commit()
            finally:
                conn.close()
        return parsed
    except Exception:
        return None


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
    """Search files from cache."""
    conn = get_db()
    like = f"%{query}%"
    rows = conn.execute(
        """SELECT * FROM files
           WHERE name LIKE ?
           AND file_type IN ('video', 'image', 'poster', 'fanart')
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
        if row["file_type"] == "video":
            poster = _find_poster_cached(row["folder_path"])
            if poster:
                entry["poster"] = poster
        results.append(entry)
    return results


def _find_poster_cached(folder_path):
    """Find poster name from cache for a given folder."""
    conn = get_db()
    row = conn.execute(
        "SELECT name FROM files WHERE folder_path=? AND file_type='poster' LIMIT 1",
        (folder_path,)
    ).fetchone()
    conn.close()
    return row["name"] if row else None


# ═══════════════════════════════════════════════
#  HTTP Handler
# ═══════════════════════════════════════════════

class TicianoFlixHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        sys.stderr.write(f"[TicianoFlix] {args[0]} {args[1]} {args[2]}\n")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send_html(self, content, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _send_error(self, msg, status=500):
        self._send_json({"error": msg}, status)

    def _stream_file(self, path):
        """Stream a file. Images are cached locally; videos go through rclone proxy."""
        ext = Path(path).suffix.lower()

        # Small images: cache locally after first fetch
        if ext in IMAGE_EXTENSIONS:
            self._stream_image_cached(path)
            return

        # Videos and other files: proxy through rclone serve or fallback
        self._stream_video_proxy(path)

    def _stream_image_cached(self, path):
        """Stream an image file, caching it locally on first access."""
        cache_key = path.strip("/").replace("/", "_")
        cache_path = IMAGE_CACHE_DIR / cache_key

        # Serve from local cache if available
        if cache_path.exists():
            mime, _ = mimetypes.guess_type(str(cache_path))
            if mime is None:
                mime = "image/jpeg"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(cache_path.stat().st_size))
            self.send_header("Cache-Control", "max-age=86400")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with open(cache_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            return

        # Not cached yet — download via rclone proxy with retry
        safe_path = urllib.parse.quote(path.strip("/"), safe="/")
        rclone_url = f"http://localhost:{RCLONE_SERVE_PORT}/{safe_path}"

        # Retry up to 3 times with 0.5s delay (rclone serve may still be starting)
        last_error = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(rclone_url, method="GET")
                resp = urllib.request.urlopen(req, timeout=60)

                data = resp.read()
                mime = resp.headers.get("Content-Type", "image/jpeg")

                # Save to local cache
                try:
                    with open(cache_path, "wb") as f:
                        f.write(data)
                    sys.stderr.write(f"[TicianoFlix] Cached image: {cache_key} ({len(data)}B)\n")
                except Exception as e:
                    sys.stderr.write(f"[TicianoFlix] Cache write failed: {e}\n")

                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
                return
            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(0.5)
                    continue

        # All retries failed — fallback to direct
        sys.stderr.write(f"[TicianoFlix] Image cache proxy failed after retries: {last_error}\n")
        self._stream_file_direct(path)

    def _stream_video_proxy(self, path):
        """Proxy video through main server (no redirect). Forwards Range
        requests to rclone serve and streams response back to client.
        Same-origin = works on mobile browsers without cross-origin issues."""
        safe_path = urllib.parse.quote(path.strip("/"), safe="/")
        rclone_url = f"http://localhost:{RCLONE_SERVE_PORT}/{safe_path}"

        range_header = self.headers.get("Range")
        mime = self._guess_mime(path)

        try:
            req = urllib.request.Request(rclone_url, method="GET")
            if range_header:
                req.add_header("Range", range_header)
            resp = urllib.request.urlopen(req, timeout=None)

            status = resp.status
            rsp_headers = resp.headers

            if status == 206:
                self.send_response(206)
                cr = rsp_headers.get("Content-Range", "")
                if cr:
                    self.send_header("Content-Range", cr)
            else:
                self.send_response(200)

            cl = rsp_headers.get("Content-Length")
            if cl:
                self.send_header("Content-Length", cl)
            self.send_header("Content-Type", mime)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            while True:
                buf = resp.read(65536)
                if not buf:
                    break
                self.wfile.write(buf)

            # If the range covered the last byte, mark as VFS-cached
            if status == 206 and range_header:
                try:
                    file_info = cached_get_file_info(path)
                    file_size = file_info.get("Size", 0) if file_info else 0
                    if file_size > 0:
                        range_match = range_header.replace("bytes=", "").split("-")
                        range_end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else None
                        if range_end is not None and range_end >= file_size - 1:
                            _mark_file_cached(path)
                except Exception:
                    pass

        except urllib.error.HTTPError as e:
            sys.stderr.write(f"[ERROR] Video proxy HTTP {e.code}: {e.reason}\n")
            self._stream_file_direct(path)
        except Exception as e:
            sys.stderr.write(f"[ERROR] Video proxy failed: {e}\n")
            self._stream_file_direct(path)

    def _stream_file_direct(self, path):
        """Fallback: stream directly via rclone cat (original method)."""
        remote_path = RCLONE_REMOTE + path.strip("/")

        file_info = cached_get_file_info(path)
        file_size = file_info.get("Size", 0) if file_info else 0

        range_header = self.headers.get("Range")
        start = 0
        end = file_size - 1 if file_size > 0 else None
        chunk_size = 10 * 1024 * 1024

        if range_header:
            range_match = range_header.replace("bytes=", "").split("-")
            try:
                start = int(range_match[0]) if range_match[0] else 0
                if len(range_match) > 1 and range_match[1]:
                    end = int(range_match[1])
                    chunk_size = end - start + 1
                else:
                    end = min(start + chunk_size, file_size - 1) if file_size > 0 else start + chunk_size
                    chunk_size = end - start + 1
            except (ValueError, IndexError):
                pass
        else:
            end = min(chunk_size - 1, file_size - 1) if file_size > 0 else chunk_size - 1
            chunk_size = end + 1

        cat_cmd = ["rclone", "cat"]
        if start > 0:
            cat_cmd.extend(["--offset", str(start)])
        cat_cmd.extend(["--count", str(chunk_size)])
        cat_cmd.append(remote_path)

        mime = self._guess_mime(path)

        if range_header:
            self.send_response(206)
            content_range = f"bytes {start}-{end}/{file_size}" if file_size > 0 else f"bytes {start}-{end}/*"
            self.send_header("Content-Range", content_range)
            self.send_header("Content-Length", str(chunk_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", mime)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(chunk_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", mime)
            self.end_headers()

        try:
            proc = subprocess.Popen(cat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            remaining = chunk_size
            while remaining > 0:
                buf = proc.stdout.read(min(65536, remaining))
                if not buf:
                    break
                self.wfile.write(buf)
                remaining -= len(buf)
            proc.stdout.close()
            proc.wait(timeout=10)
            # If range covers the last byte of the file, the whole file is cached by rclone
            if proc.returncode == 0 and file_size > 0 and end is not None and end >= file_size - 1:
                _mark_file_cached(path)
        except Exception as e:
            sys.stderr.write(f"[ERROR] Direct stream failed: {e}\n")

    def _serve_subtitle(self, path):
        """Serve a subtitle file, converting SRT→VTT if needed.
        Caches locally on first fetch for speed."""
        cache_key = "sub_" + path.strip("/").replace("/", "_").replace(" ", "_")
        cache_path = SUBS_CACHE_DIR / cache_key

        # Try local cache first
        if cache_path.exists():
            raw = cache_path.read_text(encoding="utf-8", errors="replace")
        else:
            # Fetch via rclone cat
            remote_path = RCLONE_REMOTE + path.strip("/")
            try:
                result = subprocess.run(
                    ["rclone", "cat", remote_path],
                    capture_output=True, timeout=30
                )
                if result.returncode != 0:
                    self._send_error("Subtitle not found", 404)
                    return
                # Tenta UTF-8 primeiro, fallback pra latin-1 (comum em SRT)
                raw_bytes = result.stdout
                try:
                    raw = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    raw = raw_bytes.decode("latin-1")
                # Cache local (sempre UTF-8)
                try:
                    cache_path.write_text(raw, encoding="utf-8")
                except Exception:
                    pass
            except Exception as e:
                sys.stderr.write(f"[TicianoFlix] Subtitle fetch failed: {e}\n")
                self._send_error("Subtitle not found", 404)
                return

        ext = Path(path).suffix.lower()

        # SRT → WebVTT conversion (browsers don't support SRT natively)
        if ext == ".srt":
            # Replace comma with dot in timestamps, add WEBVTT header
            lines = raw.split("\n")
            vtt = ["WEBVTT\n"]
            for line in lines:
                # SRT: 00:00:10,500 --> 00:00:13,000
                # VTT: 00:00:10.500 --> 00:00:13.000
                if "-->" in line:
                    line = line.replace(",", ".")
                vtt.append(line)
            body = "\n".join(vtt)
        else:
            # VTT/ASS already supported or passed through
            body = raw

        self.send_response(200)
        self.send_header("Content-Type", "text/vtt; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _guess_mime(self, path):
        """Guess MIME type for a file."""
        mime, _ = mimetypes.guess_type(path)
        if mime:
            return mime
        ext = Path(path).suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            return "video/mp4"
        if ext == ".mkv":
            return "video/x-matroska"
        return "application/octet-stream"

    def _serve_file(self, path):
        """Serve a file from the local filesystem."""
        filepath = Path(__file__).parent / path.lstrip("/")
        if not filepath.exists() or not filepath.is_file():
            self._send_error("File not found", 404)
            return
        mime, _ = mimetypes.guess_type(str(filepath))
        if mime is None:
            mime = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(filepath.stat().st_size))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def _generate_backup_zip(self):
        """Generate backup zip in memory. Returns bytes."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            db_path = Path(DB_PATH)
            if db_path.exists():
                z.write(db_path, "ticianoflix.db")
            img_dir = Path(IMAGE_CACHE_DIR)
            if img_dir.exists():
                for f in sorted(img_dir.iterdir()):
                    if f.is_file():
                        z.write(f, f"images/{f.name}")
            subs_dir = Path(SUBS_CACHE_DIR)
            if subs_dir.exists():
                for f in sorted(subs_dir.iterdir()):
                    if f.is_file():
                        z.write(f, f"subs/{f.name}")
        return buf.getvalue()

    def _serve_backup(self):
        """Generate and serve a zip backup of DB + images + subs."""
        data = self._generate_backup_zip()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="ticianoflix-backup.zip"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _backup_to_drive(self):
        """Generate backup zip and upload to Google Drive via rclone."""
        try:
            data = self._generate_backup_zip()
            filename = f"ticianoflix-backup-{time.strftime('%Y-%m-%d')}.zip"
            remote_path = f"{RCLONE_REMOTE}TicianoFlix/{filename}"

            proc = subprocess.run(
                ["rclone", "rcat", remote_path],
                input=data,
                capture_output=True,
                timeout=60
            )
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace").strip()
                return {"ok": False, "error": f"rclone failed: {err}"}

            return {"ok": True, "path": f"TicianoFlix/{filename}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _handle_restore_from_drive(self):
        """Find latest backup zip in Drive, download and restore."""
        try:
            # List backup files in TicianoFlix root
            result = run_rclone_cmd(["lsjson", f"{RCLONE_REMOTE}TicianoFlix"])
            if not isinstance(result, list):
                self._send_error("Failed to list Drive files")
                return

            zips = [f for f in result if f.get("Name", "").startswith("ticianoflix-backup-") and f.get("Name", "").endswith(".zip")]
            if not zips:
                self._send_error("Nenhum backup encontrado no Google Drive")
                return

            # Get most recent by ModTime
            zips.sort(key=lambda f: f.get("ModTime", ""), reverse=True)
            latest = zips[0]
            name = latest["Name"]

            self._send_json({"status": "downloading", "file": name})

            # Download in background thread
            def _do_restore():
                try:
                    remote = f"{RCLONE_REMOTE}TicianoFlix/{name}"
                    proc = subprocess.run(
                        ["rclone", "cat", remote],
                        capture_output=True, timeout=120
                    )
                    if proc.returncode != 0:
                        print(f"[TicianoFlix] Failed to download backup: {proc.stderr.decode(errors='replace')}", flush=True)
                        return

                    buf = io.BytesIO(proc.stdout)
                    with zipfile.ZipFile(buf, "r") as z:
                        names = z.namelist()
                        if "ticianoflix.db" not in names:
                            print("[TicianoFlix] Backup zip missing ticianoflix.db", flush=True)
                            return
                        db_path = Path(DB_PATH)
                        if db_path.exists():
                            shutil.copy2(db_path, db_path.with_suffix(".db.bak"))
                        db_path.write_bytes(z.read("ticianoflix.db"))
                        img_dir = Path(IMAGE_CACHE_DIR)
                        img_dir.mkdir(exist_ok=True)
                        for n in names:
                            if n.startswith("images/") and not n.endswith("/"):
                                (img_dir / Path(n).name).write_bytes(z.read(n))
                        subs_dir = Path(SUBS_CACHE_DIR)
                        subs_dir.mkdir(exist_ok=True)
                        for n in names:
                            if n.startswith("subs/") and not n.endswith("/"):
                                (subs_dir / Path(n).name).write_bytes(z.read(n))
                    print(f"[TicianoFlix] Backup restored from Drive: {name}", flush=True)
                except Exception as e:
                    print(f"[TicianoFlix] Restore from Drive failed: {e}", flush=True)

            threading.Thread(target=_do_restore, daemon=True).start()

        except Exception as e:
            self._send_error(f"Falha ao restaurar do Drive: {e}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/restore":
            self._handle_restore()
            return

        self._send_error("Not found", 404)

    def _handle_restore(self):
        """Restore backup from uploaded zip file."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0:
                self._send_error("Empty request", 400)
                return
            data = self.rfile.read(content_len)
            buf = io.BytesIO(data)
            with zipfile.ZipFile(buf, "r") as z:
                names = z.namelist()
                if "ticianoflix.db" not in names:
                    self._send_error("Backup must contain ticianoflix.db", 400)
                    return
                db_path = Path(DB_PATH)
                if db_path.exists():
                    shutil.copy2(db_path, db_path.with_suffix(".db.bak"))
                db_path.write_bytes(z.read("ticianoflix.db"))
                img_dir = Path(IMAGE_CACHE_DIR)
                img_dir.mkdir(exist_ok=True)
                for name in names:
                    if name.startswith("images/") and not name.endswith("/"):
                        (img_dir / Path(name).name).write_bytes(z.read(name))
                subs_dir = Path(SUBS_CACHE_DIR)
                subs_dir.mkdir(exist_ok=True)
                for name in names:
                    if name.startswith("subs/") and not name.endswith("/"):
                        (subs_dir / Path(name).name).write_bytes(z.read(name))
            self._send_json({"status": "ok", "message": "Backup restaurado com sucesso"})
        except Exception as e:
            self._send_error(f"Falha ao restaurar: {e}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # Serve frontend
        if path == "/" or path == "/index.html":
            html_content = FRONTEND_PATH.read_text(encoding="utf-8") if FRONTEND_PATH.exists() else "<h1>TicianoFlix</h1><p>Frontend not found.</p>"
            self._send_html(html_content)
            return

        # Static files
        if path.startswith("/static/"):
            self._serve_file(path)
            return

        # API: Refresh cache (scan drive)
        if path == "/api/refresh":
            global _scan_in_progress
            with _scan_lock:
                if _scan_in_progress:
                    self._send_json({"status": "already_scanning"})
                    return
                _scan_in_progress = True

            def scan_wrapper():
                global _scan_in_progress
                try:
                    scan_drive()
                finally:
                    with _scan_lock:
                        _scan_in_progress = False

            self._send_json({"status": "scanning"})
            threading.Thread(target=scan_wrapper, daemon=True).start()
            return

        # API: Download backup (.zip)
        if path == "/api/backup":
            self._serve_backup()
            return

        # API: Backup to Google Drive
        if path == "/api/backup/drive":
            result = self._backup_to_drive()
            if result["ok"]:
                self._send_json({"status": "ok", "path": result["path"]})
            else:
                self._send_json({"status": "error", "error": result["error"]}, 500)
            return

        # API: Restore backup from Google Drive
        if path == "/api/restore/drive":
            self._handle_restore_from_drive()
            return

        # API: Check if file is fully cached in rclone VFS
        if path == "/api/check-cached":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_json({"cached": False})
                return
            self._send_json({"cached": _is_file_cached(file_path)})
            return

        # API: Clear all caches (VFS, DB cache markers)
        if path == "/api/clear-cache":
            try:
                import shutil as sh
                # Clear VFS cache (downloaded videos)
                vfs_cache = Path.home() / ".cache" / "rclone" / "vfs"
                if vfs_cache.exists():
                    for entry in vfs_cache.iterdir():
                        if entry.is_dir():
                            sh.rmtree(entry)
                # Clear cached files list
                global _cached_files
                with _cached_files_lock:
                    _cached_files.clear()
                    if CACHED_FILES_PATH.exists():
                        CACHED_FILES_PATH.unlink()
                # Clear DB cache timestamps
                conn = get_db()
                conn.execute("DELETE FROM cache_meta")
                conn.commit()
                conn.close()
                self._send_json({"status": "ok"})
            except Exception as e:
                self._send_json({"status": "error", "error": str(e)}, 500)
            return

        # API: Cache status
        if path == "/api/cache-status":
            cache_time = get_cache_time()
            stale = is_cache_stale()
            conn = get_db()
            genres = conn.execute("SELECT COUNT(*) as c FROM folders WHERE depth=1").fetchone()["c"]
            movies = conn.execute("SELECT COUNT(*) as c FROM folders WHERE has_video=1 AND depth=2").fetchone()["c"]
            files = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
            conn.close()
            self._send_json({
                "cached": cache_time is not None,
                "last_updated": cache_time,
                "stale": stale,
                "genres": genres,
                "movies": movies,
                "files": files,
            })
            return

        # API: List genres with content (from cache)
        if path == "/api/genres":
            conn = get_db()
            genre_rows = conn.execute(
                "SELECT * FROM folders WHERE depth=1 AND has_video=1 ORDER BY name"
            ).fetchall()
            conn.close()
            data = {
                "path": "/TicianoFlix",
                "folders": [
                    {
                        "Path": row["path"].lstrip("/"),
                        "Name": row["name"],
                        "Size": 0,
                        "MimeType": "inode/directory",
                        "ModTime": "",
                        "IsDir": True,
                        "has_video": True,
                    }
                    for row in genre_rows
                ],
                "videos": [],
                "subtitles": [],
                "images": [],
            }
            self._send_json(data)
            return

        # API: List directory (from cache)
        if path == "/api/list":
            dir_path = params.get("path", [""])[0]

            # On root, auto-redirect to TicianoFlix
            if dir_path == "" or dir_path == "/":
                dir_path = "/TicianoFlix"

            data = cached_list_directory(dir_path)
            if data is None:
                self._send_error("Path not found in cache", 404)
                return

            # Ensure empty lists for missing keys
            data.setdefault("folders", [])
            data.setdefault("videos", [])
            data.setdefault("subtitles", [])
            data.setdefault("images", [])

            # No auto-scan — user must click refresh manually
            # If cache is empty, just show whatever we have (will be empty)

            self._send_json(data)
            return

        # API: Movie detail (from cache)
        if path == "/api/movie-detail":
            folder_path = params.get("path", [""])[0]
            if not folder_path:
                self._send_error("Missing 'path' parameter", 400)
                return

            data = cached_movie_detail(folder_path)
            self._send_json(data)
            return

        # API: Search (from cache)
        if path == "/api/search":
            query = params.get("q", [""])[0]
            if not query:
                self._send_error("Missing 'q' parameter", 400)
                return
            results = cached_search_files(query)
            self._send_json({"results": results})
            return

        # API: Stream (live from rclone)
        if path == "/api/stream":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_error("Missing 'path' parameter", 400)
                return
            self._stream_file(file_path)
            return

        # API: Subtitle (serve as WebVTT for browser)
        if path == "/api/subtitle":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_error("Missing 'path' parameter", 400)
                return
            self._serve_subtitle(file_path)
            return

        # API: File info (from cache)
        if path == "/api/info":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._send_error("Missing 'path' parameter", 400)
                return
            item = cached_get_file_info(file_path)
            if item:
                self._send_json(item)
            else:
                self._send_error("File not found", 404)
            return

        # API: Backup database
        if path == "/api/backup":
            db_path = DB_PATH
            if not db_path.exists():
                self._send_error("Database not found", 404)
                return

            # Save a copy to ~/Downloads/
            downloads = Path.home() / "Downloads"
            downloads.mkdir(exist_ok=True)
            today = time.strftime("%Y-%m-%d")
            backup_name = f"ticianoflix-backup-{today}.db"
            backup_path = downloads / backup_name

            try:
                import shutil as _shutil
                _shutil.copy2(db_path, backup_path)
                saved_path = str(backup_path)
            except Exception:
                saved_path = str(db_path)

            # Also serve the file for browser fallback
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{backup_name}"')
            self.send_header("Content-Length", str(db_path.stat().st_size))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Backup-Path", saved_path)
            self.end_headers()
            with open(db_path, "rb") as f:
                self.wfile.write(f.read())
            return

        self._send_error("Not found", 404)

    # ═══════════════════════════════════════════════
    #  (download removido)
    # ═══════════════════════════════════════════════

def find_free_port():
    """Find an available port starting from PORT, or use TICIANOFLIX_PORT env."""
    env_port = os.environ.get("TICIANOFLIX_PORT")
    if env_port:
        return int(env_port)
    # Sempre forçar 8080 — se estiver ocupada, liberar
    port = PORT
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, port))
        s.close()
        return port
    except OSError:
        # Porta ocupada — tentar matar processo via fuser
        import subprocess as _sp
        _sp.run(["fuser", "-k", f"{port}/tcp"], capture_output=True, timeout=5)
        time.sleep(1)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, port))
            s.close()
            return port
        except OSError:
            # Último recurso: procurar outra porta
            while port < PORT + 100:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((HOST, port))
                    s.close()
                    return port
                except OSError:
                    port += 1
            return PORT


def main():
    # Initialize database
    init_db()
    db_path_abs = DB_PATH.resolve()

    # Start rclone serve http (persistent connection = much faster streams)
    rclone_serve_port = RCLONE_SERVE_PORT
    rclone_serve_proc = None

    # Check if rclone serve is already running (e.g., started by app.py)
    rclone_was_running = False
    try:
        import urllib.request as ureq_check
        ureq_check.urlopen(f"http://localhost:{rclone_serve_port}/", timeout=2)
        print(f"[TicianoFlix] rclone serve already running on localhost:{rclone_serve_port}", flush=True)
        rclone_was_running = True
    except Exception:
        # Not running — try to start it
        rclone_was_running = False
        # Not running — try to start it
        try:
            rclone_serve_proc = subprocess.Popen(
                ["rclone", "serve", "http", "gdrive:",
                 "--addr", f"localhost:{rclone_serve_port}",
                 "--read-only",
                 "--drive-chunk-size", "128M",
                 "--buffer-size", "512M",
                 "--vfs-cache-mode", "full",
                 "--vfs-cache-max-size", "10G",
                 "--vfs-cache-max-age", "720h",
                 "--vfs-read-chunk-size", "4M",
                 "--vfs-read-chunk-size-limit", "off",
                 "--vfs-read-ahead", "512M",
                 "--header", "Access-Control-Allow-Origin: *",
                 "--log-level", "ERROR"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[TicianoFlix] Starting rclone serve http on localhost:{rclone_serve_port}...", end=" ", flush=True)

            # Wait for rclone serve to be ready (up to 10s)
            import urllib.request as ureq_health
            for _ in range(10):
                time.sleep(1)
                try:
                    ureq_health.urlopen(f"http://localhost:{rclone_serve_port}/", timeout=2)
                    print("ready!", flush=True)
                    break
                except Exception:
                    continue
            else:
                print("timed out, streams may use fallback", flush=True)
        except FileNotFoundError:
            print("[TicianoFlix] WARNING: rclone not found, streams will use fallback method", flush=True)
        except Exception as e:
            print(f"[TicianoFlix] WARNING: could not start rclone serve: {e}", flush=True)

    # No auto-scan on startup — user must click refresh manually
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) as c FROM folders").fetchone()["c"]
    conn.close()

    if count == 0:
        print("[TicianoFlix] Cache vazio. Clique em 🔄 (Atualizar) para escanear o Google Drive.", flush=True)
    else:
        cache_age = ""
        t = get_cache_time()
        if t:
            age_mins = (int(time.time()) - int(t)) // 60
            cache_age = f" (cached {age_mins}m ago)"
        print(f"[TicianoFlix] Cache loaded from {db_path_abs}{cache_age}", flush=True)

    port = find_free_port()
    server = http.server.ThreadingHTTPServer((HOST, port), TicianoFlixHandler)
    server.timeout = 0.5
    # Permite reuso imediato da porta ao reiniciar
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    print(f"""
╔══════════════════════════════════════════════╗
║            TicianoFlix Server                ║
║                                              ║
║  🌐 http://localhost:{port}                     ║
║  📁 Google Drive via rclone (cached + http)  ║
║                                              ║
║  ⚡ /api/refresh - rescan drive               ║
║  🚀 rclone proxy on localhost:{rclone_serve_port}        ║
╚══════════════════════════════════════════════╝
    """)

    # Shutdown imediato — não espera threads de stream terminarem
    def shutdown(sig, frame):
        print("\n[TicianoFlix] Desligando...")
        os._exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGHUP, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if rclone_serve_proc:
            rclone_serve_proc.terminate()
            try:
                rclone_serve_proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                rclone_serve_proc.kill()
                rclone_serve_proc.wait(timeout=1)
        server.server_close()
        print("[TicianoFlix] Servidor parado.")


if __name__ == "__main__":
    main()
