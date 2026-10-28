"""Consultas ao cache SQLite que servem o frontend."""

import json
import os
import re
import time
from pathlib import Path

from .config import (
    IMAGE_EXTENSIONS, SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS,
)
from .db import get_db, like_prefix
from .nfo import _fetch_nfo

def _assistidos_alvo(conn):
    """Conjunto de alvos com linha "assistida" (position_seconds <= 0).

    Uma consulta so para a listagem inteira: a tabela e pequena (uma linha
    por progresso) e as listagens renderizam dezenas de cards — consultas
    por card sumiriam com a folga de resposta. O alvo e folder_path, que
    para filme guardo a pasta do filme e para episodio o path do ARQUIVO.
    """
    return {r["folder_path"] for r in conn.execute(
        "SELECT folder_path FROM watch_progress "
        "WHERE position_seconds <= 0").fetchall()}


def cached_list_directory(path, so_infantil=False):
    """List directory contents from cache.

    Vídeos soltos (na raiz da fonte ou dentro de um gênero) ficam de fora da
    listagem: eles aparecem como filme de primeira classe no A-Z, e mostrá-los
    aqui também virava uma fileira de arquivos esculhambada entre os gêneros.

    Com `so_infantil`, nada fora do marcado aparece: pasta entra quando ela
    está marcada, vive abaixo de uma marcada (temporada dentro da série) ou
    leva a algo marcado (o caminho até o filme fica navegável — sem isso a
    árvore vira o índice do acervo inteiro) e arquivo entra quando ele ou
    qualquer pasta acima está marcada — a mesma regra que /api/stream aplica
    na hora de tocar (ver _filtro_infantil_sql / handler._permitido_infantil).
    O caminho pedido NÃO é validado: pedir pasta não-marcada devolve listas
    vazias, e não um 404 — que denunciaria a existência dela.
    """
    conn = get_db()

    # Os filtros são SQL fixo (nada de input interpolado). O prefixo via
    # substr/length evita o LIKE, que trataria "_" e "%" de nomes reais como
    # curinga.
    filtro_folder = ""
    filtro_file = ""
    if so_infantil:
        # As três cláusulas vão num EXISTS só (OR): pasta marcada, pasta
        # DENTRO de uma marcada (temporada da série) ou pasta ACIMA de algo
        # marcado (o caminho até o alvo continua navegável).
        filtro_folder = (
            " AND EXISTS (SELECT 1 FROM infantil_filmes ii"
            "            WHERE ii.alvo = f.path"
            "               OR (substr(f.path, 1, length(ii.alvo)) = ii.alvo"
            "                   AND substr(f.path, length(ii.alvo) + 1, 1) = '/')"
            "               OR (substr(ii.alvo, 1, length(f.path)) = f.path"
            "                   AND substr(ii.alvo, length(f.path) + 1, 1) = '/'))")
        filtro_file = _filtro_infantil_sql(
            so_infantil, "fi.folder_path || '/' || fi.name")

    # Get folders
    folder_rows = conn.execute(
        f"SELECT * FROM folders f WHERE f.parent=?{filtro_folder} ORDER BY f.name",
        (path,)
    ).fetchall()

    aqui = conn.execute(
        "SELECT has_video FROM folders WHERE path=?", (path,)).fetchone()
    pasta_de_filme = bool(aqui) and bool(aqui["has_video"])

    if pasta_de_filme:
        file_rows = conn.execute(
            f"SELECT * FROM files fi WHERE fi.folder_path=?{filtro_file} "
            "ORDER BY fi.name",
            (path,)
        ).fetchall()
    else:
        # Raiz ou gênero: sem vídeos na listagem; legenda/imagem ficam.
        file_rows = conn.execute(
            f"SELECT * FROM files fi WHERE fi.folder_path=? AND fi.file_type != 'video'"
            f"{filtro_file} ORDER BY fi.name",
            (path,)
        ).fetchall()

    # Pôsteres em lote: antes um _find_poster_cached por vídeo abria uma
    # conexão SQLite (e os PRAGMAs de WAL) por linha da listagem.
    posters = _posters_de_pastas(
        conn, [r["folder_path"] for r in file_rows if r["file_type"] == "video"])
    assistidos = _assistidos_alvo(conn)
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
            # Selo do card: linha de progresso encerrada (posicao <= 0) — o
            # mesmo estado que o switch da ficha mostra.
            "watched": row["path"] in assistidos,
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
            # Episodio solto: o progresso dele fica na key do ARQUIVO.
            entry["watched"] = (
                row["folder_path"] + "/" + row["name"]) in assistidos
            poster = posters.get(row["folder_path"])
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

    conn = get_db()
    try:
        result["infantil"] = _e_infantil(conn, folder_path)
        # Tags do app a que o filme pertence — a ficha mostra a contagem no
        # botao e abre o modal ja com elas marcadas.
        result["tags"] = [
            {"id": r["id"], "nome": r["nome"]}
            for r in conn.execute(
                """SELECT g.id, g.nome FROM generos_filmes gf
                   JOIN generos_app g ON g.id = gf.genero_id
                   WHERE gf.alvo = ? ORDER BY g.nome COLLATE NOCASE""",
                (folder_path,)).fetchall()
        ]
        # Assistido = linha de progresso zerada (marcar grava posicao 0, e
        # assistir ate o fim tambem zera). Sem linha = nunca visto; positivo =
        # em andamento. Assim o interruptor da ficha nasce no estado certo.
        prog = conn.execute(
            "SELECT position_seconds FROM watch_progress WHERE folder_path=?",
            (folder_path,)).fetchone()
        result["watched"] = bool(prog) and prog["position_seconds"] <= 0
    finally:
        conn.close()

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
    try:
        row = conn.execute(
            "SELECT * FROM files WHERE folder_path=? AND name=?",
            (folder_path, filename)
        ).fetchone()
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
            poster = _find_poster_cached(folder_path, conn)
            if poster:
                result["poster"] = poster
    finally:
        conn.close()

    return result


