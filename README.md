<div align="center">
  <h1>🎬 TicianoFlix</h1>
  <p><strong>Netflix-style movie player for Google Drive — self-hosted, lightweight, instant.</strong></p>
  <p>
    <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/rclone-1.60%2B-green" alt="rclone 1.60+">
    <img src="https://img.shields.io/badge/license-MIT-yellow" alt="MIT License">
  </p>
</div>

---

## 📖 Sobre

TicianoFlix é um servidor web auto-hospedado que transforma seu **Google Drive** em um catálogo de filmes no estilo Netflix. Ele escaneia pastas organizadas por gênero, extrai metadados de arquivos NFO (formato Kodi/tinyMediaManager), e serve tudo via uma interface web bonita e responsiva.

### ✨ Funcionalidades

- **📁 Scan manual** do Google Drive com um clique (zero requisições automáticas)
- **🎞️ Streaming direto** via `rclone serve http` — sem downloads, sem buffers infinitos
- **💾 Cache SQLite** — navegação instantânea após o primeiro scan
- **🏷️ Metadados NFO** — suporte a posters, fanarts, sinopse, elenco, avaliação (formato Kodi / tinyMediaManager)
- **🔍 Busca** por título com debounce
- **📱 Responsivo** — funciona no celular também
- **🔄 Serviço systemd** — inicia automaticamente no login

---

## 🚀 Instalação Rápida

### Pré-requisitos

- **Python 3.10+**
- **rclone** (com remote `gdrive:` configurado)
- Linux com systemd (user services)

### 1. Configurar o Google Drive no rclone

```bash
rclone config
```

Crie um remote chamado `gdrive:` com:
- Tipo: `drive`
- Escopo: `drive` (acesso completo) ou `drive.file`
- Autenticação via OAuth no navegador

### 2. Clonar e instalar

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
| **Frontend** | HTML + CSS + Vanilla JS (`cachedFetch` com TTL 2 min) |
| **Streaming** | `rclone serve http` (VFS cache 5G, chunk 32M) |
| **Cache** | SQLite (browsing) + RAM (movie details) |
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

### Limpar cache

```bash
rm -rf ~/.cache/ticianoflix/
systemctl --user restart ticianoflix
```

### Atualizar

```bash
cd ~/TicianoFlix
git pull
systemctl --user restart ticianoflix
```

---

## 📝 Licença

MIT — veja o arquivo [LICENSE](LICENSE).
