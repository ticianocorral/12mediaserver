"""Preparo de video para transmitir na TV (Chromecast e AirPlay).

O receptor do Chromecast e o AirPlay nao leem MKV — e o audio AC3/E-AC3/DTS
fica mudo ate no Chrome do computador, que nao traz esses decodificadores.
Em vez de recusar o filme, o servidor gera uma copia MP4 do original:

  - video: copiado sem re-encodar quando ja e H.264; convertido para H.264
    no resto (HEVC inclusive). Copiar HEVC parecia ideal, mas receptor
    nenhum garante HEVC 10-bit: a TV tocava so o audio e mostrava a
    protecao de tela (Chromecast) ou ficava presa no "carregando"
    (AirPlay). H.264 e o unico formato que toca em todo mundo;
  - audio: copiado quando ja e AAC/MP3; convertido para AAC no resto;
  - legenda: o .srt/.ass com o mesmo nome do video entra no MP4 como faixa
    "timed text" (mov_text) — o único formato que o AirPlay leva para a TV.
    Nota: arquivos WebVTT (<track>) sao renderizados pelo navegador do
    envio e o receptor AirPlay nunca os ve: ele busca só o vídeo. Existe
    só dentro do MP4 que a TV baixa. Na TV, a legenda liga no controle
    remoto do Apple TV (o botao CC do app nao manda no receptor).
    Dar erro na legenda nao mata o filme: refaz sem a faixa e marca
    sub_erro no meta (o cache continua valendo, so sem legenda);
  - o MP4 sai com faststart (moov no inicio).

A conversao roda em segundo plano, uma por vez, e o resultado fica em cache
(~/.cache/media-server/cast). So a primeira transmissao de cada arquivo
espera; depois e instantaneo. Se o arquivo de origem mudar (mtime/tamanho),
o cache vence sozinho e uma nova conversao acontece.

Fonte de nuvem (B2 via 'rclone serve http'): o rclone nao expoe o arquivo
como path de disco, entao o prepare baixa o original (e a legenda sidecar)
para um arquivo de palco junto do cache, converte de la e apaga o palco no
fim — o que persiste e so o MP4. A chave do cache soma a marca REMOTA do
banco (tamanho/mod_time do arquivo listado); a baixa so acontece quando a
conversao nao existe ou venceu. Sem ffprobe remota, a decisao de preparar
usa a extensao do container (e a presenca de legenda); o codec real aparece
depois da baixa e segue a mesma receita do local.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

from . import keepawake
from .config import CAST_CACHE_DIR, RCLONE_SERVE_PORT

# O que os receptores leem sem conversao: container MP4/MOV + video H.264 +
# faixa AAC/MP3 (sem faixa tambem vale — filme mudo). HEVC fica de fora de
# proposito: muito receptor (inclusive o padrao do Chromecast) nao decodifica
# HEVC 10-bit — o video nao aparece e o audio continua por baixo.
_CONTAINERS_PRONTOS = {".mp4", ".m4v", ".mov"}
_VIDEO_COPIavel = {"h264"}
_AUDIO_COPIavel = {"aac", "mp3"}

# Legenda sidecar que entra no MP4 (mov_text so aceita texto: .sup e bitmap
# e fica de fora — esse caso segue sem legenda na TV).
_EXT_LEGENDA = (".srt", ".ass", ".ssa", ".vtt")


def escolhe_legenda(stem_video, nomes):
    """Qual legenda sidecar usar, pela mesma regra no disco e na nuvem.

    O padrao do acervo e "Filme (2020).mkv" + "Filme (2020).srt"; um sufixo
    de idioma no meio ("Filme (2020).pt.srt") tambem vale. Prioridade: o
    homonimo .srt, depois qualquer .srt do mesmo comeco, depois os demais
    formatos texto. Recebe os NOMES; devolve um deles, ou None.
    """
    cands = [n for n in nomes if Path(n).suffix.lower() in _EXT_LEGENDA]
    if not cands:
        return None
    stem = (stem_video or "").lower()
    prefixo = [n for n in cands if Path(n).stem.lower().startswith(stem)]
    srt = [n for n in prefixo if Path(n).suffix.lower() == ".srt"]
    homonimo = [n for n in srt if Path(n).stem.lower() == stem]
    for grupo in (homonimo, srt, prefixo):
        if grupo:
            return sorted(grupo)[0]
    return None


def _legenda_de(src):
    """Legenda sidecar do video local (mesmo nome, mesma pasta), ou None."""
    try:
        pasta = Path(src).parent
        nomes = [p.name for p in pasta.iterdir() if p.is_file()]
    except OSError:
        return None
    nome = escolhe_legenda(Path(src).stem, nomes)
    return str(pasta / nome) if nome else None


def _assinatura_legenda(sub):
    """Marca da legenda no cache: se o .srt mudar, o cache invalida sozinho."""
    if not sub:
        return None
    try:
        st = os.stat(sub)
    except OSError:
        return None
    return {"path": str(sub), "mtime": int(st.st_mtime), "size": st.st_size}

# Teto do cache de conversoes; ao estourar, o mais antigo sai primeiro.
CAST_CACHE_MAX = 40 * 1024 ** 3

# Versao da receita de conversao. Subiu para 2 quando o video HEVC passou a
# ser convertido em H.264. Subiu para 3 quando a legenda sidecar entrou no
# MP4 (mov_text): cache sem esta marca sofre para nada a TV — vale menos
# que nada. Ao mudar o _cmd, suba este numero; as conversoes antigas se
# invalidam sozinhas (e o _cleanup as recolhe).
_PREP_VERSION = 3

# O PATH do LaunchAgent e minimo (nao inclui /opt/homebrew/bin): procurar
# nos lugares de sempre antes de desistir.
_DIRS_BIN = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")

_lock = threading.Lock()
_jobs = {}                       # path -> {state, percent, error}
_fila = deque()                  # paths aguardando o worker
_worker_ligado = False


# ── Binarios ─────────────────────────────────────────────────

def _bin(nome):
    for pasta in _DIRS_BIN:
        caminho = os.path.join(pasta, nome)
        if os.access(caminho, os.X_OK):
            return caminho
    return shutil.which(nome)


def _ffmpeg_bin():
    return _bin("ffmpeg")


def _ffprobe_bin():
    return _bin("ffprobe")


# ── Sonda ────────────────────────────────────────────────────

def _probe(path):
    """Streams principais do arquivo via ffprobe, ou None se nao der.

    O video escolhido e o primeiro que NAO e capa embutida (o attached_pic
    de MKV com capa vira "video" na lista e seria copiado no lugar do filme).
    """
    ffprobe = _ffprobe_bin()
    if not ffprobe:
        return None
    try:
        saida = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, timeout=60)
        if saida.returncode != 0:
            return None
        dados = json.loads(saida.stdout.decode("utf-8", "replace"))
    except Exception:
        return None

    streams = dados.get("streams") or []
    video = None
    for s in streams:
        if s.get("codec_type") != "video":
            continue
        if (s.get("disposition") or {}).get("attached_pic"):
            continue
        video = s
        break
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        return None

    duracao = None
    try:
        duracao = float((dados.get("format") or {}).get("duration") or 0) or None
    except (TypeError, ValueError):
        duracao = None

    return {
        "v": video.get("codec_name") or "",
        "vidx": video.get("index"),
        "a": (audio.get("codec_name") or "") if audio else None,
        "aidx": audio.get("index") if audio else None,
        "duration": duracao,
    }


def _precisa(info, path, sub=None):
    """True quando o original nao toca direto nos receptores.

    Legenda sidecar tambem pede preparo: mov_text so existe dentro do MP4
    remuxado (copia rápida quando o video/audio já servem)."""
    if sub:
        return True
    if Path(path).suffix.lower() not in _CONTAINERS_PRONTOS:
        return True
    if info.get("v") not in _VIDEO_COPIavel:
        return True
    audio = info.get("a")
    if audio and audio not in _AUDIO_COPIavel:
        return True
    return False


# ── Cache ────────────────────────────────────────────────────

def _precisa_nuvem(attrs):
    """True quando o arquivo remoto vale a baixa para converter.

    Sem ffprobe de nada que ainda nao foi baixado, a decisao usa so a
    extensao do container (e a presenca de legenda). O codec real aparece
    na sondagem do arquivo de palco — de la em diante vale o _precisa do
    local, entao um .mp4 estranho (HEVC, por exemplo) no fim da baixa
    tambem acaba convertido em vez de servido cru.
    """
    if (attrs.get("sig") or {}).get("sub"):
        return True
    remoto = (attrs.get("sig") or {}).get("remoto") or ""
    return Path(remoto).suffix.lower() not in _CONTAINERS_PRONTOS


def _normaliza(fonte):
    """Fonte (path local ou descriptor de nuvem) -> atributos para o cache.

    Local: str com o path no disco. A legenda sidecar e procurada aqui
    mesmo (mesmo nome; ver escolhe_legenda) e assinada com mtime/tamanho.

    Nuvem: dict {kind: 'nuvem', remoto, size, mtime, sub: {...|None}} que o
    handler monta a partir do banco (marca remota do arquivo listado). A
    chave soma essa marca — mudou o arquivo na nuvem, o cache vence. Os
    arquivos de palco da baixa nunca entram na chave: morrem no fim da
    conversao; so o MP4 persiste.
    """
    if isinstance(fonte, str):
        if not fonte:
            return None
        sub = _legenda_de(fonte)
        sig_sub = _assinatura_legenda(sub)
        texto = "%s\n%s" % (fonte,
                            json.dumps(sig_sub, sort_keys=True) if sig_sub else "-")
        return {
            "kind": "local",
            "path": fonte,
            "sub": sub,
            "chave": hashlib.sha1(texto.encode("utf-8")).hexdigest(),
            "rotulo": Path(fonte).name,
        }
    if not isinstance(fonte, dict) or fonte.get("kind") != "nuvem":
        return None
    remoto = str(fonte.get("remoto") or "").strip("/")
    if not remoto:
        return None
    sig = {"remoto": remoto,
           "size": fonte.get("size"),
           "mtime": fonte.get("mtime")}
    sub = fonte.get("sub") or None
    if sub:
        sig["sub"] = {
            "remoto": str(sub.get("remoto") or "").strip("/"),
            "size": sub.get("size"),
            "mtime": sub.get("mtime"),
            "nome": sub.get("nome"),
        }
    texto = "nuvem\n" + json.dumps(sig, sort_keys=True)
    return {
        "kind": "nuvem",
        "path": None,
        "sig": sig,
        "chave": hashlib.sha1(texto.encode("utf-8")).hexdigest(),
        "rotulo": Path(remoto).name,
    }


# ── Cache ────────────────────────────────────────────────────

def _cache_paths(fonte):
    """MP4 + meta do cache e os atributos da fonte.

    A chave de local soma path + assinatura da legenda; a de nuvem soma a
    marca remota do banco. Trocar ou editar o .srt (de qualquer lado)
    invalida a conversao sem tocar no resto do cache."""
    attrs = _normaliza(fonte)
    chave = attrs["chave"] if attrs else "invalido"
    return (CAST_CACHE_DIR / (chave + ".mp4"),
            CAST_CACHE_DIR / (chave + ".json"), attrs)


def prepared_file(fonte):
    """Path do MP4 convertido, se existir e corresponder a fonte.

    Tambem confere a legenda: mudou o .srt, invalida sozinho. Um cache que
    descartou a legenda com erro (sub_erro no meta) fica disponivel em
    modo degradado: melhor sem faixa de texto do que sem video."""
    if not fonte:
        return None
    mp4, meta, attrs = _cache_paths(fonte)
    if attrs is None:
        return None
    try:
        dados = json.loads(meta.read_text("utf-8"))
    except Exception:
        return None
    if dados.get("prep") != _PREP_VERSION:
        return None
    if attrs["kind"] == "local":
        try:
            st = os.stat(attrs["path"])
        except OSError:
            return None
        if (dados.get("mtime") != int(st.st_mtime)
                or dados.get("size") != st.st_size):
            return None
        if dados.get("sub") != _assinatura_legenda(attrs["sub"]):
            return None
    else:
        if dados.get("nuvem") != attrs["sig"]:
            return None
    if not mp4.is_file():
        return None
    return mp4


def mark_used(fonte):
    """Atualiza o mtime do cache: a limpeza LRU usa isso como 'uso'."""
    mp4, _, _ = _cache_paths(fonte)
    try:
        os.utime(mp4, None)
    except OSError:
        pass


# ── Status publico ───────────────────────────────────────────

def _publico(job):
    return {"needed": True, "state": job["state"],
            "percent": int(job.get("percent", 0)),
            "error": job.get("error") or ""}


def status(fonte, enqueue=False):
    """Estado do preparo para a TV.

    fonte e um path de disco local (str) ou descriptor de nuvem (dict — ver
    _normaliza). needed=False -> o original toca direto (local) ou a baixa
    nao vale a pena (nuvem: container pronto e sem legenda); o chamador
    segue com /api/stream como sempre.
    state: 'none' | 'ready' | 'queued' | 'converting' | 'error' | 'idle'
    ('idle' = precisa converter mas nada agendado — o servidor reiniciou
    no meio; com enqueue=True isso nao acontece).
    """
    attrs = _normaliza(fonte)
    if attrs is None:
        return {"needed": False, "state": "none"}
    with _lock:
        job = _jobs.get(attrs["chave"])
        if job:
            if not (job["state"] == "error" and enqueue):
                return _publico(job)
            _jobs.pop(attrs["chave"], None)   # novo pedido = nova tentativa

    if prepared_file(fonte):
        return {"needed": True, "state": "ready", "percent": 100}

    if attrs["kind"] == "nuvem":
        precisa = _precisa_nuvem(attrs)
    else:
        info = _probe(attrs["path"])
        precisa = (info is not None
                   and _precisa(info, attrs["path"], attrs["sub"]))
    if not precisa:
        return {"needed": False, "state": "none"}
    # Sem ffmpeg na maquina o preparo nao existe: transmissao segue como
    # antes (arquivo original), sem travar o usuario.
    if not _ffmpeg_bin() or not _ffprobe_bin():
        return {"needed": False, "state": "none"}

    if enqueue:
        _enqueue(fonte)
        with _lock:
            job = _jobs.get(attrs["chave"])
            return _publico(job) if job else {"needed": True, "state": "idle"}
    return {"needed": True, "state": "idle"}


# ── Fila e worker ────────────────────────────────────────────

def _enqueue(fonte):
    global _worker_ligado
    attrs = _normaliza(fonte)
    if attrs is None:
        return
    chave = attrs["chave"]
    with _lock:
        if chave in _jobs or _fila_contem(chave):
            return
        _jobs[chave] = {"state": "queued", "percent": 0, "error": "",
                        "fonte": fonte, "rotulo": attrs["rotulo"]}
        _fila.append(chave)
        if not _worker_ligado:
            _worker_ligado = True
            threading.Thread(target=_worker, name="media-server-prepare",
                             daemon=True).start()
    print("[12:00 Media Server] Preparo para TV na fila: %s" % attrs["rotulo"],
          flush=True)


def _fila_contem(chave):
    return any(k == chave for k in _fila)


def _worker():
    global _worker_ligado
    while True:
        with _lock:
            if not _fila:
                _worker_ligado = False
                return
            chave = _fila.popleft()
        try:
            _convert(chave)
        except Exception as e:   # o worker nunca morre com job preso
            with _lock:
                job = _jobs.get(chave)
                if job:
                    job.update(state="error", error=str(e)[:300])
            print("[12:00 Media Server] Falha preparando %s: %s"
                  % (job.get("rotulo", chave) if job else chave, e), flush=True)


def _convert(chave):
    with _lock:
        job = _jobs.get(chave)
        if job is None:
            return
        job.update(state="converting", percent=0, error="")
        fonte = job["fonte"]
        rotulo = job.get("rotulo") or "?"

    palco = None
    tmp = None
    try:
        attrs = _normaliza(fonte)
        if attrs["kind"] == "nuvem":
            # Do rclone nao sai path de disco: baixa o original (e a
            # legenda sidecar) para o palco e converte de la. O palco morre
            # no fim — no sucesso e no erro; so o MP4 persiste. A baixa
            # costuma ser a parte mais longa dela toda: dormirmos agora
            # travaria o job, mesmo tratamento da conversao.
            with keepawake.while_streaming():
                palco = _palco_nuvem(attrs, chave)
            if palco is None:
                raise RuntimeError("baixa do arquivo da nuvem falhou")
            path = str(palco["video"])
            sub = palco.get("sub")
            rotulo_base = attrs["rotulo"]
        else:
            path = attrs["path"]
            sub = _legenda_de(path)  # atual na hora da conversao (nao a da fila)
            rotulo_base = attrs["rotulo"]

        info = _probe(path)
        if info is None or not _precisa(info, path, sub):
            with _lock:
                _jobs.pop(chave, None)
            return

        mp4, meta, _ = _cache_paths(fonte)
        # Nome único por processo: se duas conversões do mesmo arquivo
        # correrem juntas (servidor + uma sessão manual, por exemplo), cada
        # uma escreve no seu tmp e o os.replace() fica com a última — sem
        # uma sobrescrever o arquivo da outra no meio.
        tmp = mp4.with_name("%s.tmp.%d.mp4" % (mp4.name, os.getpid()))
        print("[12:00 Media Server] Preparando para TV: %s (video %s, audio %s%s)"
              % (rotulo_base, info.get("v"), info.get("a") or "sem",
                 ", legenda %s" % Path(sub).name if sub else ""),
              flush=True)

        dur_us = (info.get("duration") or 0) * 1_000_000
        # Nuvem: a baixa ja gastou 0-40 do percentual; o ffmpeg entra
        # depois e preenche ate 99.
        base = 40 if attrs["kind"] == "nuvem" else 0
        sub_erro = None
        with keepawake.while_streaming():
            codigo, log_ultimo = _rodar(_cmd(path, info, tmp, sub), chave,
                                        dur_us, base=base)
            if codigo != 0 and sub:
                # Legenda ruim nao pode derrubar o filme: refaz sem a faixa
                # de texto e marca sub_erro — o cache segue valendo.
                sub_erro = log_ultimo or ("codigo %d" % codigo)
                print("[12:00 Media Server] Legenda %s invalida, preparando sem ela"
                      % Path(sub).name, flush=True)
                codigo, log_ultimo = _rodar(_cmd(path, info, tmp, None),
                                            chave, dur_us, base=base)

        if codigo != 0:
            raise RuntimeError("ffmpeg falhou: "
                               + (log_ultimo or "codigo %d" % codigo))

        os.replace(tmp, mp4)
        dados_meta = {
            "path": path,
            "prep": _PREP_VERSION,
            "mtime": 0,
            "size": None,
            "v": info.get("v"),
            "a": info.get("a"),
            "created": int(time.time()),
            # "sub" e a legenda tentada (mesmo quando descartada); sub_erro
            # marca o discard — o MP4 sai sem faixa de texto mas continua
            # valendo (ver prepared_file).
            "sub": None,
        }
        if attrs["kind"] == "local":
            try:
                stl = os.stat(path)
                dados_meta["mtime"] = int(stl.st_mtime)
                dados_meta["size"] = stl.st_size
            except OSError:
                pass
            dados_meta["sub"] = _assinatura_legenda(sub)
        else:
            dados_meta["path"] = attrs["sig"]["remoto"]
            dados_meta["size"] = attrs["sig"]["size"]
            dados_meta["nuvem"] = attrs["sig"]
        if sub_erro:
            dados_meta["sub_erro"] = sub_erro[:200]
        meta.write_text(json.dumps(dados_meta), "utf-8")
        with _lock:
            _jobs.pop(chave, None)
        print("[12:00 Media Server] Pronto para TV: %s" % rotulo_base, flush=True)
        _cleanup()
    except Exception as e:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        with _lock:
            j = _jobs.get(chave)
            if j:
                j.update(state="error", error=str(e)[:300])
        print("[12:00 Media Server] Falha preparando %s: %s" % (rotulo, e), flush=True)
    finally:
        if palco is not None:
            for arq in (palco.get("video"), palco.get("sub")):
                if arq:
                    try:
                        Path(arq).unlink()
                    except OSError:
                        pass


def _rodar(cmd, chave, dur_us, base=0, teto=99):
    """Roda o ffmpeg lendo o progresso; devolve (codigo, ultima linha de erro).

    Separado de _convert porque a segunda tentativa (sem legenda) repete a
    mesma leitura de progresso. base/teto remapeiam o 0-100 do ffmpeg numa
    fatia do percentual do job (na nuvem, a baixa ocupa o comeco)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    log = deque(maxlen=4)
    for linha in proc.stdout:
        texto = linha.decode("utf-8", "replace").strip()
        parte, sep, valor = texto.partition("=")
        if sep:
            if parte == "out_time_us" and dur_us:
                try:
                    pct = base + int(int(valor) * (teto - base) / dur_us)
                except ValueError:
                    continue
                with _lock:
                    j = _jobs.get(chave)
                    if j:
                        j["percent"] = max(0, min(teto, pct))
            continue
        if texto:
            log.append(texto)
    return proc.wait(), (log[-1] if log else "")