def cached_search_files(query, so_infantil=False):
    """Search video files from cache (only videos, no poster/fanart dupes).

    No perfil infantil, só aparecem vídeos de filmes marcados como infantis
    (pasta marcada, ou o próprio arquivo solto marcado).
    """
    conn = get_db()
    like = f"%{query}%"
    # fi. qualificado: sem isso o "name" da cláusula fica ambíguo entre
    # files e folders e a busca da sessão infantil quebrava (500).
    filtro_inf = _filtro_infantil_sql(
        so_infantil, "fi.folder_path || '/' || fi.name")
    rows = conn.execute(
        f"""SELECT fi.*, fo.tipo AS folder_tipo FROM files fi
           JOIN folders fo ON fo.path = fi.folder_path
           WHERE fi.name LIKE ?
           AND fi.file_type = 'video'{filtro_inf}
           ORDER BY fi.size DESC
           LIMIT 100""",
        (like,)
    ).fetchall()
    posters = _posters_de_pastas(conn, [r["folder_path"] for r in rows])
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
            # Episódio de série não tem ficha: o resultado busca tocar direto.
            "is_file": row["folder_tipo"] != "filme",
        }
        poster = posters.get(row["folder_path"])
        if poster:
            entry["poster"] = poster
        results.append(entry)
    return results


def _titulo_de_arquivo(nome):
    """"O.Filme.2023.1080p.mkv" -> "O Filme 2023 1080p" — título legível pro
    catálogo a partir do nome do arquivo solto."""
    base = nome.rsplit(".", 1)[0]
    for sep in (".", "_"):
        base = base.replace(sep, " ")
    return base.strip()


def _poster_de_solto(conn, folder_path, stem):
    """Pôster para um filme solto: imagem na mesma pasta cujo nome casa com o
    do vídeo ("Alien (1979).jpg", "Alien (1979)-poster.jpg"). Sem match, nada —
    o card mostra o placeholder."""
    row = conn.execute(
        """SELECT folder_path || '/' || name AS arquivo FROM files
           WHERE folder_path = ? AND file_type IN ('poster','image','fanart')
             AND (name = ? OR name LIKE ? ESCAPE '\\')
           ORDER BY CASE WHEN name LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END,
                    LENGTH(name) ASC
           LIMIT 1""",
        (folder_path, stem + ".jpg", stem + "-%.jpg", stem + "%.jpg")).fetchone()
    return row["arquivo"] if row else None


def _e_infantil(conn, alvo):
    """True quando o filme (pasta) ou o arquivo solto está marcado para o
    perfil infantil."""
    return bool(conn.execute(
        "SELECT 1 FROM infantil_filmes WHERE alvo=?", (alvo,)).fetchone())


