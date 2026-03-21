#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  aistra-stream — Universal Linux Installer  v2.0
#  Suporta: Ubuntu/Debian · CentOS/RHEL/AlmaLinux/Rocky · Fedora · Arch
#
#  Uso rápido (uma linha):
#    export GH_TOKEN=ghp_xxxx
#    bash <(curl -fsSL "https://raw.githubusercontent.com/tauelektronik/aistra-stream/main/install.sh")
#
#  Opções:
#    --port PORT        Porta do painel (padrão: 8001)
#    --dir  PATH        Diretório de instalação (padrão: /opt/aistra-stream)
#    --no-drm           Pular n_m3u8dl e mp4decrypt (sem suporte DRM)
#    --no-yt            Pular yt-dlp (sem suporte YouTube)
#    --upgrade          Modo atualização: preserva .env e banco, atualiza código
#    --skip-system-deps Não instalar/atualizar pacotes do sistema
#    --help             Mostrar esta ajuda
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────
PORT=8001
PROJECT_DIR="/opt/aistra-stream"
INSTALL_DRM=true
INSTALL_YT=true
UPGRADE_MODE=false
SKIP_SYSTEM_DEPS=false
DB_NAME="aistra_stream"
DB_USER="aistra"
DB_PASS=$(python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || \
          tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 32)
MANIFEST_FILE=""   # set after PROJECT_DIR is known

# ── Cores / helpers ───────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
STEP=0
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
info()  { STEP=$((STEP+1)); echo -e "\n${CYAN}${BOLD}[${STEP}]${NC} ${CYAN}$*${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $*${NC}"; }
err()   { echo -e "${RED}  ✗ ERRO: $*${NC}" >&2; exit 1; }
banner(){ echo -e "${BOLD}${CYAN}$*${NC}"; }

# ── Argparse ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)            PORT="$2"; shift 2 ;;
        --dir)             PROJECT_DIR="$2"; shift 2 ;;
        --no-drm)          INSTALL_DRM=false; shift ;;
        --no-yt)           INSTALL_YT=false; shift ;;
        --upgrade)         UPGRADE_MODE=true; shift ;;
        --skip-system-deps)SKIP_SYSTEM_DEPS=true; shift ;;
        --help|-h)
            sed -n '2,18p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) err "Opção desconhecida: $1 (use --help)" ;;
    esac
done

MANIFEST_FILE="${PROJECT_DIR}/.install-manifest"

# ── GH_TOKEN ──────────────────────────────────────────────────────────────
GH_TOKEN="${GH_TOKEN:-}"
if [ -z "$GH_TOKEN" ] && [ ! -d "${PROJECT_DIR}/.git" ]; then
    err "GH_TOKEN não definido e repositório não encontrado em ${PROJECT_DIR}.
  Configure antes de executar:
    export GH_TOKEN=ghp_xxxx
    sudo -E bash install.sh"
fi
GIT_REPO="https://${GH_TOKEN:-x}@github.com/tauelektronik/aistra-stream.git"

# ── Banner ────────────────────────────────────────────────────────────────
clear
banner "
  ╔══════════════════════════════════════════════════╗
  ║          aistra-stream  —  Installer v2.0        ║
  ║        IPTV/HLS Panel with DRM, ABR & JWT        ║
  ╚══════════════════════════════════════════════════╝
"
if $UPGRADE_MODE; then
    banner "  Modo: ATUALIZAÇÃO  (código, deps, frontend — preserva .env e banco)\n"
else
    banner "  Modo: INSTALAÇÃO COMPLETA\n"
fi

# ── Root ──────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || err "Execute como root: sudo -E bash install.sh"

# ═══════════════════════════════════════════════════
#  FUNÇÕES
# ═══════════════════════════════════════════════════