# ── Nuvem: baixa e palco ─────────────────────────────────────

def _baixar_remoto(remoto, destino, chave, base=0, teto=40):
    """Baixa um arquivo do 'rclone serve http' (localhost) para o disco.

    O canal e o mesmo que o proxy do handler usa: o serve escuta so no
    localhost, dentro da maquina. O progresso preenche a fatia base-teto
    do percentual do job — na nuvem, a baixa costuma ser a parte mais
    demorada de tudo."""
    url = ("http://localhost:%d/%s"
           % (RCLONE_SERVE_PORT, urllib.parse.quote(str(remoto).lstrip("/"),
                                                    safe="/")))
    try:
        resp = urllib.request.urlopen(url, timeout=120)
    except Exception as e:
        print("[12:00 Media Server] Baixa da nuvem falhou (%s): %s" % (remoto, e),
              flush=True)
        return False
    try:
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        feito = 0
        with open(destino, "wb") as saida:
            while True:
                pedaco = resp.read(1 << 22)          # 4 MiB por vez
                if not pedaco:
                    break
                saida.write(pedaco)
                feito += len(pedaco)
                if total:
                    pct = base + int((teto - base) * feito / total)
                    with _lock:
                        j = _jobs.get(chave)
                        if j:
                            j["percent"] = max(0, min(teto, pct))
    except OSError as e:
        print("[12:00 Media Server] Baixa da nuvem interrompida (%s): %s"
              % (remoto, e), flush=True)
        return False
    finally:
        resp.close()
    return total == 0 or feito == total


