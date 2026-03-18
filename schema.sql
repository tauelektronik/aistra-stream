-- aistra-stream — MySQL/MariaDB schema
-- Run: mysql -u root -p < schema.sql

CREATE DATABASE IF NOT EXISTS aistra_stream CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE aistra_stream;

-- Dedicated user (optional, recommended for production)
CREATE USER IF NOT EXISTS 'aistra'@'localhost' IDENTIFIED BY 'aistra123';
GRANT ALL PRIVILEGES ON aistra_stream.* TO 'aistra'@'localhost';
FLUSH PRIVILEGES;

-- Tables are created automatically by SQLAlchemy on first run.
-- This file is provided for reference / manual inspection.

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email         VARCHAR(100) NULL,
    role          ENUM('admin','operator','viewer') NOT NULL DEFAULT 'viewer',
    active        TINYINT(1)   NOT NULL DEFAULT 1,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS streams (
    id               VARCHAR(50)  PRIMARY KEY,
    name             VARCHAR(150) NOT NULL,
    url              TEXT         NOT NULL,
    drm_type         ENUM('none','cenc-ctr') NOT NULL DEFAULT 'none',
    drm_kid          VARCHAR(64)  NULL,
    drm_key          VARCHAR(64)  NULL,
    stream_type      ENUM('live','vod') NOT NULL DEFAULT 'live',
    -- Video
    video_codec      ENUM('copy','libx264','h264_nvenc') NOT NULL DEFAULT 'libx264',
    video_preset     VARCHAR(20)  NOT NULL DEFAULT 'ultrafast',
    video_crf        INT          NOT NULL DEFAULT 26,
    video_maxrate    VARCHAR(20)  NOT NULL DEFAULT '',
    video_resolution VARCHAR(20)  NOT NULL DEFAULT 'original',
    -- Audio
    audio_codec      ENUM('copy','aac') NOT NULL DEFAULT 'aac',
    audio_bitrate    VARCHAR(10)  NOT NULL DEFAULT '128k',
    -- HLS
    hls_time         INT          NOT NULL DEFAULT 4,
    hls_list_size    INT          NOT NULL DEFAULT 30,
    buffer_seconds   INT          NOT NULL DEFAULT 20,
    -- Meta
    enabled          TINYINT(1)   NOT NULL DEFAULT 1,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
