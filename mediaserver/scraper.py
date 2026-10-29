"""Metadados via TMDB — o editor que substitui o tinyMediaManager.

Preenche a MESMA tabela movie_meta que o leitor de NFO ja preenche
(nfo.py._save_nfo_to_db): o formato interno que _para_movie_meta() produz e
identico ao que _parse_nfo() devolve, entao o resto do app (queries.py,
templates, frontend) nao sabe nem precisa saber de onde os dados vieram.

A chave e gratuita e da propria pessoa que instala (Ajustes > Metadados),
nunca embutida no projeto — uma chave compartilhada por todo mundo esbarraria
no mesmo limite de uso do TMDB e quebraria pra todos se fosse revogada. Sem
chave configurada, o app funciona exatamente como hoje: so o nome da pasta.

O casamento nunca e automatico e silencioso: buscar() so devolve candidatos —
quem escolhe qual e o filme certo e sempre uma pessoa, na tela de revisao.
Isso evita o erro classico de scraper automatico (Alien de 1979 vs o remake,
vs a franquia) sem exigir nenhuma logica de desambiguacao esperta.

Grava em dois lugares, por decisao de produto:
  - SEMPRE no banco (movie_meta). E o unico caminho para a nuvem, que o app
    trata como SOMENTE LEITURA: nada e escrito, movido nem renomeado la.
  - COMO .nfo + poster.jpg/fanart.jpg nas pastas LOCAIS, pra interoperar com
    Kodi/Plex — e so quando ainda nao existe nada la. As tres regras abaixo
    (confinamento, nao sobrescrever, escrita atomica) sao o que separa
    "conveniente" de "estragou a biblioteca de alguem".

Renomear e mover arquivos (organizar) mora em organizador.py e tambem so age
em fontes locais.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from .config import TMDB_KEY_PATH
from .db import get_db
from . import sources as _sources
from .nfo import _save_nfo_to_db

TMDB_BASE = "https://api.themoviedb.org/3"
# Tamanhos estaveis da API do TMDB (developer.themoviedb.org/reference/configuration-details).
# Nao vale gastar uma chamada em /configuration so pra confirmar isso a cada boot.
IMG_POSTER = "https://image.tmdb.org/t/p/w500"
IMG_BACKDROP = "https://image.tmdb.org/t/p/w1280"
_TIMEOUT = 15
_MAX_IMG_BYTES = 8 * 1024 * 1024

_RE_TITULO_ANO = re.compile(r"^(.*?)\s*\((\d{4})\)\s*$")


# ── Chave ────────────────────────────────────────────────────

def get_api_key():
    try:
        dados = json.loads(TMDB_KEY_PATH.read_text(encoding="utf-8"))
        return str(dados.get("api_key") or "")
    except (OSError, ValueError):
        return ""


def set_api_key(chave):
    chave = (chave or "").strip()
    tmp = TMDB_KEY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"api_key": chave}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, TMDB_KEY_PATH)
    try:
        os.chmod(TMDB_KEY_PATH, 0o600)
    except OSError:
        pass


def configurado():
    return bool(get_api_key())


# ── Cliente HTTP minimo (sem dependencia) ───────────────────

def _get(caminho, params):
    chave = get_api_key()
    if not chave:
        return None, "Sem chave do TMDB configurada em Ajustes > Metadados"
    params = dict(params)
    params["api_key"] = chave
    params.setdefault("language", "pt-BR")
    url = TMDB_BASE + caminho + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            corpo = resp.read()
        return json.loads(corpo.decode("utf-8")), None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None, "Chave do TMDB invalida ou revogada"
        return None, "TMDB respondeu HTTP %d" % e.code
    except urllib.error.URLError as e:
        return None, "Falha ao alcancar o TMDB: %s" % e.reason
    except (ValueError, TimeoutError) as e:
        return None, "Falha ao falar com o TMDB: %s" % e


def _titulo_ano(nome_pasta):
    """'Nome do Filme (2020)' -> ('Nome do Filme', '2020'); sem ano: (nome, None).

    Mesma convencao de parenteses que queries.py ja usa pro fallback de
    titulo (year_match = re.search(r'\\((\\d{4})\\)', folder_name)) — aqui o
    ano tambem sai do titulo, porque buscar "Nome (2020)" no TMDB da resultado
    pior do que buscar "Nome" com o ano como filtro a parte.
    """
    nome = (nome_pasta or "").strip()
    m = _RE_TITULO_ANO.match(nome)
    if m:
        return m.group(1).strip(), m.group(2)
    return nome, None


# ── Busca (nunca aplica sozinha — so devolve candidatos) ────

def buscar_candidatos(nome_pasta, query=None):
    """Candidatos do TMDB pro nome de uma pasta. 'query' sobrepoe o titulo
    derivado do nome, pra quando o palpite automatico erra feio."""
    titulo, ano = _titulo_ano(nome_pasta)
    if query:
        titulo, ano = _titulo_ano(query) if _RE_TITULO_ANO.match(query.strip()) else (query.strip(), ano)
    if not titulo:
        return [], None
    params = {"query": titulo, "include_adult": "false"}
    if ano:
        params["primary_release_year"] = ano
    dados, erro = _get("/search/movie", params)
    if erro:
        return [], erro
    candidatos = []
    for r in (dados or {}).get("results", [])[:8]:
        candidatos.append({
            "id": r.get("id"),
            "titulo": r.get("title") or r.get("original_title") or "",
            "ano": (r.get("release_date") or "")[:4] or None,
            "poster": (IMG_POSTER + r["poster_path"]) if r.get("poster_path") else None,
            "sinopse": r.get("overview") or "",
        })
    return candidatos, None


def detalhes(tmdb_id):
    return _get("/movie/%d" % int(tmdb_id), {"append_to_response": "credits"})


def para_movie_meta(dados):
    """Traduz a resposta do TMDB pro MESMO formato que nfo._parse_nfo produz
    — mesmas chaves, mesmos tipos — pra _save_nfo_to_db/_save_collection_to_db
    receberem algo identico ao que ja recebem hoje, sem adaptar nada la."""
    credits_ = dados.get("credits") or {}
    diretores = [c.get("name", "") for c in credits_.get("crew", []) if c.get("job") == "Director"]
    roteiristas = [c.get("name", "") for c in credits_.get("crew", [])
                   if c.get("job") in ("Screenplay", "Writer", "Story")]
    elenco = [{"name": c.get("name", ""), "role": c.get("character", ""), "thumb": ""}
              for c in credits_.get("cast", [])[:20]]
    colecao = dados.get("belongs_to_collection") or {}

    return {
        "title": dados.get("title") or dados.get("original_title"),
        "originaltitle": dados.get("original_title"),
        "year": (dados.get("release_date") or "")[:4] or None,
        "plot": dados.get("overview") or None,
        "outline": None,
        "tagline": dados.get("tagline") or None,
        "runtime": str(dados["runtime"]) if dados.get("runtime") else None,
        "mpaa": None,
        "country": [c.get("name", "") for c in dados.get("production_countries", [])],
        "premiered": dados.get("release_date") or None,
        "rating": ("%.1f" % dados["vote_average"]) if dados.get("vote_average") else None,
        "votes": str(dados["vote_count"]) if dados.get("vote_count") else None,
        "genres": [g.get("name", "") for g in dados.get("genres", [])],
        "studios": [c.get("name", "") for c in dados.get("production_companies", [])],
        "directors": diretores,
        "writers": roteiristas,
        "tags": [],
        "actors": elenco,
        "video_info": {},
        "audio_info": {},
        "source": "tmdb",
        "set_name": colecao.get("name") or None,
        "set_overview": None,
        # Usados so pra baixar a arte; nao fazem parte do formato do NFO.
        "_poster_path": dados.get("poster_path"),
        "_backdrop_path": dados.get("backdrop_path"),
    }


# ── Escrita local: confinada, nao-destrutiva, atomica ───────

def _escrever_atomico(caminho, dados_bytes):
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_bytes(dados_bytes)
    os.replace(tmp, caminho)


def _baixar_imagem(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "12:00 Media Server"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            dados = resp.read(_MAX_IMG_BYTES + 1)
        if len(dados) > _MAX_IMG_BYTES:
            return None
        return dados
    except Exception:
        return None


def _construir_nfo_xml(meta):
    """XML no formato que nfo._parse_nfo ja sabe ler de volta — inclusive
    <ratings><rating> aninhado, que e a forma que rating_info() procura
    primeiro, e <set> para colecao."""
    def tag(nome, valor):
        if not valor:
            return ""
        return "  <%s>%s</%s>\n" % (nome, _xml_escape(str(valor)), nome)

    def tags(nome, valores):
        return "".join(tag(nome, v) for v in (valores or []) if v)

    partes = ["<movie>\n"]
    partes.append(tag("title", meta.get("title")))
    partes.append(tag("originaltitle", meta.get("originaltitle")))
    partes.append(tag("year", meta.get("year")))
    partes.append(tag("plot", meta.get("plot")))
    partes.append(tag("tagline", meta.get("tagline")))
    partes.append(tag("runtime", meta.get("runtime")))
    partes.append(tag("premiered", meta.get("premiered")))
    if meta.get("rating"):
        partes.append("  <ratings>\n    <rating>\n")
        partes.append("    " + tag("value", meta.get("rating")))
        partes.append("    " + tag("votes", meta.get("votes")))
        partes.append("    </rating>\n  </ratings>\n")
    partes.append(tags("genre", meta.get("genres")))
    partes.append(tags("studio", meta.get("studios")))
    partes.append(tags("country", meta.get("country")))
    partes.append(tags("director", meta.get("directors")))
    partes.append(tags("credits", meta.get("writers")))
    for ator in meta.get("actors") or []:
        if not ator.get("name"):
            continue
        partes.append("  <actor>\n")
        partes.append("    " + tag("name", ator.get("name")))
        partes.append("    " + tag("role", ator.get("role")))
        partes.append("  </actor>\n")
    partes.append(tag("source", meta.get("source")))
    if meta.get("set_name"):
        partes.append("  <set>\n")
        partes.append("    " + tag("name", meta.get("set_name")))
        if meta.get("set_overview"):
            partes.append("    " + tag("overview", meta.get("set_overview")))
        partes.append("  </set>\n")
    partes.append("</movie>\n")
    return "".join(partes)


def _escrever_local_se_possivel(folder_path, meta):
    """So mexe em fonte local (a nuvem e somente leitura) e so grava o que
    ainda nao existe — nunca sobrescreve NFO ou arte que ja esteja na pasta,
    porque pode ser curadoria manual de quem organizou o acervo antes."""
    if not _sources.is_local(folder_path):
        return
    pasta = _sources.local_real_path(folder_path)
    if pasta is None or not pasta.is_dir():
        return
    escrever_arquivos(pasta, meta)


def escrever_arquivos(pasta, meta, nome_nfo=None):
    """Grava NFO, poster.jpg e fanart.jpg em `pasta` (Path), so o que falta.
    `nome_nfo` e o nome do .nfo novo (sem extensao); padrao: nome da pasta."""
    novos = []
    try:
        existentes = list(pasta.iterdir())
    except OSError:
        return novos

    tem_nfo = any(p.suffix.lower() == ".nfo" for p in existentes)
    if not tem_nfo:
        nfo_path = pasta / ((nome_nfo or pasta.name) + ".nfo")
        try:
            _escrever_atomico(nfo_path, _construir_nfo_xml(meta).encode("utf-8"))
            novos.append(nfo_path)
        except OSError:
            pass

    tem_poster = any(p.stem.lower() in ("poster", "capa", "cover", "folder")
                     and p.suffix.lower() in (".jpg", ".jpeg", ".png") for p in existentes)
    if not tem_poster and meta.get("_poster_path"):
        dados_img = _baixar_imagem(IMG_POSTER + meta["_poster_path"])
        if dados_img:
            try:
                _escrever_atomico(pasta / "poster.jpg", dados_img)
                novos.append(pasta / "poster.jpg")
            except OSError:
                pass

    tem_fanart = any(p.stem.lower() in ("fanart", "background", "backdrop")
                     and p.suffix.lower() in (".jpg", ".jpeg", ".png") for p in existentes)
    if not tem_fanart and meta.get("_backdrop_path"):
        dados_img = _baixar_imagem(IMG_BACKDROP + meta["_backdrop_path"])
        if dados_img:
            try:
                _escrever_atomico(pasta / "fanart.jpg", dados_img)
                novos.append(pasta / "fanart.jpg")
            except OSError:
                pass
    return novos


# ── Aplicar: o unico caminho que grava alguma coisa ─────────

def aplicar(folder_path, tmdb_id):
    """Busca os detalhes de UM filme escolhido na tela de revisao, grava no
    banco e, se der, escreve na pasta local. Devolve (ok, erro)."""
    dados, erro = detalhes(tmdb_id)
    if erro:
        return False, erro
    if not dados or not dados.get("id"):
        return False, "TMDB nao devolveu dados pra esse filme"

    meta = para_movie_meta(dados)
    conn = get_db()
    try:
        _save_nfo_to_db(conn, folder_path, meta)
        conn.commit()
    finally:
        conn.close()

    _escrever_local_se_possivel(folder_path, meta)
    return True, None


# ── Fila: filmes que nunca tiveram metadado nenhum ──────────

def listar_pendentes(limite=200):
    """Pastas de filme sem nenhuma linha em movie_meta — nunca tiveram NFO
    nem foram enriquecidas pelo TMDB. E a lista que a tela de revisao mostra;
    nao ha estado persistido de fila, e recalculada a cada abertura."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT f.path, f.name FROM folders f
               LEFT JOIN movie_meta m ON m.folder_path = f.path
               WHERE f.has_video = 1 AND f.depth >= 1 AND f.tipo = 'filme'
                 AND m.folder_path IS NULL
               ORDER BY f.name COLLATE NOCASE ASC
               LIMIT ?""",
            (limite,),
        ).fetchall()
        total = conn.execute(
            """SELECT COUNT(*) as c FROM folders f
               LEFT JOIN movie_meta m ON m.folder_path = f.path
               WHERE f.has_video = 1 AND f.depth >= 1 AND f.tipo = 'filme'
                 AND m.folder_path IS NULL"""
        ).fetchone()["c"]
    finally:
        conn.close()
    return [{"path": r["path"], "name": r["name"]} for r in rows], total
