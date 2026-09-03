<div align="center">
  <h1>🎬 TicianoFlix</h1>
  <p><strong>Netflix-style movie player for Google Drive, external drives and USB sticks — self-hosted, lightweight, instant.</strong></p>
  <p>
    <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/rclone-1.60%2B-green" alt="rclone 1.60+">
    <img src="https://img.shields.io/badge/version-1.6-red" alt="v1.6">
    <img src="https://img.shields.io/badge/license-MIT-yellow" alt="MIT License">
  </p>
</div>

---

## 📖 Sobre

TicianoFlix é um servidor web auto-hospedado que transforma seu **Google Drive** — e também **HD externo, pendrive ou pastas do próprio computador** — num catálogo de filmes no estilo Netflix. Ele escaneia pastas organizadas por gênero, extrai metadados de arquivos NFO (formato Kodi/tinyMediaManager), e serve tudo via uma interface web bonita e responsiva.

### ✨ Funcionalidades

- **🔐 Login com contas** — usuário e senha por pessoa, sessão de 90 dias por aparelho, sem auto-cadastro
- **👥 Painel de contas** — administradores adicionam, removem, promovem e redefinem senhas
- **💽 Fontes locais** — HD externo, pendrive e pastas do computador entram no mesmo catálogo, sem subir nada pra nuvem
- **📁 Scan manual** — o botão **Atualizar** varre todas as fontes; cada uma também pode ser escaneada sozinha em **⚙️ Ajustes › 💽 Fontes**. Protegido contra scans concorrentes
- **🎞️ Streaming direto** via `rclone serve http` — sem downloads, sem buffers infinitos
- **💾 Cache SQLite** — navegação instantânea após o primeiro scan
- **📥 Download em background** — pause o filme e o cache VFS continua baixando
- **📦 Baixados do Drive** — filmes da nuvem 100% cacheados ganham selo e seção própria na home (filmes de fonte local não entram: eles já estão no disco)
- **🧹 Limpar cache** — apaga os vídeos baixados, dentro do próprio gerenciador de cache
- **🗺️ Navegação com histórico** — botões Voltar/Avançar do navegador funcionam dentro do app
- **💾 Backup & Restore** — modal com opções: salvar backup, upload pro Drive, restaurar de arquivo ou do Drive
- **🏷️ Metadados NFO** — suporte a posters, fanarts, sinopse, elenco, avaliação (formato Kodi / tinyMediaManager)
- **🎬 Coleções** — Star Wars 1-6 e afins agrupados numa tela só, ordenados por ano. Vem da tag `<set>` do NFO (o tinyMediaManager grava sozinho): nenhuma pasta muda de lugar, os filmes continuam cada um no seu gênero. Capa própria opcional via `movieset-poster.jpg`; sem ela, usa o cartaz do filme mais antigo
- **🔍 Busca** por título com debounce
- **📱 Responsivo de verdade** — no celular a barra lateral vira gaveta, os controles do player se reorganizam em duas faixas (nada de botão fora da tela) e tudo responde a toque
- **🔄 Serviço systemd** — inicia automaticamente no login
- **🎨 Fontes Roboto** — tipografia moderna via Google Fonts
- **🚪 Modal de confirmação** ao sair do player (sem `confirm()` nativo)
- **📺 Chromecast** — envio para a TV com URL assinada e legendas; a TV mostra pôster, ano e sinopse, e os controles do app comandam a transmissão (play, avançar, volume, legenda)
- **📡 AirPlay** — no iPhone, onde o Chromecast não funciona (limitação da Apple, não do app), o botão de AirPlay aparece no lugar; usa a mesma URL assinada, direto do `<video>`, sem SDK

---

## 🚀 Instalação Rápida

### Pré-requisitos

- **Python 3.9+**
- Linux (systemd) · macOS (LaunchAgent) · Windows — veja abaixo

