#!/usr/bin/env python3
"""Instalador visual do 12:00 Media Server (Windows, Linux e macOS).

Um assistente que abre no navegador (a mesma pagina nos tres sistemas, so com a
biblioteca padrao do Python — nada de Tk nem de pacote extra). Passos:
boas-vindas, instalacao (dependencias, servico, Bonjour), conta de
administrador, nuvem e conclusao. Roda de dentro da pasta do projeto; os
atalhos Instalador-Media-Server.* na raiz chamam este arquivo.

  python3 instalador/instalador.py            abre o assistente
  python3 instalador/instalador.py --simular  percorre as telas sem instalar nada

A parte que mexe no sistema (passo_*) nao depende da pagina, e da para testar
sem navegador. O assistente so escuta em 127.0.0.1 e exige um token na URL.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import zipfile
from http.cookiejar import CookieJar
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NOME = "12:00 Media Server"
PORTA = int(os.environ.get("MEDIA_SERVER_PORT", "9187"))
HOME = Path.home()
CACHE = HOME / ".cache" / "media-server"
LOG = CACHE / "media-server.log"
SISTEMA = {"Darwin": "mac", "Linux": "linux", "Windows": "windows"}.get(platform.system(), "outro")
SIMULAR = "--simular" in sys.argv



# ─────────────────────────── passos (sem Tk) ───────────────────────────

class Falha(Exception):
    pass


def executar(cmd, **kw):
    """subprocess.run com saida capturada; levanta Falha com o erro legivel."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    if SISTEMA == "windows":
        kw.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(cmd, **kw)
    except (OSError, subprocess.SubprocessError) as e:
        raise Falha("%s: %s" % (cmd[0], e))
    return r


def bin_rclone_dir():
    if SISTEMA == "windows":
        return Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local")) / "rclone"
    return HOME / ".local" / "bin"


def achar_rclone():
    exe = shutil.which("rclone")
    if exe:
        return exe
    cand = bin_rclone_dir() / ("rclone.exe" if SISTEMA == "windows" else "rclone")
    return str(cand) if cand.exists() else None


def url_rclone():
    sis = {"mac": "osx", "linux": "linux", "windows": "windows"}[SISTEMA]
    m = platform.machine().lower()
    arq = "arm64" if m in ("arm64", "aarch64") else "amd64"
    base = os.environ.get("MEDIA_SERVER_RCLONE_BASE", "https://downloads.rclone.org")
    return "%s/rclone-current-%s-%s.zip" % (base, sis, arq)


def passo_rclone(log):
    """Garante o rclone (que fala com a nuvem). Baixa o binario oficial pra uma
    pasta do usuario — nao precisa de administrador."""
    exe = achar_rclone()
    if exe:
        log("rclone ja instalado: %s" % exe)
        return exe
    destino = bin_rclone_dir()
    destino.mkdir(parents=True, exist_ok=True)
    url = url_rclone()
    log("Baixando o rclone (%s)..." % url)
    zip_tmp = destino / "rclone-download.zip"
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(zip_tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        nome_bin = "rclone.exe" if SISTEMA == "windows" else "rclone"
        with zipfile.ZipFile(zip_tmp) as z:
            membro = next(n for n in z.namelist() if n.endswith("/" + nome_bin))
            with z.open(membro) as src, open(destino / nome_bin, "wb") as dst:
                shutil.copyfileobj(src, dst)
        if SISTEMA != "windows":
            (destino / nome_bin).chmod(0o755)
    except (OSError, urllib.error.URLError, StopIteration, zipfile.BadZipFile) as e:
        raise Falha("Nao consegui instalar o rclone (%s). Instale por rclone.org e rode de novo." % e)
    finally:
        try:
            zip_tmp.unlink()
        except OSError:
            pass
    log("rclone instalado em %s" % destino)
    return str(destino / nome_bin)


def passo_cache(log):
    for sub in ("images", "subs"):
        (CACHE / sub).mkdir(parents=True, exist_ok=True)
    (HOME / ".cache" / "rclone").mkdir(parents=True, exist_ok=True)
    log("Pastas de cache prontas (%s)" % CACHE)


def caminho_servico(rclone):
    """PATH que o servico precisa enxergar pra achar o rclone."""
    pastas = [str(Path(rclone).parent)] if rclone else []
    pastas += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return os.pathsep.join(dict.fromkeys(pastas))


def plist_mac(label, argumentos, diretorio=None, log_path=None, env_path=None):
    args = "".join("        <string>%s</string>\n" % a for a in argumentos)
    extra = ""
    if diretorio:
        extra += "    <key>WorkingDirectory</key>\n    <string>%s</string>\n" % diretorio
    if env_path:
        extra += ("    <key>EnvironmentVariables</key>\n    <dict>\n        <key>PATH</key>\n"
                  "        <string>%s</string>\n    </dict>\n" % env_path)
    if log_path:
        extra += ("    <key>StandardOutPath</key>\n    <string>%s</string>\n"
                  "    <key>StandardErrorPath</key>\n    <string>%s</string>\n" % (log_path, log_path))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n'
            '    <key>Label</key>\n    <string>%s</string>\n'
            '    <key>ProgramArguments</key>\n    <array>\n%s    </array>\n'
            '    <key>RunAtLoad</key>\n    <true/>\n    <key>KeepAlive</key>\n    <true/>\n'
            '%s</dict>\n</plist>\n' % (label, args, extra))


