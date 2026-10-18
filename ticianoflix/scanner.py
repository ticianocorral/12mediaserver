"""Varredura das fontes e indexacao no SQLite.

O motor (`_index_tree`) e um so: ele recebe a arvore ja listada, no formato do
`rclone lsjson`, e a reconcilia com o banco. Quem muda e o modo de obter a
arvore — `rclone lsjson` para a nuvem, `os.scandir` para HD externo, pendrive e
pastas do computador.

O ciclo de vida do scan (claim, progresso, thread) mora aqui: antes o handler
HTTP manipulava as globais direto com `global _scan_in_progress`.
"""

import threading
import time
from pathlib import Path

from .config import (
    IMAGE_EXTENSIONS, LOCAL_ROOT, SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from .db import get_db, like_prefix as _like_prefix, log_notification, set_cache_time
from .paths import rc_remote as _rc_remote
from .nfo import _fetch_nfo_raw, _parse_nfo, _save_nfo_to_db
from .rclone import run_rclone_cmd
from . import localfs as _localfs
from . import sources as _sources
from . import branding as _branding

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
    # Coleções do app: o filme que sai do acervo sai das coleções — a coleção
    # fica (com os demais filmes), quem gerencia é a interface.
    conn.execute(
        "DELETE FROM colecoes_filmes WHERE folder_path=? OR folder_path LIKE ? ESCAPE '\\'",
        (path, like))
    # Gêneros do app: mesmo destino. O `alvo` pode ser pasta de filme ou o
    # path completo de um arquivo solto — o LIKE cobre os dois.
    conn.execute(
        "DELETE FROM generos_filmes WHERE alvo=? OR alvo LIKE ? ESCAPE '\\'",
        (path, like))
    # Perfil infantil: filme que sai do acervo sai da lista infantil.
    conn.execute(
        "DELETE FROM infantil_filmes WHERE alvo=? OR alvo LIKE ? ESCAPE '\\'",
        (path, like))


def _set_progress(**fields):
    with _scan_progress_lock:
        _scan_progress.update(fields)


# Nomes aceitos para os contêineres da raiz do acervo (case-insensitive).
CONTAINER_MOVIES = {"movies", "movie"}
CONTAINER_TV = {"tv shows", "tv"}


def _index_tree(conn, root_path, root_name, entries,
                progress_base=0.0, progress_span=1.0):
    """Reconcilia uma arvore ja listada com o banco.

    `entries` vem no formato do `rclone lsjson`: Path relativo a raiz, Name,
    Size, ModTime, IsDir, MimeType, ID.

    Estrutura do acervo, por regiao:

      movies/          vale a regra geral: filme = pasta com video direto
                       (qualquer profundidade); arquivo de video fora de
                       filme = filme solto (A-Z).
      tv shows/        Serie/ = pasta-filha direta do contêiner; Temporada/ =
                       pasta-filha da serie com videos diretos (S01, S02...);
                       episodios = os videos dentro da temporada. Arte e NFO
                       da serie ficam na pasta dela.
      fora dos dois    backward compat: vale a regra de movies/ — quem ja tem
                       acervo solto na raiz continua funcionando sem mover nada.

    Regras que valem para as duas fontes:
      - filme/serie novo ou alterado (conjunto de arquivos, tamanho ou mtime)
        e reindexado e tem o NFO relido;
      - inalterado nao gera nenhuma escrita;
      - pasta que sumiu da fonte sai do banco (e leva os vinculos de colecao,
        genero e infantil junto, veja _remove_folder_tree);
      - pasta que deixou de ser filme/serie/temporada so perde a marcacao
        has_video — os arquivos ficam (os videos continuam existindo como
        soltos).

    Toda consulta de estado e escopada por `root_path`: sem isso o scan de uma
    fonte apagaria o catalogo de outra.
    """
    stats = {"added": 0, "changed": 0, "removed": 0, "unchanged": 0}
    like_root = _like_prefix(root_path)

    conn.execute(
        "INSERT OR REPLACE INTO folders "
        "(path, name, parent, is_ticianoflix_root, depth) VALUES (?, ?, '', 1, 0)",
        (root_path, root_name)
    )

    # Build in-memory tree: dirs by full path, files grouped by parent folder.
    # Ignora pastas ocultas (.lixo, .deletedByTMM do tinyMediaManager...) e
    # qualquer subárvore com .nomedia — o lixo de renomeação não vira série
    # fantasma sem capa na listagem.
    dirs = {}
    files_by_parent = {}
    nomedia_prefixes = set()
    for e in entries:
        rel = e.get("Path", "")
        full = f"{root_path}/{rel}" if rel else root_path
        segmentos = rel.split("/") if rel else []
        if any(s.startswith(".") for s in segmentos):
            continue
        if any(full.startswith(p) for p in nomedia_prefixes):
            continue
        if e.get("IsDir"):
            dirs[full] = e
            if ".nomedia" in files_by_parent.get(full, {}):
                nomedia_prefixes.add(full + "/")
        else:
            parent = full.rsplit("/", 1)[0]
            files_by_parent.setdefault(parent, {})[e.get("Name", "")] = e

    # ── Contêineres da raiz: movies/ e tv shows/ ────────────────
    movies_dir = None
    tv_dir = None
    for path in dirs:
        if path == root_path:
            continue
        rel = path[len(root_path):].strip("/")
        if "/" in rel:
            continue  # só profundidade 1
        nome = rel.lower()
        if nome in CONTAINER_MOVIES and movies_dir is None:
            movies_dir = path
        elif nome in CONTAINER_TV and tv_dir is None:
            tv_dir = path

    def _regiao(p):
        if tv_dir and (p == tv_dir or p.startswith(tv_dir + "/")):
            return "tv"
        return "filmes"  # raiz fora de tv e movies/ — mesma regra

    # ── Deteção de séries e temporadas (região tv) ──────────────
    series_dirs = {}
    for path, e in dirs.items():
        if _regiao(path) != "tv" or path == tv_dir:
            continue
        if path.rsplit("/", 1)[0] == tv_dir:
            series_dirs[path] = e
    temporada_dirs = set()
    for sp in series_dirs:
        for path in dirs:
            if path == sp or path.rsplit("/", 1)[0] != sp:
                continue
            tem_video = any(Path(n).suffix.lower() in VIDEO_EXTENSIONS
                            for n in files_by_parent.get(path, {}))
            if tem_video:
                temporada_dirs.add(path)

    # ── Deteção de filmes (fora da região tv; de baixo pra cima) ──
    # Pasta com video direto = filme; a menos que um descendente dela ja seja
    # — nesses casos os videos da ancestral viram soltos, nao "o filme pai".
    movie_dirs = set()
    for path in sorted(dirs, key=lambda p: p.count("/"), reverse=True):
        if path == root_path or _regiao(path) == "tv":
            continue
        tem_video = any(Path(n).suffix.lower() in VIDEO_EXTENSIONS
                        for n in files_by_parent.get(path, {}))
        if not tem_video:
            continue
        if any(m.startswith(path + "/") for m in movie_dirs):
            continue
        movie_dirs.add(path)

    # ── Estado atual no banco ───────────────────────────────────
    db_movies = {r["path"]: r for r in conn.execute(
        "SELECT path, name, mod_time, has_video FROM folders "
        "WHERE has_video=1 AND tipo='filme' "
        "AND path LIKE ? ESCAPE '\\'", (like_root,)).fetchall()}
    db_series = {r["path"]: r for r in conn.execute(
        "SELECT path, name, mod_time, has_video FROM folders "
        "WHERE tipo='serie' AND path LIKE ? ESCAPE '\\'", (like_root,)).fetchall()}
    db_temporadas = {r["path"] for r in conn.execute(
        "SELECT path FROM folders "
        "WHERE tipo='temporada' AND path LIKE ? ESCAPE '\\'", (like_root,)).fetchall()}
    db_dirs = {r["path"]: r for r in conn.execute(
        "SELECT path, has_video FROM folders WHERE path LIKE ? ESCAPE '\\'",
        (like_root,)).fetchall()}
    db_files = {}
    for r in conn.execute(
            "SELECT folder_path, name, size, mod_time FROM files "
            "WHERE folder_path=? OR folder_path LIKE ? ESCAPE '\\'",
            (root_path, like_root)).fetchall():
        db_files[(r["folder_path"], r["name"])] = r

    # ── Pastas que sumiram da fonte ─────────────────────────────
    removed_prefixes = []
    for p in set(db_dirs) - set(dirs) - {root_path}:
        _remove_folder_tree(conn, p)
        removed_prefixes.append(p)
        stats["removed"] += 1

    # ── Pastas que deixaram de ser filme/serie/temporada ────────
    # A pasta existe, mas hoje nao tem mais esse papel (um descendente virou
    # filme, os episodios acabaram...). So perde a marcacao: os arquivos
    # continuam valendo como soltos.
    for p in set(db_movies) - movie_dirs:
        if p in dirs:
            conn.execute("UPDATE folders SET has_video=0 WHERE path=?", (p,))
    for p in set(db_series) - set(series_dirs):
        if p in dirs:
            conn.execute("UPDATE folders SET has_video=0 WHERE path=?", (p,))
    for p in db_temporadas - temporada_dirs:
        if p in dirs:
            conn.execute("UPDATE folders SET has_video=0 WHERE path=?", (p,))

    # ── Arquivos de todas as pastas (filmes e nao-filmes) ───────
    # Filmes soltos e episodios dependem disso: ambos moram na tabela files.
    # Filme/serie com conteudo alterado tem os proprios arquivos regravados
    # mais abaixo; os demais so sobem com INSERT OR REPLACE.
    live_everywhere = {}
    for parent, arquivos in files_by_parent.items():
        for name, fe in arquivos.items():
            _index_file(conn, parent, fe)
            live_everywhere[(parent, name)] = fe
    for chave in db_files:
        if chave not in live_everywhere:
            fp, name = chave
            conn.execute("DELETE FROM files WHERE folder_path=? AND name=?", chave)
            # Arquivo solto que sumiu leva os vinculos de genero junto.
            conn.execute("DELETE FROM generos_filmes WHERE alvo=?",
                         (fp + "/" + name,))
            conn.execute("DELETE FROM infantil_filmes WHERE alvo=?",
                         (fp + "/" + name,))

    # ── Upsert de filmes e séries ───────────────────────────────
    total_unidades = len(movie_dirs) + len(series_dirs)
    _set_progress(phase="genres", genre_total=total_unidades)

    def _upsert_conteudo(path, entry, parent, tipo, prev):
        """Insere/atualiza um filme ou série. Devolve (novo, alterado)."""
        nome = entry.get("Name", "")
        depth = path.count("/") - root_path.count("/")
        novo = prev is None
        alterado = novo
        live = files_by_parent.get(path, {})
        if not alterado:
            db_keys = {name for (fp, name) in db_files if fp == path}
            live_keys = set(live)
            if db_keys != live_keys:
                alterado = True
            else:
                for name in live:
                    fe = live[name]
                    dr = db_files[(path, name)]
                    if fe.get("Size", 0) != dr["size"] or fe.get("ModTime", "") != dr["mod_time"]:
                        alterado = True
                        break
        if prev is not None and not alterado:
            conn.execute("UPDATE folders SET mod_time=? WHERE path=?",
                         (entry.get("ModTime", ""), path))
            return False, False

        with _scan_progress_lock:
            _scan_progress["movie_index"] += 1
            _scan_progress["movie_current"] = nome

        conn.execute(
            """INSERT INTO folders (path, name, parent, depth, mod_time,
                                    has_video, tipo)
               VALUES (?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(path) DO UPDATE SET
                 name=excluded.name, parent=excluded.parent,
                 depth=excluded.depth, mod_time=excluded.mod_time,
                 has_video=1, tipo=excluded.tipo""",
            (path, nome, parent, depth, entry.get("ModTime", ""), tipo)
        )
        conn.execute("DELETE FROM files WHERE folder_path=?", (path,))
        for name, fe in live.items():
            _index_file(conn, path, fe)

        # NFO only for new/changed movies AND only if the folder really
        # has one (avoids a slow fetch on a missing file)
        if any(n.lower().endswith(".nfo") for n in live):
            nfo_raw = _fetch_nfo_raw(path)
            if nfo_raw:
                nfo_data = _parse_nfo(nfo_raw)
                if nfo_data:
                    _save_nfo_to_db(conn, path, nfo_data)
        return novo, alterado

    gi = 0
    for movie_path in sorted(movie_dirs):
        entry = dirs[movie_path]
        parent = movie_path.rsplit("/", 1)[0]
        frac = (gi / total_unidades) if total_unidades else 1.0
        _set_progress(genre_index=gi + 1, genre_current=entry.get("Name", ""),
                      percent=int((progress_base + frac * progress_span) * 100))
        novo, alterado = _upsert_conteudo(movie_path, entry, parent, "filme",
                                          db_movies.get(movie_path))
        if novo:
            stats["added"] += 1
        elif alterado:
            stats["changed"] += 1
        else:
            stats["unchanged"] += 1
        gi += 1

    for serie_path in sorted(series_dirs):
        entry = series_dirs[serie_path]
        frac = (gi / total_unidades) if total_unidades else 1.0
        _set_progress(genre_index=gi + 1, genre_current=entry.get("Name", ""),
                      percent=int((progress_base + frac * progress_span) * 100))
        novo, alterado = _upsert_conteudo(serie_path, entry, tv_dir, "serie",
                                          db_series.get(serie_path))
        if novo:
            stats["added"] += 1
        elif alterado:
            stats["changed"] += 1
        else:
            stats["unchanged"] += 1
        gi += 1

    # ── Upsert das temporadas (só a marca; episódios já indexados) ──
    for temp_path in temporada_dirs:
        nome = dirs[temp_path].get("Name", "")
        parent = temp_path.rsplit("/", 1)[0]
        depth = temp_path.count("/") - root_path.count("/")
        conn.execute(
            """INSERT INTO folders (path, name, parent, depth, mod_time,
                                    has_video, tipo)
               VALUES (?, ?, ?, ?, ?, 1, 'temporada')
               ON CONFLICT(path) DO UPDATE SET
                 name=excluded.name, parent=excluded.parent,
                 depth=excluded.depth, mod_time=excluded.mod_time,
                 has_video=1, tipo='temporada'""",
            (temp_path, nome, parent, depth,
             dirs[temp_path].get("ModTime", ""))
        )

    return stats
def _realinhar_progresso(conn):
    """Reata progressos órfãos em movies/series que mudaram de lugar no disco.

    Mover um filme (ex.: para dentro de movies/) muda o path dele: a linha de
    watch_progress do path antigo fica órfã e o filme recomeçaria do zero.
    Depois da reconciliação, cada progresso órfão procura um filme vivo com o
    MESMO nome de pasta (ou o mesmo nome de arquivo, para soltos/episódios);
    achando exatamente um candidato, o progresso é realinhado. Ambíguo ou sem
    candidato, fica órfão — invisível, sem risco de achar o filme errado.
    """
    orfaos = conn.execute(
        "SELECT folder_path, position_seconds, duration_seconds, updated_at "
        "FROM watch_progress").fetchall()
    realinhados = 0
    for row in orfaos:
        velho = row["folder_path"]
        vivo_pasta = conn.execute(
            "SELECT 1 FROM folders WHERE path=? AND has_video=1", (velho,)).fetchone()
        vivo_arquivo = conn.execute(
            """SELECT 1 FROM files WHERE folder_path || '/' || name = ?
               AND file_type = 'video'""", (velho,)).fetchone()
        if vivo_pasta or vivo_arquivo:
            continue  # o path ainda existe — nada a fazer

        nome = velho.rstrip("/").rsplit("/", 1)[-1]
        candidatos = [r["path"] for r in conn.execute(
            "SELECT path FROM folders WHERE name=? AND has_video=1 AND depth>0",
            (nome,)).fetchall()]
        if len(candidatos) == 1:
            conn.execute(
                "UPDATE watch_progress SET folder_path=? WHERE folder_path=?",
                (candidatos[0], velho))
            realinhados += 1
            continue
        # Soltos/episódios: procura o mesmo nome de arquivo em outra pasta.
        cand_arq = [r["folder_path"] + "/" + r["name"] for r in conn.execute(
            "SELECT folder_path, name FROM files WHERE name=? AND file_type='video'",
            (nome,)).fetchall() if r["folder_path"] + "/" + r["name"] != velho]
        if len(cand_arq) == 1:
            conn.execute(
                "UPDATE watch_progress SET folder_path=? WHERE folder_path=?",
                (cand_arq[0], velho))
            realinhados += 1
    if realinhados:
        conn.commit()
        print(f"[TicianoFlix] {realinhados} progresso(s) realinhado(s) após "
              "mudanças no acervo.", flush=True)
    return realinhados


def _report(label, root_path, stats, elapsed, conn):
    like_root = _like_prefix(root_path)
    movies = conn.execute(
        "SELECT COUNT(*) as c FROM folders "
        "WHERE has_video=1 AND depth>0 AND path LIKE ? ESCAPE '\\'",
        (like_root,)).fetchone()["c"]
    print(
        f"[TicianoFlix] {label}: {movies} filmes em {elapsed:.1f}s "
        f"(+{stats['added']} novos, ~{stats['changed']} alterados, "
        f"-{stats['removed']} removidos, {stats['unchanged']} inalterados)",
        flush=True
    )


def scan_cloud(progress_base=0.0, progress_span=1.0):
    """Varredura incremental da nuvem via uma unica listagem recursiva."""
    print("[TicianoFlix] Escaneando a nuvem (incremental)...", flush=True)
    start = time.time()
    _set_progress(phase="listing_root", source_current="Nuvem")

    logical_root = _branding.logical_root()
    # --fast-list lista a nuvem inteira em poucas requisicoes, bem mais
    # rapido que andar diretorio por diretorio
    tree = run_rclone_cmd(["lsjson", "--recursive", "--fast-list",
                           _rc_remote(logical_root)])
    if not isinstance(tree, list):
        print(f"[TicianoFlix] Falha ao listar a nuvem: {tree}", flush=True)
        log_notification("error", "Nao foi possivel listar a nuvem.")
        return False

    conn = get_db()
    try:
        stats = _index_tree(conn, logical_root, logical_root.lstrip("/"), tree,
                            progress_base, progress_span)
        conn.commit()
        _report("Nuvem", logical_root, stats, time.time() - start, conn)
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


def prune_unconfigured_cloud():
    """Apaga a arvore da nuvem quando ela nao esta configurada.

    O scan e incremental e so poda o que sumiu DE uma fonte; uma fonte que
    deixou de existir nunca e visitada, entao o catalogo de uma nuvem antiga
    (o Drive de antes da migracao, por exemplo) ficaria para sempre na home —
    com play que falha. Mesmo pacto do prune_orphan_sources: reconfigurar a
    nuvem e clicar em Atualizar recria a arvore; progresso e favoritos ficam,
    porque referenciam paths, nao as pastas em si.
    """
    from .paths import remote_configurado
    if remote_configurado():
        return 0
    raiz = _branding.logical_root()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM folders WHERE path=?", (raiz,)).fetchone()
        if not row["c"]:
            return 0
        _remove_folder_tree(conn, raiz)
        conn.commit()
        print(f"[TicianoFlix] Nuvem nao configurada — o catalogo remoto ({raiz}) "
              "saiu do acervo. Reconfigure em Ajustes > Nuvem e clique em "
              "Atualizar para reindexar.", flush=True)
        return 1
    finally:
        conn.close()


def scan_all(source_id=None):
    """Escaneia a nuvem e as fontes locais. `source_id` limita a uma delas."""
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
        if source["kind"] == "cloud":
            ok = scan_cloud(base, span)
        else:
            ok = scan_source(source, base, span)
        any_ok = any_ok or ok

    if not any_ok:
        _set_progress(phase="error")
        return False

    set_cache_time()
    try:
        _realinhar_progresso(get_db())
    except Exception as e:
        print(f"[TicianoFlix] Realinhamento de progresso falhou: {e}", flush=True)
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
        # Arte da colecao. Convencao do tinyMediaManager quando ele guarda a
        # arte do conjunto junto do filme. Classificada a parte de proposito:
        # sem isso ela cairia em "image", e cached_movie_detail usa a primeira
        # imagem solta como capa quando o filme nao tem poster — o cartaz da
        # saga acabaria virando o cartaz de um filme dela.
        if stem in ("movieset-poster", "movieset", "collection-poster"):
            file_type = "set_poster"
        elif stem in ("movieset-fanart", "collection-fanart"):
            file_type = "set_fanart"
        elif stem in ("poster", "capa", "cover", "folder"):
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
