#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  aistra-stream — Complete Uninstaller  v1.0
#
#  Uso:
#    sudo bash /opt/aistra-stream/uninstall.sh
#
#  Opções:
#    --keep-data       Preserva recordings/, logos/, backups/ e banco de dados
#    --keep-binaries   Não remove n_m3u8dl, mp4decrypt e yt-dlp
#    --purge           Remove também logs do sistema e backups antigos
#    --yes             Pular confirmação interativa (modo não-interativo)
#    --help            Mostrar esta ajuda
#
#  O que é removido por padrão:
#    • Serviço systemd aistra-stream (parado, desabilitado, unit removida)
#    • Diretório do projeto (/opt/aistra-stream ou conforme manifesto)
#    • Banco de dados e usuário MySQL (aistra_stream / aistra)
#    • Logrotate config (/etc/logrotate.d/aistra-stream)
#    • Porta no firewall (ufw/firewalld)
#    • Arquivo de manifesto
#
#  Com --purge também remove:
#    • /var/log/aistra-stream.log
#    • Arquivos temporários HLS (/tmp/aistra_*)
#
#  Com --keep-data NÃO remove:
#    • recordings/, logos/, backups/ (movidos para /opt/aistra-backup-data/)
#    • Banco de dados (preservado)
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────
KEEP_DATA=false
KEEP_BINARIES=false
PURGE=false
YES_MODE=false

# ── Cores / helpers ───────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
STEP=0
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
info() { STEP=$((STEP+1)); echo -e "\n${CYAN}${BOLD}[${STEP}]${NC} ${CYAN}$*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${NC}"; }
err()  { echo -e "${RED}  ✗ ERRO: $*${NC}" >&2; exit 1; }
skip() { echo -e "  ${YELLOW}↷${NC} $* (pulando)"; }

# ── Argparse ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep-data)      KEEP_DATA=true; shift ;;
        --keep-binaries)  KEEP_BINARIES=true; shift ;;
        --purge)          PURGE=true; shift ;;
        --yes|-y)         YES_MODE=true; shift ;;
        --help|-h)
            sed -n '2,30p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) err "Opção desconhecida: $1 (use --help)" ;;
    esac
done

# ── Root ──────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || err "Execute como root: sudo bash uninstall.sh"

# ── Ler manifesto (detectar PROJECT_DIR, PORT, DB, etc.) ─────────────────
# Valores padrão (caso manifesto não exista)
PROJECT_DIR="/opt/aistra-stream"
PORT=8001
DB_NAME="aistra_stream"
DB_USER="aistra"
SERVICE_NAME="aistra-stream"
LOG_FILE="/var/log/aistra-stream.log"
BINARIES_INSTALLED=("n_m3u8dl" "mp4decrypt" "yt-dlp")

# Tenta ler manifesto se existir
MANIFEST_CANDIDATES=(
    "/opt/aistra-stream/.install-manifest"
    "${PROJECT_DIR}/.install-manifest"
)
for mf in "${MANIFEST_CANDIDATES[@]}"; do
    if [ -f "$mf" ]; then
        # Extrai valores com sed (sem depender de jq)
        _dir=$(sed -n 's/.*"project_dir":[[:space:]]*"\(.*\)".*/\1/p' "$mf" | head -1)
        _port=$(sed -n 's/.*"port":[[:space:]]*\([0-9]*\).*/\1/p' "$mf" | head -1)
        _db=$(sed -n 's/.*"db_name":[[:space:]]*"\(.*\)".*/\1/p' "$mf" | head -1)
        _user=$(sed -n 's/.*"db_user":[[:space:]]*"\(.*\)".*/\1/p' "$mf" | head -1)
        _svc=$(sed -n 's/.*"service_name":[[:space:]]*"\(.*\)".*/\1/p' "$mf" | head -1)
        _log=$(sed -n 's/.*"log_file":[[:space:]]*"\(.*\)".*/\1/p' "$mf" | head -1)
        [ -n "$_dir"  ] && PROJECT_DIR="$_dir"
        [ -n "$_port" ] && PORT="$_port"
        [ -n "$_db"   ] && DB_NAME="$_db"
        [ -n "$_user" ] && DB_USER="$_user"
        [ -n "$_svc"  ] && SERVICE_NAME="$_svc"
        [ -n "$_log"  ] && LOG_FILE="$_log"
        ok "Manifesto lido: ${mf}"
        break
    fi
done

