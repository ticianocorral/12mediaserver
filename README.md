<div align="center">
  <h1>🎬 TicianoFlix</h1>
  <p><strong>Netflix-style movie player for your cloud, external drives and USB sticks — self-hosted, lightweight, instant.</strong></p>
  <p>
    <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/rclone-1.60%2B-green" alt="rclone 1.60+">
    <img src="https://img.shields.io/badge/version-1.21-red" alt="v1.21">
    <img src="https://img.shields.io/badge/license-MIT-yellow" alt="MIT License">
  </p>
</div>

---

## 📖 Sobre

TicianoFlix é um servidor web auto-hospedado que transforma **a sua nuvem** (qualquer remote do rclone: Backblaze B2, Google Drive, S3, SFTP...) — e também **HD externo, pendrive ou pastas do próprio computador** — num catálogo de filmes no estilo Netflix. Ele escaneia suas pastas de filmes, extrai metadados de arquivos NFO (formato Kodi/tinyMediaManager), e serve tudo via uma interface web bonita e responsiva.

### ✨ Funcionalidades

- **🔐 Login com contas** — usuário e senha por pessoa, sessão de 90 dias por aparelho, sem auto-cadastro
- **👥 Painel de contas** — administradores adicionam, removem, promovem, redefinem senhas e ativam o perfil infantil
- **👶 Perfil infantil** — contas marcadas como infantis veem apenas os filmes que o administrador liberou: o filtro vale para o catálogo, a busca e até o streaming (por URL direta não passa). Os filmes são marcados na própria ficha, com um toque
- **💽 Fontes locais** — HD externo, pendrive e pastas do computador entram no mesmo catálogo, sem subir nada pra nuvem
- **📁 Scan manual** — o botão **Atualizar** varre todas as fontes; cada uma também pode ser escaneada sozinha em **⚙️ Ajustes › 💽 Fontes**. Protegido contra scans concorrentes
- **🎞️ Streaming direto** via `rclone serve http` — sem downloads, sem buffers infinitos
- **💾 Cache SQLite** — navegação instantânea após o primeiro scan
- **📥 Download em background** — pause o filme e o cache VFS continua baixando
- **📦 Baixados da nuvem** — filmes da nuvem 100% cacheados ganham selo e seção própria na home (filmes de fonte local não entram: eles já estão no disco)
- **🧹 Limpar cache** — apaga os vídeos baixados, dentro do próprio gerenciador de cache
- **🗺️ Navegação com histórico** — botões Voltar/Avançar do navegador funcionam dentro do app
- **💾 Backup & Restore** — modal com opções: salvar backup, enviar para a nuvem, restaurar de arquivo ou da nuvem
- **🏷️ Metadados NFO** — suporte a posters, fanarts, sinopse, elenco, avaliação (formato Kodi / tinyMediaManager)
- **🎬 Coleções** — crie e edite coleções na própria interface (nome, descrição, filmes e capa a partir dos pôsteres dos escolhidos); coleções antigas da tag `<set>` do NFO são importadas uma única vez
- **🏷️ Tags na interface** — crie tags na barra lateral e atribua filmes pela ficha ou pelo A-Z, sem depender da organização de pastas
- **📺 Séries** — organize em `tv shows/Série (ano)/Season 1/S01E01...` e a série ganha página própria, com temporadas e episódios (com legenda); episódios entram no Continuar Assistindo
- **🎥 Filmes soltos** — arquivo de vídeo avulso também vira filme no catálogo, com pôster opcional de mesmo nome
- **🔍 Busca** por título com debounce
- **📱 Responsivo de verdade** — no celular a barra lateral vira gaveta, os controles do player se reorganizam em duas faixas (nada de botão fora da tela) e tudo responde a toque
- **🔄 Serviço systemd** — inicia automaticamente no login
- **🎨 Fontes Roboto** — tipografia moderna via Google Fonts
- **🚪 Modal de confirmação** ao sair do player (sem `confirm()` nativo)
- **📺 Chromecast** — envio para a TV com URL assinada e legendas; a TV mostra pôster, ano e sinopse, e os controles do app comandam a transmissão (play, avançar, volume, legenda — com tamanho e cor reguláveis na hora)
- **📡 AirPlay** — no iPhone, onde o Chromecast não funciona (limitação da Apple, não do app), o botão de AirPlay aparece no lugar; usa a mesma URL assinada, direto do `<video>`, sem SDK
- **🛠️ Preparo para TV** — MKV, áudios Dolby (AC3/E-AC3/DTS) e vídeo HEVC não tocam (ou tocam só com o som) no Chromecast e no AirPlay; em vez de recusar o filme, o servidor gera um MP4 H.264 com faixa AAC — em cache, então só a primeira transmissão de cada arquivo espera
- **🎨 Aparência configurável** — o nome do app é escolhido na instalação e fica fixo depois (é também o nome da pasta da biblioteca); a cor pode ser trocada a qualquer momento em **⚙️ Ajustes › 🎨 Aparência**, refletida na tela de login, no menu, no ícone instalado no celular e no manifesto