# ── Detectar distro ───────────────────────────────────────────────────────
detect_distro() {
    info "Detectando distribuição Linux"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="${ID}"
        DISTRO_LIKE="${ID_LIKE:-}"
        DISTRO_VERSION="${VERSION_ID:-0}"
    elif [ -f /etc/redhat-release ]; then
        DISTRO_ID="rhel"; DISTRO_LIKE=""; DISTRO_VERSION="0"
    elif [ -f /etc/arch-release ]; then
        DISTRO_ID="arch"; DISTRO_LIKE=""; DISTRO_VERSION="0"
    else
        err "Distribuição Linux não reconhecida"
    fi

    case "$DISTRO_ID" in
        ubuntu|debian|linuxmint|pop|elementary|kali|raspbian)
            PKG_MGR="apt"; FAMILY="debian" ;;
        centos|rhel|almalinux|rocky|ol|amzn)
            PKG_MGR="dnf"; FAMILY="rhel"
            command -v dnf &>/dev/null || PKG_MGR="yum" ;;
        fedora)
            PKG_MGR="dnf"; FAMILY="fedora" ;;
        arch|manjaro|endeavouros|garuda)
            PKG_MGR="pacman"; FAMILY="arch" ;;
        *)
            case "$DISTRO_LIKE" in
                *debian*|*ubuntu*) PKG_MGR="apt";    FAMILY="debian" ;;
                *rhel*|*fedora*)   PKG_MGR="dnf";    FAMILY="rhel"   ;;
                *arch*)            PKG_MGR="pacman";  FAMILY="arch"   ;;
                *) err "Distro não suportada: $DISTRO_ID (ID_LIKE=${DISTRO_LIKE:-?})" ;;
            esac ;;
    esac
    ok "Distro: ${DISTRO_ID} ${DISTRO_VERSION} — família ${FAMILY}, gerenciador ${PKG_MGR}"
}

# ── Pacotes do sistema ────────────────────────────────────────────────────
install_system_deps() {
    $SKIP_SYSTEM_DEPS && { ok "Pacotes do sistema: pulando (--skip-system-deps)"; return; }
    info "Instalando dependências do sistema"

    case "$FAMILY" in
        debian)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get remove -y libnode-dev nodejs-doc npm 2>/dev/null || true
            apt-get install -y -qq \
                curl wget git python3 python3-pip python3-venv \
                ffmpeg mariadb-server \
                build-essential libssl-dev unzip ;;
        rhel)
            $PKG_MGR install -y epel-release 2>/dev/null || true
            $PKG_MGR install -y \
                https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm \
                2>/dev/null || true
            $PKG_MGR install -y \
                curl wget git python3 python3-pip \
                ffmpeg mariadb-server \
                gcc openssl-devel unzip ;;
        fedora)
            dnf install -y \
                https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
                2>/dev/null || true
            dnf install -y \
                curl wget git python3 python3-pip \
                ffmpeg mariadb mariadb-server \
                gcc openssl-devel unzip ;;
        arch)
            pacman -Sy --noconfirm \
                curl wget git python python-pip \
                ffmpeg mariadb \
                base-devel unzip ;;
    esac
    ok "Dependências do sistema instaladas"
}

# ── Node.js ≥ 18 ──────────────────────────────────────────────────────────
ensure_node() {
    info "Verificando Node.js"
    local ver
    ver=$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1 || echo 0)
    if [ "$ver" -ge 18 ]; then
        ok "Node.js $(node --version) — OK"
        return
    fi
    info "Node.js $ver < 18 — instalando Node 20 via NodeSource"
    case "$FAMILY" in
        debian)
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
    ok "Node.js $(node --version)"
}