def mac_carregar(plist):
    uid = str(os.getuid())
    executar(["launchctl", "bootout", "gui/%s" % uid, str(plist)])
    r = executar(["launchctl", "bootstrap", "gui/%s" % uid, str(plist)])
    if r.returncode != 0:
        r = executar(["launchctl", "load", str(plist)])
    if r.returncode != 0:
        raise Falha("launchctl: %s" % (r.stderr or r.stdout).strip())


def passo_servico(log, rclone, iniciar_com_o_sistema=True):
    py = sys.executable
    env_path = caminho_servico(rclone)
    if SISTEMA == "mac":
        la = HOME / "Library" / "LaunchAgents"
        la.mkdir(parents=True, exist_ok=True)
        wrapper = RAIZ / "media-server"
        if shutil.which("clang") and (RAIZ / "media-server.c").exists():
            if not wrapper.exists() or (RAIZ / "media-server.c").stat().st_mtime > wrapper.stat().st_mtime:
                r = executar(["clang", "-O2", "-o", str(wrapper), str(RAIZ / "media-server.c")])
                log("Wrapper nativo compilado" if r.returncode == 0 else "Sem wrapper nativo (usando python3 direto)")
        argumentos = [str(wrapper)] if wrapper.exists() and os.access(wrapper, os.X_OK) else [py, "server.py"]
        plist = la / "com.mediaserver.plist"
        plist.write_text(plist_mac("com.mediaserver", argumentos, str(RAIZ), str(LOG), env_path))
        mac_carregar(plist)
        log("Servico instalado (LaunchAgent com.mediaserver)")
    elif SISTEMA == "linux":
        sd = HOME / ".config" / "systemd" / "user"
        sd.mkdir(parents=True, exist_ok=True)
        unidade = (
            "[Unit]\nDescription=%s\nAfter=network-online.target\nWants=network-online.target\n\n"
            "[Service]\nType=simple\nExecStart=%s server.py\nWorkingDirectory=%s\n"
            "Environment=PATH=%s\nRestart=on-failure\nRestartSec=5\n"
            "StandardOutput=journal\nStandardError=journal\n\n"
            "[Install]\nWantedBy=default.target\n" % (NOME, py, RAIZ, env_path))
        (sd / "media-server.service").write_text(unidade)
        executar(["systemctl", "--user", "daemon-reload"])
        executar(["systemctl", "--user", "enable", "media-server.service"] if iniciar_com_o_sistema
                 else ["systemctl", "--user", "disable", "media-server.service"])
        r = executar(["systemctl", "--user", "restart", "media-server.service"])
        if r.returncode != 0:
            raise Falha("systemd: %s" % (r.stderr or r.stdout).strip())
        log("Servico instalado (systemd --user media-server)")
    elif SISTEMA == "windows":
        bat = RAIZ / "Media-Server.bat"
        # O rclone instalado pelo assistente mora numa pasta que nao esta no PATH
        # do Windows; sem esta linha, o servidor iniciado pela tarefa agendada
        # (e nao por aqui) nao o enxergaria.
        linha_path = ('set "PATH=%s;%%PATH%%"\r\n' % Path(rclone).parent) if rclone else ""
        bat.write_text('@echo off\r\nchcp 65001 >nul\r\ncd /d "%s"\r\n%s"%s" server.py\r\n' % (RAIZ, linha_path, py))
        if iniciar_com_o_sistema:
            r = executar(["schtasks", "/Create", "/F", "/TN", "Media Server", "/SC", "ONLOGON",
                          "/RL", "LIMITED", "/TR", '"%s"' % bat])
            log("Tarefa agendada criada" if r.returncode == 0 else "Nao consegui criar a tarefa de inicio automatico")
        iniciar_windows(py, rclone)
        log("Servidor iniciado")
    else:
        raise Falha("Sistema nao suportado: %s" % platform.system())