---

## 🚀 Instalação Rápida

### Instalador visual (Windows, macOS e Linux)

Para quem prefere clicar a digitar, o projeto traz um instalador visual por plataforma, na raiz do repositório:

| Arquivo | Como usar | O que faz |
|---|---|---|
| `Instalador-TicianoFlix-Windows.bat` | Duplo clique | Assistente gráfico (PowerShell/WinForms): verifica e instala Python e rclone, cria o atalho de execução, agenda o início com o Windows e abre o app |
| `Instalador-TicianoFlix-macOS.command` | Duplo clique¹ | Diálogos nativos do macOS + a instalação rodando com a saída visível no Terminal; abre o navegador no final |
| `Instalador-TicianoFlix-Linux.sh` | `bash Instalador-TicianoFlix-Linux.sh` | Diálogos gráficos (zenity no GNOME, kdialog no KDE) e a instalação numa janela de terminal; sem gráfico, funciona no terminal mesmo |

¹ Se o macOS reclamar de permissão: clique com o direito > Abrir, ou `chmod +x Instalador-TicianoFlix-macOS.command`.

Os três reaproveitam a mesma lógica do instalador de linha de comando (verificações, downloads oficiais, serviço persistente) — mudam só a embalagem. Requerem o projeto baixado ao lado (clone/zip); sem ele, tentam baixar do GitHub.

### Pré-requisitos

- **Python 3.9+**
- Linux (systemd) · macOS (LaunchAgent) · Windows — veja abaixo

