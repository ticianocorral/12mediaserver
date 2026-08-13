<div align="center">
  <h1>🎬 TicianoFlix</h1>
  <p><strong>Netflix-style movie player for Google Drive — self-hosted, lightweight, instant.</strong></p>
  <p>
    <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/rclone-1.60%2B-green" alt="rclone 1.60+">
    <img src="https://img.shields.io/badge/version-1.5-red" alt="v1.5">
    <img src="https://img.shields.io/badge/license-MIT-yellow" alt="MIT License">
  </p>
</div>

---

## 📖 Sobre

TicianoFlix é um servidor web auto-hospedado que transforma seu **Google Drive** em um catálogo de filmes no estilo Netflix. Ele escaneia pastas organizadas por gênero, extrai metadados de arquivos NFO (formato Kodi/tinyMediaManager), e serve tudo via uma interface web bonita e responsiva.

### ✨ Funcionalidades

- **📁 Scan manual** do Google Drive com proteção contra scans concorrentes
- **🎞️ Streaming direto** via `rclone serve http` — sem downloads, sem buffers infinitos
- **💾 Cache SQLite** — navegação instantânea após o primeiro scan
- **📥 Download em background** — pause o filme e o cache VFS continua baixando
- **📦 Indicador Offline** — filmes 100% cacheados aparecem com badge 📥 e seção especial na home
- **🧹 Limpar Cache** — botão para remover vídeos baixados do cache VFS
- **🗺️ Navegação com histórico** — botões Voltar/Avançar do navegador funcionam dentro do app
- **💾 Backup & Restore** — modal com opções: salvar backup, upload pro Drive, restaurar de arquivo ou do Drive
- **🏷️ Metadados NFO** — suporte a posters, fanarts, sinopse, elenco, avaliação (formato Kodi / tinyMediaManager)
- **🔍 Busca** por título com debounce
- **📱 Responsivo** — funciona no celular também
- **🔄 Serviço systemd** — inicia automaticamente no login
- **🎨 Fontes Roboto** — tipografia moderna via Google Fonts
- **🚪 Modal de confirmação** ao sair do player (sem `confirm()` nativo)

---

## 🚀 Instalação Rápida

### Pré-requisitos

- **Python 3.10+**
- **rclone** (com remote `gdrive:` configurado)
- Linux (systemd) · macOS (LaunchAgent) · Windows — veja abaixo

### 1. Configurar o Google Drive no rclone

```bash
rclone config
```

Crie um remote chamado `gdrive:` com:
- Tipo: `drive`
- Escopo: `drive` (acesso completo) ou `drive.file`
- Autenticação via OAuth no navegador

> 💡 Depois de instalado, dá pra configurar pelo próprio TicianoFlix:
> clique em **☁️ rclone** no menu lateral — ele mostra o status (instalado,
> remote `gdrive:`, streaming) e abre o configurador oficial do rclone
> (web GUI) pra criar o remote sem usar o terminal.

### 2. Clonar e instalar

**Linux (systemd):**

```bash
git clone https://github.com/seu-usuario/ticianoflix.git
cd ticianoflix
bash install.sh
```

O instalador cuida de:
- Verificar/instalar dependências
- Criar o serviço systemd
- Ativar persistência mesmo sem login (`linger`)
- Iniciar o servidor

**macOS (LaunchAgent):**

```bash
git clone https://github.com/seu-usuario/ticianoflix.git
cd ticianoflix
bash install-macos.sh
```

O instalador verifica/instala Python e rclone (Homebrew ou script oficial),
cria o LaunchAgent `com.ticianoflix` (inicia no login, reinicia se cair) e
grava os logs em `~/.cache/ticianoflix/ticianoflix.log`.

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

### 3. Acessar

Abra **http://localhost:8080** no navegador e clique em 🔄 para escanear seu Drive.

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
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Navegador   │────▶│  server.py       │────▶│  rclone serve │
│  localhost:   │     │  ThreadingHTTP   │     │  :18082       │
│  8080         │◀────│  Server          │◀────│  (read-only)  │
└──────────────┘     └────────┬─────────┘     └──────┬───────┘
                              │                      │
                              ▼                      ▼
                     ┌──────────────┐      ┌──────────────────┐
                     │  SQLite      │      │  Google Drive    │
                     │  (cache)     │      │  (gdrive:)       │
                     └──────────────┘      └──────────────────┘
```

### Stack

| Camada | Tecnologia |
|--------|-----------|
| **Backend** | Python 3 puro (`http.server.ThreadingHTTPServer`) |
| **Frontend** | HTML + CSS + Vanilla JS (`cachedFetch` com TTL 2 min, `pushState` history) |
| **Streaming** | `rclone serve http` (VFS cache full, chunk 4M, read-ahead 512M) |
| **Cache** | SQLite (browsing) + RAM (movie details) + VFS rclone (download offline) |
| **Init** | systemd user service |

---

## 🔒 Segurança

- **Zero hardcoded secrets** — OAuth do rclone fica em `~/.config/rclone/rclone.conf`, fora do repositório
- **Read-only** no rclone — impossível deletar ou alterar arquivos no Drive
- **Firewall local** — servidor escuta em `0.0.0.0:8080` (acesso LAN) — altere para `127.0.0.1` se quiser apenas localhost
- **Serviço isolado** — systemd com `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`

---

## 📂 Estrutura do Projeto

```
TicianoFlix/
├── server.py         # Servidor HTTP (todo o backend)
├── index.html        # Frontend single-page
├── install.sh        # Instalador do serviço systemd
├── .gitignore        # Arquivos ignorados pelo Git
├── LICENSE           # Licença MIT
└── README.md         # Este arquivo
```

---

## 🧹 Manutenção

### Limpar cache de vídeos

Clique em **🧹 Limpar Cache** na sidebar ou execute:

```bash
rm -rf ~/.cache/rclone/vfs/
systemctl --user restart ticianoflix
```

### Atualizar

```bash
cd ~/TicianoFlix
git pull
systemctl --user restart ticianoflix
```

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

### v1.5.3 — botão fechar do player — modal de confirmação abria atrás do player

- Merged via PR #7


### v1.5.2 — bloquear clique no menu lateral durante reprodução

- Merged via PR #6


### v1.5.1 — cursor de clicável no breadcrumb do overlay de detalhes

- Merged via PR #5


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

