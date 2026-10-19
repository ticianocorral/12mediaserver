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
(~/.cache/ticianoflix/cast). So a primeira transmissao de cada arquivo
espera; depois e instantaneo. Se o arquivo de origem mudar (mtime/tamanho),
o cache vence sozinho e uma nova conversao acontece.
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
from collections import deque
from pathlib import Path

from . import keepawake
from .config import CAST_CACHE_DIR

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


def _legenda_de(src):
    """Legenda sidecar do video (mesmo nome, mesma pasta), ou None.

    O padrao do acervo e "Filme (2020).mkv" + "Filme (2020).srt"; um sufixo
    de idioma no meio ("Filme (2020).pt.srt") tambem vale. Prioridade: o
    homonimo .srt, depois qualquer .srt do mesmo nome, depois os outros.
    """
    try:
        pasta = Path(src).parent
        stem = Path(src).stem
        candidatos = [p for p in pasta.iterdir()
                      if p.is_file() and p.suffix.lower() in _EXT_LEGENDA]
    except OSError:
        return None
    if not candidatos:
        return None
    prefixo = [p for p in candidatos if p.stem.lower().startswith(stem.lower())]
    srt = [p for p in prefixo if p.suffix.lower() == ".srt"]
    homonimo = [p for p in srt if p.stem == stem]
    if homonimo:
        return sorted(homonimo)[0]
    if srt:
        return sorted(srt)[0]
    return sorted(prefixo)[0] if prefixo else None


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

def _cache_paths(src):
    """MP4 + meta do cache e a legenda do video.

    A chave soma src + legenda (path/mtime/tamanho): trocar ou editar o .srt
    invalida a conversao sem tocar no resto."""
    sub = _legenda_de(src)
    sig = _assinatura_legenda(sub)
    texto = "%s\n%s" % (src, json.dumps(sig, sort_keys=True) if sig else "-")
    chave = hashlib.sha1(texto.encode("utf-8")).hexdigest()
    return (CAST_CACHE_DIR / (chave + ".mp4"),
            CAST_CACHE_DIR / (chave + ".json"), sub)


def prepared_file(path):
    """Path do MP4 convertido, se ainda existir e corresponder a fonte.

    Tambem confere a legenda: mudou o .srt, invalida sozinho. Um MP4 vindo
    de conversao que descartou a legenda com erro (sub_erro no meta) fica
    disponivel em modo degradado: melhor sem faixa de texto do que sem video."""
    if not path:
        return None
    mp4, meta, sub = _cache_paths(path)
    sig = _assinatura_legenda(sub)
    try:
        dados = json.loads(meta.read_text("utf-8"))
    except Exception:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    if dados.get("prep") != _PREP_VERSION:
        return None
    if dados.get("mtime") != int(st.st_mtime) or dados.get("size") != st.st_size:
        return None
    gravado = dados.get("sub")
    if gravado != sig:
        return None
    # sub_erro (quando existe) diz que a conversao descartou a legenda ruim:
    # o MP4 vale, so nao tem faixa de texto. Trocar/editar o .srt muda a
    # assinatura, invalida a meta e a proxima conversao tenta de novo.
    if not mp4.is_file():
        return None
    return mp4


def mark_used(path):
    """Atualiza o mtime do cache: a limpeza LRU usa isso como 'uso'."""
    mp4, _, _ = _cache_paths(path)
    try:
        os.utime(mp4, None)
    except OSError:
        pass


# ── Status publico ───────────────────────────────────────────

def _publico(job):
    return {"needed": True, "state": job["state"],
            "percent": int(job.get("percent", 0)),
            "error": job.get("error") or ""}


def status(path, enqueue=False):
    """Estado do preparo para a TV.

    needed=False  -> o original toca direto (ou nao ha como sondar); o
                     chamador segue com /api/stream como sempre.
    state: 'none' | 'ready' | 'queued' | 'converting' | 'error' | 'idle'
    ('idle' = precisa converter mas nada agendado — o servidor reiniciou
    no meio; com enqueue=True isso nao acontece).
    """
    if not path:
        return {"needed": False, "state": "none"}
    with _lock:
        job = _jobs.get(path)
        if job:
            if not (job["state"] == "error" and enqueue):
                return _publico(job)
            _jobs.pop(path, None)   # novo pedido = nova tentativa

    if prepared_file(path):
        return {"needed": True, "state": "ready", "percent": 100}

    sub = _legenda_de(path)
    info = _probe(path)
    if info is None or not _precisa(info, path, sub):
        return {"needed": False, "state": "none"}
    # Sem ffmpeg na maquina o preparo nao existe: transmissao segue como
    # antes (arquivo original), sem travar o usuario.
    if not _ffmpeg_bin() or not _ffprobe_bin():
        return {"needed": False, "state": "none"}

    if enqueue:
        _enqueue(path)
        with _lock:
            job = _jobs.get(path)
            return _publico(job) if job else {"needed": True, "state": "idle"}
    return {"needed": True, "state": "idle"}