def iniciar_windows(py, rclone):
    CACHE.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if rclone:
        env["PATH"] = str(Path(rclone).parent) + os.pathsep + env.get("PATH", "")
    saida = open(LOG, "ab")
    flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen([py, "server.py"], cwd=str(RAIZ), env=env, stdout=saida, stderr=saida,
                     creationflags=flags, close_fds=True)


def passo_bonjour(log):
    """Anuncia o servidor na rede pra TV achar sozinha (_media-server._tcp)."""
    if SISTEMA == "mac":
        la = HOME / "Library" / "LaunchAgents"
        plist = la / "com.mediaserver.mdns.plist"
        plist.write_text(plist_mac("com.mediaserver.mdns",
                                   ["/usr/bin/dns-sd", "-R", NOME, "_media-server._tcp", ".", str(PORTA)],
                                   log_path=str(CACHE / "mdns.log")))
        mac_carregar(plist)
        log("Anuncio Bonjour ativo")
    elif SISTEMA == "linux":
        avahi = shutil.which("avahi-publish")
        if not avahi:
            log("avahi-publish nao encontrado: pule o anuncio ou instale o pacote avahi-utils")
            return
        sd = HOME / ".config" / "systemd" / "user"
        (sd / "media-server-mdns.service").write_text(
            "[Unit]\nDescription=%s (Bonjour)\n\n[Service]\nExecStart=%s -s \"%s\" _media-server._tcp %d\n"
            "Restart=on-failure\n\n[Install]\nWantedBy=default.target\n" % (NOME, avahi, NOME, PORTA))
        executar(["systemctl", "--user", "daemon-reload"])
        executar(["systemctl", "--user", "enable", "--now", "media-server-mdns.service"])
        log("Anuncio Bonjour ativo (avahi)")
    elif SISTEMA == "windows":
        dnssd = shutil.which("dns-sd")
        if not dnssd:
            log("Bonjour nao instalado no Windows: a TV usa o endereco digitado (opcional)")
            return
        executar(["schtasks", "/Create", "/F", "/TN", "Media Server Bonjour", "/SC", "ONLOGON", "/RL",
                  "LIMITED", "/TR", '"%s" -R "%s" _media-server._tcp . %d' % (dnssd, NOME, PORTA)])
        log("Anuncio Bonjour agendado")


def esperar_servidor(log, segundos=40):
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/auth/status" % PORTA, timeout=2).read()
            return True
        except urllib.error.HTTPError:
            return True  # respondeu (401 = precisa de login, tambem vale)
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise Falha("O servidor nao respondeu em %ds. Veja o log: %s" % (segundos, LOG))


# ─────────────────────────── conta e nuvem ───────────────────────────

class Api:
    """Fala com o servidor recem-instalado, guardando o cookie da sessao."""

    def __init__(self):
        self.jar = CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def post(self, caminho, corpo):
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (PORTA, caminho), data=json.dumps(corpo).encode(),
            # O servidor so aceita escrita com Origin local (protecao contra CSRF).
            headers={"Content-Type": "application/json", "Origin": "http://localhost:%d" % PORTA},
            method="POST")
        try:
            with self.op.open(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read())
            except ValueError:
                return {"status": "error", "error": "HTTP %d" % e.code}
        except (urllib.error.URLError, OSError) as e:
            return {"status": "error", "error": str(e)}

    def get(self, caminho):
        try:
            with self.op.open("http://127.0.0.1:%d%s" % (PORTA, caminho), timeout=10) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read())
            except ValueError:
                return {}
        except (urllib.error.URLError, OSError):
            return {}