# ── MariaDB / MySQL ───────────────────────────────────────────────────────
setup_database() {
    $UPGRADE_MODE && { ok "Banco de dados: modo upgrade — mantendo existente"; return; }
    info "Configurando banco de dados MariaDB"

    local svc="mariadb"
    systemctl list-unit-files mariadb.service &>/dev/null || svc="mysqld"
    systemctl enable --now "$svc" 2>/dev/null || true

    local t=30
    while ! mysqladmin ping --silent 2>/dev/null; do
        sleep 1; t=$((t-1))
        [ $t -gt 0 ] || err "MariaDB não iniciou em 30s — verifique: journalctl -u $svc"
    done

    mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';"
    mysql -e "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost'; FLUSH PRIVILEGES;"
    ok "Banco '${DB_NAME}' — usuário '${DB_USER}' configurado"
}

# ── ffmpeg ────────────────────────────────────────────────────────────────
check_ffmpeg() {
    info "Verificando ffmpeg"
    if command -v ffmpeg &>/dev/null; then
        ok "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
    else
        warn "ffmpeg não encontrado no PATH — instalando binário estático"
        local ARCH; ARCH=$(uname -m)
        local FF_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${ARCH}-static.tar.xz"
        curl -L "$FF_URL" -o /tmp/ffmpeg.tar.xz
        tar xf /tmp/ffmpeg.tar.xz -C /tmp
        cp /tmp/ffmpeg-*-static/ffmpeg  /usr/local/bin/ffmpeg
        cp /tmp/ffmpeg-*-static/ffprobe /usr/local/bin/ffprobe
        chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe
        rm -rf /tmp/ffmpeg*
        ok "ffmpeg instalado em /usr/local/bin/ (binário estático)"
    fi
}

# ── n_m3u8dl-RE ───────────────────────────────────────────────────────────
install_n_m3u8dl() {
    if ! $INSTALL_DRM; then ok "n_m3u8dl: pulando (--no-drm)"; return; fi
    if command -v n_m3u8dl &>/dev/null; then
        ok "n_m3u8dl já instalado: $(n_m3u8dl --version 2>&1 | head -1)"
        return
    fi
    info "Instalando N_m3u8DL-RE (CENC/DRM downloader)"
    local ARCH; ARCH=$(uname -m)

    # ── 1. Tentar vendor/ bundled no repo (offline first) ──
    local ARCH_DIR
    case "$ARCH" in
        x86_64)  ARCH_DIR="linux-x64" ;;
        aarch64) ARCH_DIR="linux-arm64" ;;
        *) ARCH_DIR="" ;;
    esac
    local VENDOR_BIN="${PROJECT_DIR}/vendor/bin/${ARCH_DIR}/n_m3u8dl"
    if [ -n "$ARCH_DIR" ] && [ -f "$VENDOR_BIN" ]; then
        cp "$VENDOR_BIN" /usr/local/bin/n_m3u8dl
        chmod +x /usr/local/bin/n_m3u8dl
        ok "n_m3u8dl instalado do vendor/ (offline)"
        return
    fi

    # ── 2. Fallback: download do GitHub ──
    local ARCH_LABEL="${ARCH_DIR:-}"
    [ -n "$ARCH_LABEL" ] || { warn "Arquitetura $ARCH não suportada para n_m3u8dl — baixe manualmente"; return; }

    local RELEASE_JSON
    RELEASE_JSON=$(curl -s "https://api.github.com/repos/nilaoda/N_m3u8DL-RE/releases/latest" 2>/dev/null) || true
    local ASSET_URL
    ASSET_URL=$(echo "$RELEASE_JSON" | grep '"browser_download_url"' \
        | grep "$ARCH_LABEL" | grep -v musl | grep -E '\.(tar\.gz|zip)' | head -1 \
        | sed 's/.*"\(https.*\)".*/\1/') || true
    if [ -z "$ASSET_URL" ]; then
        ASSET_URL=$(echo "$RELEASE_JSON" | grep '"browser_download_url"' \
            | grep "$ARCH_LABEL" | grep -E '\.(tar\.gz|zip)' | head -1 \
            | sed 's/.*"\(https.*\)".*/\1/') || true
    fi
    [ -n "$ASSET_URL" ] || { warn "Asset do n_m3u8dl não encontrado — pulando"; return; }

    local N_TMP_DIR="/tmp/n_m3u8dl_install"
    rm -rf "$N_TMP_DIR" && mkdir -p "$N_TMP_DIR"
    if [[ "$ASSET_URL" == *.zip ]]; then
        curl -L "$ASSET_URL" -o "${N_TMP_DIR}/asset.zip" || { warn "Download do n_m3u8dl falhou"; return; }
        unzip -o "${N_TMP_DIR}/asset.zip" -d "$N_TMP_DIR" &>/dev/null || true
    else
        curl -L "$ASSET_URL" -o "${N_TMP_DIR}/asset.tar.gz" || { warn "Download do n_m3u8dl falhou"; return; }
        tar xf "${N_TMP_DIR}/asset.tar.gz" -C "$N_TMP_DIR" 2>/dev/null || true
    fi
    find "$N_TMP_DIR" -name "N_m3u8DL-RE" -type f -exec cp {} /usr/local/bin/n_m3u8dl \; 2>/dev/null || true
    chmod +x /usr/local/bin/n_m3u8dl 2>/dev/null || true
    rm -rf "$N_TMP_DIR"
    ok "n_m3u8dl instalado em /usr/local/bin/n_m3u8dl"
}