def _alvos_infantis(conn, alvos):
    """Subconjunto de `alvos` marcado para o perfil infantil, numa consulta só."""
    saida = set()
    alvos = sorted({a for a in alvos if a})
    for i in range(0, len(alvos), 400):
        lote = alvos[i:i + 400]
        marca = ",".join("?" * len(lote))
        for row in conn.execute(
                f"SELECT alvo FROM infantil_filmes WHERE alvo IN ({marca})", lote):
            saida.add(row["alvo"])
    return saida


def _filtro_infantil_sql(so_infantil, expressao_alvo):
    """Cláusula SQL para restringir listagens ao perfil infantil.

    Vale o alvo em si ou qualquer pasta acima dele — a mesma regra que o
    streaming aplica (ver handler._permitido_infantil): arquivo solto marcado
    direto, filme (pasta marcada) e episódio de série (a série marcada, acima
    da temporada). O prefixo é comparado com substr/length para "_" e "%" de
    nomes reais não virarem curinga."""
    if not so_infantil:
        return ""
    return (f" AND EXISTS (SELECT 1 FROM infantil_filmes ii"
            f" WHERE ii.alvo = {expressao_alvo}"
            f"    OR substr({expressao_alvo}, 1, length(ii.alvo)) = ii.alvo"
            f"       AND substr({expressao_alvo}, length(ii.alvo) + 1, 1) = '/')")


def cached_all_movies(so_infantil=False):
    """Return all movie folders sorted A-Z, with poster and title.

    Filmes soltos (arquivo de vídeo direto na raiz da fonte ou dentro de um
    gênero, sem pasta própria) entram como filme de primeira classe: título
    vem do nome do arquivo, pôster de uma imagem de mesmo nome na pasta. Eles
    moram aqui e só aqui — as listagens de pasta não os mostram.

    Com `so_infantil`, só entram os filmes marcados para o perfil infantil.
    """
    conn = get_db()
    filtro_filme = _filtro_infantil_sql(so_infantil, "f.path")
    filtro_solto = _filtro_infantil_sql(
        so_infantil, "fo.path || '/' || fi.name")
    rows = conn.execute(
        f"""SELECT f.*, m.title FROM folders f
           LEFT JOIN movie_meta m ON m.folder_path = f.path
           WHERE f.has_video = 1 AND f.tipo = 'filme'{filtro_filme}
           ORDER BY m.title COLLATE NOCASE ASC, f.name COLLATE NOCASE ASC"""
    ).fetchall()
    soltos = conn.execute(
        f"""SELECT fi.folder_path, fi.name FROM files fi
           JOIN folders fo ON fo.path = fi.folder_path
           WHERE fi.file_type = 'video' AND fo.has_video = 0{filtro_solto}
           ORDER BY fi.name COLLATE NOCASE ASC"""
    ).fetchall()
    # Pôsteres: uma consulta por lote para as pastas e a MESMA conexão para
    # os soltos — antes cada linha abria a própria conexão.
    posters = _posters_de_pastas(conn, [r["path"] for r in rows])
    posters_soltos = [
        _poster_de_solto(conn, r["folder_path"], r["name"].rsplit(".", 1)[0])
        for r in soltos
    ]
    assistidos = _assistidos_alvo(conn)
    conn.close()

    results = []
    for row in rows:
        folder_path = row["path"]
        results.append({
            "path": folder_path,
            "name": row["name"],
            "title": row["title"] or row["name"],
            "is_serie": row["tipo"] == "serie",
            "poster": posters.get(folder_path),
            "watched": folder_path in assistidos,
        })
    for row, poster in zip(soltos, posters_soltos):
        results.append({
            "path": row["folder_path"] + "/" + row["name"],
            "name": row["name"],
            "title": _titulo_de_arquivo(row["name"]),
            "poster": poster,
            "is_file": True,
            "watched": (row["folder_path"] + "/" + row["name"]) in assistidos,
        })
    results.sort(key=lambda m: (m.get("title") or m.get("name") or "").lower())

    return results


