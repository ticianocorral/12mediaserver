"""Registro das fontes do catalogo: o Drive e as pastas locais.

O Drive deixou de ser "a" fonte e passou a ser "uma" fonte. Cada fonte tem um
ponto de montagem no namespace logico que o DB e o frontend ja usam:

    Drive          /TicianoFlix/Terror/O Iluminado (1980)/filme.mkv
    HD externo     /Local/hd-externo/Terror/Alien (1979)/filme.mkv

O registro mora num JSON ao lado do auth.json, e nao no SQLite: fonte e
configuracao, nao cache — restaurar um backup feito em outra maquina nao pode
ressuscitar caminhos que so existiam la.

Modulo folha: importa apenas o config.
"""

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from .config import LOCAL_ROOT, LOGICAL_ROOT, RCLONE_REMOTE, SOURCES_PATH
from . import localfs as _localfs

DRIVE_ID = "drive"

_lock = threading.Lock()


# ── Persistencia ─────────────────────────────────────────────

def _load_raw():
    """Fontes locais gravadas, sem a fonte sintetica do Drive."""
    try:
        data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("id") and item.get("root"):
            out.append({
                "id": str(item["id"]),
                "kind": "local",
                "name": str(item.get("name") or item["id"]),
                "root": str(item["root"]),
                "mount": local_mount(str(item["id"])),
                "added_at": item.get("added_at", 0),
            })
    return out


def _save_raw(sources):
    payload = [{"id": s["id"], "name": s["name"], "root": s["root"],
                "kind": "local", "added_at": s.get("added_at", 0)}
               for s in sources]
    tmp = SOURCES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, SOURCES_PATH)
    try:
        os.chmod(SOURCES_PATH, 0o600)
    except OSError:
        pass


def drive_source():
    """A fonte sintetica do Drive — nao mora no JSON, sempre existe."""
    return {
        "id": DRIVE_ID,
        "kind": "drive",
        "name": "Google Drive",
        "root": RCLONE_REMOTE,
        "mount": LOGICAL_ROOT,
        "added_at": 0,
    }


def list_sources(include_drive=True):
    """Todas as fontes, o Drive primeiro."""
    with _lock:
        local = _load_raw()
    local.sort(key=lambda s: s["name"].lower())
    return ([drive_source()] if include_drive else []) + local


def local_sources():
    return list_sources(include_drive=False)


def local_mount(source_id):
    """Prefixo logico de uma fonte local."""
    return f"{LOCAL_ROOT}/{source_id}"


def get_source(source_id):
    for s in list_sources():
        if s["id"] == source_id:
            return s
    return None


# ── Cadastro ─────────────────────────────────────────────────

def _slugify(name):
    slug = name.strip().lower()
    for a, b in (("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"), ("é", "e"),
                 ("ê", "e"), ("í", "i"), ("ó", "o"), ("ô", "o"), ("õ", "o"),
                 ("ú", "u"), ("ç", "c")):
        slug = slug.replace(a, b)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "fonte"


def _unique_id(slug, taken):
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    return f"{slug}-{n}"


def _forbidden_roots():
    """Diretorios que nao podem virar fonte inteira.

    Cadastrar a raiz do sistema ou o home puro publicaria o computador inteiro
    na LAN via /api/stream para qualquer conta logada.
    """
    out = {Path(os.sep).resolve()}
    try:
        home = Path.home().resolve()
        out.add(home)
        out.add(home.parent)      # /Users, /home
    except (OSError, RuntimeError):
        pass
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            out.add(Path(f"{letter}:\\"))
    else:
        for p in ("/Volumes", "/media", "/mnt", "/run/media"):
            out.add(Path(p))
    return out