def _palco_nuvem(attrs, chave):
    """Baixa video + legenda da nuvem para o cache (copia de trabalho).

    Devolve {'video': path, 'sub': path|None} para o _convert usar como se
    fossem arquivos locais — o ffmpeg nao conversa com o rclone. O chamador
    apaga esses arquivos no fim (sucesso ou erro); so o MP4 persiste."""
    try:
        CAST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    video = CAST_CACHE_DIR / (attrs["chave"] + ".orig.video")
    if not _baixar_remoto(attrs["sig"]["remoto"], video, chave, 0, 40):
        try:
            video.unlink()
        except OSError:
            pass
        return None
    sub = None
    info_sub = (attrs.get("sig") or {}).get("sub")
    if info_sub:
        sub = (CAST_CACHE_DIR / ("%s.orig.legenda%s"
                                 % (attrs["chave"],
                                    Path(info_sub.get("nome") or "x")
                                    .suffix or ".srt")))
        if not _baixar_remoto(info_sub["remoto"], sub, chave, 40, 41):
            try:
                sub.unlink()
            except OSError:
                pass
            sub = None
    return {"video": video, "sub": sub}


def _cmd(src, info, dest, sub):
    ffmpeg = _ffmpeg_bin()
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-progress", "pipe:1", "-y",
           "-i", src]
    if sub:
        # Legenda sidecar como segundo input. Toda opcao de SAIDA vem depois
        # de todos os inputs — colocada entre eles, o ffmpeg a le como opcao
        # de input e barra arquivos.
        cmd += ["-i", str(sub)]

    cmd += ["-map", "0:%d" % info["vidx"]]
    if info.get("aidx") is not None:
        cmd += ["-map", "0:%d" % info["aidx"]]

    if info.get("v") in _VIDEO_COPIavel:
        cmd += ["-c:v", "copy"]
    else:
        # HEVC/Main10 e codecs exoticos caem aqui: e esta conversao que faz
        # o video APARECER na TV (com HEVC copiado so o audio tocava). O
        # crf 20 + veryfast converte a ~12x em tempo real no Mac; o
        # yuv420p baixa o 10-bit para 8-bit, formato que todo receptor le.
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p"]

    if info.get("aidx") is not None:
        if info.get("a") in _AUDIO_COPIavel:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "448k"]

    if sub:
        # Faixa "timed text" (mov_text) — o unico formato que o AVPlayer/
        # AirPlay le embutido. default: o receptor ja considera pronta para
        # ligar no menu do Apple TV.
        cmd += ["-map", "1:0", "-c:s", "mov_text", "-disposition:s:0", "default"]
    else:
        # -sn: sem legenda sidecar, as embutidas do MKV tambem nao vao —
        # receptores as ignoram de qualquer jeito.
        cmd += ["-sn"]

    # +faststart: moov no inicio — receptores buscam o container antes do
    # primeiro quadro e nao gostam de esperar o final do arquivo.
    cmd += ["-movflags", "+faststart", str(dest)]
    return cmd


