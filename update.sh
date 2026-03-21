#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  aistra-stream — Update Script
#  Atualiza uma instalação existente em /opt/aistra-stream
#
#  Uso:
#    sudo bash update.sh
# ═══════════════════════════════════════════════════════════════
set -e

PROJECT_DIR="/opt/aistra-stream"
PORT=${PORT:-8001}

# ── Helper functions (must be defined FIRST) ──────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
info() { echo -e "${CYAN}[..] $*${NC}"; }
warn() { echo -e "${YELLOW}[AV] $*${NC}"; }
err()  { echo -e "${RED}[ERRO] $*${NC}"; exit 1; }

# ── Token GitHub read-only — passe via env var (nunca hardcode):
#   export GH_TOKEN=ghp_xxxx && sudo -E bash update.sh
GH_TOKEN="${GH_TOKEN:-}"
[ -n "$GH_TOKEN" ] || err "GH_TOKEN não definido. Configure antes de executar:
  export GH_TOKEN=ghp_xxxx
  sudo -E bash update.sh"
GIT_REPO="https://${GH_TOKEN}@github.com/tauelektronik/aistra-stream.git"

echo -e "${BOLD}${CYAN}"
echo "  ╔═══════════════════════════════════╗"
echo "  ║   aistra-stream  updater          ║"
echo "  ╚═══════════════════════════════════╝"
echo -e "${NC}"

[ "$(id -u)" -eq 0 ] || err "Execute como root: sudo bash update.sh"
[ -d "$PROJECT_DIR" ]  || err "Instalação não encontrada em $PROJECT_DIR. Execute install.sh primeiro."

cd "$PROJECT_DIR"

# ── 1. Ler PORT do .env existente ────────────────────────────
if [ -f .env ]; then
    PORT=$(grep -E '^PORT=' .env | cut -d= -f2 | tr -d ' ' || echo "8001")
    PORT=${PORT:-8001}
fi

# ── 2. git pull ───────────────────────────────────────────────
if [ -d .git ]; then
    info "Baixando atualizações do repositório..."
    # Injeta token temporariamente para o fetch (sem persistir credenciais)
    git remote set-url origin "$GIT_REPO" 2>/dev/null || true
    GIT_TERMINAL_PROMPT=0 git fetch --quiet
    # Restaura URL pública (sem token) imediatamente após o fetch
    git remote set-url origin "https://github.com/tauelektronik/aistra-stream.git" 2>/dev/null || true
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse '@{u}' 2>/dev/null || echo "unknown")
    if [ "$LOCAL" = "$REMOTE" ]; then
        ok "Código já está atualizado ($(git rev-parse --short HEAD))"
    else
        git merge --ff-only FETCH_HEAD || { warn "git merge falhou — tente resolver conflitos manualmente"; exit 1; }
        ok "Código atualizado para $(git rev-parse --short HEAD)"
    fi
else
    warn "Diretório sem git — pulando git pull"
fi

# ── 3. Adicionar variáveis novas ao .env (se ausentes) ───────
info "Verificando variáveis do .env..."
grep -q "^RECORDINGS_BASE=" .env  || echo "RECORDINGS_BASE=${PROJECT_DIR}/recordings"                   >> .env
grep -q "^THUMBNAILS_BASE=" .env  || echo "THUMBNAILS_BASE=/tmp/aistra_thumbnails"                      >> .env
grep -q "^LOGOS_BASE="      .env  || echo "LOGOS_BASE=${PROJECT_DIR}/logos"                             >> .env
grep -q "^YTDLP="           .env  || echo "YTDLP=$(command -v yt-dlp || echo /usr/local/bin/yt-dlp)"   >> .env
grep -q "^YTDLP_COOKIES="   .env  || echo "YTDLP_COOKIES=/opt/youtube_cookies.txt"                     >> .env
grep -q "^PIPE_BASE="       .env  || echo "PIPE_BASE=/tmp/aistra_stream_pipes"                          >> .env
grep -q "^TMP_BASE="        .env  || echo "TMP_BASE=/tmp/aistra_stream_tmp"                             >> .env
grep -q "^METRICS_TOKEN="   .env  || {
    T=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "METRICS_TOKEN=${T}" >> .env
    warn "METRICS_TOKEN gerado e adicionado ao .env"
}
mkdir -p "${PROJECT_DIR}/recordings" "${PROJECT_DIR}/logos" "${PROJECT_DIR}/data" "${PROJECT_DIR}/backups"
chmod 750 "${PROJECT_DIR}/recordings" "${PROJECT_DIR}/logos" "${PROJECT_DIR}/data" "${PROJECT_DIR}/backups"
ok ".env verificado"

# ── 4. Atualizar dependências Python ──────────────────────────
info "Atualizando dependências Python..."
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r backend/requirements.txt
ok "Dependências Python atualizadas"

# ── 5. Rebuild frontend ───────────────────────────────────────
info "Buildando frontend React..."
cd frontend
npm install --loglevel=warn
npm run build
cd ..
ok "Frontend atualizado em frontend/dist/"

# ── 6. Aplicar migrações de banco (run_migrations via init_db) ─
#      As migrações são aplicadas automaticamente ao reiniciar o serviço
#      (database.py → run_migrations() executa ALTERs idempotentes)

# ── 7. Reiniciar serviço ──────────────────────────────────────
info "Reiniciando serviço..."
systemctl restart aistra-stream
sleep 3

if systemctl is-active --quiet aistra-stream; then
    ok "Serviço aistra-stream ativo"
else
    warn "Serviço não iniciou — verificando logs..."
    journalctl -u aistra-stream -n 20 --no-pager
    exit 1
fi

# ── 8. Health check ───────────────────────────────────────────
info "Verificando serviço..."
tries=0
while [ $tries -lt 15 ]; do
    http_code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/health" 2>/dev/null || echo "000")
    if [ "$http_code" = "200" ]; then
        ok "Health check OK (HTTP 200)"
        break
    fi
    sleep 2; tries=$((tries+1))
done
[ "$http_code" = "200" ] || warn "Health check não respondeu — verifique: journalctl -u aistra-stream -n 30"

# ── Resumo ────────────────────────────────────────────────────
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo ""
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Atualização concluída!${NC}"
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Painel:${NC}  http://${IP}:${PORT}"
echo -e "  ${BOLD}Versão:${NC}  $(git rev-parse --short HEAD 2>/dev/null || echo 'desconhecida')"
echo ""
echo -e "  ${BOLD}Comandos úteis:${NC}"
echo "    Logs:     journalctl -u aistra-stream -f"
echo "    Reiniciar: systemctl restart aistra-stream"
echo ""
