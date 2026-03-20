#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  aistra-stream — Universal Linux Install Script
#  Suporta: Ubuntu/Debian · CentOS/RHEL/AlmaLinux/Rocky · Fedora · Arch
#
#  Instalação rápida (uma linha — repositório privado):
#    bash <(curl -fsSL "https://raw.githubusercontent.com/tauelektronik/aistra-stream/main/install.sh?token=TOKEN")
#
#  Ou baixe o script e execute:
#    curl -fsSL -H "Authorization: token GITHUB_PAT" \
#         https://raw.githubusercontent.com/tauelektronik/aistra-stream/main/install.sh \
#         -o install.sh && sudo bash install.sh
# ═══════════════════════════════════════════════════════════════
set -e

PROJECT_DIR="/opt/aistra-stream"

# ── Helper functions (must be defined FIRST) ──────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
info() { echo -e "${CYAN}[..] $*${NC}"; }
warn() { echo -e "${YELLOW}[AV] $*${NC}"; }
err()  { echo -e "${RED}[ERRO] $*${NC}"; exit 1; }

# ── Token GitHub (read-only, repositório aistra-stream) ───────
# Fine-grained PAT com permissão "Contents: Read-only" no repo.
# Passe via variável de ambiente para não expor em disco:
#   export GH_TOKEN=ghp_xxxx && sudo -E bash install.sh
# Ou inline: GH_TOKEN=ghp_xxxx sudo -E bash install.sh
GH_TOKEN="${GH_TOKEN:-}"
[ -n "$GH_TOKEN" ] || err "GH_TOKEN não definido. Configure antes de executar:
  export GH_TOKEN=ghp_xxxx
  sudo -E bash install.sh"
GIT_REPO="https://${GH_TOKEN}@github.com/tauelektronik/aistra-stream.git"
PORT=8001
DB_NAME="aistra_stream"
DB_USER="aistra"
# Gera senha aleatória segura para o banco (32 chars hex)
DB_PASS=$(python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || \
          cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 32)

echo -e "${BOLD}${CYAN}"
echo "  ╔═══════════════════════════════════╗"
echo "  ║     aistra-stream installer       ║"
echo "  ╚═══════════════════════════════════╝"
echo -e "${NC}"

# ── Root check ────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || err "Execute como root: sudo bash install.sh"

# ── Detectar distro ───────────────────────────────────────────
detect_distro() {
    if   [ -f /etc/os-release ]; then . /etc/os-release; DISTRO_ID="${ID}"; DISTRO_LIKE="${ID_LIKE:-}"
    elif [ -f /etc/redhat-release ]; then DISTRO_ID="rhel"
    elif [ -f /etc/arch-release ];   then DISTRO_ID="arch"
    else err "Distribuição Linux não reconhecida"
    fi

    case "$DISTRO_ID" in
        ubuntu|debian|linuxmint|pop|elementary|kali)
            PKG_MGR="apt"; FAMILY="debian" ;;
        centos|rhel|almalinux|rocky|ol|amzn)
            PKG_MGR="dnf"; FAMILY="rhel"
            command -v dnf &>/dev/null || PKG_MGR="yum" ;;
        fedora)
            PKG_MGR="dnf"; FAMILY="fedora" ;;
        arch|manjaro|endeavouros)
            PKG_MGR="pacman"; FAMILY="arch" ;;
        *)
            # Tenta via ID_LIKE
            case "$DISTRO_LIKE" in
                *debian*|*ubuntu*) PKG_MGR="apt";    FAMILY="debian" ;;
                *rhel*|*fedora*)   PKG_MGR="dnf";    FAMILY="rhel"   ;;
                *arch*)            PKG_MGR="pacman";  FAMILY="arch"   ;;
                *) err "Distro não suportada: $DISTRO_ID (ID_LIKE=$DISTRO_LIKE)" ;;
            esac ;;
    esac
    ok "Distro: ${DISTRO_ID} (família ${FAMILY}, gerenciador ${PKG_MGR})"
}

