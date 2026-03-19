# ── Build stage: React/Vite ───────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System deps: ffmpeg, yt-dlp, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
         -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY backend/ ./backend/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Persistent dirs
RUN mkdir -p /tmp/aistra_stream_hls /tmp/aistra_recordings /tmp/aistra_thumbnails

ENV PYTHONUNBUFFERED=1
ENV HLS_BASE=/tmp/aistra_stream_hls
ENV RECORDINGS_BASE=/data/recordings
ENV THUMBNAILS_BASE=/tmp/aistra_thumbnails

EXPOSE 8001

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
