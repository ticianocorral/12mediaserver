<div align="center">
  <h1>🎬 12:00 Media Server</h1>
  <p><strong>Seu catálogo de filmes e séries no estilo Netflix — da nuvem, de HD externo ou de pendrive. Auto-hospedado e leve.</strong></p>
  <p>
    <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/rclone-1.60%2B-green" alt="rclone 1.60+">
    <img src="https://img.shields.io/badge/version-1.27-red" alt="v1.27">
    <img src="https://img.shields.io/badge/license-MIT-yellow" alt="MIT License">
  </p>
</div>

---

## ✨ O que faz

- **Um login, vários perfis** — conta única da casa; cada pessoa escolhe o perfil (12 avatares, até 6 perfis, PIN opcional de 4 números). Cada perfil tem seu histórico e o seu *Continuar assistindo*.
- **Perfil infantil** — só vê os filmes liberados pelo administrador, no catálogo, na busca e no streaming.
- **Fontes** — qualquer remote do rclone (B2, Drive, S3, SFTP…) e fontes locais (HD, pendrive, pastas) no mesmo catálogo.
- **Organizador TMDB** — renomeia filmes locais, baixa `.nfo` e capa (você escolhe a capa), com histórico e desfazer. Dispensa o tinyMediaManager. A nuvem é somente leitura.
- **Player** — legendas, próximo episódio com contagem, Chromecast e AirPlay.
- **App de Android TV** — ExoPlayer nativo com legenda ajustável; veja [`tv/README.md`](tv/README.md).
- **PWA** — instala na tela inicial do celular. Fonte embutida: funciona sem internet.
- **Coleções, tags, busca e séries** com temporadas e episódios.

---

## 🚀 Instalação

### Instaladores nativos (recomendado)