def validate_root(raw_root):
    """Normaliza e valida um caminho candidato. Devolve (Path, erro)."""
    raw = (raw_root or "").strip()
    if not raw:
        return None, "Informe o caminho da pasta."
    raw = os.path.expanduser(os.path.expandvars(raw))
    try:
        root = Path(raw).resolve()
    except (OSError, RuntimeError):
        return None, "Caminho invalido."
    if not root.exists():
        return None, f"A pasta nao existe: {root}"
    if not root.is_dir():
        return None, f"Isso nao e uma pasta: {root}"
    if root in _forbidden_roots():
        return None, ("Essa pasta e ampla demais para virar fonte — ela ficaria "
                      "acessivel na rede local. Aponte para a pasta dos filmes.")
    if not os.access(root, os.R_OK):
        return None, f"Sem permissao de leitura em: {root}"
    return root, None


def add_source(name, raw_root):
    """Cadastra uma fonte local. Devolve (fonte, erro).

    A fonte precisa conter uma pasta chamada "Mediaflix" (localfs.CATALOG_DIR_NAME)
    — a mesma convencao do Drive. Ela pode estar na pasta escolhida ou ate dois
    niveis abaixo, ja que o volume que o usuario seleciona costuma ficar acima
    do acervo ("/Volumes/MeuHD" com os filmes em "MeuHD/Filmes/Mediaflix/...").
    Uma pasta ja existente chamada "TicianoFlix" (o nome antigo) tambem serve —
    ninguem deveria ter que renomear nada no HD por causa de uma troca de marca.

    Sem essa pasta o cadastro e recusado: o scanner le a estrutura em posicao
    fixa, entao aceitar uma pasta qualquer produziria um catalogo vazio sem
    explicacao.
    """
    root, err = validate_root(raw_root)
    if err:
        return None, err

    catalog = _localfs.find_catalog_dir(root)
    if catalog is None:
        return None, (
            f'Nao encontrei uma pasta "{_localfs.CATALOG_DIR_NAME}" em {root}. '
            f"Crie uma pasta com esse nome e ponha os generos dentro dela "
            f"({_localfs.CATALOG_DIR_NAME.capitalize()}/Terror/Filme (2024)/filme.mkv) "
            "— e a mesma organizacao do Google Drive.")
    descended = catalog != root
    root = catalog

    with _lock:
        existing = _load_raw()
        for s in existing:
            try:
                other = Path(s["root"]).resolve()
            except (OSError, RuntimeError):
                continue
            if other == root:
                return None, f"Essa pasta ja esta cadastrada como \"{s['name']}\"."

        label = (name or "").strip() or root.name or "Fonte local"
        taken = {s["id"] for s in existing} | {DRIVE_ID}
        source_id = _unique_id(_slugify(label), taken)
        source = {
            "id": source_id,
            "kind": "local",
            "name": label,
            "root": str(root),
            "mount": local_mount(source_id),
            "added_at": time.time(),
            # Sinaliza pro handler avisar que a raiz nao foi a escolhida.
            "descended": descended,
        }
        existing.append(source)
        try:
            _save_raw(existing)
        except OSError as e:
            return None, f"Nao foi possivel gravar a configuracao: {e}"
    return source, None


def remove_source(source_id):
    """Descadastra uma fonte local. A poda do catalogo fica com o scanner."""
    if source_id == DRIVE_ID:
        return False
    with _lock:
        existing = _load_raw()
        keep = [s for s in existing if s["id"] != source_id]
        if len(keep) == len(existing):
            return False
        _save_raw(keep)
    return True


def rename_source(source_id, name):
    label = (name or "").strip()
    if not label or source_id == DRIVE_ID:
        return False
    with _lock:
        existing = _load_raw()
        for s in existing:
            if s["id"] == source_id:
                s["name"] = label
                _save_raw(existing)
                return True
    return False


# ── Resolucao de path ────────────────────────────────────────

def resolve(logical_path):
    """Path logico -> fonte dona dele, ou None se estiver fora de todas."""
    p = "/" + str(logical_path or "").strip("/")
    if p == LOGICAL_ROOT or p.startswith(LOGICAL_ROOT + "/"):
        return drive_source()
    if not p.startswith(LOCAL_ROOT + "/"):
        return None
    for s in local_sources():
        if p == s["mount"] or p.startswith(s["mount"] + "/"):
            return s
    return None