# ── Instalar pacotes do sistema ───────────────────────────────
install_system_deps() {
    info "Atualizando repositórios e instalando dependências..."

    case "$FAMILY" in
        debian)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            # Remove Ubuntu npm/libnode-dev that conflict with NodeSource nodejs
            apt-get remove -y libnode-dev nodejs-doc npm 2>/dev/null || true
            apt-get install -y -qq \
                curl wget git python3 python3-pip python3-venv \
                ffmpeg mariadb-server \
                build-essential libssl-dev unzip ;;

        rhel)
            # EPEL + RPM Fusion para ffmpeg
            $PKG_MGR install -y epel-release 2>/dev/null || true
            $PKG_MGR install -y \
                https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm \
                2>/dev/null || true
            $PKG_MGR install -y \
                curl wget git python3 python3-pip \
                nodejs npm ffmpeg mariadb-server \
                gcc openssl-devel unzip ;;

        fedora)
            dnf install -y \
                https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
                2>/dev/null || true
            dnf install -y \
                curl wget git python3 python3-pip \
                nodejs npm ffmpeg mariadb mariadb-server \
                gcc openssl-devel unzip ;;

        arch)
            pacman -Sy --noconfirm \
                curl wget git python python-pip \
                nodejs npm ffmpeg mariadb \
                base-devel unzip ;;
    esac
    ok "Dependências do sistema instaladas"
}

# ── Node.js: garantir versão ≥ 18 ────────────────────────────
ensure_node() {
    local ver
    ver=$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1 || echo 0)
    if [ "$ver" -lt 18 ]; then
        info "Node.js $ver < 18 — instalando Node 20 via NodeSource..."
        case "$FAMILY" in
            debian)
                # Remove conflicting packages before NodeSource install
                apt-get remove -y nodejs libnode-dev nodejs-doc 2>/dev/null || true
                apt-get autoremove -y 2>/dev/null || true
                curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
                apt-get install -y nodejs ;;
            rhel|fedora)
                curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
                $PKG_MGR install -y nodejs ;;
            arch)
                pacman -S --noconfirm nodejs-lts-iron npm ;;
        esac
    fi
    ok "Node.js $(node --version)"
}

# ── MariaDB / MySQL ───────────────────────────────────────────
setup_database() {
    info "Configurando banco de dados MariaDB..."

    # Determinar serviço correto
    local svc="mariadb"
    systemctl list-unit-files mariadb.service &>/dev/null || svc="mysqld"

    systemctl enable --now "$svc" 2>/dev/null || true

    # Aguardar socket
    local timeout=30
    while ! mysqladmin ping --silent 2>/dev/null; do
        sleep 1; timeout=$((timeout-1))
        [ $timeout -gt 0 ] || err "MariaDB não iniciou em 30s"
    done

    mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
    mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';" 2>/dev/null
    mysql -e "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost'; FLUSH PRIVILEGES;" 2>/dev/null
    ok "Banco '${DB_NAME}' criado, usuário '${DB_USER}' configurado"
}

# ── ffmpeg: verificar versão ──────────────────────────────────
check_ffmpeg() {
    if command -v ffmpeg &>/dev/null; then
        ok "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
    else
        warn "ffmpeg não encontrado — tentando instalar manualmente..."
        # Fallback: baixar binário estático
        local ARCH; ARCH=$(uname -m)
        local FF_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${ARCH}-static.tar.xz"
        curl -L "$FF_URL" -o /tmp/ffmpeg.tar.xz
        tar xf /tmp/ffmpeg.tar.xz -C /tmp
        cp /tmp/ffmpeg-*-static/ffmpeg /usr/local/bin/ffmpeg
        cp /tmp/ffmpeg-*-static/ffprobe /usr/local/bin/ffprobe
        chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe
        rm -rf /tmp/ffmpeg*
        ok "ffmpeg instalado em /usr/local/bin/ffmpeg (binário estático)"
    fi
}

