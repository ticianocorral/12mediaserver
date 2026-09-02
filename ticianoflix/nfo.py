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
from . import localfs as _localfs
from . import sources as _sources

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

    # Colecao (movie set). O tinyMediaManager grava assim ao agrupar um
    # conjunto; o Kodi tambem le esse formato. Aceita as duas formas que
    # aparecem na pratica: <set><name>X</name></set> e o antigo <set>X</set>.
    set_name = None
    set_overview = None
    set_el = root.find("set")
    if set_el is not None:
        nome = set_el.findtext("name")
        if nome and nome.strip():
            set_name = nome.strip()
            resumo = set_el.findtext("overview")
            set_overview = resumo.strip() if resumo and resumo.strip() else None
        elif set_el.text and set_el.text.strip():
            set_name = set_el.text.strip()

    return {
        "set_name": set_name,
        "set_overview": set_overview,
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


def _local_nfo_file(folder_path):
    """Arquivo .nfo de uma pasta local.

    Prefere o nome da pasta (convencao do Kodi/tinyMediaManager) e cai para
    qualquer .nfo presente — no disco listar a pasta e barato, entao vale
    aceitar acervos gravados como "movie.nfo".
    """
    folder = _sources.local_real_path(folder_path)
    if folder is None or not folder.is_dir():
        return None
    preferred = folder / (folder.name + ".nfo")
    if preferred.is_file():
        return preferred
    try:
        for entry in sorted(folder.iterdir()):
            if entry.is_file() and entry.suffix.lower() == ".nfo":
                return entry
    except OSError:
        pass
    return None


def _fetch_nfo_raw(folder_path):
    """Texto XML do NFO de um filme, direto da fonte. Sem cache.

    Despacha por fonte: pasta local le do disco, Drive continua no rclone cat.
    """
    if _sources.is_local(folder_path):
        nfo_file = _local_nfo_file(folder_path)
        if nfo_file is None:
            return None
        raw = _localfs.read_bytes(nfo_file, MAX_NFO_BYTES)
        if raw is None:
            sys.stderr.write("[TicianoFlix] NFO ignorado (acima de %d bytes): %s\n"
                             % (MAX_NFO_BYTES, nfo_file))
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")

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


def _save_collection_to_db(conn, folder_path, nfo_data):
    """Grava (ou desfaz) a participacao de um filme numa colecao.

    Um filme pertence a no maximo um conjunto, que e como o Kodi e o
    tinyMediaManager modelam <set>. Por isso qualquer vinculo anterior deste
    filme sai antes: se voce tirou a tag <set> do NFO, ou trocou o filme de
    conjunto, o scan seguinte reflete isso em vez de acumular vinculo velho.
    """
    conn.execute("DELETE FROM movie_collections WHERE folder_path=?", (folder_path,))
    nome = (nfo_data or {}).get("set_name")
    if not nome:
        return
    resumo = nfo_data.get("set_overview")
    # Casa o nome ignorando maiusculas: NFO editado a mao com "star wars
    # collection" tem que cair na mesma colecao que "Star Wars Collection",
    # e nao virar uma segunda coleção de um filme só. O primeiro a chegar
    # define a grafia exibida.
    row = conn.execute(
        "SELECT id FROM collections WHERE name = ? COLLATE NOCASE", (nome,)).fetchone()
    if row:
        if resumo:
            conn.execute("UPDATE collections SET overview=? WHERE id=?",
                         (resumo, row["id"]))
    else:
        conn.execute("INSERT INTO collections (name, overview) VALUES (?, ?)",
                     (nome, resumo))
        row = conn.execute("SELECT id FROM collections WHERE name=?", (nome,)).fetchone()
    if row:
        conn.execute(
            "INSERT OR IGNORE INTO movie_collections (folder_path, collection_id) "
            "VALUES (?, ?)", (folder_path, row["id"]))


def _prune_empty_collections(conn):
    """Remove colecoes que ficaram sem nenhum filme.

    Acontece quando o ultimo filme do conjunto sai do acervo, ou quando a tag
    <set> e removida do NFO — sem isso a colecao vazia continuaria aparecendo.
    """
    conn.execute(
        "DELETE FROM collections WHERE id NOT IN "
        "(SELECT collection_id FROM movie_collections)")


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
    """Metadados do NFO, do banco quando ja indexado, da fonte quando nao."""
    # Try DB cache first
    from_db = _fetch_nfo_from_db(folder_path)
    if from_db:
        return from_db

    # Fallback: le da fonte (disco ou Drive) e memoriza pra proxima
    raw = _fetch_nfo_raw(folder_path)
    if not raw:
        return None
    parsed = _parse_nfo(raw)
    if parsed:
        conn = get_db()
        try:
            _save_nfo_to_db(conn, folder_path, parsed)
            conn.commit()
        finally:
            conn.close()
    return parsed