def under_local_root(logical_path):
    """True para qualquer path no namespace das fontes locais.

    Serve para distinguir "fonte removida" de "path do Drive": sem isso um
    /Local/... orfao cairia no ramo do rclone e voltaria um 502 confuso.
    """
    p = "/" + str(logical_path or "").strip("/")
    return p == LOCAL_ROOT or p.startswith(LOCAL_ROOT + "/")


def is_local(logical_path):
    src = resolve(logical_path)
    return bool(src and src["kind"] == "local")


def local_real_path(logical_path):
    """Path logico -> arquivo real no disco, confinado a raiz da fonte.

    Esta e a fronteira de seguranca da feature: /api/stream escuta na LAN, e sem
    o confinamento abaixo qualquer conta logada leria arquivo arbitrario da
    maquina. O resolve() antes da comparacao tambem barra symlink que aponte pra
    fora da fonte. Devolve None quando o caminho escapa — o handler traduz em 403.
    """
    src = resolve(logical_path)
    if not src or src["kind"] != "local":
        return None
    p = "/" + str(logical_path).strip("/")
    rel = p[len(src["mount"]):].strip("/")
    if "\x00" in rel:
        return None
    try:
        base = Path(src["root"]).resolve()
        target = (base / rel).resolve() if rel else base
        target.relative_to(base)
    except (ValueError, OSError, RuntimeError):
        return None
    return target


def is_online(source):
    """True quando o volume da fonte esta montado e legivel."""
    if source.get("kind") != "local":
        return True
    try:
        root = Path(source["root"])
        return root.is_dir() and os.access(root, os.R_OK)
    except OSError:
        return False


# ── Deteccao de volumes ──────────────────────────────────────

_SKIP_VOLUME_NAMES = {
    "com.apple.TimeMachine.localsnapshots", "Preboot", "Recovery", "VM",
    "Update", "xarts", "iSCPreboot", "Hardware",
}


def _candidate_dirs():
    """Diretorios plausiveis de midia, por plataforma."""
    out = []
    home = Path.home()
    if sys.platform == "darwin":
        out.append(("volume", Path("/Volumes")))
        out.append(("folder", home / "Movies"))
    elif os.name == "nt":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            if drive.is_dir():
                out.append(("volume:direct", drive))
        out.append(("folder", home / "Videos"))
    else:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
        for base in (f"/media/{user}", f"/run/media/{user}", "/media", "/mnt"):
            out.append(("volume", Path(base)))
        for name in ("Videos", "Vídeos", "Filmes"):
            out.append(("folder", home / name))
    return out


def detect_volumes():
    """Volumes conectados e pastas de midia que ainda nao sao fonte.

    So sugere: adicionar continua sendo um POST explicito de admin.
    """
    try:
        registered = {Path(s["root"]).resolve() for s in local_sources()}
    except (OSError, RuntimeError):
        registered = set()
    try:
        boot = Path(os.sep).resolve()
    except (OSError, RuntimeError):
        boot = None

    found = []
    seen = set()

    def offer(path, kind):
        try:
            real = path.resolve()
        except (OSError, RuntimeError):
            return
        if real in seen or real in registered or real == boot:
            return
        if not real.is_dir() or not os.access(real, os.R_OK):
            return
        if real.name in _SKIP_VOLUME_NAMES or real.name.startswith("."):
            return
        seen.add(real)
        found.append({"path": str(real), "name": real.name or str(real),
                      "kind": kind,
                      # Ja tem a pasta TicianoFlix dentro? A UI destaca essas,
                      # para o usuario nao clicar no que vai ser recusado.
                      "pronto": _localfs.has_catalog_dir(real)})

    for kind, base in _candidate_dirs():
        if kind == "volume:direct":
            offer(base, "volume")
            continue
        if kind == "folder":
            offer(base, "folder")
            continue
        try:
            entries = sorted(base.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            offer(entry, "volume")

    # As que ja estao prontas primeiro.
    found.sort(key=lambda c: (not c["pronto"], c["name"].lower()))
    return found