# ── Fila e worker ────────────────────────────────────────────

def _enqueue(path):
    global _worker_ligado
    with _lock:
        if path in _jobs or _fila_contem(path):
            return
        _jobs[path] = {"state": "queued", "percent": 0, "error": ""}
        _fila.append(path)
        if not _worker_ligado:
            _worker_ligado = True
            threading.Thread(target=_worker, name="ticianoflix-prepare",
                             daemon=True).start()
    print("[TicianoFlix] Preparo para TV na fila: %s" % Path(path).name,
          flush=True)


def _fila_contem(path):
    return any(p == path for p in _fila)


def _worker():
    global _worker_ligado
    while True:
        with _lock:
            if not _fila:
                _worker_ligado = False
                return
            path = _fila.popleft()
        try:
            _convert(path)
        except Exception as e:   # o worker nunca morre com job preso
            with _lock:
                job = _jobs.get(path)
                if job:
                    job.update(state="error", error=str(e)[:300])
            print("[TicianoFlix] Falha preparando %s: %s"
                  % (Path(path).name, e), flush=True)


def _convert(path):
    with _lock:
        job = _jobs.get(path)
        if job is None:
            return
        job.update(state="converting", percent=0, error="")

    tmp = None
    try:
        info = _probe(path)
        sub = _legenda_de(path)       # atual na hora da conversao (nao a da fila)
        if info is None or not _precisa(info, path, sub):
            with _lock:
                _jobs.pop(path, None)
            return

        mp4, meta, _ = _cache_paths(path)
        # Nome único por processo: se duas conversões do mesmo arquivo
        # correrem juntas (servidor + uma sessão manual, por exemplo), cada
        # uma escreve no seu tmp e o os.replace() fica com a última — sem
        # uma sobrescrever o arquivo da outra no meio.
        tmp = mp4.with_name("%s.tmp.%d.mp4" % (mp4.name, os.getpid()))
        cmd = _cmd(path, info, tmp, sub)
        print("[TicianoFlix] Preparando para TV: %s (video %s, audio %s%s)"
              % (Path(path).name, info.get("v"), info.get("a") or "sem",
                 ", legenda %s" % Path(sub).name if sub else ""),
              flush=True)

        dur_us = (info.get("duration") or 0) * 1_000_000
        sub_erro = None
        with keepawake.while_streaming():
            codigo, log_ultimo = _rodar(_cmd(path, info, tmp, sub), path, dur_us)
            if codigo != 0 and sub:
                # Legenda ruim nao pode derrubar o filme: refaz sem a faixa
                # de texto e marca sub_erro — o cache segue valendo.
                sub_erro = log_ultimo or ("codigo %d" % codigo)
                print("[TicianoFlix] Legenda %s invalida, preparando sem ela"
                      % Path(sub).name, flush=True)
                codigo, log_ultimo = _rodar(_cmd(path, info, tmp, None),
                                            path, dur_us)

        if codigo != 0:
            raise RuntimeError("ffmpeg falhou: "
                               + (log_ultimo or "codigo %d" % codigo))

        st = os.stat(path)
        os.replace(tmp, mp4)
        dados_meta = {
            "path": path,
            "prep": _PREP_VERSION,
            "mtime": int(st.st_mtime),
            "size": st.st_size,
            "v": info.get("v"),
            "a": info.get("a"),
            "created": int(time.time()),
            # "sub" e a legenda tentada (mesmo quando descartada); sub_erro
            # marca o discard — o MP4 sai sem faixa de texto mas continua
            # valendo (ver prepared_file).
            "sub": _assinatura_legenda(sub),
        }
        if sub_erro:
            dados_meta["sub_erro"] = sub_erro[:200]
        meta.write_text(json.dumps(dados_meta), "utf-8")
        with _lock:
            _jobs.pop(path, None)
        print("[TicianoFlix] Pronto para TV: %s" % Path(path).name, flush=True)
        _cleanup()
    except Exception as e:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        with _lock:
            j = _jobs.get(path)
            if j:
                j.update(state="error", error=str(e)[:300])
        print("[TicianoFlix] Falha preparando %s: %s"
              % (Path(path).name, e), flush=True)


def _rodar(cmd, path, dur_us):
    """Roda o ffmpeg lendo o progresso; devolve (codigo, ultima linha de erro).

    Separado de _convert porque a segunda tentativa (sem legenda) repete a
    mesma leitura de progresso."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    log = deque(maxlen=4)
    for linha in proc.stdout:
        texto = linha.decode("utf-8", "replace").strip()
        chave, sep, valor = texto.partition("=")
        if sep:
            if chave == "out_time_us" and dur_us:
                try:
                    pct = int(int(valor) * 100 / dur_us)
                except ValueError:
                    continue
                with _lock:
                    j = _jobs.get(path)
                    if j:
                        j["percent"] = max(0, min(99, pct))
            continue
        if texto:
            log.append(texto)
    return proc.wait(), (log[-1] if log else "")


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
