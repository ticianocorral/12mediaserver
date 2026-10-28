"""Conexão da nuvem: qualquer remote rclone, configurado por um wizard.

A escolha do usuario mora no nuvem.json: qual remote do rclone usar e a pasta
de dentro dele onde esta o acervo. O remote pode ser um que ja existia no
rclone.conf (o wizard lista com "rclone listremotes") ou um criado ali mesmo,
com formulario gerado a partir de "rclone config providers" — o proprio rclone
descreve todos os backends que conhece e os campos de cada um.

O app nunca le segredos do rclone.conf: quando o wizard cria um remote, as
keys passam obscurecidas direto ao rclone. Desconectar apenas desliga o app
da nuvem — o remote do usuario e o acervo ficam intactos.

Modulo folha: importa config e paths.
"""

import json
import re
import subprocess

from .config import NUVEM_PATH
from .paths import rclone_conf_path, read_remote_conf, reset_nuvem_cache

_NOME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,29}$")


# ── nuvem.json (remote + pasta) ──────────────────────────────

def _carregar():
    """Conexão gravada, migrando o cadastro antigo de B2 se houver."""
    try:
        data = json.loads(NUVEM_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("remote"):
            return data
    except (OSError, ValueError):
        pass
    # Formato anterior (migração B2 -> genérico): b2.json guardava bucket e
    # pasta; o remote "b2" criado pelo app continua no rclone.conf.
    try:
        velho = json.loads(
            (NUVEM_PATH.parent / "b2.json").read_text(encoding="utf-8"))
        if isinstance(velho, dict) and velho.get("bucket"):
            pasta = "/".join(
                p for p in (str(velho.get("bucket") or "").strip("/"),
                            str(velho.get("pasta") or "").strip("/")) if p)
            dados = {"remote": "b2", "pasta": pasta}
            _gravar(dados)
            return dados
    except (OSError, ValueError):
        pass
    return {}


def _gravar(dados):
    import os
    tmp = NUVEM_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, NUVEM_PATH)
    try:
        os.chmod(NUVEM_PATH, 0o600)
    except OSError:
        pass


def _run(args, timeout=90):
    """rclone sem herdar output pra log: devolve (codigo, stdout, stderr)."""
    try:
        res = subprocess.run(["rclone"] + args, capture_output=True,
                             text=True, timeout=timeout)
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "tempo esgotado"
    except FileNotFoundError:
        return 127, "", "rclone nao esta instalado"


def _ultimo_erro(stderr):
    linhas = [l for l in (stderr or "").strip().splitlines() if l.strip()]
    return linhas[-1] if linhas else "falha desconhecida"


def _remotes_no_conf():
    secoes = set()
    try:
        for raw in rclone_conf_path().read_text(encoding="utf-8").splitlines():
            linha = raw.strip()
            if linha.startswith("[") and linha.endswith("]"):
                secoes.add(linha[1:-1])
    except OSError:
        pass
    return secoes


# ── API para o handler ───────────────────────────────────────

def status():
    """O que o painel mostra, sem segredos."""
    dados = _carregar()
    remote = str(dados.get("remote") or "")
    conf = read_remote_conf(remote) if remote else {}
    return {
        "configurado": bool(remote) and (conf.get("type") is not None),
        "remote": remote or None,
        "pasta": str(dados.get("pasta") or ""),
        "tipo": conf.get("type"),
    }


def listar_remotes():
    """Remotes que já existem no rclone.conf, com o tipo de cada um."""
    code, out, err = _run(["listremotes"])
    if code != 0:
        return [], _ultimo_erro(err)
    saida = []
    for linha in out.splitlines():
        nome = linha.strip().rstrip(":")
        if nome:
            saida.append({"nome": nome,
                          "tipo": read_remote_conf(nome).get("type") or "?"})
    return saida, None