# ── mp4decrypt (Bento4) ───────────────────────────────────────────────────
install_mp4decrypt() {
    if ! $INSTALL_DRM; then ok "mp4decrypt: pulando (--no-drm)"; return; fi
    if command -v mp4decrypt &>/dev/null; then ok "mp4decrypt já instalado"; return; fi
    info "Instalando mp4decrypt (Bento4)"
    local ARCH; ARCH=$(uname -m)

    # ── 1. Tentar vendor/ bundled no repo (offline first) ──
    local ARCH_DIR
    case "$ARCH" in
        x86_64)  ARCH_DIR="linux-x64" ;;
        aarch64) ARCH_DIR="linux-arm64" ;;
        *) ARCH_DIR="" ;;
    esac
    local VENDOR_BIN="${PROJECT_DIR}/vendor/bin/${ARCH_DIR}/mp4decrypt"
    if [ -n "$ARCH_DIR" ] && [ -f "$VENDOR_BIN" ]; then
        cp "$VENDOR_BIN" /usr/local/bin/mp4decrypt
        chmod +x /usr/local/bin/mp4decrypt
        ok "mp4decrypt instalado do vendor/ (offline)"
        return
    fi

    # ── 2. Fallback: download do bok.net/Bento4 ──
    local BENTO_ARCH
    case "$ARCH" in
        x86_64)  BENTO_ARCH="x86_64-unknown-linux" ;;
        aarch64) BENTO_ARCH="aarch64-unknown-linux" ;;
        *) warn "Arquitetura $ARCH não suportada para mp4decrypt"; return ;;
    esac
    local BENTO_VER="1-6-0-641"
    local URL="https://www.bok.net/Bento4/binaries/Bento4-SDK-${BENTO_VER}.${BENTO_ARCH}.zip"
    curl -L "$URL" -o /tmp/bento4.zip || { warn "Download do Bento4 falhou"; return; }
    unzip -o /tmp/bento4.zip -d /tmp/bento4 &>/dev/null
    find /tmp/bento4 -name "mp4decrypt" -type f -exec cp {} /usr/local/bin/mp4decrypt \;
    chmod +x /usr/local/bin/mp4decrypt
    rm -rf /tmp/bento4.zip /tmp/bento4
    ok "mp4decrypt instalado em /usr/local/bin/mp4decrypt"
}