É só isso. O instalador **instala o rclone sozinho** (baixa o binário oficial
para `~/.local/bin`, sem precisar de sudo); se preferir, qualquer rclone já
instalado no sistema é respeitado. O TicianoFlix funciona com filmes que já
estão no seu computador, num HD externo ou num pendrive — veja
[Fontes locais](#fontes-locais-hd-externo-pendrive-pasta-do-computador).

A **nuvem é opcional** e entra depois, quando você quiser: com o rclone já
instalado, basta conectar qualquer remote em **⚙️ Ajustes › ☁️ Nuvem**. Sem ela
nada deixa de funcionar — o servidor sobe igual e nem tenta contato com a nuvem.

### 1. (Opcional) Conectar a nuvem (qualquer remote do rclone)

A nuvem do TicianoFlix é **qualquer remote do rclone** — Backblaze B2, Google
Drive, S3, Dropbox, SFTP, o que for. Em **⚙️ Ajustes › ☁️ Nuvem › Conectar
nuvem**, o assistente oferece dois caminhos:

- **Usar um remote existente**: escolhe na lista do seu `rclone.conf`
  (`rclone listremotes`), informa a pasta do acervo dentro dele e conecta;
- **Criar um remote novo**: escolhe o tipo numa lista filtrável e o formulário
  é gerado com os campos exatos daquela nuvem (o rclone mesmo descreve cada
  um). O app cria, testa a conexão e conecta — sem terminal.

Desconectar não apaga nada: o remote e o acervo ficam intactos. O backup do
catálogo vai para a pasta `TicianoFlix Backups/` na mesma nuvem.

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
- Instala o rclone (binário oficial em `~/.local/bin`, sem sudo; usa
  Homebrew/apt/dnf/pacman como alternativa se o download falhar)
- No Linux, cria o serviço systemd e ativa persistência sem login (`linger`)
- No macOS, cria o LaunchAgent `com.ticianoflix` (inicia no login, reinicia se cair)
- Sobe o servidor, espera ele responder e **mostra o código de instalação na
  própria tela** — sem precisar abrir o log
- Abre o navegador no endereço certo

Não pede nenhuma credencial: a nuvem é 100% opcional e configurada depois pela
interface (com o rclone já instalado). Veja
[Fontes locais](#fontes-locais-hd-externo-pendrive-pasta-do-computador)
e [Conectar a nuvem](#1-opcional-conectar-a-nuvem-qualquer-remote-do-rclone)
acima.

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

Feito o login, clique em 🔄 para escanear sua nuvem.

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

### Estrutura da nuvem

Organize seus filmes assim na nuvem, dentro de uma pasta com o nome escolhido
na instalação (aqui, `Mediaflix` é só um exemplo; se preferir, use a raiz da
nuvem cadastrando a pasta em branco):

```
Mediaflix/
├── movies/
│   ├── Filme A (2024)/
│   │   ├── Filme A (2024).mp4
│   │   ├── poster.jpg
│   │   └── Filme A (2024).nfo
│   ├── Filmes B e C/
│   │   └── Filme B (2023)/    ← pastas intermediárias não importam
│   └── Filme C.mp4            ← arquivo solto também vale (aparece no A-Z)
└── tv shows/
    └── Breaking Bad/
        ├── poster.jpg          ← arte da série (opcional)
        ├── S01/
        │   ├── S01E01.mkv
        │   └── S01E01.srt
        └── S02/
            └── Breaking Bad S02E01.mkv

**movies/** funciona como sempre funcionou o acervo: filme = pasta com vídeo
direto (qualquer profundidade), arquivo solto vale. Em **tv shows/**, cada
pasta é uma série, as pastas dentro dela são as temporadas (S01, S02...) e os
vídeos dentro das temporadas são os episódios. Séries também entram no A-Z,
nos recentes e aceitam marcação de perfil infantil.

Tags não vêm de pasta: você cria na interface (barra lateral › Tags) e
atribui os filmes a elas pela ficha ou pelo A-Z, de qualquer fonte.

> Fora de `movies/` e `tv shows/` a regra de filme vale igual — quem já tem
> acervo solto na raiz continua funcionando sem mover nada. Os nomes dos
> contêineres valem em maiúsculas ou minúsculas (`TV Shows` funciona igual).
```

### Fontes locais (HD externo, pendrive, pasta do computador)

A nuvem não precisa ser o único acervo. Em **⚙️ Ajustes › 💽 Fontes do acervo** (só para
administradores) dá pra apontar o TicianoFlix para qualquer pasta da máquina:

- os **volumes conectados** aparecem prontos pra adicionar com um clique
  (`/Volumes` no macOS, `/media` e `/run/media` no Linux, letras de unidade no
  Windows), e as pastas de mídia do usuário (`~/Movies`, `~/Videos`) também;
- ou cole o caminho à mão, se preferir.

A regra é **uma só, igual à da nuvem: tem que existir uma pasta com o nome
escolhido na instalação** (`Mediaflix` no exemplo abaixo), com os filmes
dentro dela — cada filme numa pasta com o vídeo, ou como arquivo solto.

```
/Volumes/MeuHD/
└── Mediaflix/               ← o nome é obrigatório (o escolhido na instalação)
    └── Alien (1979)/
        ├── Alien (1979).mkv
        ├── Alien (1979).nfo
        └── poster.jpg
```

**Não precisa apontar exato.** O volume que você escolhe quase sempre fica acima
do acervo — você pluga o HD e escolhe `/Volumes/MeuHD`, mas os filmes estão em
`/Volumes/MeuHD/Filmes/Mediaflix/...`. O TicianoFlix procura essa pasta na
raiz escolhida e em até **dois níveis abaixo**, ancora a fonte nela e avisa qual
encontrou. Maiúsculas não importam, e uma pasta já criada com um nome genérico
de versão anterior (`mediaflix` ou `ticianoflix`) também é sempre aceita.

Sem essa pasta, o cadastro é **recusado** com uma mensagem dizendo o que criar —
em vez de aceitar uma pasta qualquer e devolver um catálogo vazio sem explicação.
No modal, os volumes detectados que já têm a pasta aparecem marcados com ✓.

Cada fonte vira um grupo próprio na barra lateral; as **Tags** do app ficam
numa seção à parte, logo abaixo.

Uma vez indexado, o filme local se comporta como qualquer outro: busca, A-Z,
continuar assistindo, legendas, metadados NFO e Chromecast funcionam igual — só
que os bytes saem direto do disco, sem passar pelo rclone.

**Detalhes que valem saber:**

| Situação | O que acontece |
|---|---|
| HD desconectado no momento do scan | A fonte é pulada e **o catálogo dela é preservado** — nada é apagado. Ela aparece marcada como *desconectada*. |
| Filme numa fonte local | Ganha o selo **Local**. Não há o que baixar pro cache, e ele não entra em *Baixados da nuvem* — nunca foi baixado. |
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
              │  SQLite      │  │ disco      │  │  nuvem (rclone)  │
              │  (catálogo)  │  │ (Range)    │  │ pasta escolhida  │
              └──────────────┘  └─────┬──────┘  └──────────────────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │ HD externo · pendrive  │
                          │ pasta do computador    │
                          └────────────────────────┘
```

O catálogo é um só: o SQLite guarda caminhos lógicos (`/<nome do app>/...` para a
nuvem, `/Local/<fonte>/...` para as pastas locais) e cada requisição é roteada
para a fonte dona daquele caminho. Por isso busca, A-Z, continuar assistindo e
Chromecast valem para as duas origens sem código duplicado.

### Stack

| Camada | Tecnologia |
|--------|-----------|
| **Backend** | Python 3 puro (`http.server.ThreadingHTTPServer`) |
| **Frontend** | HTML + CSS + Vanilla JS (`cachedFetch` com TTL 2 min, `pushState` history) |
| **Streaming** | Nuvem: `rclone serve http` (VFS cache full, chunk 4M, read-ahead 512M) · Local: leitura direta do disco com HTTP Range |
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
  arquivo, em vez de abrir as rotas de mídia; a versão convertida para TV
  (`/api/prepared`) usa o mesmo token do arquivo original.
- **`rclone serve` apenas em `127.0.0.1:18082`**, read-only e montado na pasta
  da biblioteca — nunca na raiz da nuvem. O TicianoFlix faz o proxy; nada
  externo alcança essa porta.
- **Configurador do rclone desligado por padrão.** Habilite com
  `TICIANOFLIX_RCLONE_GUI=1` — sobe apenas em `127.0.0.1`.

### Acesso à nuvem

O app não guarda credencial nenhuma: tudo vive no `rclone.conf` do usuário
(segredos obscurecidos pelo próprio rclone). O backup do catálogo é escrito na
pasta `TicianoFlix Backups/` da nuvem conectada — o único lugar onde o app
escreve. Vale a pena aplicar o mínimo privilégio na nuvem: credencial de
leitura para o acervo e, se quiser, uma de escrita para os backups, cadastrada
como remote separado no rclone.

### Superfície da aplicação

- **Rotas destrutivas exigem POST** com `Origin` local (limpar cache, remover do
  cache, rescan, backup e restauração), o que impede CSRF por `<img>` ou `<form>`.
- **Restauração validada** — o backup precisa ser um SQLite íntegro com o schema
  esperado antes de substituir o banco, com teto de tamanho.
- **Metadados NFO escapados** na renderização, e arquivos com `<!ENTITY>`
  recusados (bomba XML).
- **Zero hardcoded secrets** — as credenciais ficam no
  `~/.config/rclone/rclone.conf` (obscurecidas pelo próprio rclone), fora do
  repositório.
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
>
> O certificado HTTPS cobre o IP da LAN **e** o nome Bonjour da máquina — no Mac,
> `https://<nome-do-mac>.local:9443` (ex.: `https://Mac-mini-de-Ticiano.local:9443`).
> O nome `.local` não muda quando o IP muda: o certificado se regenera sozinho ao
> reiniciar o servidor. Em celulares e tablets, instale a CA para o navegador
> aceitar sem aviso: baixe em `http://<servidor>:9187/ca.crt` (só o certificado
> público; a chave nunca é servida).

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
│   ├── nuvem.py           #   wizard da nuvem (qualquer remote do rclone)
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
├── install.sh             # Instalador único (Linux e macOS) — baixa, instala, sobe
├── install-windows.bat    # Instalador (Windows)
├── Instalador-TicianoFlix-Windows.ps1/.bat  # Instalador visual (assistente gráfico)
├── Instalador-TicianoFlix-macOS.command     # Instalador visual (diálogos nativos)
├── Instalador-TicianoFlix-Linux.sh          # Instalador visual (zenity/kdialog)
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
nuvem.json         # Remote e pasta da nuvem   (600)
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

### v1.23 — ficha do filme: 'já assisti' que desmarca, Gêneros viram Tags e o AirPlay emendando episódios

- Botão 'Já assisti' na ficha vira interruptor: marca e desmarca, e o filme sai na hora de Continuar Assistindo

- 'Gêneros' viram 'Tags' em todo o app (barra lateral, A-Z, modais e mensagens) — a ficha do filme mostra quantas tags ele tem

- Chips de gênero da ficha ganham ícone, e as tags do metadado aparecem rotuladas como 'Palavras-chave'

- Fim do episódio emenda o próximo também fora do Chromecast: no AirPlay e assistindo no navegador a reprodução não para mais na tela final

- AirPlay: a TV anuncia o nome do filme/episódio (antes mostrava o nome do app) — vale também para a tela de bloqueio e a central de mídia

- AirPlay: a legenda do filme entra no MP4 preparado (mov_text, o formato que o receptor lê embutido) — aparece na TV, ativada pelo controle remoto do Apple TV; o botão CC do app continua mandando na legenda do Chromecast e do player local

- Nuvem ensina a converter para a TV: o MKV/HEVC da B2 agora passa pelo mesmo preparo do disco local (e leva a legenda no AirPlay) — o servidor baixa por trás, converte uma vez e serve do cache; custa tráfego da nuvem na primeira vez de cada filete


### v1.22 — transmissão sem sustos: capa da série, próximo episódio e vídeo em toda TV

- Transmissão: a capa da série aparece no painel e na TV ao transmitir um episódio (o arquivo não tem pôster próprio)

- Transmissão: quando o episódio termina, o próximo da série entra sozinho — a TV não fica mais parada na tela final

- Transmissão: vídeo HEVC é convertido para H.264 no preparo — era o HEVC 10-bit que deixava a TV com o som rolando e a proteção de tela ligada

- AirPlay: a URL enviada à TV é reconstruída do zero — o token velho do player podia duplicar e derrubar a reprodução

- Android: o painel não chama mais o aparelho de 'media receiver' — mostra o nome do Chromecast, ou nada quando o SDK não informa

- Coleções e séries: a capa não duplica mais o caminho do arquivo (adeus, pôster 404)


### v1.21 — coleções criadas e editadas no próprio app

- Botão **Nova coleção**: nome, descrição, escolha dos filmes e da capa — sem NFO nem tinyMediaManager

- **Editar coleção**: adicionar/remover filmes, trocar capa, nome e descrição

- Coleções vindas de NFO (`<set>`) são importadas uma única vez, com os mesmos filmes

- **Gêneros criados na interface**, independentes de pastas: atribua pela ficha do filme ou pelo A-Z

- **Séries**: organize em `tv shows/Série/Temporada (S01, S02...)/episódios` — listagem própria em A-Z, página da série com temporadas e episódios em lista (com legenda)

- Continuar assistindo: episódios de série aparecem como lista na home, com retomada no ponto exato

- Perfil infantil vira interruptor claro na ficha e na série (marcar a série vale para todos os episódios)

- Pasta `movies/` na raiz do acervo organiza os filmes (a regra de filme continua valendo fora dela também)

- Perfil infantil: conta com modo criança que só vê (e só pode tocar) os filmes marcados — o resto bloqueia até por URL

- **Chromecast**: tamanho e cor da legenda regulam na TV ao vivo (a escolha fica salva), e o painel de transmissão virou um controle remoto (play, ±10s, Aa, CC)

- Instalador visual nas 3 plataformas: assistente gráfico no Windows, diálogos nativos no macOS e zenity/kdialog no Linux

- Nuvem vira wizard: use qualquer remote do rclone (da lista) ou crie um novo com formulário guiado — B2, Drive, S3, SFTP...

- **Gênero por pasta sai de vez**: filme é qualquer pasta com vídeo direto, na profundidade que for

- **Filmes soltos** (arquivo avulso na pasta) viram filme no A-Z — clique toca direto

- Um filme pode estar em várias coleções; quem sai do acervo sai das coleções e dos gêneros no scan

- Tabelas novas `colecoes`, `colecoes_filmes`, `generos_app` e `generos_filmes` (as antigas `collections`/`movie_collections` ficam como histórico)

### v1.20 — nuvem passa a ser Backblaze B2, configurada pelo próprio app

- O Google Drive sai do código: a nuvem agora é um bucket **Backblaze B2** (rclone continua sendo o motor de streaming, scan e backup)

- Cadastro pela interface, em **⚙️ Ajustes › ☁️ Nuvem**: keyID, applicationKey e bucket — sem OAuth, sem script no terminal, sem navegador

- Backup e restauração vão para o mesmo bucket, com suporte a uma application key separada (só de escrita) para o mínimo privilégio

- `setup-rclone-seguro.sh` sai do repositório: o `rclone.conf` agora é escrito pelo próprio app (`ticianoflix/b2setup.py`)

- Streaming, cache VFS, scanner, fontes locais e banco de dados permanecem iguais — só o remote mudou (`gdrive:` → `b2:`)


### v1.19.2 — migração do prefixo de marca esquecia folders.parent

- migração do prefixo de marca esquecia folders.parent


### v1.19.1 — rclone em modo raiz volta a usar o nome real da pasta no Drive

- rclone em modo raiz volta a usar o nome real da pasta no Drive


### v1.19 — pasta do acervo deixa de exigir o nome TicianoFlix

- `LOGICAL_ROOT`: `/TicianoFlix` → `/Mediaflix` — a pasta exigida no Google Drive

- `CATALOG_DIR_NAME`: `ticianoflix` → `mediaflix` — a pasta exigida no HD/pendrive, com **compatibilidade retroativa**: quem já tinha criado `TicianoFlix` continua funcionando

- Migração de banco automática, uma única vez, na próxima subida do servidor

- Textos ajustados para bater com a pasta de verdade (modal de Fontes, painel de rclone, `setup-rclone-seguro.sh`, README)


### v1.18 — metadados via TMDB — editor que substitui o tinyMediaManager

- `ticianoflix/scraper.py` — cliente TMDB mínimo (`urllib`, sem dependência nova)

- Chave gratuita da própria pessoa (**Ajustes › Metadados**), nunca embutida no projeto

- Rotas `/api/scrape/status`, `/pendentes`, `/search`, `/apply`, `/key/set` — todas admin

- **Ajustes › Metadados**: formulário de chave, lista de filmes sem metadado, busca com resultados, "Usar este" aplica


### v1.17 — marca configurável (nome, cor e ícone por instalação)

- `ticianoflix/branding.py` — `get()`/`set()` com validação, persistido em `CACHE_DIR/branding.json`

- Rotas públicas `/manifest.webmanifest`, `/branding.css`, `/icone-*.png` — geradas em runtime

- `/api/branding` (GET) e `/api/branding/set` (POST) — admin, com `Origin` exigido no POST

- `<title>`, topbar, sidebar e a tela de login passam a refletir o nome e a cor escolhidos

- **Ajustes › Aparência**: nome + seletor de cor, seguindo o padrão visual de Contas/Fontes


### v1.16 — instalar o TicianoFlix como app na tela inicial do celular

- `static/manifest.webmanifest` — `display: standalone`, `start_url: /`, cor do tema

- `static/icons/` — 192, 512, maskable 512 e apple-touch 180

- `tools/gerar-icones.py` — gera os ícones a partir do `favicon.svg`

- Metatags `apple-*` e `mobile-web-app-capable` no `index.html`

- Manifest e ícones passam a responder sem sessão

- `mimetypes.add_type` para `.webmanifest`


### v1.15 — instalador único (curl | bash), sem exigir git nem log

- `install.sh` único, cobrindo Linux e macOS — substitui `install.sh` (Linux) e `install-macos.sh`, que sai do repositório

- Serve por `curl -fsSL <url>

- bash`, sem clonar nada antes

- Não instala nem exige rclone — Drive é 100% opcional

- Ao final, espera o servidor responder, lê o código de instalação do log e mostra na tela — ninguém precisa mais abrir arquivo de log — e abre o navegador sozinho


### v1.14 — Google Drive deixa de ser pré-requisito (boot de 31s para 0,3s)

- `paths.remote_configurado()` — o servidor só tenta subir o `rclone serve` se houver remote

- `_porta_responde()` separa "o processo subiu?" de "o Drive respondeu?"

- README: Drive sai dos pré-requisitos e vira seção opcional

- Exigência cai de Python 3.10+ para **3.9+**


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

