"""Organizar a biblioteca: renomear e mover filmes de fontes LOCAIS para o padrao.

Padrao do acervo:

    movies/Titulo (Ano)/Titulo (Ano).mkv      (+ legendas, .nfo e a capa poster.jpg)

Regras que nao se negociam (e por que):
  - So fonte LOCAL. A nuvem e somente leitura: este modulo nunca escreve,
    renomeia nem move nada la. Quem quer a nuvem organizada organiza no disco
    e copia.
  - Tudo confinado a raiz da fonte (mesma ideia de sources.local_real_path):
    nenhum caminho vindo da tela sai dela, nem por ".." nem por symlink.
  - Nunca sobrescreve, nunca apaga arquivo. A unica remocao e de pasta que
    ficou VAZIA depois da mudanca.
  - Cada operacao vai para um historico e pode ser desfeita.
  - O casamento com o TMDB nunca e automatico: a pessoa escolhe na tela.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from .config import ORGANIZAR_LOG_PATH, VIDEO_EXTENSIONS
from .db import get_db
from . import scraper as _scraper
from . import sources as _sources

CONTAINER_FILMES = "movies"
# Contêineres da raiz que NAO sao filmes: o organizador de filmes nao entra.
_CONTAINERS_SERIE = {"tv shows", "tv"}
_IGNORAR_DIRS = {"@eadir", ".trashes", "$recycle.bin", "system volume information",
                 "lost+found", ".spotlight-v100", ".fseventsd"}
_MIN_VIDEO_BYTES = 30 * 1024 * 1024        # abaixo disso e amostra/trailer
_RE_PADRAO = re.compile(r"^(.+) \((\d{4})\)$")
_RE_ANO = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_RE_TAGS = re.compile(
    r"\b(480p|576p|720p|1080p|1080i|2160p|4k|uhd|bluray|blu-ray|bdrip|brrip|webrip|"
    r"web-dl|webdl|hdrip|hdtv|dvdrip|dvdscr|remux|x264|x265|h264|h265|hevc|xvid|"
    r"aac|ac3|dts|atmos|hdr|dual|dublado|legendado|nacional|extended|unrated|"
    r"remastered|criterion|imax|proper|repack)\b", re.I)
_RE_COLCHETES = re.compile(r"[\[\(][^\]\)]*[\]\)]")
_SEP_SIDECAR = (".", " ", "-", "_")

_lock = threading.RLock()


# ── Nomes ────────────────────────────────────────────────────

def nome_seguro(texto):
    """Nome valido de arquivo/pasta nos tres sistemas."""
    t = (texto or "").replace(":", " -")
    t = re.sub(r'[\\/*?"<>|\x00-\x1f]', "", t)
    t = re.sub(r"\s+", " ", t).strip().rstrip(". ")
    return t[:120].rstrip(". ")


def nome_padrao(titulo, ano):
    base = nome_seguro(titulo)
    return "%s (%s)" % (base, ano) if ano else base


def limpar_nome(nome):
    """'Alien.1979.1080p.BluRay.x264-GRP' -> ('Alien', '1979'). Palpite para a
    busca; quem confirma e a pessoa."""
    base = nome
    if Path(nome).suffix.lower() in VIDEO_EXTENSIONS:
        base = Path(nome).stem
    ano = None
    # ano entre parenteses/colchetes vale mais que um numero solto no titulo
    m_par = re.search(r"[\(\[]((?:19|20)\d{2})[\)\]]", base)
    if m_par:
        ano = m_par.group(1)
        base = base[:m_par.start()] + " " + base[m_par.end():]
    s = _RE_COLCHETES.sub(" ", base)
    s = re.sub(r"[._]+", " ", s)
    if not ano:
        anos = list(_RE_ANO.finditer(s))
        # ignora um ano no comeco ("2001 Uma Odisseia") se for o unico
        validos = [m for m in anos if m.start() > 0]
        if validos:
            m = validos[-1]
            ano = m.group(1)
            s = s[:m.start()]
    tag = _RE_TAGS.search(s)
    if tag:
        s = s[:tag.start()]
    s = re.sub(r"\s+", " ", s).strip(" -–_.")
    return s, ano


# ── Confinamento ─────────────────────────────────────────────

def _raiz_local(source_id):
    """Path real da raiz da fonte local, ou (None, erro)."""
    src = _sources.get_source(source_id)
    if not src or src.get("kind") != "local":
        return None, "A nuvem é somente leitura: só dá para organizar fontes locais."
    raiz = Path(src["root"])
    if not raiz.is_dir():
        return None, "A fonte está offline (disco ou pendrive desconectado)."
    return raiz.resolve(), None


def _dentro(raiz, rel):
    """Path real de raiz/rel confinado a raiz, ou None."""
    rel = str(rel or "").replace("\\", "/").strip("/")
    if not rel or "\x00" in rel or any(p in ("", ".", "..") for p in rel.split("/")):
        return None
    alvo = raiz.joinpath(*rel.split("/"))
    try:
        alvo.resolve().relative_to(raiz)
    except (ValueError, OSError, RuntimeError):
        return None
    return alvo


def _logico(src, rel):
    return src["mount"].rstrip("/") + "/" + rel.strip("/")


# ── Descoberta ───────────────────────────────────────────────

def _videos_da_pasta(pasta):
    saida = []
    try:
        for e in os.scandir(pasta):
            if e.is_file() and Path(e.name).suffix.lower() in VIDEO_EXTENSIONS:
                try:
                    tam = e.stat().st_size
                except OSError:
                    continue
                if tam >= _MIN_VIDEO_BYTES and "sample" not in e.name.lower():
                    saida.append((e.name, tam))
    except OSError:
        pass
    return sorted(saida)


def _tem_videos_abaixo(pasta):
    """True se ha video grande em ALGUMA subpasta (a pasta nao e de um filme so)."""
    for dirpath, dirnames, _ in os.walk(pasta):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if Path(dirpath) != Path(pasta) and _videos_da_pasta(dirpath):
            return True
    return False


def _ja_no_padrao(partes, nome_arquivo):
    """movies/Titulo (Ano)/Titulo (Ano).ext"""
    if len(partes) != 3 or partes[0].lower() != CONTAINER_FILMES:
        return False
    m = _RE_PADRAO.match(partes[1])
    return bool(m) and Path(partes[2]).stem == partes[1] and nome_arquivo == partes[2]


def listar_itens(source_id):
    """Filmes da fonte que ainda nao estao no padrao.

    Cada item: {id, tipo: 'pasta'|'arquivo', origem (rel), nome, titulo, ano,
    tamanho}. 'pasta' = pasta com um unico video (a pasta inteira vai junto);
    'arquivo' = video solto ou pasta com varios videos (cada um vira um filme).
    Nao consulta o TMDB: isso e feito um a um pela tela.
    """
    raiz, erro = _raiz_local(source_id)
    if erro:
        return None, erro
    itens = []
    for dirpath, dirnames, _ in os.walk(raiz):
        rel_dir = Path(dirpath).relative_to(raiz)
        partes_dir = rel_dir.parts
        # poda: series, lixo do sistema e pastas ocultas
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d.lower() not in _IGNORAR_DIRS
            and not (not partes_dir and d.lower() in _CONTAINERS_SERIE))
        videos = _videos_da_pasta(dirpath)
        if not videos:
            continue
        # uma pasta com 1 video e filha de qualquer pasta (nao e a raiz nem o
        # contêiner movies/) e "a pasta do filme"
        e_pasta_do_filme = (len(videos) == 1 and partes_dir
                            and not (len(partes_dir) == 1 and partes_dir[0].lower() == CONTAINER_FILMES)
                            and not _tem_videos_abaixo(dirpath))
        if e_pasta_do_filme:
            nome_video, tam = videos[0]
            if _ja_no_padrao(list(partes_dir) + [nome_video], nome_video):
                continue
            titulo, ano = limpar_nome(partes_dir[-1])
            if not titulo or (not ano and len(partes_dir) >= 1):
                t2, a2 = limpar_nome(nome_video)
                titulo, ano = (titulo or t2), (ano or a2)
            itens.append({"tipo": "pasta", "origem": rel_dir.as_posix(),
                          "nome": partes_dir[-1], "titulo": titulo, "ano": ano,
                          "tamanho": tam})
        else:
            for nome_video, tam in videos:
                rel = (rel_dir / nome_video).as_posix() if partes_dir else nome_video
                titulo, ano = limpar_nome(nome_video)
                itens.append({"tipo": "arquivo", "origem": rel, "nome": nome_video,
                              "titulo": titulo, "ano": ano, "tamanho": tam})
    for it in itens:
        it["id"] = hashlib.sha1(it["origem"].encode("utf-8")).hexdigest()[:12]
    itens.sort(key=lambda x: x["origem"].lower())
    return itens, None


# ── Busca (so devolve candidatos) ────────────────────────────

def buscar(source_id, origem, query=None):
    """Candidatos do TMDB para um item, ja com o destino que cada um geraria."""
    raiz, erro = _raiz_local(source_id)
    if erro:
        return [], erro
    alvo = _dentro(raiz, origem)
    if alvo is None or not alvo.exists():
        return [], "Item não encontrado na fonte."
    base = alvo.name
    titulo, ano = limpar_nome(base)
    if alvo.is_dir():
        v = _videos_da_pasta(alvo)
        if v and not titulo:
            titulo, ano = limpar_nome(v[0][0])
    texto = (query or "").strip() or (nome_padrao(titulo, ano) if titulo else base)
    cands, erro = _scraper.buscar_candidatos(texto)
    if erro:
        return [], erro
    for c in cands:
        pasta = nome_padrao(c["titulo"], c["ano"])
        c["destino"] = "%s/%s" % (CONTAINER_FILMES, pasta)
    return cands, None


# ── Aplicar ──────────────────────────────────────────────────

def _mesmo_arquivo(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _planejar_movimentos(raiz, tipo, origem_rel, destino_rel, nome_base):
    """Lista de (origem_abs, destino_abs). Levanta ValueError com a mensagem."""
    origem = _dentro(raiz, origem_rel)
    if origem is None or not origem.exists():
        raise ValueError("Item não encontrado na fonte.")
    destino_dir = _dentro(raiz, destino_rel)
    if destino_dir is None:
        raise ValueError("Destino inválido.")
    movs = []
    if tipo == "pasta":
        if not origem.is_dir():
            raise ValueError("Esperava uma pasta.")
        videos = _videos_da_pasta(origem)
        if len(videos) != 1 or _tem_videos_abaixo(origem):
            raise ValueError("A pasta mudou: não tem mais exatamente um vídeo.")
        video = origem / videos[0][0]
        stem = video.stem
        for e in sorted(origem.iterdir()):
            if e == video:
                novo = nome_base + video.suffix
            elif e.is_file() and e.name.startswith(stem) and \
                    (len(e.name) == len(stem) or e.name[len(stem)] in _SEP_SIDECAR):
                novo = nome_base + e.name[len(stem):]
            elif e.is_file() and e.suffix.lower() == ".nfo":
                novo = nome_base + ".nfo"
            else:
                novo = e.name
            movs.append((e, destino_dir / novo))
    else:
        if not origem.is_file():
            raise ValueError("Esperava um arquivo.")
        stem = origem.stem
        for e in sorted(origem.parent.iterdir()):
            if e == origem:
                novo = nome_base + origem.suffix
            elif e.is_file() and e.name.startswith(stem) and e.name != origem.name and \
                    e.name[len(stem)] in _SEP_SIDECAR and \
                    Path(e.name).suffix.lower() not in VIDEO_EXTENSIONS:
                novo = nome_base + e.name[len(stem):]
            else:
                continue
            movs.append((e, destino_dir / novo))
    # conflitos: destino ja existe (e nao e o proprio arquivo) ou dois para o mesmo
    vistos = set()
    for src, dst in movs:
        chave = str(dst).lower()
        if chave in vistos:
            raise ValueError("Dois arquivos viriam para o mesmo nome: %s" % dst.name)
        vistos.add(chave)
        if src == dst:
            continue
        if dst.exists() and not _mesmo_arquivo(src, dst):
            raise ValueError("Já existe \"%s\" no destino. Nada foi alterado." % dst.name)
    return [(s, d) for s, d in movs if s != d]


def _mover(src, dst):
    try:
        os.rename(src, dst)
    except OSError:
        shutil.move(str(src), str(dst))


def _remapear_banco(antigo, novo):
    """Leva progresso, colecoes, tags e perfil infantil do path antigo para o
    novo, para o filme nao perder o que ja tinha ao mudar de lugar."""
    if antigo == novo:
        return
    conn = get_db()
    try:
        for tabela, coluna in (("watch_progress", "folder_path"),
                               ("colecoes_filmes", "folder_path"),
                               ("colecoes", "capa"),
                               ("generos_filmes", "alvo"),
                               ("infantil_filmes", "alvo")):
            conn.execute("UPDATE OR REPLACE %s SET %s=? WHERE %s=?" % (tabela, coluna, coluna),
                         (novo, antigo))
        conn.commit()
    finally:
        conn.close()


def _aplicar_um(src_cfg, raiz, item):
    """Organiza UM item. Devolve (resultado_dict, None) ou (None, erro)."""
    origem_rel = str(item.get("origem") or "")
    try:
        tmdb_id = int(item.get("tmdb_id"))
    except (TypeError, ValueError):
        return None, "Falta escolher o filme."
    # valida o caminho ANTES de falar com o TMDB
    pre = _dentro(raiz, origem_rel)
    if pre is None or not pre.exists():
        return None, "Item não encontrado na fonte."
    dados, erro = _scraper.detalhes(tmdb_id)
    if erro:
        return None, erro
    if not dados or not dados.get("id"):
        return None, "O TMDB não devolveu dados para esse filme."
    meta = _scraper.para_movie_meta(dados)
    nome_base = nome_padrao(meta.get("title"), meta.get("year"))
    if not nome_base:
        return None, "Título inválido."
    destino_rel = "%s/%s" % (CONTAINER_FILMES, nome_base)
    origem = _dentro(raiz, origem_rel)
    if origem is None or not origem.exists():
        return None, "Item não encontrado na fonte."
    tipo = "pasta" if origem.is_dir() else "arquivo"
    try:
        movs = _planejar_movimentos(raiz, tipo, origem_rel, destino_rel, nome_base)
    except ValueError as e:
        return None, str(e)

    destino_dir = _dentro(raiz, destino_rel)
    criadas = []
    feitos = []
    try:
        # cria cada nivel que faltar e guarda quais foram criados (para desfazer)
        niveis = []
        p = destino_dir
        while not p.exists() and p != raiz:
            niveis.append(p)
            p = p.parent
        for d in reversed(niveis):
            d.mkdir()
            criadas.append(d)
        for src, dst in movs:
            _mover(src, dst)
            feitos.append((src, dst))
    except OSError as e:
        # desfaz o que ja foi feito, na ordem inversa
        for src, dst in reversed(feitos):
            try:
                _mover(dst, src)
            except OSError:
                pass
        for d in reversed(criadas):
            try:
                d.rmdir()
            except OSError:
                pass
        return None, "Não foi possível mover os arquivos: %s" % e

    # pasta de origem que ficou vazia sai (so vazia; nada e apagado)
    removidas = []
    if tipo == "pasta" and origem.exists() and origem != destino_dir:
        try:
            if not any(origem.iterdir()):
                origem.rmdir()
                removidas.append(origem)
        except OSError:
            pass
    elif tipo == "arquivo":
        pai = origem.parent
        try:
            if pai != raiz and pai != destino_dir and not any(pai.iterdir()):
                pai.rmdir()
                removidas.append(pai)
        except OSError:
            pass

    # a capa e a que a pessoa escolheu na tela; sem escolha vale a principal do
    # TMDB, e "sem_capa" deixa a pasta sem baixar nada
    novos = _scraper.escrever_arquivos(
        destino_dir, meta, nome_nfo=nome_base,
        poster_path=item.get("poster_path"), sem_capa=bool(item.get("sem_capa")))

    logico_antigo = _logico(src_cfg, origem_rel)
    logico_novo = _logico(src_cfg, destino_rel)
    _remapear_banco(logico_antigo, logico_novo)
    # filme solto: o progresso podia estar no path do arquivo
    return {
        "origem": origem_rel, "destino": destino_rel, "titulo": meta.get("title"),
        "movimentos": [[s.relative_to(raiz).as_posix(), d.relative_to(raiz).as_posix()]
                       for s, d in feitos],
        "criadas": [d.relative_to(raiz).as_posix() for d in criadas],
        "removidas": [d.relative_to(raiz).as_posix() for d in removidas],
        "gerados": [p.relative_to(raiz).as_posix() for p in novos],
        "mapa": [logico_antigo, logico_novo],
    }, None


def aplicar(source_id, itens):
    """Organiza os itens escolhidos. Devolve {op, resultados:[{origem, ok, ...}]}."""
    raiz, erro = _raiz_local(source_id)
    if erro:
        return None, erro
    src_cfg = _sources.get_source(source_id)
    resultados, feitos = [], []
    with _lock:
        for item in itens[:200]:
            res, err = _aplicar_um(src_cfg, raiz, item)
            if err:
                resultados.append({"origem": item.get("origem"), "ok": False, "erro": err})
            else:
                resultados.append({"origem": res["origem"], "ok": True,
                                   "destino": res["destino"], "titulo": res["titulo"]})
                feitos.append(res)
        op = None
        if feitos:
            op = _registrar(source_id, feitos)
    return {"op": op, "resultados": resultados}, None


# ── Historico e desfazer ─────────────────────────────────────

def _ler_log():
    try:
        dados = json.loads(ORGANIZAR_LOG_PATH.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else []
    except (OSError, ValueError):
        return []


def _gravar_log(ops):
    tmp = ORGANIZAR_LOG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ops[-50:], ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ORGANIZAR_LOG_PATH)


def _registrar(source_id, feitos):
    op = {"id": "%d" % int(time.time() * 1000), "ts": int(time.time()),
          "source": source_id, "desfeita": False, "itens": feitos}
    ops = _ler_log()
    ops.append(op)
    _gravar_log(ops)
    return op["id"]


def historico():
    return [{"id": o["id"], "ts": o["ts"], "source": o["source"],
             "desfeita": bool(o.get("desfeita")),
             "filmes": [i["titulo"] for i in o["itens"]]}
            for o in reversed(_ler_log())]


def desfazer(op_id):
    """Volta tudo de uma operacao: arquivos para onde estavam, pastas criadas
    saem (se vazias) e as removidas voltam. Para no primeiro conflito."""
    with _lock:
        ops = _ler_log()
        op = next((o for o in ops if o["id"] == str(op_id)), None)
        if not op:
            return False, "Operação não encontrada."
        if op.get("desfeita"):
            return False, "Essa operação já foi desfeita."
        raiz, erro = _raiz_local(op["source"])
        if erro:
            return False, erro
        src_cfg = _sources.get_source(op["source"])
        for item in reversed(op["itens"]):
            # arquivos que o app gerou nesta operacao (NFO e capa)
            for rel in item.get("gerados", []):
                f = _dentro(raiz, rel)
                try:
                    if f is not None and f.is_file():
                        f.unlink()
                except OSError:
                    pass
            for rel in item["removidas"]:
                d = _dentro(raiz, rel)
                if d is not None:
                    d.mkdir(parents=True, exist_ok=True)
            for de, para in reversed(item["movimentos"]):
                atual, volta = _dentro(raiz, para), _dentro(raiz, de)
                if atual is None or volta is None:
                    return False, "Caminho inválido no histórico."
                if not atual.exists():
                    return False, "Não achei \"%s\": ele foi movido depois." % para
                if volta.exists() and not _mesmo_arquivo(atual, volta):
                    return False, "Já existe \"%s\": não dá para voltar." % de
                volta.parent.mkdir(parents=True, exist_ok=True)
                _mover(atual, volta)
            for rel in reversed(item["criadas"]):
                d = _dentro(raiz, rel)
                try:
                    if d is not None and d.is_dir() and not any(d.iterdir()):
                        d.rmdir()
                except OSError:
                    pass
            _remapear_banco(item["mapa"][1], item["mapa"][0])
        op["desfeita"] = True
        _gravar_log(ops)
        return True, None