# ── yt-dlp ────────────────────────────────────────────────────────────────
install_ytdlp() {
    if ! $INSTALL_YT; then ok "yt-dlp: pulando (--no-yt)"; return; fi
    info "Instalando yt-dlp"

    # ── 1. Tentar vendor/ bundled no repo (offline first, universal binary) ──
    local ARCH; ARCH=$(uname -m)
    local ARCH_DIR
    case "$ARCH" in
        x86_64)  ARCH_DIR="linux-x64" ;;
        aarch64) ARCH_DIR="linux-arm64" ;;
        *) ARCH_DIR="linux-x64" ;;  # yt-dlp é Python, tenta x64 de qualquer forma
    esac
    local VENDOR_BIN="${PROJECT_DIR}/vendor/bin/${ARCH_DIR}/yt-dlp"
    if [ -f "$VENDOR_BIN" ]; then
        cp "$VENDOR_BIN" /usr/local/bin/yt-dlp
        chmod +x /usr/local/bin/yt-dlp
        ok "yt-dlp instalado do vendor/ (offline): $(yt-dlp --version 2>/dev/null || echo 'ok')"
        return
    fi

    # ── 2. Fallback: download do GitHub ──
    curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
         -o /usr/local/bin/yt-dlp || { warn "Download do yt-dlp falhou"; return; }
    chmod +x /usr/local/bin/yt-dlp
    ok "yt-dlp $(yt-dlp --version 2>/dev/null || echo 'instalado')"
}

# ── Clone / pull do projeto ───────────────────────────────────────────────
deploy_project() {
    info "Implantando código do projeto"
    local SRC; SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"

    if [ "$SRC" = "$PROJECT_DIR" ]; then
        ok "Projeto já em ${PROJECT_DIR}"
        cd "$PROJECT_DIR"
        # Corrige remote se aponta para bundle local ou caminho não-GitHub (git clone de bundle)
        _cur_remote=$(git remote get-url origin 2>/dev/null || true)
        if [ -n "$_cur_remote" ] && [[ "$_cur_remote" != "https://github.com"* ]]; then
            git remote set-url origin "https://github.com/tauelektronik/aistra-stream.git"
            ok "Remote origin corrigido → GitHub"
        fi
    elif [ -d "$PROJECT_DIR/.git" ]; then
        info "Atualizando via git pull"
        cd "$PROJECT_DIR"
        git remote set-url origin "$GIT_REPO" 2>/dev/null || true
        git pull --ff-only || warn "git pull falhou — mantendo versão atual"
        git remote set-url origin "https://github.com/tauelektronik/aistra-stream.git" 2>/dev/null || true
        ok "Código atualizado em ${PROJECT_DIR}"
    elif [ -n "$SRC" ] && [ -d "${SRC}/.git" ]; then
        info "Copiando projeto local para ${PROJECT_DIR}"
        mkdir -p "$PROJECT_DIR"
        cp -r "${SRC}/." "$PROJECT_DIR/"
        cd "$PROJECT_DIR"
        ok "Projeto copiado para ${PROJECT_DIR}"
    else
        info "Clonando repositório privado do GitHub"
        command -v git &>/dev/null || { apt-get install -y git 2>/dev/null || $PKG_MGR install -y git; }
        [ -d "$PROJECT_DIR" ] && rm -rf "$PROJECT_DIR"
        GIT_TERMINAL_PROMPT=0 git clone --depth 1 "$GIT_REPO" "$PROJECT_DIR"
        cd "$PROJECT_DIR"
        git remote set-url origin "https://github.com/tauelektronik/aistra-stream.git"
        ok "Repositório clonado em ${PROJECT_DIR}"
    fi
}

# ── Python venv + dependências ────────────────────────────────────────────
setup_python() {
    info "Configurando Python venv e dependências"
    cd "$PROJECT_DIR"
    python3 -m venv venv
    ./venv/bin/pip install -q --upgrade pip
    ./venv/bin/pip install -q -r backend/requirements.txt
    ok "Python venv pronto com todas as dependências (incluindo Pillow)"
}

