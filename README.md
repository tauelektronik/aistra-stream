# aistra-stream

Painel de gerenciamento de streams IPTV com entrega HLS, suporte a DRM CENC-CTR, ABR multi-qualidade e autenticação JWT por papéis.

---

## Índice

- [Visão Geral](#visão-geral)
- [Funcionalidades](#funcionalidades)
- [Arquitetura](#arquitetura)
- [Requisitos](#requisitos)
- [Instalação Rápida](#instalação-rápida)
- [Instalação Manual](#instalação-manual)
- [Configuração (.env)](#configuração-env)
- [Atualização](#atualização)
- [Docker Compose](#docker-compose)
- [API REST](#api-rest)
- [Papéis e Permissões](#papéis-e-permissões)
- [Pipelines de Streaming](#pipelines-de-streaming)
- [Variáveis de Ambiente Avançadas](#variáveis-de-ambiente-avançadas)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Banco de Dados](#banco-de-dados)
- [Segurança](#segurança)
- [Solução de Problemas](#solução-de-problemas)

---

## Visão Geral

**aistra-stream** é um painel web completo para recepção, transcodificação e distribuição de canais IPTV via HLS. Recebe streams de qualquer origem (HTTP, RTSP, RTMP, UDP, arquivos locais, YouTube) e os distribui como HLS segmentado para players como hls.js, VLC ou qualquer dispositivo compatível.

| Componente | Tecnologia |
|---|---|
| Backend API | FastAPI + SQLAlchemy (async) + aiomysql |
| Banco de Dados | MySQL 8 / MariaDB 10.6+ |
| Frontend | React 18 + TypeScript + Vite |
| Streaming | ffmpeg (transcodificação e HLS) |
| DRM | n_m3u8DL-RE + mp4decrypt (CENC-CTR) |
| YouTube | yt-dlp |
| Autenticação | JWT (python-jose) + bcrypt |

---

## Funcionalidades

### Streams
- Cadastro de streams com ID personalizado e número de canal auto-incrementado
- Suporte a múltiplos protocolos de entrada: `http`, `https`, `rtmp`, `rtsp`, `udp`, `rtp`, `srt`, `file`
- Transcodificação de vídeo: `copy` (passthrough), `libx264`, `h264_nvenc` (GPU NVIDIA)
- Transcodificação de áudio: `copy`, `aac`
- Controle de CRF, preset, resolução e bitrate máximo
- Seleção de faixa de áudio (track 0–9)
- URLs de backup / failover (newline-separated) com troca automática em caso de falha
- Proxy HTTP/HTTPS/SOCKS4/SOCKS5 por stream
- User-Agent personalizado por stream
- Saída simultânea para RTMP (ex: YouTube Live, Twitch) e UDP/RTP/SRT
- ABR multi-qualidade: 360p / 480p / 720p / 1080p geradas em paralelo

### DRM
- Suporte completo a CENC-CTR (streams protegidos com Widevine/PlayReady)
- Pipeline: `n_m3u8DL-RE` (download + decrypt) → FIFO → `ffmpeg` → HLS
- Múltiplas chaves DRM (KID:KEY) por stream

### HLS
- Segmentos `.ts` com duração e tamanho de playlist configuráveis
- Limpeza automática de sessões inativas (60 s)
- Watchdog com restart automático (máx 5 tentativas, delay de 15 s)
- Detecção de stall por bitrate zero (3 polls consecutivos → restart)
- Thumbnail automático por stream (atualiza a cada 30 s)
- Exportação M3U de todos os canais habilitados

### Categorias
- Agrupamento de streams por categoria
- Logo de categoria com upload de imagem

### Usuários
- Três papéis: `admin`, `operator`, `viewer`
- Criação / edição / desativação de usuários (admin only)
- Usuário padrão criado automaticamente: `admin` / `admin123`

### Painel
- Dashboard com stats do servidor em tempo real: CPU, RAM, disco, rede, GPU (NVIDIA)
- Stats por stream: uptime, bitrate, FPS, speed, total transferido
- Log de ffmpeg por stream (últimas N linhas)
- Alertas via Telegram (bot token + chat ID)

### Backup / Restore
- Backup profissional em ZIP: streams, usuários, categorias, configurações e logos
- Backup automático agendável com retenção configurável (padrão: diário, 7 arquivos)
- Armazenamento no servidor com lista, download, restauração e deleção via painel
- Restauração por upload de arquivo ZIP ou seleção de backup armazenado
- Backup legado JSON mantido para compatibilidade

### Importação M3U
- Import em lote de canais a partir de arquivo `.m3u` ou `.m3u8`
- Lê automaticamente `tvg-id`, `tvg-name`, `group-title`
- Opção de sobrescrever streams existentes (mesmo ID)

---

## Arquitetura

```
┌──────────────────────────────────────────────────────────┐
│                    Cliente (Browser)                     │
│          React SPA  ←→  hls.js (player HLS)             │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP  (porta 8001)
┌──────────────────────▼───────────────────────────────────┐
│                FastAPI  (backend/main.py)                │
│   Auth JWT · CRUD Streams/Users/Categories · Settings   │
│   Rate limiting · Security headers · Audit log          │
└──────┬──────────────────────────┬────────────────────────┘
       │                          │
┌──────▼──────┐          ┌────────▼──────────────────────┐
│  MariaDB/   │          │    HLS Manager                │
│  MySQL      │          │  (backend/hls_manager.py)     │
│  (SQLAlchemy│          │                               │
│   async)    │          │  ┌─── Pipeline CENC ───────┐  │
└─────────────┘          │  │ n_m3u8dl → FIFO → ffmpeg│  │
                         │  └─────────────────────────┘  │
                         │  ┌─── Pipeline HTTP ────────┐  │
                         │  │ ffmpeg (direct)          │  │
                         │  └─────────────────────────┘  │
                         │  ┌─── Pipeline YouTube ─────┐  │
                         │  │ yt-dlp → ffmpeg pipe     │  │
                         │  └─────────────────────────┘  │
                         │                               │
                         │  Watchdog · Cleanup · Thumbs  │
                         └──────────────┬────────────────┘
                                        │
                         /tmp/aistra_stream_hls/{id}/
                         stream.m3u8 + seg*.ts
```

---

## Requisitos

### Sistema Operacional
- Ubuntu 22.04 / 24.04 (recomendado)
- Debian 11/12, CentOS 8+, AlmaLinux, Rocky, Fedora, Arch

### Software Obrigatório
| Software | Versão Mínima | Notas |
|---|---|---|
| Python | 3.10+ | com `venv` |
| Node.js | 18+ | para build do frontend |
| MariaDB / MySQL | 10.6+ / 8.0+ | |
| ffmpeg | 4.4+ | no `PATH` |

### Software Opcional (features avançadas)
| Software | Finalidade |
|---|---|
| `n_m3u8dl` | Streams CENC-CTR (DRM) |
| `mp4decrypt` (Bento4) | Descriptografia CENC (usado internamente pelo n_m3u8dl) |
| `yt-dlp` | Streams do YouTube |
| NVIDIA GPU + drivers | Transcodificação com `h264_nvenc` |

---

## Instalação Rápida

Execute em um servidor Linux limpo como **root**:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/tauelektronik/aistra-stream/main/install.sh)
```

O script:
1. Detecta a distribuição Linux automaticamente
2. Instala Node.js 20, MariaDB, ffmpeg e dependências
3. Instala `n_m3u8dl`, `mp4decrypt` (Bento4) e `yt-dlp`
4. Clona o repositório em `/opt/aistra-stream`
5. Cria o banco de dados com senha aleatória segura
6. Gera o arquivo `.env` com `SECRET_KEY` aleatória
7. Builda o frontend React
8. Cria e inicia o serviço systemd `aistra-stream`
9. Configura logrotate
10. Libera a porta no firewall (ufw/firewalld)

Após a instalação, acesse: `http://SEU_IP:8001` — login: `admin` / `admin123`

> **IMPORTANTE:** Troque a senha padrão imediatamente após o primeiro acesso.

---

## Instalação Manual

```bash
# 1. Clonar o repositório
git clone https://github.com/tauelektronik/aistra-stream.git /opt/aistra-stream
cd /opt/aistra-stream

# 2. Criar banco de dados
mysql -u root -e "
  CREATE DATABASE aistra_stream CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER 'aistra'@'localhost' IDENTIFIED BY 'SUA_SENHA_AQUI';
  GRANT ALL ON aistra_stream.* TO 'aistra'@'localhost';
  FLUSH PRIVILEGES;"

# 3. Configurar .env
cp .env.example .env
# Edite .env com suas credenciais (veja seção Configuração)

# 4. Criar venv Python e instalar dependências
python3 -m venv venv
./venv/bin/pip install -r backend/requirements.txt

# 5. Build do frontend
cd frontend && npm install && npm run build && cd ..

# 6. Criar serviço systemd
cat > /etc/systemd/system/aistra-stream.service <<EOF
[Unit]
Description=Aistra Stream Panel
After=network.target mariadb.service

[Service]
Type=simple
WorkingDirectory=/opt/aistra-stream
EnvironmentFile=/opt/aistra-stream/.env
ExecStart=/opt/aistra-stream/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5
StandardOutput=append:/var/log/aistra-stream.log
StandardError=append:/var/log/aistra-stream.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now aistra-stream
```

---

## Configuração (.env)

Copie `.env.example` para `.env` e preencha:

```env
# ── Banco de dados ─────────────────────────────────────────
DATABASE_URL=mysql+aiomysql://aistra:SENHA@localhost:3306/aistra_stream

# ── Segurança ──────────────────────────────────────────────
# Gere com: python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=GERE_UMA_CHAVE_SEGURA_AQUI

# Expiração do token JWT em minutos (padrão: 24h)
TOKEN_EXPIRE_MINUTES=1440

# ── CORS ───────────────────────────────────────────────────
# Origens permitidas, vírgula-separadas
# Deixe vazio para usar apenas localhost
ALLOWED_ORIGINS=https://meupanel.com

# ── Rate Limiting (login) ──────────────────────────────────
LOGIN_RATE_LIMIT=10     # tentativas máximas por IP
LOGIN_RATE_WINDOW=60    # janela em segundos

# ── Binários ───────────────────────────────────────────────
FFMPEG=/usr/bin/ffmpeg
N_M3U8DL=/usr/local/bin/n_m3u8dl
MP4DECRYPT=/usr/local/bin/mp4decrypt
YTDLP=/usr/local/bin/yt-dlp

# ── Diretórios ─────────────────────────────────────────────
HLS_BASE=/tmp/aistra_stream_hls
PIPE_BASE=/tmp/aistra_stream_pipes
TMP_BASE=/tmp/aistra_stream_tmp
RECORDINGS_BASE=/opt/aistra-stream/recordings
THUMBNAILS_BASE=/tmp/aistra_thumbnails
LOGOS_BASE=/opt/aistra-stream/logos
BACKUPS_BASE=/opt/aistra-stream/backups

# ── Servidor ───────────────────────────────────────────────
HOST=0.0.0.0
PORT=8001

# ── Telegram (opcional) ────────────────────────────────────
# TELEGRAM_BOT_TOKEN=123456:ABCdef...
# TELEGRAM_CHAT_ID=-100123456789

# ── Watchdog HLS ───────────────────────────────────────────
# HLS_MAX_RESTARTS=5        # máx restarts antes de desistir
# HLS_WATCHDOG_INTERVAL=10  # intervalo de verificação (s)
# HLS_RESTART_DELAY=15      # delay entre restarts (s)
# HLS_STABLE_RUN=60         # segundos rodando para resetar contador
# HLS_STALL_CHECKS=3        # polls de bitrate zero antes de restart

# ── Dev / Debug ────────────────────────────────────────────
# AISTRA_SHOW_DOCS=1        # Habilita /docs e /openapi.json
```

---

## Atualização

Para atualizar uma instalação existente:

```bash
sudo bash /opt/aistra-stream/update.sh
```

O script faz: `git pull` → `pip install` → `npm build` → `systemctl restart` → health check.

Ou manualmente, passo a passo:

```bash
cd /opt/aistra-stream
git pull
./venv/bin/pip install -q -r backend/requirements.txt
cd frontend && npm install --silent && npm run build && cd ..
systemctl restart aistra-stream
```

As **migrações de banco** são aplicadas automaticamente no startup via `run_migrations()` em `database.py` — sem intervenção manual.

---

## Docker Compose

```bash
# Copiar e editar variáveis
cp .env.example .env
# Edite .env conforme necessário

# Subir os serviços
docker compose up -d

# Ver logs
docker compose logs -f app
```

O `docker-compose.yml` inclui:
- Serviço `app` (FastAPI + frontend buildado)
- Serviço `db` (MySQL 8) com healthcheck
- Volume persistente para gravações

> Para usar DRM (n_m3u8dl, mp4decrypt) no container, adicione os binários à imagem via `Dockerfile`.

---

## API REST

Todas as rotas (exceto `/auth/login` e `/health`) requerem header:
```
Authorization: Bearer <token>
```

### Autenticação

| Método | Rota | Descrição |
|---|---|---|
| POST | `/auth/login` | Login — retorna `access_token` |
| GET | `/auth/me` | Dados do usuário autenticado |

**Login:**
```json
POST /auth/login
{"username": "admin", "password": "admin123"}

→ {"access_token": "eyJ...", "token_type": "bearer"}
```

### Streams

| Método | Rota | Permissão | Descrição |
|---|---|---|---|
| GET | `/api/streams` | viewer+ | Listar todos os streams com status |
| POST | `/api/streams` | operator+ | Criar stream |
| GET | `/api/streams/{id}` | viewer+ | Detalhe de um stream |
| PUT | `/api/streams/{id}` | operator+ | Atualizar stream |
| DELETE | `/api/streams/{id}` | operator+ | Remover stream |
| POST | `/api/streams/{id}/stop` | operator+ | Parar pipeline HLS |
| GET | `/api/streams/{id}/log` | operator+ | Log ffmpeg (últimas N linhas) |
| GET | `/api/streams/{id}/stats` | viewer+ | Stats em tempo real (bitrate, fps, uptime) |
| GET | `/api/streams/{id}/thumbnail` | viewer+ | Thumbnail JPEG atual |
| POST | `/api/streams/{id}/start` | operator+ | Iniciar pipeline HLS manualmente |
| GET | `/api/streams/export.m3u` | viewer+ | Exportar playlist M3U de todos os canais |

**Criar stream (exemplo mínimo):**
```json
POST /api/streams
{
  "id": "globo-hd",
  "name": "Globo HD",
  "url": "http://exemplo.com/stream.m3u8"
}
```

**Campos disponíveis em StreamCreate/StreamUpdate:**

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `id` | string(2-50) | — | ID único (a-z, 0-9, `_`, `-`) — só em Create |
| `name` | string | — | Nome do canal |
| `url` | string | — | URL de origem |
| `channel_num` | int(1-99999) | auto | Número do canal (auto-incrementado se omitido) |
| `stream_type` | `live`/`vod` | `live` | Tipo de stream |
| `drm_type` | `none`/`cenc-ctr` | `none` | Tipo de DRM |
| `drm_keys` | string | null | Chaves DRM no formato `KID:KEY` (uma por linha) |
| `video_codec` | `copy`/`libx264`/`h264_nvenc` | `libx264` | Codec de vídeo |
| `video_preset` | string | `ultrafast` | Preset de compressão libx264 |
| `video_crf` | int(0-51) | 26 | Qualidade (CRF) — 0=lossless, 51=pior |
| `video_maxrate` | string | `""` | Bitrate máximo (ex: `"4000k"`) |
| `video_resolution` | string | `original` | Resolução: `original`, `1920x1080`, `1280x720`, `854x480` |
| `audio_codec` | `copy`/`aac` | `aac` | Codec de áudio |
| `audio_bitrate` | string | `128k` | Bitrate de áudio (ex: `"192k"`) |
| `audio_track` | int(0-9) | 0 | Índice da faixa de áudio |
| `hls_time` | int(1-10) | 4 | Duração dos segmentos HLS em segundos |
| `hls_list_size` | int(3-30) | 8 | Número de segmentos na playlist |
| `output_rtmp` | string | null | URL RTMP de saída (ex: `rtmp://live.twitch.tv/live/KEY`) |
| `output_udp` | string | null | URL UDP/RTP/SRT de saída |
| `output_qualities` | string | null | ABR: `"1080p,720p,480p"` |
| `proxy` | string | null | Proxy: `http://user:pass@host:port` ou `socks5://...` |
| `user_agent` | string | null | User-Agent personalizado |
| `backup_urls` | string | null | URLs de failover (uma por linha) |
| `category` | string | null | Categoria/grupo |
| `enabled` | bool | true | Habilita/desabilita o canal |

### Usuários (admin only)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/users` | Listar usuários |
| POST | `/api/users` | Criar usuário |
| PUT | `/api/users/{id}` | Atualizar usuário |
| DELETE | `/api/users/{id}` | Remover usuário |

### Categorias

| Método | Rota | Permissão | Descrição |
|---|---|---|---|
| GET | `/api/categories` | viewer+ | Listar categorias |
| POST | `/api/categories` | operator+ | Criar categoria |
| PUT | `/api/categories/{id}` | operator+ | Atualizar nome |
| DELETE | `/api/categories/{id}` | operator+ | Remover (desassocia streams) |
| POST | `/api/categories/{id}/logo` | operator+ | Upload de logo (imagem) |
| PUT | `/api/categories/{id}/streams` | operator+ | Atribuir streams à categoria |

### Configurações (admin only)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/settings` | Ler configurações (Telegram, backup, etc) |
| PUT | `/api/settings` | Salvar configurações |

### Backup Profissional (admin only)

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/backup/create` | Criar backup ZIP manual e armazenar no servidor |
| GET | `/api/backup/list` | Listar backups armazenados |
| GET | `/api/backup/download/{filename}` | Baixar arquivo ZIP |
| DELETE | `/api/backup/{filename}` | Deletar backup do servidor |
| POST | `/api/backup/restore/{filename}` | Restaurar de backup armazenado no servidor |
| POST | `/api/backup/restore-upload` | Restaurar a partir de upload de ZIP |
| GET | `/api/settings/backup` | (legado) Exportar backup JSON |
| POST | `/api/settings/restore` | (legado) Importar backup JSON |

### Importação M3U (admin only)

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/streams/import-m3u` | Importar canais em lote a partir de arquivo M3U |

### Dashboard / Stats

| Método | Rota | Permissão | Descrição |
|---|---|---|---|
| GET | `/api/server/stats` | operator+ | CPU, RAM, disco, rede, GPU |
| GET | `/health` | público | Health check (retorna `{"status":"ok"}`) |

### HLS — Player

| Método | Rota | Descrição |
|---|---|---|
| GET | `/stream/{id}/hls/stream.m3u8` | Playlist HLS — inicia pipeline automaticamente |
| GET | `/stream/{id}/hls/{segment}` | Segmento `.ts` |

**Exemplo de play no VLC:**
```
http://SEU_IP:8001/stream/globo-hd/hls/stream.m3u8
```

---

## Papéis e Permissões

| Ação | viewer | operator | admin |
|---|:---:|:---:|:---:|
| Ver streams e status | ✓ | ✓ | ✓ |
| Assistir HLS / baixar M3U | ✓ | ✓ | ✓ |
| Criar / editar / deletar streams | — | ✓ | ✓ |
| Iniciar / parar pipelines | — | ✓ | ✓ |
| Ver logs de ffmpeg | — | ✓ | ✓ |
| Gerenciar categorias | — | ✓ | ✓ |
| Ver stats do servidor | — | ✓ | ✓ |
| Gerenciar usuários | — | — | ✓ |
| Backup / Restore | — | — | ✓ |
| Configurações (Telegram, etc) | — | — | ✓ |

---

## Pipelines de Streaming

### Pipeline 1 — HTTP/HTTPS (sem DRM)

```
URL de origem (HTTP/HTTPS/RTSP/RTMP/UDP)
    ↓
ffmpeg -i <url>
    → HLS: /tmp/aistra_stream_hls/{id}/stream.m3u8 + seg*.ts
    → RTMP (opcional): rtmp://...
    → UDP/SRT (opcional): udp://...
```

### Pipeline 2 — CENC-CTR (DRM)

```
URL protegida (HLS/DASH CENC)
    ↓
n_m3u8DL-RE --key KID:KEY --live-pipe-mux
    ↓ (pipe FIFO: /tmp/aistra_stream_pipes/{id}.ts)
ffmpeg -i <fifo>
    → HLS: /tmp/aistra_stream_hls/{id}/stream.m3u8 + seg*.ts
```

### Pipeline 3 — YouTube

```
URL do YouTube (watch?v=...)
    ↓
yt-dlp -f bestvideo+bestaudio (cookies opcionais)
    ↓ (stdout pipe)
ffmpeg -i pipe:0
    → HLS: /tmp/aistra_stream_hls/{id}/stream.m3u8 + seg*.ts
```

### Watchdog

O HLS Manager monitora cada sessão a cada `HLS_WATCHDOG_INTERVAL` (padrão: 10 s):
- Se o processo ffmpeg morreu → restart automático
- Se o bitrate ficou em 0 por `HLS_STALL_CHECKS` (3) polls consecutivos → restart
- Após `HLS_STABLE_RUN` (60 s) rodando continuamente → contador de restarts é zerado
- Após `HLS_MAX_RESTARTS` (5) restarts sem sucesso → sessão marcada como `error` e alerta Telegram enviado

### Thumbnail automático

A cada 30 s para streams em execução, o backend executa:
```
ffmpeg -ss 0 -i stream.m3u8 -vframes 1 -f image2 {id}.jpg
```
O resultado é servido em `/api/streams/{id}/thumbnail`.

---

## Variáveis de Ambiente Avançadas

| Variável | Padrão | Descrição |
|---|---|---|
| `HLS_MAX_RESTARTS` | `5` | Máximo de restarts automáticos do watchdog |
| `HLS_WATCHDOG_INTERVAL` | `10` | Intervalo do watchdog em segundos |
| `HLS_RESTART_DELAY` | `15` | Delay entre restarts em segundos |
| `HLS_STABLE_RUN` | `60` | Segundos rodando para resetar contador de restarts |
| `HLS_STALL_CHECKS` | `3` | Polls de bitrate zero antes de acionar restart |
| `HLS_YT_REFRESH_H` | `4.0` | Horas para refresh proativo de URLs do YouTube |
| `TELEGRAM_BOT_TOKEN` | `""` | Token do bot do Telegram para alertas |
| `TELEGRAM_CHAT_ID` | `""` | Chat ID do Telegram (pode ser grupo, negativo) |
| `YTDLP_COOKIES` | `/opt/youtube_cookies.txt` | Path para arquivo de cookies do YouTube |
| `AISTRA_SHOW_DOCS` | — | Qualquer valor ativa `/docs` (Swagger UI) |
| `AISTRA_INSECURE_KEY` | — | Permite iniciar sem `SECRET_KEY` (apenas dev) |
| `BACKUPS_BASE` | `PROJECT_ROOT/backups` | Diretório para armazenar arquivos de backup ZIP |
| `AISTRA_SETTINGS_FILE` | `PROJECT_ROOT/data/settings.json` | Path legado do JSON de settings (migrado automaticamente para o DB) |

---

## Estrutura do Projeto

```
aistra-stream/
├── backend/
│   ├── __init__.py
│   ├── main.py           # FastAPI app, todas as rotas, middleware
│   ├── models.py         # SQLAlchemy ORM (User, Stream, Category)
│   ├── schemas.py        # Pydantic schemas com validação
│   ├── crud.py           # Operações CRUD assíncronas
│   ├── database.py       # Engine SQLAlchemy + init_db + run_migrations
│   ├── auth.py           # JWT, bcrypt, decorators de permissão
│   ├── hls_manager.py    # Pipelines HLS, watchdog, thumbnails
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Login.tsx       # Tela de login
│   │   │   ├── Dashboard.tsx   # Stats do servidor
│   │   │   ├── Streams.tsx     # Lista e gerenciamento de streams
│   │   │   ├── Categories.tsx  # Gerenciamento de categorias
│   │   │   ├── Users.tsx       # Gerenciamento de usuários (admin)
│   │   │   ├── Settings.tsx    # Configurações (Telegram, backup)
│   │   │   └── Layout.tsx      # Layout com sidebar de navegação
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
│
├── .env.example          # Template de configuração
├── install.sh            # Instalador universal Linux
├── update.sh             # Script de atualização
├── docker-compose.yml    # Deploy via Docker
├── Dockerfile            # Imagem Docker
├── nginx.conf            # Config Nginx (proxy reverso)
├── schema.sql            # Schema inicial do banco
└── setup_ssl.sh          # Configuração SSL com Let's Encrypt
```

---

## Banco de Dados

### Tabelas

**`users`**
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | INT PK | ID auto-incrementado |
| `username` | VARCHAR(50) UNIQUE | Nome de usuário |
| `password_hash` | VARCHAR(255) | Hash bcrypt |
| `email` | VARCHAR(100) | Email (opcional) |
| `role` | ENUM | `admin`, `operator`, `viewer` |
| `active` | BOOLEAN | Ativo/inativo |
| `created_at` | DATETIME | Data de criação |

**`streams`**
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | VARCHAR(50) PK | ID textual definido pelo usuário |
| `channel_num` | INT UNIQUE | Número de canal (auto-incrementado) |
| `name` | VARCHAR(150) | Nome do canal |
| `url` | TEXT | URL de origem |
| `drm_type` | ENUM | `none`, `cenc-ctr` |
| `drm_keys` | TEXT | Chaves DRM (KID:KEY por linha) |
| `stream_type` | ENUM | `live`, `vod` |
| `video_codec` | ENUM | `copy`, `libx264`, `h264_nvenc` |
| `video_crf` | INT | CRF de compressão |
| `output_rtmp` | VARCHAR(500) | URL RTMP de saída |
| `output_udp` | VARCHAR(200) | URL UDP/SRT de saída |
| `output_qualities` | VARCHAR(50) | ABR qualities |
| `category` | VARCHAR(100) | Categoria |
| `enabled` | BOOLEAN | Habilitado/desabilitado |
| `created_at` / `updated_at` | DATETIME | Timestamps |

**`categories`**
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | INT PK | ID auto-incrementado |
| `name` | VARCHAR(100) UNIQUE | Nome da categoria |
| `logo_path` | VARCHAR(500) | Nome do arquivo de logo |
| `created_at` | DATETIME | Data de criação |

**`settings`**
| Coluna | Tipo | Descrição |
|---|---|---|
| `key` | VARCHAR(100) PK | Nome da configuração |
| `value` | TEXT | Valor serializado em JSON |

Substitui o arquivo `data/settings.json`. Ao atualizar, o arquivo existente é migrado automaticamente para o banco e renomeado para `.migrated`.

**`connection_logs`**
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | INT PK | ID auto-incrementado |
| `username` | VARCHAR(50) | Usuário que tentou login |
| `ip` | VARCHAR(64) | IP do cliente |
| `success` | BOOLEAN | Login bem-sucedido ou não |
| `created_at` | DATETIME | Timestamp (auto-rotação: 90 dias) |

**`login_attempts_rl`**
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | INT PK | ID auto-incrementado |
| `ip` | VARCHAR(64) | IP do cliente |
| `attempted_at` | DATETIME | Timestamp da tentativa |

Rate limiter persistente em banco — substitui o dict em memória. Sobrevive a restarts e funciona com múltiplos workers.

### Migrações

Novas colunas são adicionadas automaticamente via `run_migrations()` no startup. Para adicionar uma migração:

```python
# backend/database.py → run_migrations()
migrations = [
    "ALTER TABLE streams ADD COLUMN channel_num INT NULL UNIQUE",
    # adicione novas aqui — cada ALTER é idempotente (try/except)
]
```

---

## Segurança

O backend aplica as seguintes proteções:

- **JWT com expiração**: tokens expiram após `TOKEN_EXPIRE_MINUTES` (padrão: 24 h)
- **bcrypt**: todas as senhas armazenadas com hash bcrypt
- **Rate limiting no login (DB-backed)**: máximo de `LOGIN_RATE_LIMIT` tentativas por IP por `LOGIN_RATE_WINDOW` segundos — persistido no banco, sobrevive a restarts (429 Too Many Requests)
- **Security headers** em todas as respostas:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Content-Security-Policy` restritiva
  - `Referrer-Policy: strict-origin-when-cross-origin`
- **Validação de URL**: apenas protocolos permitidos (`http`, `https`, `rtmp`, `rtsp`, `udp`, `rtp`, `srt`, `file`)
- **Path traversal prevention**: endpoints de arquivo usam `os.path.realpath()` para impedir acesso fora dos diretórios base
- **Audit log**: criação/edição/deleção de streams e usuários registrados com ator, alvo e IP (`logger aistra.audit`)
- **CORS configurável**: origens permitidas definidas via `ALLOWED_ORIGINS`
- **SECRET_KEY obrigatória**: o serviço não inicia se `SECRET_KEY` não estiver definida ou tiver menos de 32 caracteres (exceto com `AISTRA_INSECURE_KEY=1`)

---

## Solução de Problemas

### Serviço não inicia

```bash
journalctl -u aistra-stream -n 50 --no-pager
```

Causas comuns:
- `SECRET_KEY` não configurada no `.env`
- MariaDB não está rodando: `systemctl status mariadb`
- Credenciais de banco incorretas no `DATABASE_URL`

### Stream não inicia / fica em "stopped"

```bash
# Ver log do ffmpeg para o stream
curl -H "Authorization: Bearer TOKEN" http://localhost:8001/api/streams/ID/log

# Ou direto no arquivo:
cat /tmp/ffmpeg_ID.log
```

Causas comuns:
- URL de origem inacessível do servidor
- ffmpeg não encontrado: verifique `FFMPEG=` no `.env`
- Para DRM: `n_m3u8dl` não instalado ou chaves incorretas

### Dashboard sem stats do servidor (CPU/RAM)

O módulo `psutil` precisa estar instalado no venv:
```bash
/opt/aistra-stream/venv/bin/pip install psutil
```

### Frontend não carrega (tela em branco)

Verifique se o build existe:
```bash
ls /opt/aistra-stream/frontend/dist/
# Se vazio: cd /opt/aistra-stream/frontend && npm install && npm run build
```

### Porta 8001 não acessível

```bash
# ufw
ufw allow 8001/tcp

# firewalld
firewall-cmd --permanent --add-port=8001/tcp && firewall-cmd --reload
```

### Atualizar sem perder dados

Use `update.sh` — ele **nunca** apaga o `.env` ou o banco de dados.
As migrações de schema são aplicadas automaticamente e de forma segura.

---

## Comandos Úteis

```bash
# Status do serviço
systemctl status aistra-stream

# Logs em tempo real
journalctl -u aistra-stream -f

# Reiniciar
systemctl restart aistra-stream

# Parar
systemctl stop aistra-stream

# Atualizar
sudo bash /opt/aistra-stream/update.sh

# Backup manual do banco
mysqldump -u aistra -p aistra_stream > backup_$(date +%Y%m%d).sql

# Ver logs de auditoria
journalctl -u aistra-stream | grep "aistra.audit"
```

---

## Licença

Projeto proprietário — todos os direitos reservados.