def precisa_de_conta(api):
    """True quando ainda nao existe administrador (o status diz configured=false)."""
    return api.get("/api/auth/status").get("configured") is False


def ler_codigo_de_instalacao():
    """O servidor imprime 'Codigo de instalacao: NNNNNN' no log ao subir sem
    administrador. O instalador le dali — e o mesmo que o usuario digitaria."""
    texto = ""
    try:
        texto = LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    if SISTEMA == "linux" and "Codigo de instalacao" not in texto:
        r = executar(["journalctl", "--user", "-u", "media-server", "-n", "200", "--no-pager"])
        texto = r.stdout or ""
    achados = re.findall(r"Codigo de instalacao:\s*(\d{6})", texto)
    return achados[-1] if achados else ""


def criar_administrador(api, usuario, senha):
    codigo = ler_codigo_de_instalacao()
    if not codigo:
        raise Falha("Nao achei o codigo de instalacao no log (%s)." % LOG)
    r = api.post("/api/auth/setup", {"username": usuario, "password": senha, "code": codigo})
    if r.get("status") != "ok":
        raise Falha(r.get("error") or "Nao foi possivel criar a conta.")


# Nuvens mais usadas com o rclone. Todas guardam por chave (nada de login pelo
# navegador): o app so liga num remote ja criado, e o assistente de Ajustes >
# Nuvem tambem so cria remotes assim. Google Drive, OneDrive e Dropbox pedem
# autorizacao no navegador e ficam pelo rclone (rclone config) ou pelo app.
# campo = (id, rotulo, segredo, valor padrao)
PROVEDORES = [
    {"id": "b2", "nome": "Backblaze B2", "detalhe": "armazenamento barato, o mais usado com o rclone",
     "campos": [("conta", "ID da chave (keyID)", False, ""), ("chave", "Chave de aplicação", True, ""),
                ("bucket", "Bucket", False, ""), ("pasta", "Pasta dentro do bucket (opcional)", False, "")]},
    {"id": "s3", "nome": "Amazon S3", "detalhe": "S3 da AWS",
     "campos": [("acesso", "Access key ID", False, ""), ("segredo", "Secret access key", True, ""),
                ("regiao", "Região", False, "us-east-1"), ("bucket", "Bucket", False, ""),
                ("pasta", "Pasta dentro do bucket (opcional)", False, "")]},
    {"id": "r2", "nome": "Cloudflare R2", "detalhe": "sem taxa de saída de dados",
     "campos": [("conta", "ID da conta Cloudflare", False, ""), ("acesso", "Access key ID", False, ""),
                ("segredo", "Secret access key", True, ""), ("bucket", "Bucket", False, ""),
                ("pasta", "Pasta dentro do bucket (opcional)", False, "")]},
    {"id": "wasabi", "nome": "Wasabi", "detalhe": "armazenamento compatível com S3",
     "campos": [("acesso", "Access key", False, ""), ("segredo", "Secret key", True, ""),
                ("regiao", "Região", False, "us-east-1"), ("bucket", "Bucket", False, ""),
                ("pasta", "Pasta dentro do bucket (opcional)", False, "")]},
]


def provedor(prov_id):
    return next((p for p in PROVEDORES if p["id"] == prov_id), None)


def parametros_remote(prov_id, c):
    """(tipo do rclone, nome do remote, parametros, pasta no remote) para a
    escolha do usuario. Levanta Falha se faltar um campo obrigatorio."""
    prov = provedor(prov_id)
    if prov is None:
        raise Falha("Provedor desconhecido.")
    c = {k: str(v or "").strip() for k, v in c.items()}
    for cid, rotulo, _seg, _val in prov["campos"]:
        if cid != "pasta" and not c.get(cid):
            raise Falha("Preencha: %s." % rotulo)
    pasta = "/".join(p for p in (c["bucket"].strip("/"), c.get("pasta", "").strip("/")) if p)
    if prov_id == "b2":
        return "b2", "b2", ["account=" + c["conta"], "key=" + c["chave"]], pasta
    if prov_id == "s3":
        return "s3", "s3", ["provider=AWS", "access_key_id=" + c["acesso"],
                            "secret_access_key=" + c["segredo"], "region=" + c["regiao"]], pasta
    if prov_id == "r2":
        return "s3", "r2", ["provider=Cloudflare", "access_key_id=" + c["acesso"],
                            "secret_access_key=" + c["segredo"], "region=auto", "no_check_bucket=true",
                            "endpoint=https://%s.r2.cloudflarestorage.com" % c["conta"]], pasta
    return "s3", "wasabi", ["provider=Wasabi", "access_key_id=" + c["acesso"],
                            "secret_access_key=" + c["segredo"], "region=" + c["regiao"],
                            "endpoint=s3.%s.wasabisys.com" % c["regiao"]], pasta