# ── n_m3u8dl-RE ───────────────────────────────────────────────
install_n_m3u8dl() {
    if command -v n_m3u8dl &>/dev/null; then
        ok "n_m3u8dl já instalado: $(n_m3u8dl --version 2>&1 | head -1)"
        return
    fi
    info "Instalando N_m3u8DL-RE (CENC/DRM downloader)..."
    local ARCH; ARCH=$(uname -m)
    local TAG
    TAG=$(curl -s https://api.github.com/repos/nilaoda/N_m3u8DL-RE/releases/latest \
          | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\(.*\)".*/\1/')
    [ -n "$TAG" ] || { warn "Não foi possível obter versão do n_m3u8dl — pulando"; return; }

    # Try filename formats: newer releases use date suffix, older use _v2
    local FNAME FNAME2
    case "$ARCH" in
        x86_64)
            FNAME="N_m3u8DL-RE_${TAG}_linux-x64_$(date +%Y%m%d).tar.gz"
            FNAME2="N_m3u8DL-RE_${TAG}_linux-x64_v2.tar.gz" ;;
        aarch64)
            FNAME="N_m3u8DL-RE_${TAG}_linux-arm64_$(date +%Y%m%d).tar.gz"
            FNAME2="N_m3u8DL-RE_${TAG}_linux-arm64_v2.tar.gz" ;;
        *) warn "Arquitetura $ARCH não suportada para n_m3u8dl — baixe manualmente"; return ;;
    esac

    # Get actual asset name from GitHub API
    local ACTUAL_FNAME
    ACTUAL_FNAME=$(curl -s "https://api.github.com/repos/nilaoda/N_m3u8DL-RE/releases/latest" \
        | grep '"browser_download_url"' \
        | grep "linux-$([ "$ARCH" = x86_64 ] && echo x64 || echo arm64)" \
        | grep -v musl | grep '\.tar\.gz' | head -1 \
        | sed 's/.*"\(https.*\)".*/\1/')

    [ -n "$ACTUAL_FNAME" ] || { warn "Não foi possível encontrar asset do n_m3u8dl"; return; }

    curl -L "$ACTUAL_FNAME" -o /tmp/n_m3u8dl.tar.gz \
        || { warn "Download do n_m3u8dl falhou"; return; }

    tar xf /tmp/n_m3u8dl.tar.gz -C /tmp 2>/dev/null || true
    find /tmp -name "N_m3u8DL-RE" -type f -exec cp {} /usr/local/bin/n_m3u8dl \; 2>/dev/null || true
    chmod +x /usr/local/bin/n_m3u8dl 2>/dev/null || true
    rm -f /tmp/n_m3u8dl.tar.gz
    ok "n_m3u8dl instalado em /usr/local/bin/n_m3u8dl"
}

# ── mp4decrypt (Bento4) ───────────────────────────────────────
install_mp4decrypt() {
    if command -v mp4decrypt &>/dev/null; then
        ok "mp4decrypt já instalado"
        return
    fi
    info "Instalando mp4decrypt (Bento4)..."
    local ARCH; ARCH=$(uname -m)
    local BENTO_ARCH
    case "$ARCH" in
        x86_64)  BENTO_ARCH="x86_64-unknown-linux" ;;
        aarch64) BENTO_ARCH="aarch64-unknown-linux" ;;
        *)       warn "Arquitetura $ARCH não suportada para mp4decrypt — baixe manualmente"; return ;;
    esac

    local BENTO_VER="1-6-0-641"
    local URL="https://www.bok.net/Bento4/binaries/Bento4-SDK-${BENTO_VER}.${BENTO_ARCH}.zip"
    curl -L "$URL" -o /tmp/bento4.zip \
        || { warn "Download do Bento4 falhou — mp4decrypt não instalado"; return; }

    unzip -o /tmp/bento4.zip -d /tmp/bento4 &>/dev/null
    find /tmp/bento4 -name "mp4decrypt" -type f -exec cp {} /usr/local/bin/mp4decrypt \;
    chmod +x /usr/local/bin/mp4decrypt
    rm -rf /tmp/bento4.zip /tmp/bento4
    ok "mp4decrypt instalado em /usr/local/bin/mp4decrypt"
}

# ── yt-dlp ────────────────────────────────────────────────────
install_ytdlp() {
    info "Instalando yt-dlp..."
    curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
         -o /usr/local/bin/yt-dlp 2>/dev/null
    chmod +x /usr/local/bin/yt-dlp
    ok "yt-dlp $(yt-dlp --version 2>/dev/null)"
}

# ── Copiar / clonar projeto ───────────────────────────────────
deploy_project() {
    local SRC; SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [ "$SRC" = "$PROJECT_DIR" ]; then
        # Já está no destino (clone direto em /opt/aistra-stream)
        ok "Projeto já em ${PROJECT_DIR}"
    elif [ -d "$PROJECT_DIR/.git" ]; then
        # Instalação existente — atualiza via git pull com token
        info "Atualizando instalação existente..."
        cd "$PROJECT_DIR"
        # Injeta token temporariamente no remote, sem persistir em disco
        git remote set-url origin "$GIT_REPO" 2>/dev/null || true
        git pull --ff-only || { warn "git pull falhou — mantendo versão atual"; }
        # Remove token do remote (deixa URL limpa sem credenciais armazenadas)
        git remote set-url origin "https://github.com/tauelektronik/aistra-stream.git" 2>/dev/null || true
        ok "Projeto atualizado em ${PROJECT_DIR}"
    elif [ -d "$SRC/.git" ]; then
        # Clone local — copia para destino
        info "Copiando projeto para ${PROJECT_DIR}..."
        mkdir -p "$PROJECT_DIR"
        cp -r "$SRC/." "$PROJECT_DIR/"
        ok "Projeto copiado para ${PROJECT_DIR}"
    else
        # Clona do GitHub usando token (sem interação)
        info "Clonando repositório privado do GitHub..."
        command -v git &>/dev/null || { apt-get install -y git 2>/dev/null || $PKG_MGR install -y git; }
        [ -d "$PROJECT_DIR" ] && rm -rf "$PROJECT_DIR"
        # GIT_TERMINAL_PROMPT=0 garante que não abre prompt de senha em caso de falha
        GIT_TERMINAL_PROMPT=0 git clone --depth 1 "$GIT_REPO" "$PROJECT_DIR"
        # Substitui remote URL pelo endereço público (sem token) para não persistir credenciais
        cd "$PROJECT_DIR"
        git remote set-url origin "https://github.com/tauelektronik/aistra-stream.git"
        ok "Repositório clonado em ${PROJECT_DIR}"
    fi
    cd "$PROJECT_DIR"
}

