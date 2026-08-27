"""Metadados NFO (formato Kodi / tinyMediaManager).

Usado tanto pelo scanner (grava no banco durante a varredura) quanto pelas
consultas (le do banco, com fallback pro Drive).
"""

import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from .config import MAX_NFO_BYTES
from .db import get_db
from .paths import rc_remote as _rc_remote

def _parse_nfo(xml_text):
    """Parse Kodi-style NFO XML into a dict of metadata."""
    # NFOs legitimos nao declaram entidades. Recusar <!ENTITY fecha o vetor de
    # bomba XML (billion laughs) do ElementTree sem dependencia externa.
    if xml_text and "<!ENTITY" in xml_text.upper():
        sys.stderr.write("[TicianoFlix] NFO recusado: declara entidades XML\n")
        return None
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
    remote_path = _rc_remote(nfo_path)
    try:
        result = subprocess.run(
            ["rclone", "cat", remote_path],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None
        if len(result.stdout) > MAX_NFO_BYTES:
            sys.stderr.write("[TicianoFlix] NFO ignorado (acima de %d bytes): %s\n"
                             % (MAX_NFO_BYTES, nfo_path))
            return None
        return result.stdout
    except Exception:
        return None


def _save_nfo_to_db(conn, folder_path, nfo_data):
    """Save parsed NFO metadata into movie_meta table."""
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
    remote_path = _rc_remote(nfo_path)
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