def cached_movie_count(so_infantil=False):
    """Quantos filmes a página A-Z vai listar.

    Contar só "folders has_video=1" somava séries e temporadas junto — a home
    mostrava mais filmes do que a própria lista de Filmes. A definição aqui é
    a mesma de cached_all_movies: pastas de filme + arquivos soltos.
    """
    conn = get_db()
    try:
        filtro_filme = _filtro_infantil_sql(so_infantil, "f.path")
        filtro_solto = _filtro_infantil_sql(
            so_infantil, "fo.path || '/' || fi.name")
        total = conn.execute(
            f"SELECT COUNT(*) c FROM folders f "
            f"WHERE f.has_video = 1 AND f.tipo = 'filme'{filtro_filme}"
        ).fetchone()["c"]
        total += conn.execute(
            f"""SELECT COUNT(*) c FROM files fi
                JOIN folders fo ON fo.path = fi.folder_path
                WHERE fi.file_type = 'video' AND fo.has_video = 0{filtro_solto}"""
        ).fetchone()["c"]
    finally:
        conn.close()
    return total


def cached_series_count(so_infantil=False):
    """Quantas séries a página de Séries vai listar (mesmo filtro de lá)."""
    conn = get_db()
    try:
        filtro_inf = _filtro_infantil_sql(so_infantil, "f.path")
        total = conn.execute(
            f"SELECT COUNT(*) c FROM folders f "
            f"WHERE f.tipo = 'serie' AND f.has_video = 1{filtro_inf}"
        ).fetchone()["c"]
    finally:
        conn.close()
    return total


def _colecao_capa(conn, colecao_id):
    """Capa da coleção: o pôster do filme escolhido no cadastro.

    A capa é gravada como folder_path do filme (colecoes.capa). Se esse filme
    saiu do acervo ou ficou sem pôster, cai para o cartaz do filme mais antigo
    ainda na coleção — o mesmo fallback que a tela sempre usou, para nenhuma
    coleção ficar com ícone genérico. Devolve (caminho_servivel, usa_fanart).
    """
    row = conn.execute(
        """SELECT c.capa FROM colecoes c WHERE c.id=?""", (colecao_id,)).fetchone()
    capa = row["capa"] if row else ""
    if capa:
        tem = conn.execute(
            """SELECT fi.folder_path || '/' || fi.name AS arquivo
               FROM files fi WHERE fi.folder_path=? AND fi.file_type='poster'
               LIMIT 1""", (capa,)).fetchone()
        if tem:
            return tem["arquivo"]
    fallback = conn.execute(
        """SELECT fi.folder_path || '/' || fi.name AS arquivo
           FROM colecoes_filmes cf
           JOIN folders f ON f.path = cf.folder_path
           LEFT JOIN movie_meta m ON m.folder_path = f.path
           JOIN files fi ON fi.folder_path = f.path AND fi.file_type = 'poster'
           WHERE cf.colecao_id = ?
           ORDER BY CASE WHEN m.year IS NULL OR m.year = '' THEN 1 ELSE 0 END,
                    CAST(m.year AS INTEGER) ASC, f.name COLLATE NOCASE ASC
           LIMIT 1""", (colecao_id,)).fetchone()
    return fallback["arquivo"] if fallback else None


def _colecao_fanart(conn, colecao_id):
    """Fanart para o fundo do cabeçalho: a do filme da capa, se existir."""
    row = conn.execute(
        """SELECT c.capa FROM colecoes c WHERE c.id=?""", (colecao_id,)).fetchone()
    capa = row["capa"] if row else ""
    if not capa:
        return None
    row = conn.execute(
        """SELECT folder_path || '/' || name AS arquivo FROM files
           WHERE folder_path=? AND file_type='fanart' LIMIT 1""", (capa,)).fetchone()
    return row["arquivo"] if row else None