# ── .env ──────────────────────────────────────────────────────────────────
create_env() {
    cd "$PROJECT_DIR"
    info "Configurando arquivo .env"

    # Auto-detectar IP principal do servidor
    local SERVER_IP
    SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

    if [ ! -f .env ] || ! $UPGRADE_MODE; then
        [ -f .env ] && cp .env ".env.backup.$(date +%Y%m%d_%H%M%S)" && warn ".env anterior salvo como backup"

        local SECRET METRICS_TOKEN
        SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        METRICS_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")

        cp .env.example .env

        # Banco de dados
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=mysql+aiomysql://${DB_USER}:${DB_PASS}@localhost:3306/${DB_NAME}|" .env
        # Segurança
        sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
        # Metrics
        grep -q "^METRICS_TOKEN=" .env && \
            sed -i "s|^METRICS_TOKEN=.*|METRICS_TOKEN=${METRICS_TOKEN}|" .env || \
            echo "METRICS_TOKEN=${METRICS_TOKEN}" >> .env
        # CORS — usar IP do servidor automaticamente
        sed -i "s|^ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=http://${SERVER_IP}:${PORT}|" .env
        # Porta
        grep -q "^PORT=" .env && \
            sed -i "s|^PORT=.*|PORT=${PORT}|" .env || \
            echo "PORT=${PORT}" >> .env
        # Binários
        local FFMPEG_PATH N_M3U8DL_PATH MP4DECRYPT_PATH YTDLP_PATH
        FFMPEG_PATH=$(command -v ffmpeg 2>/dev/null || echo "/usr/bin/ffmpeg")
        N_M3U8DL_PATH=$(command -v n_m3u8dl 2>/dev/null || echo "/usr/local/bin/n_m3u8dl")
        MP4DECRYPT_PATH=$(command -v mp4decrypt 2>/dev/null || echo "/usr/local/bin/mp4decrypt")
        YTDLP_PATH=$(command -v yt-dlp 2>/dev/null || echo "/usr/local/bin/yt-dlp")
        sed -i "s|^FFMPEG=.*|FFMPEG=${FFMPEG_PATH}|" .env
        sed -i "s|^N_M3U8DL=.*|N_M3U8DL=${N_M3U8DL_PATH}|" .env
        sed -i "s|^MP4DECRYPT=.*|MP4DECRYPT=${MP4DECRYPT_PATH}|" .env
        grep -q "^YTDLP=" .env && \
            sed -i "s|^YTDLP=.*|YTDLP=${YTDLP_PATH}|" .env || \
            echo "YTDLP=${YTDLP_PATH}" >> .env
        # Diretórios persistentes
        sed -i "s|^RECORDINGS_BASE=.*|RECORDINGS_BASE=${PROJECT_DIR}/recordings|" .env
        sed -i "s|^THUMBNAILS_BASE=.*|THUMBNAILS_BASE=/tmp/aistra_thumbnails|" .env
        sed -i "s|^LOGOS_BASE=.*|LOGOS_BASE=${PROJECT_DIR}/logos|" .env

        ok ".env criado — SECRET_KEY, METRICS_TOKEN e DB gerados automaticamente"
    else
        # Modo upgrade: adicionar apenas variáveis novas ausentes
        grep -q "^METRICS_TOKEN=" .env || {
            local T; T=$(python3 -c "import secrets; print(secrets.token_hex(32))")
            echo "METRICS_TOKEN=${T}" >> .env
            ok "METRICS_TOKEN adicionado ao .env existente"
        }
        grep -q "^ALLOWED_ORIGINS=" .env || \
            echo "ALLOWED_ORIGINS=http://${SERVER_IP}:${PORT}" >> .env
        grep -q "^RECORDINGS_BASE=" .env || echo "RECORDINGS_BASE=${PROJECT_DIR}/recordings" >> .env
        grep -q "^THUMBNAILS_BASE=" .env || echo "THUMBNAILS_BASE=/tmp/aistra_thumbnails"    >> .env
        grep -q "^LOGOS_BASE="      .env || echo "LOGOS_BASE=${PROJECT_DIR}/logos"            >> .env
        grep -q "^YTDLP="           .env || echo "YTDLP=$(command -v yt-dlp || echo /usr/local/bin/yt-dlp)" >> .env
        grep -q "^YTDLP_COOKIES="   .env || echo "YTDLP_COOKIES=/opt/youtube_cookies.txt"    >> .env
        grep -q "^PIPE_BASE="       .env || echo "PIPE_BASE=/tmp/aistra_stream_pipes"         >> .env
        grep -q "^TMP_BASE="        .env || echo "TMP_BASE=/tmp/aistra_stream_tmp"            >> .env
        ok ".env existente preservado — novas variáveis adicionadas se ausentes"
    fi

    # Criar diretórios persistentes
    mkdir -p "${PROJECT_DIR}/recordings" "${PROJECT_DIR}/logos" "${PROJECT_DIR}/data" \
             "${PROJECT_DIR}/backups"
    chmod 750 "${PROJECT_DIR}/recordings" "${PROJECT_DIR}/logos" \
              "${PROJECT_DIR}/data"       "${PROJECT_DIR}/backups"
}