É só isso. O TicianoFlix funciona com filmes que já estão no seu computador, num
HD externo ou num pendrive — veja [Fontes locais](#fontes-locais-hd-externo-pendrive-pasta-do-computador).

O **Google Drive é opcional** e entra depois, quando você quiser: precisa do
rclone e de uma autorização no Google, e dá pra fazer tudo pelo próprio
TicianoFlix, em **⚙️ Ajustes › ☁️ rclone**. Sem ele nada deixa de funcionar —
o servidor sobe igual e nem tenta contato com o Drive.

### 1. (Opcional) Configurar o Google Drive no rclone

```bash
rclone config
```

Crie um remote chamado `gdrive:` com:
- Tipo: `drive`
- Escopo: **`drive.readonly`** — o TicianoFlix só lê
- Autenticação via OAuth no navegador

> ⚠️ O assistente do rclone oferece `drive` como padrão, que dá **leitura e
> escrita no seu Drive inteiro**. O TicianoFlix não precisa disso. Se você já
> criou o remote assim, o instalador oferece corrigir — e o painel **☁️ rclone**
> avisa enquanto estiver largo. Veja [Acesso ao Google Drive](#acesso-ao-google-drive).

> 💡 Depois de instalado, dá pra configurar pelo próprio TicianoFlix:
> **⚙️ Ajustes › ☁️ rclone** no menu lateral — ele mostra o status (instalado,
> remote `gdrive:`, streaming, **acesso ao Drive**) e abre o configurador
> oficial do rclone (web GUI) pra criar o remote sem usar o terminal.

### 2. Instalar

**Linux e macOS**, com um comando só — não precisa clonar nada:

```bash
curl -fsSL https://raw.githubusercontent.com/ticianocorral/TicianoFlix/main/install.sh | bash
```

> O repositório está privado no momento, então esse comando só funciona para
> quem já tem acesso autenticado a ele. Enquanto isso, clone e rode local:
>
> ```bash
> git clone https://github.com/ticianocorral/TicianoFlix.git
> cd TicianoFlix
> bash install.sh
> ```
>
> O script detecta os dois casos sozinho — rodando de dentro de um clone ele
> usa esse clone; rodando via `curl | bash` ele baixa o projeto.

O mesmo `install.sh` cuida de tudo, nos dois sistemas:
- Verifica o Python (3.9+; instala pelo gerenciador de pacotes se faltar)
- No Linux, cria o serviço systemd e ativa persistência sem login (`linger`)
- No macOS, cria o LaunchAgent `com.ticianoflix` (inicia no login, reinicia se cair)
- Sobe o servidor, espera ele responder e **mostra o código de instalação na
  própria tela** — sem precisar abrir o log
- Abre o navegador no endereço certo

Não pede nada de Google Drive nem de rclone — isso é totalmente opcional, veja
a seção [Fontes locais](#fontes-locais-hd-externo-pendrive-pasta-do-computador)
e [Google Drive](#1-opcional-configurar-o-google-drive-no-rclone) acima.

**Windows:** baixe o projeto e rode `install-windows.bat` de dentro da pasta.

Logs em `~/.cache/ticianoflix/ticianoflix.log` (macOS/Linux).

Comandos úteis:
```bash
# Reiniciar
launchctl kickstart gui/$(id -u)/com.ticianoflix
# Parar/desativar
launchctl bootout gui/$(id -u)/com.ticianoflix
```

**Windows (Task Scheduler opcional):**

```bat
git clone https://github.com/seu-usuario/ticianoflix.git
cd ticianoflix
install-windows.bat
```

O instalador verifica/instala Python e rclone (winget ou download oficial),
cria o `TicianoFlix.bat` na pasta do projeto e pergunta se você quer iniciar
junto com o Windows (tarefa agendada no login) e se quer iniciar agora.

### 3. Primeiro acesso

Na primeira execução o servidor imprime um **código de instalação** de 6 dígitos no log:

```
  ──────────────────────────────────────────────
  PRIMEIRO ACESSO — crie a conta de administrador
  Codigo de instalacao: 249768
  Abra o endereco acima e informe esse codigo.
  ──────────────────────────────────────────────
```

Onde ver o log:

```bash
# Linux
journalctl --user -u ticianoflix -n 20

# macOS
tail -20 ~/.cache/ticianoflix/ticianoflix.log
```

Abra **http://localhost:9187**, informe o código e escolha usuário e senha. Essa
conta vira o administrador.

O código existe para fechar a janela em que qualquer pessoa na sua rede poderia
criar a conta inicial antes de você — quem não tem acesso ao terminal da máquina
não passa dessa tela. Depois disso o código não vale mais: contas novas só pelo
painel **⚙️ Ajustes › 👥 Contas**.

Feito o login, clique em 🔄 para escanear seu Drive.

### 4. Criar contas para a casa

Em **⚙️ Ajustes › 👥 Contas** (visível apenas para administradores) dá para
adicionar pessoas, remover, promover a administrador e redefinir senhas.
Não existe auto-cadastro: só quem está nessa lista consegue entrar.

Remover uma conta encerra as sessões dela na hora. O mesmo vale para redefinir
a senha de alguém.

---

## 🛠️ Uso

### Comandos do serviço

```bash
# Status
systemctl --user status ticianoflix

# Logs
journalctl --user -u ticianoflix -f

# Reiniciar (após alterar server.py)
systemctl --user restart ticianoflix

# Parar
systemctl --user stop ticianoflix
```

### Estrutura do Google Drive

Organize seus filmes assim no Drive:

```
TicianoFlix/
├── Acervo/
│   ├── Filme A (2024)/
│   │   ├── Filme A (2024).mp4
│   │   ├── poster.jpg
│   │   └── Filme A (2024).nfo
│   └── Filme B (2023)/
├── Ficção Científica/
├── Terror/
├── Shows/
└── Trash/
```

### Fontes locais (HD externo, pendrive, pasta do computador)

O Drive não precisa ser o único acervo. Em **⚙️ Ajustes › 💽 Fontes do acervo** (só para
administradores) dá pra apontar o TicianoFlix para qualquer pasta da máquina:

- os **volumes conectados** aparecem prontos pra adicionar com um clique
  (`/Volumes` no macOS, `/media` e `/run/media` no Linux, letras de unidade no
  Windows), e as pastas de mídia do usuário (`~/Movies`, `~/Videos`) também;
- ou cole o caminho à mão, se preferir.

A regra é **uma só, igual à do Drive: tem que existir uma pasta chamada
`TicianoFlix`**, com os gêneros dentro dela.

```
/Volumes/MeuHD/
└── TicianoFlix/            ← o nome é obrigatório
    ├── Terror/
    │   └── Alien (1979)/
    │       ├── Alien (1979).mkv
    │       ├── Alien (1979).nfo
    │       └── poster.jpg
    └── Ficção Científica/
```

**Não precisa apontar exato.** O volume que você escolhe quase sempre fica acima
do acervo — você pluga o HD e escolhe `/Volumes/MeuHD`, mas os filmes estão em
`/Volumes/MeuHD/Filmes/TicianoFlix/...`. O TicianoFlix procura essa pasta na
raiz escolhida e em até **dois níveis abaixo**, ancora a fonte nela e avisa qual
encontrou. Maiúsculas não importam (`ticianoflix` serve).

Sem essa pasta, o cadastro é **recusado** com uma mensagem dizendo o que criar —
em vez de aceitar uma pasta qualquer e devolver um catálogo vazio sem explicação.
No modal, os volumes detectados que já têm a pasta aparecem marcados com ✓.

Cada fonte vira um grupo próprio na barra lateral, com os gêneros dela embaixo.

Uma vez indexado, o filme local se comporta como qualquer outro: busca, A-Z,
continuar assistindo, legendas, metadados NFO e Chromecast funcionam igual — só
que os bytes saem direto do disco, sem passar pelo rclone.

**Detalhes que valem saber:**

| Situação | O que acontece |
|---|---|
| HD desconectado no momento do scan | A fonte é pulada e **o catálogo dela é preservado** — nada é apagado. Ela aparece marcada como *desconectada*. |
| Filme numa fonte local | Ganha o selo **Local**. Não há o que baixar pro cache, e ele não entra em *Baixados do Drive* — nunca foi baixado. |
| Remover uma fonte | Sai do catálogo. **Os arquivos no disco não são tocados.** |
| Backup restaurado de outra máquina | As fontes daquela máquina são podadas do catálogo no boot, já que os caminhos não existem aqui. |

> 🔒 Só administradores cadastram fontes, e o servidor recusa pastas amplas
> demais (a raiz do sistema, o home puro) — cadastrar uma delas publicaria o
> computador inteiro na rede local. Todo acesso a arquivo é confinado à raiz da
> fonte: `..` e symlink apontando pra fora recebem **403**.

### Na TV (Android TV)

O app em `tv/` abre o TicianoFlix na TV com o controle remoto. A interface é a
**própria web**, carregada numa WebView com `?tv=1` — o modo que torna tudo
navegável pelas setas. Assim a TV herda cada novidade da web sem uma segunda
interface para manter.

A exceção é a reprodução: o Chromium da WebView do Android não é confiável com
MKV e faixas AC3/DTS, então quem toca é o **ExoPlayer** nativo, com decodificação
por hardware. A URL vai assinada pelo mesmo token do Chromecast
(`/api/cast-token`), então o player busca os bytes sozinho e o app nunca lida
com sessão nem senha.

O `?tv=1` também funciona no computador: abra
`http://localhost:9187/?tv=1` e o site inteiro passa a ser navegável só com as
setas e Enter.

Para compilar e instalar, veja [`tv/README.md`](tv/README.md).

### Metadados NFO

O TicianoFlix lê arquivos `.nfo` no formato **Kodi / tinyMediaManager**:

```xml
<?xml version="1.0" encoding="utf-8"?>
<movie>
  <title>Meu Filme</title>
  <year>2024</year>
  <plot>Sinopse do filme...</plot>
  <rating>8.5</rating>
  <thumb>poster.jpg</thumb>
  <fanart>fanart.jpg</fanart>
  <genre>Terror</genre>
  <director>Diretor</director>
  <actor>
    <name>Ator</name>
    <role>Personagem</role>
  </actor>
</movie>
```

---

## ⚙️ Arquitetura

```
┌──────────────┐     ┌──────────────────┐     ┌───────────────┐
│  Navegador   │────▶│  server.py       │────▶│ rclone serve  │
│  localhost:  │     │  ThreadingHTTP   │     │ :18082        │
│  9187        │◀────│  Server          │◀────│ (read-only)   │
└──────────────┘     └───┬──────────┬───┘     └───────┬───────┘
                         │          │                 │
                         ▼          ▼                 ▼
              ┌──────────────┐  ┌────────────┐  ┌──────────────────┐
              │  SQLite      │  │ disco      │  │  Google Drive    │
              │  (catálogo)  │  │ (Range)    │  │ pasta TicianoFlix│
              └──────────────┘  └─────┬──────┘  └──────────────────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │ HD externo · pendrive  │
                          │ pasta do computador    │
                          └────────────────────────┘
```

O catálogo é um só: o SQLite guarda caminhos lógicos (`/TicianoFlix/...` para o
Drive, `/Local/<fonte>/...` para as pastas locais) e cada requisição é roteada
para a fonte dona daquele caminho. Por isso busca, A-Z, continuar assistindo e
Chromecast valem para as duas origens sem código duplicado.

### Stack

| Camada | Tecnologia |
|--------|-----------|
| **Backend** | Python 3 puro (`http.server.ThreadingHTTPServer`) |
| **Frontend** | HTML + CSS + Vanilla JS (`cachedFetch` com TTL 2 min, `pushState` history) |
| **Streaming** | Drive: `rclone serve http` (VFS cache full, chunk 4M, read-ahead 512M) · Local: leitura direta do disco com HTTP Range |
| **Cache** | SQLite (browsing) + RAM (movie details) + VFS rclone (download offline) |
| **Init** | systemd user service |

---

## 🔒 Segurança

O servidor continua acessível pela rede local — Chromecast e celular dependem
disso — mas nada nele responde sem autenticação.

### Autenticação

- **Contas com papéis** (admin / usuário). Senhas guardadas como hash
  **PBKDF2-HMAC-SHA256** (100 000 iterações, salt de 16 bytes) em
  `~/.cache/ticianoflix/auth.json`, com permissão `600`.
- **Sem auto-cadastro.** O primeiro administrador exige o código de instalação
  impresso no log; os demais são criados pelo painel.
- **Sessão sem estado**: cookie `HttpOnly`, `SameSite=Lax`, assinado por
  HMAC-SHA256 com a chave em `~/.cache/ticianoflix/secret.key` (`600`).
  Reiniciar o servidor não desloga ninguém.
- **Revogação granular**: trocar a senha, mudar o papel ou remover a conta
  encerram as sessões daquela pessoa. "Sair de todos" derruba todo mundo.
- **Rate limit**: 8 tentativas erradas por IP a cada 15 minutos.

### Rede

- **Host e Origin validados** em toda requisição: aceita `localhost`, `.local` e
  faixas privadas (10/8, 192.168/16, 172.16–31, 169.254/16, 100.64/10); recusa
  domínio público. É o que fecha **DNS rebinding**.
- **CORS restrito** — as respostas de API não liberam origem alguma. Mídia e
  legenda devolvem `*` apenas quando não há header `Origin` (o caso do
  Chromecast, que busca o arquivo sozinho).
- **Chromecast por URL assinada** — token HMAC de 12h válido só para aquele
  arquivo, em vez de abrir as rotas de mídia.
- **`rclone serve` apenas em `127.0.0.1:18082`**, read-only e montado na pasta
  `TicianoFlix` — nunca na raiz do Drive. O TicianoFlix faz o proxy; nada
  externo alcança essa porta.
- **Configurador do rclone desligado por padrão.** Habilite com
  `TICIANOFLIX_RCLONE_GUI=1` — sobe apenas em `127.0.0.1`.

### Acesso ao Google Drive

Por padrão o `rclone config` cria um remote com escopo `drive`: **leitura e
escrita no Drive inteiro**. O TicianoFlix não precisa de nada disso — ele só lê
uma pasta.

Você não precisa lembrar disso sozinho:

- **Os instaladores perguntam.** Se o remote estiver mais largo que o
  necessário, eles oferecem corrigir na hora.
- **O painel avisa.** Em **⚙️ Ajustes › ☁️ rclone**, a linha *Acesso ao Google Drive* mostra
  o nível atual e, quando está largo, explica o risco e dá o comando.

Para rodar manualmente, a qualquer momento:

```bash
./setup-rclone-seguro.sh
```

| Remote | Escopo | Alcance |
|--------|--------|---------|
| `gdrive` | `drive.readonly` + `root_folder_id` | Só lê, e só enxerga a pasta `TicianoFlix` |
| `gdrive_backup` | `drive.file` | Só os arquivos que o próprio TicianoFlix criou |

Depois disso, o resto do seu Drive fica fora de alcance mesmo que algo dê errado
no servidor. Confira com:

```bash
rclone lsjson gdrive: --dirs-only        # deve listar só os gêneros do catálogo
echo x | rclone rcat gdrive:probe.tmp    # deve falhar
```

> O escopo é aplicado pelo **Google**, não pelo rclone: editar o campo `scope`
> no `rclone.conf` não rebaixa um token já emitido. O script roda
> `rclone config reconnect`, que abre o navegador e pede um consentimento novo —
> esse passo é o que realmente fecha a escrita.

O código funciona com o remote escopado ou não: ele lê o `root_folder_id` do
`rclone.conf` na inicialização e ajusta os caminhos sozinho.

### Superfície da aplicação

- **Rotas destrutivas exigem POST** com `Origin` local (limpar cache, remover do
  cache, rescan, backup e restauração), o que impede CSRF por `<img>` ou `<form>`.
- **Restauração validada** — o backup precisa ser um SQLite íntegro com o schema
  esperado antes de substituir o banco, com teto de tamanho.
- **Metadados NFO escapados** na renderização, e arquivos com `<!ENTITY>`
  recusados (bomba XML).
- **Zero hardcoded secrets** — OAuth do rclone fica em
  `~/.config/rclone/rclone.conf`, fora do repositório.
- **SQL sempre parametrizado**, nenhum `shell=True`, nenhum caminho de usuário
  chegando ao shell.

### Variáveis de ambiente

| Variável | Padrão | Para quê |
|----------|--------|----------|
| `TICIANOFLIX_BIND` | `0.0.0.0` | Interface de escuta. Use `127.0.0.1` para fechar na máquina. |
| `TICIANOFLIX_PORT` | `9187` | Porta HTTP. |
| `TICIANOFLIX_RCLONE_GUI` | desligado | `1` habilita o configurador do rclone em `127.0.0.1:5572`. |

> ⚠️ Pela porta **9187** a senha trafega em claro na sua rede. O servidor também
> sobe em **HTTPS na 9443** — prefira esse endereço, ele aparece no banner de
> inicialização.

A porta é fixa: se a 9187 estiver ocupada por uma instância anterior do
TicianoFlix, o servidor a encerra e assume a porta, em vez de migrar para outra.

---

## 📂 Estrutura do Projeto

```
TicianoFlix/
├── server.py              # Entrypoint (13 linhas — chama ticianoflix.app)
├── ticianoflix/           # O backend
│   ├── config.py          #   constantes, caminhos, variáveis de ambiente
│   ├── paths.py           #   fronteira de caminhos com o rclone
│   ├── netsec.py          #   validação de Host e Origin
│   ├── procutil.py        #   PIDs por porta (lsof/fuser)
│   ├── netutil.py         #   IP local, cert self-signed, escolha de porta
│   ├── db.py              #   SQLite: conexões, schema, metadados
│   ├── auth.py            #   contas, sessões HMAC, tokens de mídia
│   ├── templates.py       #   tela de login servida pelo Python
│   ├── rclone.py          #   comandos, cache VFS, processo do serve
│   ├── nfo.py             #   metadados Kodi / tinyMediaManager
│   ├── sources.py         #   registro de fontes e confinamento de caminho
│   ├── localfs.py         #   listagem de pasta local no formato do rclone
│   ├── scanner.py         #   varredura das fontes e indexação
│   ├── queries.py         #   consultas ao cache
│   ├── handler.py         #   roteamento HTTP e streaming
│   └── app.py             #   composição e ciclo de vida
├── index.html             # Estrutura da página + sprites SVG
├── static/
│   ├── styles.css         #   estilos
│   ├── app.js             #   lógica do frontend
│   ├── tv.js              #   navegação por controle remoto (só com ?tv=1)
│   ├── tv.css             #   foco visível e margem de overscan na TV
│   └── vendor/            #   polyfill de spatial navigation do W3C (MIT)
├── tv/                    # App de Android TV (Kotlin) — veja tv/README.md
├── tools/check_names.py   # Detecta nomes usados mas não definidos
├── setup-rclone-seguro.sh # Reduz o acesso ao Drive ao mínimo
├── install.sh             # Instalador único (Linux e macOS) — baixa, instala, sobe
├── install-windows.bat    # Instalador (Windows)
├── bump-version.sh        # Versionamento SemVer
├── .gitignore             # Arquivos ignorados pelo Git
├── LICENSE                # Licença MIT
└── README.md              # Este arquivo
```

> `server.py` continua na raiz porque o `ExecStart` do systemd, o LaunchAgent
> do macOS, o `.bat` do Windows e o wrapper nativo `ticianoflix-server.c` fixam
> esse caminho — movê-lo quebraria instalações existentes.

Fora do repositório, em `~/.cache/ticianoflix/`:

```
ticianoflix.db     # Catálogo (SQLite)
auth.json          # Contas e hashes de senha  (600)
sources.json       # Fontes locais cadastradas (600)
secret.key         # Chave HMAC das sessões    (600)
cert.pem / key.pem # Certificado HTTPS         (600)
images/ · subs/    # Cache de pôsteres e legendas
```

---

## 🧹 Manutenção

### Limpar cache de vídeos

Abra **⚙️ Ajustes › 📦 Cache offline** e clique em **Limpar tudo**, ou execute:

```bash
rm -rf ~/.cache/rclone/vfs/
systemctl --user restart ticianoflix
```

### Esqueci a senha

Peça a um administrador para redefinir em **👥 Contas**. Se ninguém mais tiver
acesso de administrador, apague o arquivo de contas na máquina do servidor — o
fluxo de primeiro acesso volta, com um código de instalação novo:

```bash
rm ~/.cache/ticianoflix/auth.json
# reinicie o serviço e veja o novo código no log
```

Isso apaga **todas** as contas, não só a sua. O catálogo e o cache não são afetados.

### Atualizar

```bash
cd ~/TicianoFlix
git pull

# Linux
systemctl --user restart ticianoflix

# macOS
launchctl kickstart -k gui/$(id -u)/com.ticianoflix
```

> O servidor lê o `index.html` do disco a cada requisição. Depois de um `git pull`
> que mexa no frontend, reinicie antes de usar — senão a interface nova conversa
> com o backend antigo.

---

## 🏷️ Versionamento (SemVer)

O TicianoFlix segue **Semantic Versioning** (`MAJOR.MINOR.PATCH`) — padrão de mercado.

| Incremento | Quando | Exemplo |
|---|---|---|
| **MAJOR** | Quebra de compatibilidade (API diferente, remoção de recurso, formato novo) | 1.5 → **2.0** |
| **MINOR** | Nova funcionalidade visível ao usuário | 1.5 → **1.6** |
| **PATCH** | Correção de bug, ajuste visual, melhoria sem recurso novo | 1.5 → **1.5.1** |
| — (sem bump) | `docs:` / `chore:` / `refactor:` (sem impacto pra quem usa) | 1.5 → 1.5 |

> 📌 **Regra:** TODO PR mergeado na main que seja `feat:` ou `fix:` **DEVE** atualizar o README (changelog) e a versão. O workflow `version-bump` faz isso automaticamente analisando o título do PR.

### Como funciona o bump automático

1. PR mergeado na main → workflow `Auto version bump` dispara
2. Analisa o título: `feat:` → MINOR, `fix:` → PATCH, `BREAKING`/`!` → MAJOR
3. Atualiza os 3 lugares: badge da sidebar, changelog do app (`_CHANGELOG`) e README

### Manual (alternativa ao automático)

```bash
./bump-version.sh <major|minor|patch|none> "Título do changelog" "item 1|item 2"
```

Exemplo:
```bash
./bump-version.sh patch "Fix: auto-hide no fullscreen" "Controles somem com mouse parado"
```

---

## 🔀 Fluxo Git — Pull Requests obrigatórios

Mudanças na `main` **só entram via Pull Request**. Push direto é bloqueado por um hook local.

### ⚠️ Regra: teste manual ANTES do merge

**Nenhum PR é mergeado antes do teste manual.** O fluxo de trabalho é:

1. A mudança é aplicada **localmente** (o servidor em `localhost:9187` já roda a versão nova)
2. **Você testa** no navegador e dá o OK
3. Só então o PR é criado e mergeado (com bump automático de versão)

> 📌 Isso evita que mudanças não testadas entrem na main — e garante que a versão que você vê na interface sempre bate com o que está no repositório.

### Instalar o hook (uma vez por clone)

```bash
cd ~/TicianoFlix
cp git-hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

O hook bloqueia `git push` para `main`/`master` e mostra o fluxo correto.

### Fluxo padrão

```bash
# 1. Branch de trabalho (sempre fora da main)
git checkout -b fix/nome-do-fix        # ou feat/nome

# 2. Commit
git add . && git commit -m "descrição"

# 3. Push da branch
git push origin fix/nome-do-fix

# 4. Abrir o PR
gh pr create --fill --base main        # ou pelo site do GitHub
```

### Atualizar a main (após o merge do PR)

```bash
git checkout main
git pull
systemctl --user restart ticianoflix    # Linux
launchctl kickstart -k gui/$(id -u)/com.ticianoflix   # macOS
```

---

## 📝 Licença

MIT — veja o arquivo [LICENSE](LICENSE).

---

## 📋 Changelog

### v1.13 — app de Android TV, com a interface da web navegável por controle

- Modo TV na web com `?tv=1`: navegação por setas, foco visível e overscan — nada carrega sem a query

- Ponte `TicianoFlixTV` no `playMovie()`, desviando o filme para o player nativo quando o app de TV está presente

- App de Android TV em Kotlin em `tv/`: WebView + ExoPlayer + descoberta do servidor na rede

- Login e `pushState` deixam de descartar a query string da URL

- `tv.js` e `tv.css` entram no cache-busting por mtime


### v1.12 — coleções de filmes (Star Wars 1-6 e afins)

- Item **Coleções** na barra lateral, listando as coleções do acervo

- Tela da coleção com os filmes ordenados por ano

- Chip na ficha do filme levando para a saga inteira

- Rotas `/api/collections` e `/api/collection?name=`

- Tabelas `collections` e `movie_collections` — nada alterado nas existentes


### v1.11 — AirPlay como alternativa ao Chromecast no iPhone

- Botão de AirPlay ao lado do de Chromecast, visível só quando o próprio `<video>` confirma suporte (feature detection via `webkitShowPlaybackTargetPicker`, não user-agent sniffing)

- Ao clicar, vídeo e legenda trocam para uma URL assinada (mesmo mecanismo de token do Chromecast) antes de abrir o seletor nativo do iOS

- `_fetchMediaToken()` extraído como helper compartilhado entre Cast e AirPlay, no lugar da lógica duplicada


### v1.10.3 — modais e menu lateral cortados no Safari/Chrome do iPhone

- modais e menu lateral cortados no Safari/Chrome do iPhone


### v1.10.2 — icone de play do logo quebrava pra linha de baixo no desktop

- `.logo-text` ganha `white-space: nowrap` + `flex-shrink: 0`: ícone e nome nunca mais quebram entre si

- `.sidebar-header` ganha `flex-wrap: wrap`: quando o selo de versão não cabe do lado, ele desce para uma segunda linha em vez de espremer o logo


### v1.10.1 — wrapper nativo do macOS para de depender de $HOME/TicianoFlix fixo

- `ticianoflix-server.c` resolve `server.py` como caminho relativo ao `cwd`, em vez de montar `$HOME/TicianoFlix/server.py`


### v1.10 — responsividade real no celular

- Barra lateral vira gaveta abaixo de 768px, com barra superior fixa (menu, logo, busca)

- Ordem de empilhamento (z-index) organizada numa escala única e documentada

- Controles do player reorganizados em duas faixas, com os secundários (volume, velocidade, legenda) num menu "⋯"

- Barra de progresso e controle de volume utilizáveis com o dedo

- Título do filme sempre visível nos cartazes (antes só aparecia no hover)

- Cabeçalho do gênero compacto (de 200px fixos para altura pelo conteúdo)

- Toque revela os controles do player (antes dependia de hover/mousemove)


### v1.9 — fontes locais — HD externo, pendrive e pastas do computador

- Fontes locais: HD externo, pendrive e pastas do computador no mesmo catálogo do Drive

- Cadastro por detecção de volumes conectados ou caminho digitado, restrito a administradores

- A fonte precisa conter uma pasta `TicianoFlix` (na raiz escolhida ou até dois níveis abaixo), com os gêneros dentro dela

- Streaming direto do disco com suporte a Range, para o player conseguir pular no meio do filme

- HD desconectado no scan preserva o catálogo daquela fonte em vez de apagá-lo

- Menu lateral enxuto: os painéis de manutenção passam a viver num item "Ajustes"

- Home com três seções (Últimos Adicionados, Continuar Assistindo, Baixados do Drive) e estatísticas de acervo, fontes conectadas e último scan

- Chromecast: legenda corrigida, ficha do filme na TV (pôster, ano, sinopse) e controles do app comandando a transmissão


### v1.8 — feat(ui): troca os emojis por ícones SVG em contorno

- feat(ui): troca os emojis por ícones SVG em contorno


### v1.7 — feat(segurança): reduz o acesso ao Drive ao mínimo necessário

- feat(segurança): reduz o acesso ao Drive ao mínimo necessário


### v1.6 — Login com contas e hardening de segurança

- Login obrigatório: contas com usuário e senha, sessão de 90 dias por aparelho

- Primeiro acesso protegido por código de instalação impresso no log do servidor

- Painel 👥 Contas para administradores: adicionar, remover, promover e redefinir senha

- Chromecast preservado por URL assinada, válida só para aquele arquivo

- Fim do CORS aberto e do acesso sem autenticação: Host e Origin validados em toda requisição

- Correções: path traversal em /static/, XSS em metadados NFO e rotas destrutivas via GET

- rclone serve e configurador passam a escutar apenas em 127.0.0.1


### v1.5.3 — Botão fechar do player

- Corrigido modal de confirmação ao fechar o player — abria atrás do vídeo e o botão ✕ parecia não funcionar

### v1.5.2 — Bloqueio do menu durante reprodução

- Menu lateral e navegação ao fundo ficam bloqueados enquanto o filme toca (camada do player acima de tudo)

### v1.5.1 — Controles, header e legenda do player

- Controles e header somem no fullscreen com o mouse parado (cursor também) — estilo Netflix
- Legenda proporcional ao tamanho do player — deixa de ficar gigante ao sair do fullscreen
- Cursor de clicável (mãozinha) no breadcrumb do overlay de detalhes


### v1.5 — Busca na sidebar, scan incremental, home reorganizada

- Busca movida para a sidebar (acima de Início), com resultados ao vivo enquanto digita e botão limpar (✕)
- Resultados de busca em grade única, sem mostrar as pastas dos filmes
- Atualização (scan) incremental: só busca filmes novos/alterados e remove os apagados — ~2s em vez de ~40s
- Barra de progresso do scan mais compacta
- Home reorganizada: Últimos Adicionados (máx. 7) → Continuar Assistindo → Offline
- Acesso rápido ao rclone via ☁️ ao lado do uso de cache; menu: Atualizar, Backup, Gerenciar Cache, Limpar Cache
- Versão clicável (v1.5) abre o changelog da última versão

### v1.1 — Limpeza de código

- **-469 linhas** de código morto removidas entre `server.py` e `index.html`
- `server.py`: removidos `_human_size()`, `POSTER_EXTENSIONS`, imports `json` duplicados, código duplicado na inicialização do rclone, comentário residual
- `index.html` (CSS): removidos blocos `.copy-url-btn`, `.cast-btn`, `.logo`, `.header-actions`, `.btn-close-info`, `.movie-info-files`, `.genre-movies-preview`, `.preview-card`, `.empty-genre`
- `index.html` (CSS): consolidados dois blocos `.header` duplicados em um único bloco com `left: 220px`
- `index.html` (JS): removido código Google Cast SDK (~120 linhas, botão 📺 removido anteriormente)
- `index.html` (JS): removidas funções mortas `fetchGenrePreview`, `loadGenre`, `copyStreamUrl`, `fallbackCopy`, `updateSubtitleButton`, `_bufferTimer`/`_bufferSafetyTimeout`
- Removidos CSS responsivo residual de `.preview-card`

### v1.0 — Backup modal, cache tracker, player history, offline badges

- Backup em modal com 4 opções (salvar, upload Drive, restaurar de arquivo, restaurar do Drive)
- Cache tracker visual com barra de progresso em tempo real
- Navegação com histórico (`pushState` + `popstate`)
- Badge 📥 Offline para filmes cacheados
- Seção "Disponíveis Offline" na home
- Botões de legenda Aa (tamanho) + 🟡/⬜ (cor)
- Download em background (range requests 5MB)
- Modal de confirmação ao sair do player
- Google Fonts Roboto
- Player loading otimizado: `readyState >= 3` para cache instantâneo, `play()` antecipado

### v0.9 — Scan progress, sidebar fixa, cache VFS

- Barra de progresso do scan em tempo real no sidebar
- Sidebar fixa 220px (sempre visível, sem toggle)
- rclone serve com `--vfs-cache-mode full`, chunk 4M, read-ahead 512M
- ThreadingHTTPServer (multithread) — fim dos travamentos
- SQLite WAL mode com thread safety
- `cachedFetch` com TTL 2 min no frontend
- Scan apenas manual (botão 🔄) — zero requisições automáticas ao Drive
- Uso de cache (🗄️) no sidebar com atualização a cada 30s

