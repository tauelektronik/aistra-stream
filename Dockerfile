# ── Build stage: React/Vite ───────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

ARG TARGETARCH

# System deps: ffmpeg, curl, unzip, ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        unzip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── yt-dlp ────────────────────────────────────────────────────────────────────
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
         -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp

# ── n_m3u8dl-RE (CENC/DRM downloader) ────────────────────────────────────────
RUN set -e; \
    ARCH=$(uname -m); \
    case "$ARCH" in \
        x86_64)  NARCH="linux-x64" ;; \
        aarch64) NARCH="linux-arm64" ;; \
        *) echo "Unsupported arch $ARCH for n_m3u8dl — skipping" && exit 0 ;; \
    esac; \
    URL=$(curl -s https://api.github.com/repos/nilaoda/N_m3u8DL-RE/releases/latest \
          | grep '"browser_download_url"' \
          | grep "$NARCH" | grep -v musl | grep '\.tar\.gz' | head -1 \
          | sed 's/.*"\(https[^"]*\)".*/\1/'); \
    if [ -n "$URL" ]; then \
        curl -L "$URL" -o /tmp/n_m3u8dl.tar.gz; \
        tar xf /tmp/n_m3u8dl.tar.gz -C /tmp 2>/dev/null || true; \
        find /tmp -name "N_m3u8DL-RE" -type f -exec cp {} /usr/local/bin/n_m3u8dl \; 2>/dev/null || true; \
        chmod +x /usr/local/bin/n_m3u8dl 2>/dev/null || true; \
        rm -f /tmp/n_m3u8dl.tar.gz; \
    else \
        echo "WARNING: n_m3u8dl not installed (CENC streams will not work)"; \
    fi

# ── mp4decrypt (Bento4 SDK) ───────────────────────────────────────────────────
RUN set -e; \
    ARCH=$(uname -m); \
    case "$ARCH" in \
        x86_64)  BARCH="x86_64-unknown-linux" ;; \
        aarch64) BARCH="aarch64-unknown-linux" ;; \
        *) echo "Unsupported arch $ARCH for mp4decrypt — skipping" && exit 0 ;; \
    esac; \
    URL="https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-641.${BARCH}.zip"; \
    curl -L "$URL" -o /tmp/bento4.zip || { echo "WARNING: mp4decrypt download failed"; exit 0; }; \
    unzip -o /tmp/bento4.zip -d /tmp/bento4 &>/dev/null || true; \
    find /tmp/bento4 -name "mp4decrypt" -type f -exec cp {} /usr/local/bin/mp4decrypt \; || true; \
    chmod +x /usr/local/bin/mp4decrypt 2>/dev/null || true; \
    rm -rf /tmp/bento4.zip /tmp/bento4

WORKDIR /app

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY backend/ ./backend/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create persistent and temp directories
RUN mkdir -p \
        /data/recordings \
        /data/logos \
        /tmp/aistra_stream_hls \
        /tmp/aistra_stream_pipes \
        /tmp/aistra_stream_tmp \
        /tmp/aistra_thumbnails \
    && chmod 755 /data/recordings /data/logos

# Environment defaults (override via docker-compose or -e flags)
ENV PYTHONUNBUFFERED=1 \
    FFMPEG=/usr/bin/ffmpeg \
    N_M3U8DL=/usr/local/bin/n_m3u8dl \
    MP4DECRYPT=/usr/local/bin/mp4decrypt \
    YTDLP=/usr/local/bin/yt-dlp \
    YTDLP_COOKIES=/opt/youtube_cookies.txt \
    HLS_BASE=/tmp/aistra_stream_hls \
    PIPE_BASE=/tmp/aistra_stream_pipes \
    TMP_BASE=/tmp/aistra_stream_tmp \
    THUMBNAILS_BASE=/tmp/aistra_thumbnails \
    RECORDINGS_BASE=/data/recordings \
    LOGOS_BASE=/data/logos

EXPOSE 8001

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