# ── Build frontend ────────────────────────────────────────────────────────
build_frontend() {
    info "Build do frontend React"
    cd "${PROJECT_DIR}/frontend"
    npm install --loglevel=warn
    npm run build --silent
    ok "Frontend buildado em frontend/dist/"
}

# ── Systemd ───────────────────────────────────────────────────────────────
install_service() {
    info "Configurando serviço systemd"
    cat > /etc/systemd/system/aistra-stream.service <<EOF
[Unit]
Description=Aistra Stream Panel
Documentation=https://github.com/tauelektronik/aistra-stream
After=network-online.target mariadb.service mysqld.service
Wants=network-online.target mariadb.service

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${PROJECT_DIR}/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
StandardOutput=append:/var/log/aistra-stream.log
StandardError=append:/var/log/aistra-stream.log

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable aistra-stream

    if $UPGRADE_MODE; then
        systemctl restart aistra-stream
        ok "Serviço reiniciado (upgrade)"
    else
        systemctl start aistra-stream
        ok "Serviço iniciado e habilitado no boot"
    fi
}

# ── Health check ──────────────────────────────────────────────────────────
health_check() {
    info "Health check"
    local tries=0
    while [ $tries -lt 20 ]; do
        local code
        code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/health" 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            ok "Serviço respondendo — HTTP 200 em /health"
            return 0
        fi
        sleep 2; tries=$((tries+1))
    done
    warn "Health check não respondeu em 40s"
    warn "Verifique: journalctl -u aistra-stream -n 40 --no-pager"
    return 1
}

# ── Logrotate ─────────────────────────────────────────────────────────────
setup_logrotate() {
    info "Configurando logrotate"
    cat > /etc/logrotate.d/aistra-stream <<'LOGEOF'
/var/log/aistra-stream.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    copytruncate
}
LOGEOF
    ok "Logrotate configurado — 14 dias de retenção"
}

# ── Firewall ──────────────────────────────────────────────────────────────
open_firewall() {
    info "Configurando firewall"
    if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
        ufw allow "${PORT}/tcp" &>/dev/null
        ok "Porta ${PORT} liberada no ufw"
    elif command -v firewall-cmd &>/dev/null && firewall-cmd --state &>/dev/null; then
        firewall-cmd --permanent --add-port="${PORT}/tcp" &>/dev/null
        firewall-cmd --reload &>/dev/null
        ok "Porta ${PORT} liberada no firewalld"
    else
        ok "Nenhum firewall ativo detectado — sem alterações"
    fi
}