# ─────────────────────────────────────────────────────────────────────────
#  BANNER E CONFIRMAÇÃO
# ─────────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${RED}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║       aistra-stream — Desinstalador v1.0         ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "${BOLD}  O seguinte será removido:${NC}"
echo ""
echo "    Serviço:        ${SERVICE_NAME} (systemd)"
echo "    Projeto:        ${PROJECT_DIR}"
if $KEEP_DATA; then
    echo -e "    Banco:          ${YELLOW}PRESERVADO (--keep-data)${NC}"
    echo -e "    Dados:          ${YELLOW}MOVIDOS para /opt/aistra-backup-data/ (--keep-data)${NC}"
else
    echo "    Banco:          ${DB_NAME} (MySQL/MariaDB)"
    echo "    Dados:          recordings/, logos/, backups/"
fi
if $KEEP_BINARIES; then
    echo -e "    Binários:       ${YELLOW}PRESERVADOS (--keep-binaries)${NC}"
else
    echo "    Binários:       n_m3u8dl, mp4decrypt, yt-dlp (se instalados por este script)"
fi
if $PURGE; then
    echo -e "    Logs:           ${RED}${LOG_FILE} (--purge)${NC}"
    echo -e "    /tmp/aistra_*:  ${RED}removidos (--purge)${NC}"
else
    echo "    Logs:           ${LOG_FILE} (preservados — use --purge para remover)"
fi
echo ""

if ! $YES_MODE; then
    echo -e "${BOLD}${RED}  ATENÇÃO: Esta ação é irreversível!${NC}"
    echo ""
    read -rp "  Digite 'SIM' para confirmar a desinstalação: " CONFIRM
    if [ "$CONFIRM" != "SIM" ]; then
        echo ""
        echo "  Desinstalação cancelada."
        exit 0
    fi
fi

echo ""
echo -e "${CYAN}  Iniciando desinstalação...${NC}"

# ═══════════════════════════════════════════════════
#  ETAPAS DE DESINSTALAÇÃO
# ═══════════════════════════════════════════════════

# ── 1. Parar e desabilitar serviço ────────────────────────────────────────
info "Parando serviço ${SERVICE_NAME}"
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl stop "$SERVICE_NAME"
    ok "Serviço parado"
else
    skip "Serviço já estava inativo"
fi

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl disable "$SERVICE_NAME"
    ok "Serviço desabilitado do boot"
fi

# ── 2. Remover unit systemd ───────────────────────────────────────────────
info "Removendo unit systemd"
local_unit="/etc/systemd/system/${SERVICE_NAME}.service"
if [ -f "$local_unit" ]; then
    rm -f "$local_unit"
    systemctl daemon-reload
    ok "Unit /etc/systemd/system/${SERVICE_NAME}.service removida"
else
    skip "Unit não encontrada em /etc/systemd/system/"
fi

# ── 3. Preservar ou remover dados ─────────────────────────────────────────
if $KEEP_DATA; then
    info "Preservando dados do usuário"
    BACKUP_DATA_DIR="/opt/aistra-backup-data"
    mkdir -p "$BACKUP_DATA_DIR"
    for subdir in recordings logos backups data; do
        src="${PROJECT_DIR}/${subdir}"
        if [ -d "$src" ] && [ "$(ls -A "$src" 2>/dev/null)" ]; then
            cp -r "$src" "${BACKUP_DATA_DIR}/${subdir}"
            ok "  → ${subdir}/ copiado para ${BACKUP_DATA_DIR}/${subdir}/"
        fi
    done
    # Preservar .env
    [ -f "${PROJECT_DIR}/.env" ] && cp "${PROJECT_DIR}/.env" "${BACKUP_DATA_DIR}/.env.bak"
    ok "Dados preservados em ${BACKUP_DATA_DIR}"
fi

# ── 4. Remover banco de dados ─────────────────────────────────────────────
info "Removendo banco de dados"
if $KEEP_DATA; then
    skip "Banco preservado (--keep-data)"
else
    if mysqladmin ping --silent 2>/dev/null; then
        mysql -e "DROP DATABASE IF EXISTS \`${DB_NAME}\`;" 2>/dev/null && \
            ok "Banco '${DB_NAME}' removido" || warn "Falha ao remover banco '${DB_NAME}'"
        mysql -e "DROP USER IF EXISTS '${DB_USER}'@'localhost'; FLUSH PRIVILEGES;" 2>/dev/null && \
            ok "Usuário '${DB_USER}' removido" || warn "Falha ao remover usuário '${DB_USER}'"
    else
        warn "MySQL/MariaDB não está rodando — banco não removido automaticamente"
        warn "Remova manualmente: DROP DATABASE ${DB_NAME}; DROP USER '${DB_USER}'@'localhost';"
    fi
fi