def cached_collection_movies(key, so_infantil=False):
    """Os filmes de uma coleção, na ordem dos anos.

    `key` aceita id ("12" — o que a interface usa desde que coleções viraram
    coisas do app) ou nome (links antigos e histórico de navegação que ainda
    guardam o nome da coleção importada do NFO).
    """
    conn = get_db()
    try:
        if str(key).isdigit():
            col = conn.execute(
                "SELECT id, nome, descricao, capa FROM colecoes WHERE id=?",
                (int(key),)).fetchone()
        else:
            # NOCASE: o link pode vir com outra grafia.
            col = conn.execute(
                "SELECT id, nome, descricao, capa FROM colecoes "
                "WHERE nome = ? COLLATE NOCASE",
                (str(key),)).fetchone()
        if not col:
            return None
        rows = conn.execute(
            """SELECT f.path, f.name, f.tipo, m.title, m.year
               FROM colecoes_filmes cf
               JOIN folders f ON f.path = cf.folder_path
               LEFT JOIN movie_meta m ON m.folder_path = f.path
               WHERE cf.colecao_id = ?
               ORDER BY CASE WHEN m.year IS NULL OR m.year = '' THEN 1 ELSE 0 END,
                        CAST(m.year AS INTEGER) ASC,
                        f.name COLLATE NOCASE ASC""",
            (col["id"],)).fetchall()
        capa = _colecao_capa(conn, col["id"])
        fanart = _colecao_fanart(conn, col["id"])
        alvos = [r["path"] for r in rows]
        posters = _posters_de_pastas(conn, alvos)
        # O filtro infantil rodava com a conexão JÁ fechada (500 na cara do
        # perfil infantil) e uma consulta por filme; agora é uma só, antes
        # do close.
        infantis = _alvos_infantis(conn, alvos) if so_infantil else set()
        assistidos = _assistidos_alvo(conn)
    finally:
        conn.close()

    filmes = []
    for row in rows:
        if so_infantil and row["path"] not in infantis:
            continue
        filmes.append({
            "path": row["path"],
            "name": row["name"],
            "title": row["title"] or row["name"],
            "year": row["year"],
            "poster": posters.get(row["path"]),
            "is_serie": row["tipo"] == "serie",
            "watched": row["path"] in assistidos,
        })
    return {"id": col["id"], "name": col["nome"], "overview": col["descricao"],
            "capa_path": col["capa"], "movies": filmes,
            "poster": capa, "fanart": fanart}


def cached_movie_infantil(alvo):
    """True se o filme (pasta ou arquivo solto) está marcado como infantil."""
    conn = get_db()
    try:
        return _e_infantil(conn, alvo)
    finally:
        conn.close()


def cached_algum_infantil(alvos):
    """True se qualquer um dos alvos está marcado como infantil.

    Usado pelo streaming: o alvo é o arquivo pedido + todas as pastas acima
    dele — assim arquivo solto (marcado direto), filme (pasta própria) e
    episódio de série (pasta da série marcada, acima da temporada) valem.
    Uma consulta só, com os alvos em lote."""
    alvos = sorted({a for a in alvos if a})
    if not alvos:
        return False
    conn = get_db()
    try:
        marca = ",".join("?" * len(alvos))
        return bool(conn.execute(
            f"SELECT 1 FROM infantil_filmes WHERE alvo IN ({marca}) LIMIT 1",
            alvos).fetchone())
    finally:
        conn.close()


