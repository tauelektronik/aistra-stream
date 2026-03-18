"""
SQLAlchemy ORM models for aistra-stream.
"""
from datetime import datetime
from sqlalchemy import (
    Integer, String, Boolean, Text, DateTime, Enum as SAEnum, ForeignKey
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base
import enum


class UserRole(str, enum.Enum):
    admin    = "admin"
    operator = "operator"
    viewer   = "viewer"


class StreamType(str, enum.Enum):
    live = "live"
    vod  = "vod"


class DrmType(str, enum.Enum):
    none     = "none"
    cenc_ctr = "cenc-ctr"


class VideoCodec(str, enum.Enum):
    copy       = "copy"
    libx264    = "libx264"
    h264_nvenc = "h264_nvenc"


class AudioCodec(str, enum.Enum):
    copy       = "copy"
    aac        = "aac"


class User(Base):
    __tablename__ = "users"

    id            : Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    username      : Mapped[str]      = mapped_column(String(50), unique=True, nullable=False)
    password_hash : Mapped[str]      = mapped_column(String(255), nullable=False)
    email         : Mapped[str|None] = mapped_column(String(100), nullable=True)
    role          : Mapped[str]      = mapped_column(SAEnum(UserRole), default=UserRole.viewer, nullable=False)
    active        : Mapped[bool]     = mapped_column(Boolean, default=True, nullable=False)
    created_at    : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Stream(Base):
    __tablename__ = "streams"

    id            : Mapped[str]      = mapped_column(String(50), primary_key=True)
    name          : Mapped[str]      = mapped_column(String(150), nullable=False)
    url           : Mapped[str]      = mapped_column(Text, nullable=False)

    # DRM
    drm_type      : Mapped[str]      = mapped_column(SAEnum(DrmType), default=DrmType.none, nullable=False)
    drm_keys      : Mapped[str|None] = mapped_column(Text, nullable=True)          # "KID:KEY\nKID:KEY\n..." (CDM format)
    drm_kid       : Mapped[str|None] = mapped_column(String(64), nullable=True)    # legacy single KID
    drm_key       : Mapped[str|None] = mapped_column(String(64), nullable=True)    # legacy single KEY

    stream_type   : Mapped[str]      = mapped_column(SAEnum(StreamType), default=StreamType.live)

    # Video transcoding
    video_codec   : Mapped[str]      = mapped_column(SAEnum(VideoCodec), default=VideoCodec.libx264)
    video_preset  : Mapped[str]      = mapped_column(String(20), default="ultrafast")
    video_crf     : Mapped[int]      = mapped_column(Integer, default=26)
    video_maxrate : Mapped[str]      = mapped_column(String(20), default="")        # e.g. "4000k", "" = no limit
    video_resolution: Mapped[str]    = mapped_column(String(20), default="original") # "original" | "1920x1080" | "1280x720" | "854x480"

    # Audio transcoding
    audio_codec   : Mapped[str]      = mapped_column(SAEnum(AudioCodec), default=AudioCodec.aac)
    audio_bitrate : Mapped[str]      = mapped_column(String(10), default="128k")

    # HLS settings
    hls_time      : Mapped[int]      = mapped_column(Integer, default=4)   # segment duration (s)
    hls_list_size : Mapped[int]      = mapped_column(Integer, default=30)  # segments in playlist

    # Player settings (sent to frontend)
    buffer_seconds: Mapped[int]      = mapped_column(Integer, default=20)  # target latency buffer (s)

    # Output destinations (optional, in addition to HLS)
    output_rtmp   : Mapped[str|None] = mapped_column(String(500), nullable=True)   # e.g. rtmp://live.twitch.tv/live/KEY
    output_udp    : Mapped[str|None] = mapped_column(String(200), nullable=True)   # e.g. udp://239.0.0.1:1234

    # Multi-quality ABR output
    output_qualities: Mapped[str|None] = mapped_column(String(50), nullable=True)  # e.g. "1080p,720p,480p"

    # Proxy / network
    proxy         : Mapped[str|None] = mapped_column(String(500), nullable=True)   # http://user:pass@host:port or socks5://
    user_agent    : Mapped[str|None] = mapped_column(String(500), nullable=True)   # custom UA string
    backup_urls   : Mapped[str|None] = mapped_column(Text, nullable=True)          # newline-separated fallback URLs (failover)

    # Metadata
    enabled       : Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at    : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at    : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