def conectar(remote, pasta):
    """Aponta o app para um remote existente. Devolve (dict, erro)."""
    remote = (remote or "").strip().rstrip(":")
    pasta = (pasta or "").strip().strip("/")
    if not _NOME_RE.match(remote):
        return None, "Remote inválido."
    if remote not in _remotes_no_conf():
        return None, (f'O remote "{remote}" não existe no rclone.conf — '
                      "crie ele no wizard ou escolha outro da lista.")
    destino = remote + (":" + pasta if pasta else ":")
    code, _, err = _run(["lsd", destino, "--max-depth", "1"], timeout=60)
    if code != 0:
        detalhe = _ultimo_erro(err)
        if "directory not found" in detalhe.lower() or "404" in detalhe:
            return None, f'A pasta "{pasta}" não existe nesse remote.'
        return None, (f"O remote respondeu com erro ao listar: {detalhe}. "
                      "Confira as credenciais dele no rclone.")
    _gravar({"remote": remote, "pasta": pasta})
    reset_nuvem_cache()
    return {"remote": remote, "pasta": pasta}, None


def desconectar():
    """Desliga o app da nuvem. O remote e o acervo ficam intactos."""
    try:
        NUVEM_PATH.unlink()
    except OSError:
        pass
    reset_nuvem_cache()
    return {"status": "ok"}


def providers():
    """Catálogo de backends do próprio rclone, enxuto para o wizard."""
    code, out, err = _run(["config", "providers"], timeout=30)
    if code != 0:
        return None, _ultimo_erro(err)
    try:
        brutos = json.loads(out)
    except ValueError:
        return None, "Resposta inesperada do rclone config providers."
    saida = []
    for p in brutos:
        opcoes = []
        for o in p.get("Options", []):
            # Provider="" vale para o backend inteiro; variantes por provider
            # (ex.: S3 de cada fornecedor) o wizard não precisa — o campo
            # "provider" do backend cobre quando necessario.
            if o.get("Provider"):
                continue
            opcoes.append({
                "nome": o.get("Name", ""),
                "ajuda": (o.get("Help") or "").strip(),
                "padrao": str(o.get("Default") or ""),
                "senha": bool(o.get("IsPassword")),
                "obrigatorio": bool(o.get("Required")),
                "exemplos": [ex.get("Value") or ex.get("Help", "")
                             for ex in (o.get("Examples") or [])][:12],
            })
        saida.append({
            "tipo": p.get("Name", ""),
            "nome": p.get("Description") or p.get("Name", ""),
            "opcoes": opcoes,
        })
    saida.sort(key=lambda x: x["nome"].lower())
    return saida, None


def criar_remote(nome, tipo, parametros):
    """Cria um remote novo no rclone.conf pelo wizard. Devolve (dict, erro).

    Se o teste de leitura falhar depois de criar, o remote e apagado de volta:
    nao fica configuração quebrada no rclone.conf do usuario.
    """
    nome = (nome or "").strip()
    tipo = (tipo or "").strip()
    if not _NOME_RE.match(nome):
        return None, ("Nome de remote inválido — use letras, números, "
                      "hífen ou underline (até 30 caracteres).")
    if nome in _remotes_no_conf():
        return None, f'Já existe um remote chamado "{nome}" no rclone.conf.'
    catalogo, err = providers()
    if err:
        return None, err
    if not any(p["tipo"] == tipo for p in catalogo):
        return None, f'Tipo de remote "{tipo}" não existe nesse rclone.'
    args = ["config", "create", nome, tipo, "--non-interactive", "--obscure"]
    parametros = parametros or {}
    for opcao in next(p["opcoes"] for p in catalogo if p["tipo"] == tipo):
        valor = str(parametros.get(opcao["nome"]) or "").strip()
        if valor:
            args += [opcao["nome"], valor]
    code, _, err = _run(args, timeout=60)
    if code != 0:
        _run(["config", "delete", nome])
        return None, f"O rclone recusou a criação: {_ultimo_erro(err)}"
    code, _, err = _run(["lsd", nome + ":", "--max-depth", "1"], timeout=60)
    if code != 0:
        detalhe = _ultimo_erro(err)
        _run(["config", "delete", nome])
        return None, ("O remote foi criado, mas o teste de conexão falhou "
                      f"({detalhe}) — foi removido. Revise os valores.")
    return {"nome": nome, "tipo": tipo}, None