# ── Python venv + deps ────────────────────────────────────────
setup_python() {
    info "Criando ambiente Python..."
    cd "$PROJECT_DIR"

    # Garantir python3 com venv
    python3 -m venv venv
    ./venv/bin/pip install -q --upgrade pip
    ./venv/bin/pip install -q -r backend/requirements.txt
    ok "Dependências Python instaladas"
}

# ── .env ─────────────────────────────────────────────────────
create_env() {
    cd "$PROJECT_DIR"
    if [ ! -f .env ]; then
        cp .env.example .env
        local SECRET
        SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=mysql+aiomysql://${DB_USER}:${DB_PASS}@localhost:3306/${DB_NAME}|" .env

        # Detectar caminhos dos binários e atualizar .env
        FFMPEG_PATH=$(command -v ffmpeg || echo "/usr/bin/ffmpeg")
        N_M3U8DL_PATH=$(command -v n_m3u8dl || echo "/usr/local/bin/n_m3u8dl")
        MP4DECRYPT_PATH=$(command -v mp4decrypt || echo "/usr/local/bin/mp4decrypt")
        YTDLP_PATH=$(command -v yt-dlp || echo "/usr/local/bin/yt-dlp")
        sed -i "s|^FFMPEG=.*|FFMPEG=${FFMPEG_PATH}|" .env
        sed -i "s|^N_M3U8DL=.*|N_M3U8DL=${N_M3U8DL_PATH}|" .env
        sed -i "s|^MP4DECRYPT=.*|MP4DECRYPT=${MP4DECRYPT_PATH}|" .env
        sed -i "s|^YTDLP=.*|YTDLP=${YTDLP_PATH}|" .env
        # Diretórios persistentes (fora do /tmp)
        sed -i "s|^RECORDINGS_BASE=.*|RECORDINGS_BASE=${PROJECT_DIR}/recordings|" .env
        sed -i "s|^THUMBNAILS_BASE=.*|THUMBNAILS_BASE=/tmp/aistra_thumbnails|" .env
        sed -i "s|^LOGOS_BASE=.*|LOGOS_BASE=${PROJECT_DIR}/logos|" .env
        ok "Arquivo .env criado com credenciais seguras"
    else
        warn ".env já existe — mantendo configuração atual"
        # Garantir que novas variáveis existam no .env atual
        grep -q "^RECORDINGS_BASE=" .env  || echo "RECORDINGS_BASE=${PROJECT_DIR}/recordings"  >> .env
        grep -q "^THUMBNAILS_BASE=" .env  || echo "THUMBNAILS_BASE=/tmp/aistra_thumbnails"      >> .env
        grep -q "^LOGOS_BASE="      .env  || echo "LOGOS_BASE=${PROJECT_DIR}/logos"              >> .env
        grep -q "^YTDLP="           .env  || echo "YTDLP=$(command -v yt-dlp || echo /usr/local/bin/yt-dlp)" >> .env
        grep -q "^YTDLP_COOKIES="   .env  || echo "YTDLP_COOKIES=/opt/youtube_cookies.txt"      >> .env
        grep -q "^PIPE_BASE="       .env  || echo "PIPE_BASE=/tmp/aistra_stream_pipes"           >> .env
        grep -q "^TMP_BASE="        .env  || echo "TMP_BASE=/tmp/aistra_stream_tmp"              >> .env
        ok ".env existente — novas variáveis adicionadas se ausentes"
    fi

    # Criar diretórios persistentes
    mkdir -p "${PROJECT_DIR}/recordings" "${PROJECT_DIR}/logos" "${PROJECT_DIR}/data"
    chmod 750 "${PROJECT_DIR}/recordings" "${PROJECT_DIR}/logos" "${PROJECT_DIR}/data"
}