def cached_collection_of(folder_path):
    """A coleção a que um filme pertence, ou None. So o cabeçalho — sem a
    lista de filmes, que a ficha do filme não precisa carregar.

    Um filme pode estar em várias coleções agora; a ficha mostra a primeira
    (ordem alfabética) para não virar uma fileira de botões.
    """
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT c.id, c.nome, c.descricao, COUNT(cf2.folder_path) AS total
               FROM colecoes_filmes cf
               JOIN colecoes c ON c.id = cf.colecao_id
               JOIN colecoes_filmes cf2 ON cf2.colecao_id = c.id
               WHERE cf.folder_path = ?
               GROUP BY c.id
               ORDER BY c.nome COLLATE NOCASE ASC
               LIMIT 1""",
            (folder_path,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"id": row["id"], "name": row["nome"],
            "overview": row["descricao"], "total": row["total"]}


def cached_all_collections(so_infantil=False):
    """Todas as coleções do acervo, com quantos filmes cada uma tem.

    Criadas e editadas no próprio app (colecoes) — nada de NFO. O JOIN com
    folders deixa de contar filme que saiu do acervo: o vínculo é podado pelo
    scanner, mas entre um scan e outro a contagem fica honesta.

    Com `so_infantil`, coleção sem nenhum filme marcado nem aparece, o total
    conta só os marcados e capa de filme não-marcado vira placeholder — o
    perfil não deve ver nem os nomes de quem está fora dele.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT c.id, c.nome, c.descricao,
                      COUNT(DISTINCT f.path) AS total
               FROM colecoes c
               LEFT JOIN colecoes_filmes cf ON cf.colecao_id = c.id
               LEFT JOIN folders f ON f.path = cf.folder_path
               GROUP BY c.id
               ORDER BY c.nome COLLATE NOCASE ASC""").fetchall()
        saida = []
        for r in rows:
            capa = _colecao_capa(conn, r["id"])
            total = r["total"]
            if so_infantil:
                total = conn.execute(
                    """SELECT COUNT(DISTINCT f.path) AS c FROM colecoes_filmes cf
                       JOIN folders f ON f.path = cf.folder_path
                       WHERE cf.colecao_id = ?
                         AND EXISTS (SELECT 1 FROM infantil_filmes ii
                                     WHERE ii.alvo = f.path)""",
                    (r["id"],)).fetchone()["c"]
                if total == 0:
                    continue
                # A capa é um arquivo (".../pasta/foto.jpg"); quem precisa
                # estar marcado é a pasta do filme, não o arquivo.
                if capa and not _e_infantil(conn, capa.rsplit("/", 1)[0]):
                    capa = None
            saida.append({"id": r["id"], "name": r["nome"],
                          "overview": r["descricao"],
                          "total": total, "poster": capa})
    finally:
        conn.close()
    return saida


def cached_source_counts(mount):
    """Quantos filmes o catalogo tem sob um ponto de montagem.

    Genero por pasta deixou de existir — a organização agora vive nos gêneros
    do app, então só o número de filmes importa aqui. A contagem usa a mesma
    definição da página A-Z: pastas de filme + arquivos soltos. Contar só
    "has_video=1" somava séries e temporadas junto e esquecia os soltos.
    """
    like = like_prefix(mount)
    conn = get_db()
    try:
        genres = 0
        movies = conn.execute(
            "SELECT COUNT(*) AS c FROM folders "
            "WHERE has_video=1 AND tipo='filme' AND depth>0 "
            "AND path LIKE ? ESCAPE '\\'",
            (like,)).fetchone()["c"]
        movies += conn.execute(
            "SELECT COUNT(*) AS c FROM files fi "
            "JOIN folders fo ON fo.path = fi.folder_path "
            "WHERE fi.file_type='video' AND fo.has_video=0 "
            "AND (fo.path = ? OR fo.path LIKE ? ESCAPE '\\')",
            (mount, like)).fetchone()["c"]
    finally:
        conn.close()
    return {"genres": genres, "movies": movies}


def _find_poster_cached(folder_path, conn=None):
    """Find poster name from cache for a given folder.

    Com `conn`, reaproveita uma conexão já aberta; sem ela, abre e fecha a
    própria (chamadas avulsas). Dentro de laço prefira `_posters_de_pastas`,
    que resolve a lista inteira numa consulta só.
    """
    fechar = conn is None
    if conn is None:
        conn = get_db()
    try:
        row = conn.execute(
            "SELECT name FROM files WHERE folder_path=? AND file_type='poster' LIMIT 1",
            (folder_path,)
        ).fetchone()
    finally:
        if fechar:
            conn.close()
    return row["name"] if row else None


def _posters_de_pastas(conn, pastas):
    """Nome do pôster por pasta, numa consulta só.

    Cada _find_poster_cached abria a própria conexão; dentro dos laços das
    listagens isso virava N+1 (uma conexão — e os PRAGMAs de WAL — por
    filme). A consulta sai fatiada em lotes de 400: o SQLite tem teto de
    999 variáveis por statement. `ORDER BY id` + setdefault preservam a
    escolha do LIMIT 1 antigo (o primeiro pôster gravado na pasta).
    """
    saida = {}
    pastas = sorted({p for p in pastas if p})
    for i in range(0, len(pastas), 400):
        lote = pastas[i:i + 400]
        marca = ",".join("?" * len(lote))
        for row in conn.execute(
                f"SELECT folder_path, name FROM files "
                f"WHERE file_type='poster' AND folder_path IN ({marca}) "
                f"ORDER BY id", lote):
            saida.setdefault(row["folder_path"], row["name"])
    return saida


# ── Gêneros do app ───────────────────────────────────────────

def cached_generos(so_infantil=False):
    """Gêneros criados na interface, com quantos filmes cada um tem.

    Com `so_infantil` (sessão de perfil infantil), a contagem só considera os
    filmes marcados como infantis — gênero sem filme infantil nem aparece.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, nome FROM generos_app ORDER BY nome COLLATE NOCASE"
        ).fetchall()
        filtro_alvo = "gf.alvo"
        if so_infantil:
            filtro_alvo = "gf.alvo"
            filtro_inf = (" AND EXISTS (SELECT 1 FROM infantil_filmes ii "
                          "WHERE ii.alvo = gf.alvo)")
        else:
            filtro_inf = ""
        saida = []
        for r in rows:
            total = conn.execute(
                f"""SELECT COUNT(*) AS c FROM generos_filmes gf
                   WHERE gf.genero_id = ?{filtro_inf}
                     AND (EXISTS (SELECT 1 FROM folders f WHERE f.path = {filtro_alvo}
                                  AND f.has_video = 1)
                          OR EXISTS (SELECT 1 FROM files fi
                                     WHERE fi.folder_path || '/' || fi.name = {filtro_alvo}
                                     AND fi.file_type = 'video'))""",
                (r["id"],)).fetchone()["c"]
            if so_infantil and total == 0:
                continue
            saida.append({"id": r["id"], "nome": r["nome"], "total": total})
    finally:
        conn.close()
    return saida