Python e rclone vêm embutidos; não é preciso instalar nada antes. Baixe em [Releases](https://github.com/ticianocorral/12mediaserver/releases):

| Sistema | Arquivo | Como instalar |
|---|---|---|
| Windows 10/11 | `Instalador-12-00-Media-Server-<versão>-Windows.exe` | Duplo clique (sem administrador) |
| macOS (Apple Silicon) | `12-00-Media-Server-<versão>-macOS-arm64.dmg` | Arraste para Aplicativos; 1ª vez: botão direito › Abrir |
| Linux (Debian/Ubuntu, 64 bits) | `12-00-media-server_<versão>_amd64.deb` | `sudo apt install ./12-00-media-server_*.deb` |

O servidor sobe em segundo plano e abre `http://localhost:9187`. Os instaladores não são assinados: o macOS e o SmartScreen avisam "desenvolvedor não verificado". `mkcert` e `ffmpeg` são opcionais (Chromecast e conversão para a TV).

### Linha de comando (macOS Intel, Linux, Windows)

```bash
git clone https://github.com/ticianocorral/12mediaserver.git
cd 12mediaserver
bash install.sh            # Windows: install-windows.bat
```

Instala o rclone sozinho, cria o serviço (systemd no Linux, LaunchAgent no macOS, tarefa agendada no Windows), sobe o servidor e mostra o código de instalação. Também há instaladores visuais na raiz (`Instalador-Media-Server-*`).

Logs: `~/.cache/media-server/media-server.log`.

### Primeiro acesso

1. Abra **http://localhost:9187** e informe o **código de instalação** de 6 dígitos (impresso no log; já vem preenchido quando você abre no próprio computador).
2. Crie usuário e senha: essa conta é o administrador.
3. Crie os perfis em **Gerenciar perfis** (nome, avatar, infantil, admin, PIN).
4. Adicione fontes em **⚙️ Ajustes › 💽 Fontes** (locais) ou **☁️ Nuvem** (rclone) e clique em 🔄 **Atualizar**.

---

## 📂 Organização do acervo

```
Acervo/
├── movies/
│   └── Filme (2024)/
│       ├── Filme (2024).mkv
│       ├── poster.jpg
│       └── Filme (2024).nfo
└── tv shows/
    └── Série/
        ├── S01/S01E01.mkv
        └── S02/S02E01.mkv
```

Pastas intermediárias e arquivos soltos também funcionam. Não tem a estrutura? Use **⚙️ Ajustes › Organizar e metadados** (precisa de uma chave gratuita do TMDB, guardada só neste computador): nada muda até você confirmar e tudo fica no histórico para desfazer. Nunca sobrescreve nem apaga arquivos.

Tags, coleções e perfil infantil são criados na interface, não por pastas.

---

## ⚙️ Configuração

| Variável | Padrão | Para quê |
|---|---|---|
| `MEDIA_SERVER_BIND` | `0.0.0.0` | Interface de escuta (`127.0.0.1` fecha na máquina) |
| `MEDIA_SERVER_PORT` | `9187` | Porta HTTP |
| `MEDIA_SERVER_RCLONE_GUI` | desligado | `1` habilita o configurador do rclone em `127.0.0.1:5572` |

O servidor também sobe em **HTTPS na 9443** (prefira; a senha trafega em claro na 9187). Em celulares, instale a CA em `http://<servidor>:9187/ca.crt`.

**Segurança:** sessão por cookie assinado, PIN e senha com hash, SQL parametrizado, sem `shell=True`, arquivos confinados à raiz de cada fonte.

---

## 🧹 Manutenção

- **Atualizar:** `git pull` e reinicie o serviço (`systemctl --user restart media-server` ou `launchctl kickstart -k gui/$(id -u)/com.mediaserver`). Nos instaladores, instale a nova versão por cima.
- **Limpar cache de vídeo:** **⚙️ Ajustes › 📦 Cache offline › Limpar tudo**.
- **Esqueci a senha:** outro administrador redefine em **👥 Contas**. Sem nenhum, apague `~/.cache/media-server/auth.json` e reinicie (apaga todas as contas; o catálogo fica).
- **Esqueci o PIN:** um administrador remove em Gerenciar perfis.

---

## 🧑‍💻 Desenvolvimento

- Backend em Python puro (`mediaserver/`), SQLite, interface em JS puro (`static/`, `index.html`); app de TV em `tv/`; empacotamento em `packaging/`.
- **Versão (SemVer):** `./bump-version.sh <major|minor|patch|none> "Título" "item1|item2"` atualiza badge, changelog do app, README e `__version__`.
- **PR obrigatório:** a `main` só recebe mudanças por Pull Request (hook local em `git-hooks/pre-push`; instale com `cp git-hooks/pre-push .git/hooks/`). Teste manualmente antes do merge.

## 📝 Licença

MIT — veja [LICENSE](LICENSE). Histórico completo no changelog do próprio app.

---

## 📋 Changelog

### v1.27 — Instaladores nativos, organizador com capas e próximo episódio

- Instaladores nativos (Windows .exe, macOS .dmg, Linux .deb) com Python e rclone embutidos

- Fonte Jost embutida: interface igual sem internet

- Organizador local e metadados via TMDB: renomeia filmes, escolhe a capa, desfaz; nuvem somente leitura

- Próximo episódio com contagem no navegador, no AirPlay e na TV


### v1.26 — Player da TV com legenda, capa e nome

- Botão Legenda no player da TV: liga/desliga, tamanho e cor

- Capa e nome do filme ou série no topo do player

- App da TV na versão 1.1


### v1.25 — Login único com perfis, avatares e PIN

- Um login da casa e tela Quem está assistindo?

- Perfis com avatar, perfil infantil e PIN de 4 números

- Progresso de exibição separado por perfil


### v1.24 — Renomeia para 12:00 Media Server e visual retrô discreto

- Novo nome: 12:00 Media Server

- Fonte Jost, cantos menores e calço nos cards

- Sem breadcrumb; Sair abaixo do videocassete

- Remove compatibilidade com instalações do nome antigo


