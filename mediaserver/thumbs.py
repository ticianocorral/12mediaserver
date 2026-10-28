"""Miniaturas de imagem para o grid.

Os posteres do acervo (locais ou do cache da nuvem) tem de centenas de KB
a poucos MB; a home mostra dezenas deles em cartoes de ~300 px e cada
navegador pagava o arquivo inteiro. Na primeira visualizacao geramos uma
miniatura de 640 px e guardamos em IMAGE_CACHE_DIR/thumbs — assim "Limpar
cache de imagens" leva as miniaturas junto, e o backup ignora a pasta
(arquivo derivado, regeneravel).

O Python padrao nao tem biblioteca de imagem; quem redimensiona e o sips
do macOS. Onde ele nao existir (Linux/Windows) — ou qualquer passo falhar
— a funcao devolve None e o chamador serve o original: nada quebra.
"""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .config import IMAGE_CACHE_DIR

THUMBS_DIR = IMAGE_CACHE_DIR / "thumbs"

# Lado maior: cobre com folga o cartao de grid (~300 px) e o poster da
# ficha; daí pra cima o ganho de bytes nao paga a perda de nitidez.
MAX_PX = 640

# Imagem menor que isso ja e leve — converter nao compensa.
MIN_BYTES = 200 * 1024


def miniatura_para(orig, tipo=""):
    """Caminho da miniatura de `orig`, gerando-a se preciso.

    Devolve None (serve o original) quando: nao ha sips, a imagem e leve,
    o tipo e fanart (fundo de tela em tamanho cheio) ou algo falhou.
    """
    if tipo == "fanart" or shutil.which("sips") is None:
        return None
    try:
        orig = Path(orig)
        suf = orig.suffix.lower()
        if suf == ".gif":
            return None   # pode ser animado; achatar pra 1 quadro seria errado
        st = orig.stat()
        if st.st_size < MIN_BYTES:
            return None
        ext = ".png" if suf == ".png" else ".jpg"
        dest = THUMBS_DIR / f"{_chave(orig)}_{st.st_mtime_ns}_{st.st_size}{ext}"
        if dest.exists():
            return dest
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + f".{os.getpid()}.tmp")
        if ext == ".png":
            fmt = ["-s", "format", "png"]
        else:
            fmt = ["-s", "format", "jpeg", "-s", "formatOptions", "82"]
        r = subprocess.run(
            ["sips", "-Z", str(MAX_PX)] + fmt + [str(orig), "--out", str(tmp)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if r.returncode != 0 or not tmp.exists() or \
                tmp.stat().st_size >= st.st_size:
            # Falhou, ou a "miniatura" ficou maior que o original: desiste.
            _apagar(tmp)
            return None
        os.replace(tmp, dest)
        _limpar_versoes_antigas(orig, dest)
        return dest
    except Exception:
        return None


def _chave(orig):
    return hashlib.sha1(str(orig).encode("utf-8")).hexdigest()[:20]


def _apagar(p):
    try:
        p.unlink()
    except OSError:
        pass


def _limpar_versoes_antigas(orig, dest):
    """Apaga miniaturas de versoes antigas (mtime/tamanho velhos) da imagem."""
    try:
        for velha in THUMBS_DIR.glob(_chave(orig) + "_*"):
            if velha != dest and ".tmp" not in velha.name:
                _apagar(velha)
    except OSError:
        pass
