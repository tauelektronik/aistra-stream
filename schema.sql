-- aistra-stream — MySQL/MariaDB schema
-- Run: mysql -u root -p < schema.sql
-- NOTE: SQLAlchemy also auto-creates these tables on first run (init_db).
--       This file is for reference, manual inspection, and Docker init.

CREATE DATABASE IF NOT EXISTS aistra_stream CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE aistra_stream;

-- Dedicated user (recommended for production)
CREATE USER IF NOT EXISTS 'aistra'@'localhost' IDENTIFIED BY 'aistra123';
GRANT ALL PRIVILEGES ON aistra_stream.* TO 'aistra'@'localhost';
FLUSH PRIVILEGES;

-- ── categories ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS categories (
    id         INT          AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) UNIQUE NOT NULL,
    logo_path  VARCHAR(500) NULL,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── users ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            INT          AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email         VARCHAR(100) NULL,
    role          ENUM('admin','operator','viewer') NOT NULL DEFAULT 'viewer',
    active        TINYINT(1)   NOT NULL DEFAULT 1,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── streams ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS streams (
    id               VARCHAR(50)  PRIMARY KEY,
    name             VARCHAR(150) NOT NULL,
    url              TEXT         NOT NULL,

    -- DRM
    drm_type         ENUM('none','cenc_ctr') NOT NULL DEFAULT 'none',
    drm_keys         TEXT         NULL,          -- "KID:KEY\nKID:KEY\n..." (CDM format)
    drm_kid          VARCHAR(64)  NULL,           -- legacy single KID
    drm_key          VARCHAR(64)  NULL,           -- legacy single KEY

    stream_type      ENUM('live','vod') NOT NULL DEFAULT 'live',

    -- Video transcoding
    video_codec      ENUM('copy','libx264','h264_nvenc') NOT NULL DEFAULT 'libx264',
    video_preset     VARCHAR(20)  NOT NULL DEFAULT 'ultrafast',
    video_crf        INT          NOT NULL DEFAULT 26,
    video_maxrate    VARCHAR(20)  NOT NULL DEFAULT '',
    video_resolution VARCHAR(20)  NOT NULL DEFAULT 'original',

    -- Audio transcoding
    audio_codec      ENUM('copy','aac') NOT NULL DEFAULT 'aac',
    audio_bitrate    VARCHAR(10)  NOT NULL DEFAULT '128k',
    audio_track      INT          NOT NULL DEFAULT 0,

    -- HLS settings
    hls_time         INT          NOT NULL DEFAULT 15,  -- segment duration (s)
    hls_list_size    INT          NOT NULL DEFAULT 15,  -- segments in playlist
    buffer_seconds   INT          NOT NULL DEFAULT 20,

    -- Output destinations
    output_rtmp      VARCHAR(500) NULL,   -- e.g. rtmp://live.twitch.tv/live/KEY
    output_udp       VARCHAR(200) NULL,   -- e.g. udp://239.0.0.1:1234
    output_qualities VARCHAR(50)  NULL,   -- e.g. "1080p,720p,480p"

    -- Proxy / network
    proxy            VARCHAR(500) NULL,
    user_agent       VARCHAR(500) NULL,
    backup_urls      TEXT         NULL,   -- newline-separated fallback URLs

    -- Category / ordering
    category         VARCHAR(100) NULL,
    channel_num      INT          NULL UNIQUE,

    -- Metadata
    enabled          TINYINT(1)   NOT NULL DEFAULT 1,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