# ── Limpeza ──────────────────────────────────────────────────

def _limpar_vencidos():
    """Joga fora conversoes de receitas antigas (sem a marca atual).

    Sem isso, um MP4 gerado pela receita anterior ficaria ocupando espaco
    para sempre: o prepared_file ja o considera invalido."""
    for meta in CAST_CACHE_DIR.glob("*.json"):
        try:
            dados = json.loads(meta.read_text("utf-8"))
        except Exception:
            continue
        if dados.get("prep") == _PREP_VERSION:
            continue
        try:
            meta.with_suffix(".mp4").unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
        except OSError:
            pass


def _cleanup():
    """Mantem o cache dentro do teto: mais antigos (menos usados) saem."""
    try:
        _limpar_vencidos()
        agora = time.time()
        # Restos de conversoes interrompidas por queda do servidor.
        for orfao in CAST_CACHE_DIR.glob("*.tmp.mp4"):
            try:
                if agora - orfao.stat().st_mtime > 3600:
                    orfao.unlink()
            except OSError:
                pass
        # Palcos de nuvem que sobraram de queda no meio de uma baixa
        # (o _convert os apaga em qualquer saida normal).
        for orfao in CAST_CACHE_DIR.glob("*.orig.*"):
            try:
                if agora - orfao.stat().st_mtime > 6 * 3600:
                    orfao.unlink()
            except OSError:
                pass

        itens = []
        for meta in CAST_CACHE_DIR.glob("*.json"):
            mp4 = meta.with_suffix(".mp4")
            try:
                st = mp4.stat()
                itens.append((meta, st, st.st_size))
            except OSError:
                itens.append((meta, None, 0))
        total = sum(t for _, _, t in itens)
        if total <= CAST_CACHE_MAX:
            return
        for meta, st, tamanho in sorted(
                itens, key=lambda i: i[1].st_mtime if i[1] else 0):
            if total <= CAST_CACHE_MAX * 0.8:
                break
            if st is not None and (agora - st.st_mtime) < 600:
                continue   # possivel transmissao em andamento
            try:
                meta.with_suffix(".mp4").unlink(missing_ok=True)
                meta.unlink(missing_ok=True)
                total -= tamanho
            except OSError:
                pass
    except Exception:
        pass