# ── 5. Remover diretório do projeto ───────────────────────────────────────
info "Removendo diretório do projeto"
if [ -d "$PROJECT_DIR" ]; then
    rm -rf "$PROJECT_DIR"
    ok "Diretório ${PROJECT_DIR} removido"
else
    skip "${PROJECT_DIR} não encontrado"
fi

# ── 6. Remover binários opcionais ─────────────────────────────────────────
info "Removendo binários opcionais"
if $KEEP_BINARIES; then
    skip "Binários preservados (--keep-binaries)"
else
    for bin in n_m3u8dl mp4decrypt; do
        bin_path="/usr/local/bin/${bin}"
        if [ -f "$bin_path" ]; then
            rm -f "$bin_path"
            ok "  Removido: ${bin_path}"
        fi
    done
    # yt-dlp — só remove se instalado no /usr/local/bin (não toca instalações do sistema)
    ytdlp_path="/usr/local/bin/yt-dlp"
    if [ -f "$ytdlp_path" ]; then
        rm -f "$ytdlp_path"
        ok "  Removido: ${ytdlp_path}"
    fi
fi

# ── 7. Remover logrotate ──────────────────────────────────────────────────
info "Removendo configuração de logrotate"
logrotate_conf="/etc/logrotate.d/${SERVICE_NAME}"
if [ -f "$logrotate_conf" ]; then
    rm -f "$logrotate_conf"
    ok "Logrotate config removida"
else
    skip "Logrotate config não encontrada"
fi

# ── 8. Remover log do sistema (apenas com --purge) ────────────────────────
info "Logs do sistema"
if $PURGE; then
    [ -f "$LOG_FILE" ] && rm -f "$LOG_FILE" && ok "Log removido: ${LOG_FILE}"
    # Remover logs rotacionados
    rm -f "${LOG_FILE}."* 2>/dev/null || true
    ok "Logs do sistema removidos (--purge)"
else
    skip "Logs preservados (use --purge para remover: ${LOG_FILE})"
fi

# ── 9. Remover arquivos temporários (apenas com --purge) ──────────────────
if $PURGE; then
    info "Removendo arquivos temporários"
    rm -rf /tmp/aistra_stream_hls  \
           /tmp/aistra_stream_pipes \
           /tmp/aistra_stream_tmp   \
           /tmp/aistra_thumbnails   \
           /tmp/ffmpeg_*.log        \
           /tmp/ffmpeg_progress_*.txt 2>/dev/null || true
    ok "Arquivos temporários em /tmp/ removidos"
fi

# ── 10. Fechar porta no firewall ──────────────────────────────────────────
info "Revertendo regras de firewall"
if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    ufw delete allow "${PORT}/tcp" &>/dev/null && ok "Porta ${PORT} removida do ufw" || \
        warn "Porta ${PORT} não estava no ufw"
elif command -v firewall-cmd &>/dev/null && firewall-cmd --state &>/dev/null; then
    firewall-cmd --permanent --remove-port="${PORT}/tcp" &>/dev/null && \
        firewall-cmd --reload &>/dev/null && \
        ok "Porta ${PORT} removida do firewalld" || \
        warn "Porta ${PORT} não estava no firewalld"
else
    skip "Nenhum firewall ativo detectado"
fi

# ── 11. Verificar que o serviço sumiu ─────────────────────────────────────
info "Verificação final"
if systemctl list-units --all 2>/dev/null | grep -q "$SERVICE_NAME"; then
    warn "Serviço ainda aparece no systemd — execute: systemctl reset-failed"
else
    ok "Serviço ${SERVICE_NAME} completamente removido do systemd"
fi

# ── Resumo ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║      aistra-stream desinstalado com sucesso!         ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

if $KEEP_DATA; then
    echo -e "  ${BOLD}Dados preservados em:${NC} /opt/aistra-backup-data/"
    echo "    → Banco de dados '${DB_NAME}' intacto"
    echo "    → .env salvo como .env.bak"
fi

echo ""
echo -e "  ${BOLD}Removido:${NC}"
echo "    • Serviço systemd ${SERVICE_NAME}"
echo "    • Diretório ${PROJECT_DIR}"
$KEEP_DATA || echo "    • Banco de dados ${DB_NAME} e usuário ${DB_USER}"
$KEEP_BINARIES || echo "    • Binários: n_m3u8dl, mp4decrypt, yt-dlp"
$PURGE && echo "    • Log ${LOG_FILE} e temporários /tmp/aistra_*"
echo ""
echo "  Para reinstalar: export GH_TOKEN=ghp_xxxx && bash <(curl -fsSL ...)"
echo ""