def cached_generos_de(alvo):
    """Ids dos gêneros do app a que um filme pertence."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT genero_id FROM generos_filmes WHERE alvo=?", (alvo,)).fetchall()
    finally:
        conn.close()
    return [r["genero_id"] for r in rows]


def _entrada_de_filme(conn, alvo):
    """alvo -> card de filme (pasta ou arquivo solto), ou None se sumiu."""
    visto = bool(conn.execute(
        "SELECT 1 FROM watch_progress "
        "WHERE folder_path=? AND position_seconds <= 0 LIMIT 1",
        (alvo,)).fetchone())
    pasta = conn.execute(
        """SELECT f.path, f.name, m.title, m.year FROM folders f
           LEFT JOIN movie_meta m ON m.folder_path = f.path
           WHERE f.path = ? AND f.has_video = 1""",
        (alvo,)).fetchone()
    if pasta:
        return {"path": pasta["path"], "name": pasta["name"],
                "title": pasta["title"] or pasta["name"], "year": pasta["year"],
                "poster": _find_poster_cached(alvo, conn), "is_file": False,
                "infantil": _e_infantil(conn, alvo), "watched": visto}
    solto = conn.execute(
        """SELECT fi.folder_path, fi.name FROM files fi
           WHERE fi.folder_path || '/' || fi.name = ? AND fi.file_type = 'video'""",
        (alvo,)).fetchone()
    if solto:
        stem = solto["name"].rsplit(".", 1)[0]
        return {"path": solto["folder_path"] + "/" + solto["name"],
                "name": solto["name"],
                "title": _titulo_de_arquivo(solto["name"]), "year": None,
                "poster": _poster_de_solto(conn, solto["folder_path"], stem),
                "is_file": True, "infantil": _e_infantil(conn, alvo),
                "watched": visto}
    return None


def cached_genero_filmes(genero_id, so_infantil=False):
    """Os filmes de um gênero do app, em ordem alfabética de título."""
    conn = get_db()
    try:
        gen = conn.execute(
            "SELECT id, nome FROM generos_app WHERE id=?", (genero_id,)).fetchone()
        if not gen:
            return None
        alvos = [r["alvo"] for r in conn.execute(
            "SELECT alvo FROM generos_filmes WHERE genero_id=?",
            (genero_id,)).fetchall()]
        filmes = [e for e in (_entrada_de_filme(conn, a) for a in alvos) if e]
        if so_infantil:
            filmes = [e for e in filmes if e["infantil"]]
    finally:
        conn.close()
    filmes.sort(key=lambda m: (m.get("title") or "").lower())
    return {"id": gen["id"], "name": gen["nome"], "movies": filmes}


# ── Séries ───────────────────────────────────────────────────

def _ordem_temporada(nome):
    """S01 < S02 < S10 — extrai o número da temporada para ordenar."""
    import re
    m = re.search(r"(\d+)", nome or "")
    return int(m.group(1)) if m else 999


def cached_series_list(so_infantil=False):
    """Todas as séries do acervo, para a listagem própria delas."""
    conn = get_db()
    try:
        filtro_inf = ""
        if so_infantil:
            filtro_inf = (" AND EXISTS (SELECT 1 FROM infantil_filmes ii "
                          "WHERE ii.alvo = f.path)")
        rows = conn.execute(
            f"""SELECT f.path, f.name,
                   (SELECT COUNT(*) FROM folders t
                    WHERE t.parent = f.path AND t.tipo = 'temporada'
                      AND t.has_video = 1) AS temporadas,
                   (SELECT COUNT(*) FROM files fi
                    JOIN folders t2 ON t2.path = fi.folder_path
                    WHERE t2.parent = f.path AND t2.tipo = 'temporada'
                      AND fi.file_type = 'video') AS episodios
               FROM folders f
               WHERE f.tipo = 'serie' AND f.has_video = 1{filtro_inf}
               ORDER BY f.name COLLATE NOCASE ASC""").fetchall()
        saida = []
        for r in rows:
            art = conn.execute(
                "SELECT folder_path || '/' || name AS arquivo FROM files "
                "WHERE folder_path=? AND file_type='poster' LIMIT 1",
                (r["path"],)).fetchone()
            meta = conn.execute(
                "SELECT title FROM movie_meta WHERE folder_path=?",
                (r["path"],)).fetchone()
            saida.append({
                "path": r["path"],
                "name": r["name"],
                "title": (meta["title"] if meta and meta["title"] else r["name"]),
                "poster": art["arquivo"] if art else None,
                "temporadas": r["temporadas"],
                "episodios": r["episodios"],
            })
    finally:
        conn.close()
    return saida


def cached_serie(serie_path, so_infantil=False):
    """Uma série com suas temporadas e episódios, para a página dela.

    Episódio = vídeo dentro de uma temporada; a legenda de mesmo nome no
    mesmo diretório já vai pronta para o player.
    """
    conn = get_db()
    try:
        serie = conn.execute(
            "SELECT * FROM folders WHERE path=? AND tipo='serie'",
            (serie_path,)).fetchone()
        if not serie:
            return None
        if so_infantil and not _e_infantil(conn, serie_path):
            return None
        meta = conn.execute(
            "SELECT title, plot, year FROM movie_meta WHERE folder_path=?",
            (serie_path,)).fetchone()

        def _art(tipo):
            row = conn.execute(
                "SELECT folder_path || '/' || name AS arquivo FROM files "
                "WHERE folder_path=? AND file_type=? LIMIT 1",
                (serie_path, tipo)).fetchone()
            return row["arquivo"] if row else None

        temporadas = []
        for temp in conn.execute(
                "SELECT path, name FROM folders "
                "WHERE parent=? AND tipo='temporada' AND has_video=1",
                (serie_path,)).fetchall():
            eps = []
            for fi in conn.execute(
                    "SELECT name, size FROM files "
                    "WHERE folder_path=? AND file_type='video' ORDER BY name",
                    (temp["path"],)).fetchall():
                stem = fi["name"].rsplit(".", 1)[0]
                ep_path = temp["path"] + "/" + fi["name"]
                leg = conn.execute(
                    "SELECT name FROM files WHERE folder_path=? AND name LIKE ? "
                    "AND file_type='subtitle' LIMIT 1",
                    (temp["path"], stem + "%")).fetchone()
                prog = conn.execute(
                    "SELECT position_seconds, duration_seconds FROM watch_progress "
                    "WHERE folder_path=?", (ep_path,)).fetchone()
                eps.append({
                    "path": ep_path,
                    "name": fi["name"],
                    "title": _titulo_de_arquivo(fi["name"]),
                    "size": fi["size"],
                    "subtitle": (temp["path"] + "/" + leg["name"]) if leg else None,
                    "position": (prog["position_seconds"] if prog else 0),
                    "duration": (prog["duration_seconds"] if prog else 0),
                    # Selo do episodio assistido: linha encerrada (pos <= 0).
                    "watched": bool(prog) and prog["position_seconds"] <= 0,
                })
            temporadas.append({"nome": temp["name"], "episodios": eps})
        temporadas.sort(key=lambda x: _ordem_temporada(x["nome"]))
        poster = _art("poster")
        fanart = _art("fanart")
        infantil = _e_infantil(conn, serie_path)
    finally:
        conn.close()

    return {
        "path": serie_path,
        "name": (meta["title"] if meta and meta["title"] else serie["name"]),
        "overview": (meta["plot"] if meta else None),
        "year": (meta["year"] if meta else None),
        "poster": poster,
        "fanart": fanart,
        "infantil": infantil,
        "temporadas": temporadas,
    }
