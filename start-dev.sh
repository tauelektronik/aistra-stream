#!/usr/bin/env bash
# Modo desenvolvimento — backend + frontend em paralelo
set -e

# Backend
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    cp .env.example .env
fi
export $(grep -v '^#' .env | xargs) 2>/dev/null || true

echo "Iniciando backend em :8001..."
./venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload &
BACK_PID=$!

echo "Iniciando frontend em :5174..."
cd frontend && npm run dev &
FRONT_PID=$!

trap "kill $BACK_PID $FRONT_PID 2>/dev/null; exit" INT TERM
wait
