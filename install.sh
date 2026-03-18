#!/usr/bin/env bash
# aistra-stream — Install script (Ubuntu 22.04 / 24.04)
set -e

PROJECT_DIR="/opt/aistra-stream"
SERVICE_USER="root"

echo "=== aistra-stream install ==="

# ── 1. Dependencies ───────────────────────────────────────────────────────────
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv nodejs npm mariadb-server curl

# ── 2. MariaDB setup ──────────────────────────────────────────────────────────
echo "Configurando MariaDB..."
systemctl enable --now mariadb
mysql -e "CREATE DATABASE IF NOT EXISTS aistra_stream CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -e "CREATE USER IF NOT EXISTS 'aistra'@'localhost' IDENTIFIED BY 'aistra123';"
mysql -e "GRANT ALL PRIVILEGES ON aistra_stream.* TO 'aistra'@'localhost'; FLUSH PRIVILEGES;"

# ── 3. Copy project files ─────────────────────────────────────────────────────
echo "Copiando arquivos para $PROJECT_DIR..."
mkdir -p "$PROJECT_DIR"
cp -r . "$PROJECT_DIR/"
cd "$PROJECT_DIR"

# ── 4. Backend venv ───────────────────────────────────────────────────────────
echo "Instalando dependências Python..."
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r backend/requirements.txt

# ── 5. .env ───────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/change-me-to-a-long-random-string/$SECRET/" .env
    echo "Arquivo .env criado. Revise as configurações em $PROJECT_DIR/.env"
fi

# ── 6. Frontend build ─────────────────────────────────────────────────────────
echo "Instalando e buildando frontend..."
cd frontend
npm install --silent
npm run build
cd ..

# ── 7. Systemd service ────────────────────────────────────────────────────────
cat > /etc/systemd/system/aistra-stream.service <<EOF
[Unit]
Description=Aistra Stream Panel
After=network.target mariadb.service

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5
StandardOutput=append:/var/log/aistra-stream.log
StandardError=append:/var/log/aistra-stream.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now aistra-stream

echo ""
echo "=== Instalação concluída! ==="
echo ""
echo "  Painel: http://$(hostname -I | awk '{print $1}'):8001"
echo "  Login:  admin / admin123"
echo ""
echo "  IMPORTANTE: troque a senha padrão após o primeiro acesso!"
echo "  Logs: journalctl -u aistra-stream -f"