def conectar_nuvem(api, rclone, prov_id, campos):
    """Cria o remote no rclone e liga o app nele (mesmo caminho do assistente
    de Ajustes > Nuvem: config create ... --non-interactive --obscure)."""
    tipo, remote, params, pasta = parametros_remote(prov_id, campos)
    r = executar([rclone, "config", "create", remote, tipo] + params + ["--non-interactive", "--obscure"])
    if r.returncode != 0:
        raise Falha("rclone: %s" % (r.stderr or r.stdout).strip()[-300:])
    resp = api.post("/api/nuvem/conectar", {"remote": remote, "pasta": pasta})
    if resp.get("status") != "ok":
        raise Falha(resp.get("error") or "O app nao conseguiu usar essa nuvem.")


def endereco_na_rede():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return "http://%s:%d" % (ip, PORTA)
    except OSError:
        return ""


# ───────────────────────────── assistente web ─────────────────────────────

class Estado:
    """Tudo o que a pagina precisa saber, atras de um lock (a instalacao roda
    numa thread e a pagina pergunta o andamento por polling)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.linhas = []
        self.frac = 0.0
        self.etapa = ""
        self.rodando = False
        self.fim = False
        self.erro = None
        self.precisa_conta = False
        self.rclone = None
        self.api = Api()

    def log(self, txt):
        with self.lock:
            self.linhas.append(txt)

    def instantaneo(self, desde):
        with self.lock:
            return {"linhas": self.linhas[desde:], "total": len(self.linhas), "frac": self.frac,
                    "etapa": self.etapa, "rodando": self.rodando, "fim": self.fim, "erro": self.erro,
                    "precisa_conta": self.precisa_conta}


ESTADO = Estado()


def rodar_instalacao(opts):
    e = ESTADO
    with e.lock:
        if e.rodando:
            return
        e.rodando, e.fim, e.erro, e.frac = True, False, None, 0.0
        e.linhas.clear()

    def passo_deps():
        e.rclone = passo_rclone(e.log) if opts.get("deps") else achar_rclone()

    passos = [
        ("Dependências", passo_deps),
        ("Pastas de cache", lambda: passo_cache(e.log)),
        ("Serviço", lambda: passo_servico(e.log, e.rclone, bool(opts.get("auto")))),
        ("Anúncio na rede", lambda: passo_bonjour(e.log) if opts.get("bonjour") else None),
        ("Aguardando o servidor", lambda: (esperar_servidor(e.log),
                                           e.log("Servidor no ar em http://localhost:%d" % PORTA))),
    ]
    try:
        for i, (nome, fn) in enumerate(passos):
            with e.lock:
                e.etapa = nome
            if SIMULAR:
                e.log("[simulação] %s" % nome)
                time.sleep(0.8)
            else:
                fn()
            with e.lock:
                e.frac = (i + 1) / len(passos)
        precisa = SIMULAR or precisa_de_conta(e.api)
        with e.lock:
            e.precisa_conta, e.fim = precisa, True
    except Falha as ex:
        with e.lock:
            e.erro = str(ex)
    except Exception as ex:  # inesperado: mostra na pagina em vez de morrer calado
        with e.lock:
            e.erro = "%s: %s" % (type(ex).__name__, ex)
    finally:
        with e.lock:
            e.rodando = False


class Assistente(BaseHTTPRequestHandler):
    token = ""
    porta = 0
    servidor = None

    def log_message(self, *a):
        pass

    def _host_ok(self):
        return (self.headers.get("Host") or "") in ("127.0.0.1:%d" % self.porta, "localhost:%d" % self.porta)

    def _responder(self, corpo, tipo="application/json; charset=utf-8", codigo=200):
        dados = corpo if isinstance(corpo, bytes) else corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(dados)

    def _json(self, obj, codigo=200):
        self._responder(json.dumps(obj, ensure_ascii=False), codigo=codigo)

    def _autorizado(self):
        if not self._host_ok():
            self._responder(b"host invalido", "text/plain", 403)
            return False
        if self.headers.get("X-Token") != self.token:
            self._responder(b"token invalido", "text/plain", 403)
            return False
        return True

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if not self._host_ok():
            return self._responder(b"host invalido", "text/plain", 403)
        if u.path == "/":
            if parse_qs(u.query).get("t", [""])[0] != self.token:
                return self._responder("Abra o endereço completo que o instalador mostrou no terminal.",
                                       "text/plain; charset=utf-8", 403)
            html = (Path(__file__).parent / "assistente.html").read_text(encoding="utf-8")
            return self._responder(html.replace("__TOKEN__", self.token).replace("__NOME__", NOME)
                                   .replace("__SIMULAR__", "true" if SIMULAR else "false"),
                                   "text/html; charset=utf-8")
        if u.path == "/logo.svg":
            return self._responder((RAIZ / "static" / "wordmark.svg").read_bytes(), "image/svg+xml")
        if not self._autorizado():
            return
        if u.path == "/api/progresso":
            desde = int(parse_qs(u.query).get("desde", ["0"])[0] or 0)
            return self._json(ESTADO.instantaneo(desde))
        if u.path == "/api/provedores":
            return self._json([{"id": p["id"], "nome": p["nome"], "detalhe": p["detalhe"],
                                "campos": [{"id": i, "rotulo": r, "segredo": s, "valor": v}
                                           for i, r, s, v in p["campos"]]} for p in PROVEDORES])
        if u.path == "/api/info":
            return self._json({"sistema": SISTEMA, "porta": PORTA, "rede": endereco_na_rede(), "nome": NOME})
        self._responder(b"nao encontrado", "text/plain", 404)

    def do_POST(self):
        if not self._autorizado():
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            corpo = {}
        e = ESTADO
        if self.path == "/api/instalar":
            threading.Thread(target=rodar_instalacao, args=(corpo,), daemon=True).start()
            return self._json({"status": "ok"})
        try:
            if self.path == "/api/conta":
                if corpo.get("senha") != corpo.get("repete"):
                    raise Falha("As senhas não conferem.")
                if not SIMULAR:
                    criar_administrador(e.api, str(corpo.get("usuario", "")).strip().lower(), str(corpo.get("senha", "")))
                return self._json({"status": "ok"})
            if self.path == "/api/nuvem":
                prov_id = str(corpo.get("provedor", ""))
                campos = corpo.get("campos") if isinstance(corpo.get("campos"), dict) else {}
                if SIMULAR:
                    parametros_remote(prov_id, campos)  # valida os campos mesmo na simulacao
                else:
                    rc = e.rclone or achar_rclone()
                    if not rc:
                        raise Falha("rclone não encontrado.")
                    conectar_nuvem(e.api, rc, prov_id, campos)
                return self._json({"status": "ok"})
            if self.path == "/api/sair":
                self._json({"status": "ok"})
                threading.Thread(target=self.servidor.shutdown, daemon=True).start()
                return
        except Falha as ex:
            return self._json({"status": "error", "error": str(ex)}, 400)
        self._responder(b"nao encontrado", "text/plain", 404)


def porta_livre(inicio=9190):
    for p in range(inicio, inicio + 40):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise Falha("Nao achei uma porta livre para o assistente.")


def main():
    if not (RAIZ / "server.py").exists():
        print("Rode a partir da pasta do projeto (nao achei server.py em %s)." % RAIZ)
        return 1
    if sys.version_info < (3, 7):
        print("Precisa do Python 3.7 ou mais novo.")
        return 1
    token = secrets.token_urlsafe(16)
    try:
        porta = porta_livre()
    except Falha as e:
        print(e)
        return 1
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Assistente)
    Assistente.token, Assistente.porta, Assistente.servidor = token, porta, srv
    url = "http://localhost:%d/?t=%s" % (porta, token)
    print("\n  %s — instalador\n  Abrindo o assistente no navegador:\n  %s\n\n  (Ctrl+C aqui encerra.)\n" % (NOME, url))
    if not SIMULAR or os.environ.get("MEDIA_SERVER_ABRIR", "1") == "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