# ── Frontend build ─────────────────────────────────────────────
build_frontend() {
    info "Instalando dependências e buildando frontend React..."
    cd "$PROJECT_DIR/frontend"
    npm install --loglevel=warn
    npm run build
    ok "Frontend buildado em frontend/dist/"
}

# ── Systemd service ───────────────────────────────────────────
install_service() {
    info "Criando serviço systemd..."
    cat > /etc/systemd/system/aistra-stream.service <<EOF
[Unit]
Description=Aistra Stream Panel
After=network.target mariadb.service mysqld.service
Wants=mariadb.service

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${PROJECT_DIR}/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5
StandardOutput=append:/var/log/aistra-stream.log
StandardError=append:/var/log/aistra-stream.log

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable aistra-stream
    systemctl restart aistra-stream
    sleep 3

    if systemctl is-active --quiet aistra-stream; then
        ok "Serviço aistra-stream ativo"
    else
        warn "Serviço não iniciou — verificando logs..."
        journalctl -u aistra-stream -n 20 --no-pager
    fi
}

# ── Health check ──────────────────────────────────────────────
health_check() {
    info "Verificando serviço..."
    local tries=0
    while [ $tries -lt 15 ]; do
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/health" 2>/dev/null || echo "000")
        if [ "$http_code" = "200" ]; then
            ok "Health check OK (HTTP 200)"
            return
        fi
        sleep 2; tries=$((tries+1))
    done
    warn "Health check não respondeu em 30s — verifique: journalctl -u aistra-stream -n 30"
}

# ── Logrotate ─────────────────────────────────────────────────
setup_logrotate() {
    cat > /etc/logrotate.d/aistra-stream <<'EOF'
/var/log/aistra-stream.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    copytruncate
}
EOF
    ok "Logrotate configurado para /var/log/aistra-stream.log"
}

# ── Firewall (se ativo) ───────────────────────────────────────
open_firewall() {
    if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
        ufw allow "$PORT/tcp" &>/dev/null
        ok "Porta $PORT liberada no ufw"
    elif command -v firewall-cmd &>/dev/null && firewall-cmd --state &>/dev/null; then
        firewall-cmd --permanent --add-port="${PORT}/tcp" &>/dev/null
        firewall-cmd --reload &>/dev/null
        ok "Porta $PORT liberada no firewalld"
    fi
}

# ── Resumo ────────────────────────────────────────────────────
print_summary() {
    local IP
    IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
    echo ""
    echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}  Instalação concluída com sucesso!${NC}"
    echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}Painel:${NC}  http://${IP}:${PORT}"
    echo -e "  ${BOLD}Login:${NC}   admin / admin123"
    echo ""
    echo -e "  ${BOLD}${RED}IMPORTANTE: Troque a senha padrão!${NC}"
    echo ""
    echo -e "  ${BOLD}Comandos úteis:${NC}"
    echo "    Logs em tempo real: journalctl -u aistra-stream -f"
    echo "    Reiniciar:          systemctl restart aistra-stream"
    echo "    Parar:              systemctl stop aistra-stream"
    echo "    Atualizar:          cd ${PROJECT_DIR} && git pull && ./venv/bin/pip install -q -r backend/requirements.txt && (cd frontend && npm install --loglevel=warn && npm run build) && systemctl restart aistra-stream"
    echo ""
    echo -e "  ${BOLD}Binários detectados:${NC}"
    echo "    ffmpeg:      $(command -v ffmpeg 2>/dev/null || echo 'não encontrado')"
    echo "    n_m3u8dl:    $(command -v n_m3u8dl 2>/dev/null || echo 'não encontrado')"
    echo "    mp4decrypt:  $(command -v mp4decrypt 2>/dev/null || echo 'não encontrado')"
    echo "    yt-dlp:      $(command -v yt-dlp 2>/dev/null || echo 'não encontrado')"
    echo ""
}

# ══════════════════════════════════════════════════
#  EXECUÇÃO
# ══════════════════════════════════════════════════
detect_distro
install_system_deps
ensure_node
check_ffmpeg
install_n_m3u8dl
install_mp4decrypt
install_ytdlp
setup_database
deploy_project
setup_python
create_env
build_frontend
install_service
health_check
setup_logrotate
open_firewall
print_summary