# ── Manifesto ─────────────────────────────────────────────────────────────
save_manifest() {
    info "Salvando manifesto de instalação"
    local INSTALLED_BINS="[]"
    local bins_list=""
    command -v n_m3u8dl   &>/dev/null && bins_list="${bins_list}\"n_m3u8dl\","
    command -v mp4decrypt &>/dev/null && bins_list="${bins_list}\"mp4decrypt\","
    command -v yt-dlp     &>/dev/null && bins_list="${bins_list}\"yt-dlp\","
    # Remove trailing comma
    bins_list="${bins_list%,}"
    [ -n "$bins_list" ] && INSTALLED_BINS="[${bins_list}]"

    cat > "$MANIFEST_FILE" <<MANEOF
{
  "version":       "2.0",
  "installed_at":  "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "project_dir":   "${PROJECT_DIR}",
  "port":          ${PORT},
  "db_name":       "${DB_NAME}",
  "db_user":       "${DB_USER}",
  "service_name":  "aistra-stream",
  "log_file":      "/var/log/aistra-stream.log",
  "binaries_installed": ${INSTALLED_BINS},
  "distro":        "${DISTRO_ID:-unknown}",
  "family":        "${FAMILY:-unknown}"
}
MANEOF
    chmod 600 "$MANIFEST_FILE"
    ok "Manifesto salvo em ${MANIFEST_FILE}"
}

# ── Resumo final ──────────────────────────────────────────────────────────
print_summary() {
    local IP
    IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
    local METRICS_TOKEN_VAL=""
    [ -f "${PROJECT_DIR}/.env" ] && METRICS_TOKEN_VAL=$(grep "^METRICS_TOKEN=" "${PROJECT_DIR}/.env" | cut -d= -f2 || true)

    echo ""
    echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
    if $UPGRADE_MODE; then
        echo -e "${BOLD}${GREEN}║         Atualização concluída com sucesso!           ║${NC}"
    else
        echo -e "${BOLD}${GREEN}║         Instalação concluída com sucesso!            ║${NC}"
    fi
    echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}Painel:${NC}          http://${IP}:${PORT}"
    echo -e "  ${BOLD}Login padrão:${NC}    admin / admin123"
    if [ -n "$METRICS_TOKEN_VAL" ]; then
        echo -e "  ${BOLD}Metrics token:${NC}   ${METRICS_TOKEN_VAL}"
    fi
    echo ""
    echo -e "  ${BOLD}${RED}⚠  IMPORTANTE: Troque a senha padrão imediatamente!${NC}"
    echo ""
    echo -e "  ${BOLD}Binários disponíveis:${NC}"
    printf "    %-14s %s\n" "ffmpeg:"     "$(command -v ffmpeg     2>/dev/null || echo '✗ não encontrado')"
    printf "    %-14s %s\n" "n_m3u8dl:"  "$(command -v n_m3u8dl   2>/dev/null || echo '✗ não instalado')"
    printf "    %-14s %s\n" "mp4decrypt:""$(command -v mp4decrypt  2>/dev/null || echo '✗ não instalado')"
    printf "    %-14s %s\n" "yt-dlp:"    "$(command -v yt-dlp      2>/dev/null || echo '✗ não instalado')"
    echo ""
    echo -e "  ${BOLD}Comandos úteis:${NC}"
    echo "    Logs em tempo real:  journalctl -u aistra-stream -f"
    echo "    Status:              systemctl status aistra-stream"
    echo "    Reiniciar:           systemctl restart aistra-stream"
    echo "    Atualizar:           bash ${PROJECT_DIR}/update.sh"
    echo "    Desinstalar:         bash ${PROJECT_DIR}/uninstall.sh"
    echo ""
}

# ═══════════════════════════════════════════════════
#  EXECUÇÃO PRINCIPAL
# ═══════════════════════════════════════════════════
detect_distro

if $UPGRADE_MODE; then
    # Upgrade: só atualiza código, deps e frontend
    deploy_project
    setup_python
    create_env
    build_frontend
    install_service
    health_check
    save_manifest
    print_summary
else
    # Instalação completa
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
    save_manifest
    print_summary
fi
