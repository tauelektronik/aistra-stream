# Tutorial Completo — aistra-stream

Guia passo a passo para instalar, configurar e operar o painel de streaming IPTV.

---

## Índice

1. [O que é o aistra-stream](#1-o-que-é-o-aistra-stream)
2. [Requisitos do servidor](#2-requisitos-do-servidor)
3. [Antes de instalar — GitHub Token](#3-antes-de-instalar--github-token)
4. [Instalação automática](#4-instalação-automática)
5. [Primeiro acesso](#5-primeiro-acesso)
6. [Configuração inicial](#6-configuração-inicial)
7. [Adicionando streams](#7-adicionando-streams)
8. [Streams YouTube](#8-streams-youtube)
9. [Streams com DRM (CENC-CTR)](#9-streams-com-drm-cenc-ctr)
10. [Categorias](#10-categorias)
11. [Gravações](#11-gravações)
12. [Dashboard e monitoramento](#12-dashboard-e-monitoramento)
13. [Usuários e permissões](#13-usuários-e-permissões)
14. [Backup e restore](#14-backup-e-restore)
15. [Alertas Telegram](#15-alertas-telegram)
16. [Prometheus / métricas](#16-prometheus--métricas)
17. [Atualizando o sistema](#17-atualizando-o-sistema)
18. [Desinstalação](#18-desinstalação)
19. [Solução de problemas](#19-solução-de-problemas)
20. [Referência rápida — variáveis de ambiente](#20-referência-rápida--variáveis-de-ambiente)

---

## 1. O que é o aistra-stream

O **aistra-stream** é um painel web completo para receber canais de TV ao vivo (IPTV) de qualquer origem e redistribuí-los como HLS para qualquer player ou dispositivo.

```
Fonte de vídeo            aistra-stream             Dispositivos
─────────────             ─────────────             ────────────
TV ao vivo (HTTP)  ───►   ffmpeg transcodifica  ───► Browser
Canal CENC/DRM     ───►   e entrega como HLS    ───► VLC
YouTube live       ───►   via /stream/{id}/     ───► Smart TV
RTSP / RTMP / UDP  ───►   hls/stream.m3u8       ───► Qualquer player
```

**Principais recursos:**
- Recebe streams de qualquer protocolo (HTTP, HTTPS, RTSP, RTMP, UDP, SRT, YouTube)
- Transcodifica com ffmpeg (ou passthrough `copy`)
- ABR multi-qualidade (1080p / 720p / 480p / 360p simultâneos)
- Suporte a DRM CENC-CTR (streams protegidos)
- Dashboard de monitoramento em tempo real
- Detecção visual automática de tela preta, frame congelado e perda de sinal
- Alertas via Telegram
- Backup/restore completo
- API REST + Prometheus

---

## 2. Requisitos do servidor

### Sistema operacional
- **Ubuntu 22.04 ou 24.04** (recomendado)
- Debian 11/12, CentOS 8+, AlmaLinux, Rocky Linux, Fedora 38+, Arch Linux

### Hardware mínimo
| Componente | Mínimo | Recomendado |
|---|---|---|
| CPU | 2 vCPU | 4+ vCPU |
| RAM | 2 GB | 4+ GB |
| Disco | 20 GB | 50+ GB (para gravações) |
| Rede | 100 Mbps | 1 Gbps |

> Para cada stream em transcodificação (`libx264`), calcule ~1 núcleo de CPU.
> Com `copy` (passthrough), o consumo é mínimo.

### Acesso necessário
- Acesso SSH como **root** ao servidor
- Porta **8001** aberta no firewall (ou a porta escolhida)

---

## 3. Antes de instalar — GitHub Token

O repositório é privado. Para o instalador clonar automaticamente, você precisa de um **GitHub Personal Access Token (PAT)** com permissão de leitura.

### Passo a passo para criar o token

1. Acesse: **GitHub.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens**

2. Clique em **"Generate new token"**

3. Preencha:
   - **Token name:** `aistra-stream-install`
   - **Expiration:** 90 days (ou conforme necessidade)
   - **Repository access:** Only select repositories → `tauelektronik/aistra-stream`
   - **Permissions → Contents:** `Read-only`

4. Clique em **"Generate token"** e copie o token (começa com `ghp_...`)

> **Guarde esse token!** Ele só é exibido uma vez.

---

## 4. Instalação automática

### Instalação em uma linha (modo padrão — porta 8001)

Conecte ao servidor via SSH e execute:

```bash
# 1. Exporte o token GitHub (substitua pelo seu token)
export GH_TOKEN=ghp_SEU_TOKEN_AQUI

# 2. Execute o instalador
bash <(curl -fsSL "https://raw.githubusercontent.com/tauelektronik/aistra-stream/main/install.sh")
```

O instalador vai automaticamente:
1. Detectar a distribuição Linux
2. Instalar ffmpeg, MariaDB, Node.js 20 e Python 3
3. Instalar n_m3u8dl, mp4decrypt e yt-dlp
4. Criar banco de dados com senha segura aleatória
5. Clonar o repositório em `/opt/aistra-stream`
6. Criar o ambiente Python com todas as dependências
7. Buildar o frontend React
8. Criar e iniciar o serviço systemd
9. Configurar logrotate
10. Abrir a porta no firewall

**Duração estimada:** 5–15 minutos dependendo da velocidade da internet.

---

### Opções de instalação avançada

```bash
# Porta personalizada
export GH_TOKEN=ghp_xxx
bash <(curl -fsSL "...install.sh") --port 9000

# Sem DRM (não instala n_m3u8dl/mp4decrypt)
bash <(curl -fsSL "...install.sh") --no-drm

# Sem YouTube (não instala yt-dlp)
bash <(curl -fsSL "...install.sh") --no-yt

# Diretório personalizado
bash <(curl -fsSL "...install.sh") --dir /srv/aistra

# Combinar opções
bash <(curl -fsSL "...install.sh") --port 9000 --no-drm --dir /srv/aistra
```

---

### O que o instalador cria

```
/opt/aistra-stream/          ← Diretório do projeto
├── .env                     ← Configurações (gerado automaticamente)
├── .install-manifest        ← Manifesto para o desinstalador
├── recordings/              ← Gravações MP4
├── logos/                   ← Logos de categorias
├── backups/                 ← Backups ZIP
├── venv/                    ← Ambiente Python
└── frontend/dist/           ← Frontend React buildado

/etc/systemd/system/aistra-stream.service
/etc/logrotate.d/aistra-stream
/var/log/aistra-stream.log
```

---

### Ao final da instalação você verá

```
╔══════════════════════════════════════════════════════╗
║         Instalação concluída com sucesso!            ║
╚══════════════════════════════════════════════════════╝

  Painel:          http://SEU_IP:8001
  Login padrão:    admin / admin123
  Metrics token:   a1b2c3d4...

  ⚠  IMPORTANTE: Troque a senha padrão imediatamente!
```

---

## 5. Primeiro acesso

1. Abra o navegador e acesse: `http://SEU_IP:8001`

2. Faça login com as credenciais padrão:
   - **Usuário:** `admin`
   - **Senha:** `admin123`

3. **Imediatamente** vá em **Configurações → Usuários → admin → Editar** e troque a senha.

---

## 6. Configuração inicial

### 6.1 Trocar a senha do admin

1. Menu lateral → **Usuários**
2. Clique em **Editar** no usuário `admin`
3. Preencha **Nova Senha** (mínimo 8 caracteres)
4. Clique em **Salvar**

### 6.2 Configurar Telegram (opcional mas recomendado)

Receba alertas automáticos quando um stream cair, for banido ou o disco encher.

**Criar o bot:**
1. No Telegram, converse com `@BotFather`
2. Envie `/newbot`
3. Dê um nome e username para o bot
4. Copie o token (formato: `123456789:ABCdefGhI...`)

**Obter o Chat ID:**
1. Adicione o bot a um grupo **ou** inicie conversa direta com ele
2. Envie qualquer mensagem
3. Acesse: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Copie o valor de `"id"` dentro de `"chat"` (pode ser negativo para grupos)

**Configurar no painel:**
1. Menu lateral → **Configurações**
2. Seção **Telegram**
3. Preencha **Bot Token** e **Chat ID**
4. Clique em **Salvar**
5. Clique em **Testar** para confirmar que está funcionando

### 6.3 Configurar backup automático

1. Menu lateral → **Configurações**
2. Seção **Backup Automático**
3. Marque **Ativar backup automático**
4. Configure **intervalo** (ex: 24 horas) e **retenção** (ex: 7 arquivos)
5. Clique em **Salvar**

---

## 7. Adicionando streams

### 7.1 Criar um stream simples (HTTP/HTTPS)

1. Menu lateral → **Streams**
2. Clique em **+ Novo Stream**
3. Preencha os campos:

| Campo | Exemplo | Descrição |
|---|---|---|
| **ID** | `globo-hd` | Identificador único (letras, números, `-`, `_`) |
| **Nome** | `Globo HD` | Nome exibido no painel |
| **URL** | `http://...` | URL da fonte do stream |

4. Clique em **Salvar**
5. O stream aparece no painel com status **parado** (cinza)

### 7.2 Iniciar o stream

- Clique no botão **▶ Play** no card do stream
- Ou acesse a URL diretamente: `http://SEU_IP:8001/stream/globo-hd/hls/stream.m3u8`

Na primeira vez, pode levar 5–15 segundos para o buffer iniciar.

### 7.3 Configurações avançadas de stream

**Aba Vídeo:**
- **Codec:** `copy` (sem transcodificação, mais leve) ou `libx264` (transcodifica)
- **Resolução:** `original`, `1920x1080`, `1280x720`, etc.
- **CRF:** Qualidade de compressão (18 = alta qualidade, 28 = menor arquivo, padrão: 26)
- **Preset:** `ultrafast` (padrão, menos CPU) até `slow` (mais CPU, melhor compressão)

**Aba HLS:**
- **Duração do segmento:** 4–15 segundos (padrão: 15s — quanto menor, menor a latência)
- **Tamanho da playlist:** 8–15 segmentos (padrão: 15)

**Aba Saídas:**
- **RTMP:** Para restream simultâneo (YouTube Live, Twitch, etc.)
- **UDP/SRT:** Para retransmissão em rede local
- **ABR Multi-qualidade:** Gera 1080p+720p+480p ao mesmo tempo

**Aba Rede:**
- **Proxy:** `http://user:pass@proxy:3128` ou `socks5://proxy:1080`
- **User-Agent:** Header HTTP personalizado para a fonte

**Aba Failover:**
- **URLs de backup:** Uma URL por linha — troca automaticamente se a principal falhar

### 7.4 Assistir no player interno

Clique no ícone **▶** dentro do card do stream para abrir o player HLS.js integrado.

### 7.5 Assistir no VLC

```
Mídia → Abrir local de rede → http://SEU_IP:8001/stream/STREAM_ID/hls/stream.m3u8
```

### 7.6 Exportar playlist M3U

Todos os streams habilitados em formato M3U:
```
http://SEU_IP:8001/api/streams/export.m3u
```

---

## 8. Streams YouTube

Para streams do YouTube que requerem login (canais de membros, conteúdo restrito):

### 8.1 Stream YouTube público

1. Cole a URL do YouTube no campo **URL** do stream
2. Salve e inicie normalmente

### 8.2 Stream YouTube com login (cookies)

Quando o stream exibe o aviso **🔑 YouTube exige login**, você precisa exportar seus cookies:

**Método 1 — Extensão de navegador (recomendado):**
1. Instale a extensão **"Get cookies.txt LOCALLY"** no Chrome/Firefox
2. Acesse `youtube.com` e faça login com sua conta
3. Clique na extensão → **Export as cookies.txt**
4. Copie o conteúdo do arquivo

**Configurar no stream:**
1. Abra as **Configurações do stream**
2. Aba **YouTube**
3. Cole o conteúdo dos cookies no campo **Cookies (formato Netscape)**
4. Clique em **Salvar**

> **Aviso:** Os cookies expiram periodicamente (geralmente após 30–90 dias).
> Quando isso acontecer, o card mostrará **🔑 Cookies expirados** — basta exportar novos cookies e colar novamente.

---

## 9. Streams com DRM (CENC-CTR)

Para canais protegidos por DRM (Widevine/PlayReady):

1. Configure o stream normalmente
2. Na aba **DRM**:
   - **Tipo DRM:** `CENC-CTR`
   - **Chaves DRM:** Cole as chaves no formato `KID:KEY` (uma por linha):
     ```
     0102030405060708090a0b0c0d0e0f10:aabbccddeeff00112233445566778899
     a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6:112233445566778899aabbccddeeff00
     ```

> As chaves DRM precisam ser obtidas de forma legal (ex: ferramentas de análise próprias).

---

## 10. Categorias

Organize seus streams em grupos com logos personalizadas.

### Criar uma categoria

1. Menu lateral → **Categorias**
2. Clique em **+ Nova Categoria**
3. Digite o nome (ex: `Esportes`, `Filmes`, `Notícias`)
4. Clique em **Salvar**

### Adicionar logo à categoria

1. Na lista de categorias, clique em **Editar**
2. Clique em **Upload de Logo**
3. Selecione uma imagem (JPG, PNG, WebP — máx. 5 MB)
4. Clique em **Salvar**

### Atribuir streams a uma categoria

**Método 1 — No formulário do stream:**
- Campo **Categoria** → selecione ou digite o nome

**Método 2 — Na página de categorias:**
- Clique em **Gerenciar Streams** na categoria
- Marque os streams desejados

---

## 11. Gravações

### Iniciar uma gravação manual

1. No card do stream (que deve estar rodando), clique em **⏺ Gravar**
2. Opcional: defina a duração em minutos
3. O arquivo MP4 é salvo em `/opt/aistra-stream/recordings/`

### Agendamento de gravações

1. No stream, clique em **Agendar Gravação**
2. Configure:
   - **Horário de início**
   - **Duração** (minutos)
   - **Repetição:** único, diário ou semanal
   - **Label:** nome para identificar a gravação

### Gerenciar gravações

Menu lateral → **Gravações**
- Lista todas as gravações com tamanho e data
- Download direto pelo painel
- Exclusão individual ou em lote

### Retenção automática (opcional)

Para limpar gravações antigas automaticamente, adicione ao `.env`:
```env
RECORDING_RETENTION_DAYS=30   # apaga gravações com mais de 30 dias
```
Reinicie o serviço após alterar o `.env`:
```bash
systemctl restart aistra-stream
```

---

## 12. Dashboard e monitoramento

### Status dos streams

Cada card de stream exibe em tempo real:
- **Status:** rodando (verde), parado (cinza), erro (vermelho)
- **Bitrate:** kbits/s processados pelo ffmpeg
- **FPS:** frames por segundo
- **Uptime:** há quanto tempo está rodando
- **↻ N/5:** contador de reinícios automáticos

**Avisos automáticos no card:**
| Ícone | Significado | O que fazer |
|---|---|---|
| `⬛ Vídeo preto` | Fonte transmitindo tela preta | Verificar se a fonte está no ar |
| `🔁 Frame congelado` | Mesmo frame há mais de 30s | Reiniciar o stream |
| `📡 Sem sinal` | Nenhum segmento novo gerado | Verificar conectividade com a fonte |
| `🔑 YouTube exige login` | Sem cookies configurados | Adicionar cookies nas configurações |
| `🔑 Cookies expirados` | Cookies presentes mas inválidos | Exportar e colar novos cookies |
| `🚫 IP/conta banida` | HTTP 403/401 detectado | Trocar URL ou usar proxy |

### Dashboard do servidor

Menu lateral → **Dashboard**

Gráficos em tempo real (histórico de 5 minutos):
- **CPU:** por núcleo + total, nome, frequência, temperatura
- **Memória:** RAM + Swap (usada/total em GB)
- **Rede:** upload/download em Mbps + total acumulado
- **Disco:** porcentagem de uso (verde < 70%, laranja < 90%, vermelho ≥ 90%)
- **GPU NVIDIA:** utilização, memória, encoder %, temperatura (se disponível)

### Log em tempo real

No card do stream, clique em **Log** para ver as últimas linhas do ffmpeg ao vivo.

---

## 13. Usuários e permissões

O sistema tem três níveis de acesso:

| Permissão | viewer | operator | admin |
|---|:---:|:---:|:---:|
| Ver streams e assistir | ✓ | ✓ | ✓ |
| Baixar playlist M3U | ✓ | ✓ | ✓ |
| Criar/editar/deletar streams | — | ✓ | ✓ |
| Iniciar/parar streams | — | ✓ | ✓ |
| Ver logs do ffmpeg | — | ✓ | ✓ |
| Gerenciar categorias | — | ✓ | ✓ |
| Ver dashboard do servidor | — | ✓ | ✓ |
| Gerenciar usuários | — | — | ✓ |
| Backup/restore | — | — | ✓ |
| Configurações (Telegram, etc.) | — | — | ✓ |

### Criar um novo usuário

1. Menu lateral → **Usuários**
2. Clique em **+ Novo Usuário**
3. Preencha usuário, senha e papel (`viewer`, `operator`, `admin`)
4. Clique em **Salvar**

> **Dica de segurança:** Para equipes de operação que só precisam iniciar/parar streams, use o papel `operator`. Para clientes que só assistem, use `viewer`.

---

## 14. Backup e restore

### Criar um backup manual

1. Menu lateral → **Backup**
2. Clique em **Criar Backup Agora**
3. Um arquivo `.zip` é gerado com: streams, usuários, categorias, configurações e logos
4. Clique em **Download** para baixar o arquivo

### O que o backup contém
```
backup_20260321_143000.zip
├── streams.json       ← Todos os streams com configurações
├── users.json         ← Usuários e papéis (sem senhas em texto claro)
├── categories.json    ← Categorias
├── settings.json      ← Configurações do painel
├── logos/             ← Imagens de logo das categorias
└── manifest.json      ← Versão e checksum de integridade
```

### Restaurar um backup

**Opção 1 — Backup armazenado no servidor:**
1. Menu lateral → **Backup**
2. Escolha um backup da lista
3. Clique em **Restaurar**

**Opção 2 — Upload de arquivo:**
1. Menu lateral → **Backup**
2. Clique em **Restaurar de Arquivo**
3. Selecione o arquivo `.zip`
4. Clique em **Restaurar**

> **Atenção:** A restauração substitui streams, usuários e configurações existentes. Faça um backup antes de restaurar.

### Backup automático

1. Menu lateral → **Configurações**
2. Seção **Backup Automático**
3. Ative e configure intervalo (horas) e retenção (quantidade de arquivos a manter)

---

## 15. Alertas Telegram

Com o Telegram configurado (seção 6.2), você recebe alertas automáticos:

| Evento | Mensagem |
|---|---|
| Stream caiu e atingiu máx. de restarts | ❌ Stream `canal-hd` parou após 5 restarts |
| IP/conta banida pelo provedor | 🚫 Ban detectado em `canal-hd` — HTTP 403 |
| Ban em todas as URLs de backup | 🚫 Todas as URLs banidas — aguardando cooldown |
| Stream reiniciado após ban | ✅ `canal-hd` reiniciado com URL de backup |
| Disco quase cheio (≥ 90%) | ⚠️ Disco quase cheio! Uso: 92.3% (8.1 GB livres) |

> O alerta de disco é enviado no máximo 1 vez a cada 6 horas para evitar spam.

---

## 16. Prometheus / métricas

O endpoint `/metrics` expõe 27 métricas no formato Prometheus:

```bash
# Com autenticação (token configurado no .env)
curl -H "Authorization: Bearer SEU_METRICS_TOKEN" http://SEU_IP:8001/metrics
```

**Principais métricas:**
```
aistra_streams_total          # Total de streams cadastrados
aistra_streams_running        # Streams ativos agora
aistra_streams_error          # Streams em estado de erro
aistra_cpu_usage_percent      # CPU total (%)
aistra_memory_usage_percent   # RAM (%)
aistra_disk_usage_percent     # Disco (%)
aistra_stream_uptime_seconds{id="..."} # Uptime por stream
aistra_stream_bitrate_kbps{id="..."}   # Bitrate por stream
```

### Configurar scrape no Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: aistra-stream
    static_configs:
      - targets: ['SEU_IP:8001']
    authorization:
      credentials: SEU_METRICS_TOKEN
```

---

## 17. Atualizando o sistema

### Atualização automática

```bash
export GH_TOKEN=ghp_SEU_TOKEN
sudo -E bash /opt/aistra-stream/update.sh
```

O script faz:
1. `git pull` — baixa o código mais recente
2. `pip install -r requirements.txt` — atualiza dependências Python
3. `npm run build` — rebuilda o frontend
4. `systemctl restart aistra-stream` — reinicia o serviço
5. Health check — confirma que o serviço está respondendo

> As **migrações de banco** são aplicadas automaticamente ao reiniciar o serviço. Não há passo manual.

### Usando o instalador em modo upgrade

```bash
export GH_TOKEN=ghp_SEU_TOKEN
bash <(curl -fsSL "...install.sh") --upgrade
```

Modo `--upgrade` é equivalente ao `update.sh` mas com mais validações.

---

## 18. Desinstalação

### Desinstalação completa (remove tudo)

```bash
sudo bash /opt/aistra-stream/uninstall.sh
```

O script pede que você digite `SIM` para confirmar. Remove:
- Serviço systemd
- Diretório `/opt/aistra-stream`
- Banco de dados e usuário MySQL
- Logrotate config
- Porta no firewall
- Binários opcionais (n_m3u8dl, mp4decrypt, yt-dlp)

### Desinstalar preservando os dados

```bash
sudo bash /opt/aistra-stream/uninstall.sh --keep-data
```

Os dados são movidos para `/opt/aistra-backup-data/` antes da remoção.

### Remover tudo incluindo logs

```bash
sudo bash /opt/aistra-stream/uninstall.sh --purge
```

### Modo não-interativo (para scripts)

```bash
sudo bash /opt/aistra-stream/uninstall.sh --yes --keep-data
```

---

## 19. Solução de problemas

### O serviço não inicia

```bash
# Ver os últimos 50 logs
journalctl -u aistra-stream -n 50 --no-pager

# Ver logs em tempo real
journalctl -u aistra-stream -f
```

**Causa comum 1 — SECRET_KEY não definida:**
```
ERROR: SECRET_KEY must be at least 32 characters
```
Solução: Edite `/opt/aistra-stream/.env` e defina uma chave:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Copie o resultado e cole em .env como SECRET_KEY=...
```

**Causa comum 2 — Banco de dados não conecta:**
```
ERROR: Can't connect to MySQL server
```
Solução:
```bash
systemctl status mariadb    # Ver se está rodando
systemctl start mariadb     # Iniciar se parado
```

**Causa comum 3 — Porta já em uso:**
```
ERROR: [Errno 98] Address already in use
```
Solução:
```bash
ss -tlnp | grep 8001        # Ver quem usa a porta
# Ou altere a porta no .env: PORT=8002
```

---

### Stream não inicia / fica em erro

```bash
# Ver log do ffmpeg para um stream específico
tail -100 /tmp/ffmpeg_STREAM_ID.log
```

**Stream para imediatamente:**
- Verifique se a URL está acessível: `curl -I "URL_DO_STREAM"`
- Tente acessar a URL no VLC para confirmar que funciona

**Bitrate zero / stream trava:**
- O watchdog reinicia automaticamente após 3 polls com 0 kbps
- Se persistir, verifique a fonte: pode estar fora do ar

**Ban detectado (403/401):**
- A fonte bloqueou seu IP
- Use um proxy: nas configurações do stream, aba **Rede** → **Proxy**

---

### Erro no frontend (tela branca)

```bash
# Ver erros do serviço
journalctl -u aistra-stream -n 20

# Verificar se o frontend foi buildado
ls /opt/aistra-stream/frontend/dist/
```

Se o diretório `dist/` estiver vazio:
```bash
cd /opt/aistra-stream/frontend
npm ci && npm run build
systemctl restart aistra-stream
```

---

### Verificar status geral

```bash
# Status do serviço
systemctl status aistra-stream

# Health check da API
curl http://localhost:8001/health

# Ver streams rodando
curl -s http://localhost:8001/health | python3 -m json.tool
```

---

### Comandos úteis do dia a dia

```bash
# Logs em tempo real
journalctl -u aistra-stream -f

# Reiniciar serviço
systemctl restart aistra-stream

# Ver uso de disco
df -h /opt/aistra-stream

# Listar gravações
ls -lh /opt/aistra-stream/recordings/

# Verificar Pillow (análise visual)
/opt/aistra-stream/venv/bin/python -c "from PIL import Image; print('Pillow OK')"

# Executar todos os testes
cd /opt/aistra-stream
./venv/bin/python -m pytest tests/ -v

# Forçar atualização do yt-dlp
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
     -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp
```

---

## 20. Referência rápida — variáveis de ambiente

Edite `/opt/aistra-stream/.env` e reinicie o serviço após qualquer alteração:

```bash
nano /opt/aistra-stream/.env
systemctl restart aistra-stream
```

| Variável | Padrão | Descrição |
|---|---|---|
| `SECRET_KEY` | *(obrigatório)* | Chave JWT — mín. 32 chars |
| `DATABASE_URL` | *(obrigatório)* | URL de conexão MySQL |
| `PORT` | `8001` | Porta do servidor |
| `ALLOWED_ORIGINS` | `http://IP:8001` | Origens CORS permitidas |
| `METRICS_TOKEN` | `""` | Token Bearer para `/metrics` (vazio = aberto) |
| `TELEGRAM_BOT_TOKEN` | `""` | Token do bot Telegram |
| `TELEGRAM_CHAT_ID` | `""` | Chat ID para alertas |
| `DISK_WARN_PERCENT` | `90` | % de disco para alertar |
| `RECORDING_RETENTION_DAYS` | `0` | Dias para manter gravações (0 = desabilitado) |
| `CONNECTION_LOG_RETENTION_DAYS` | `90` | Dias de retenção dos logs de conexão |
| `HLS_MAX_RESTARTS` | `5` | Máx. reinícios antes de desistir |
| `HLS_WATCHDOG_INTERVAL` | `10` | Intervalo do watchdog em segundos |
| `HLS_RESTART_DELAY` | `15` | Espera entre reinícios em segundos |
| `HLS_STALL_CHECKS` | `3` | Polls com bitrate zero antes de reiniciar |
| `HLS_YT_REFRESH_H` | `4.0` | Horas para atualizar URL do YouTube |
| `FFMPEG` | `/usr/bin/ffmpeg` | Caminho do ffmpeg |
| `N_M3U8DL` | `/usr/local/bin/n_m3u8dl` | Caminho do n_m3u8dl |
| `MP4DECRYPT` | `/usr/local/bin/mp4decrypt` | Caminho do mp4decrypt |
| `YTDLP` | `/usr/local/bin/yt-dlp` | Caminho do yt-dlp |
| `RECORDINGS_BASE` | `PROJECT_DIR/recordings` | Diretório para gravações MP4 |
| `LOGOS_BASE` | `PROJECT_DIR/logos` | Diretório para logos de categorias |
| `BACKUPS_BASE` | `PROJECT_DIR/backups` | Diretório para backups ZIP |
| `HLS_BASE` | `/tmp/aistra_stream_hls` | Diretório HLS (temporário) |
| `AISTRA_SHOW_DOCS` | *(ausente)* | Qualquer valor ativa `/docs` (Swagger) |

---

*Tutorial aistra-stream — última atualização: março de 2026*
