"""
Pydantic schemas for request/response validation.
"""
import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from urllib.parse import urlparse


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str
    active: bool
    class Config: from_attributes = True

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    email:    Optional[str] = None
    role:     str = "viewer"

class UserUpdate(BaseModel):
    email:    Optional[str] = None
    role:     Optional[str] = None
    active:   Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)


# ── Categories ────────────────────────────────────────────────────────────────

class CategoryOut(BaseModel):
    id:         int
    name:       str
    logo_path:  Optional[str] = None
    created_at: datetime
    class Config: from_attributes = True

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)


# ── Validators ────────────────────────────────────────────────────────────────

_ALLOWED_SCHEMES = {"http", "https", "rtmp", "rtmps", "rtsp", "rtsps", "udp", "rtp", "srt", "file"}
_PROXY_SCHEMES   = {"http", "https", "socks4", "socks5"}
_HEX_RE = re.compile(r'^[0-9a-fA-F]+$')

def _validate_stream_url(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    if len(v) > 2048:
        raise ValueError("URL muito longa (máx 2048 caracteres)")
    if any(c in v for c in '\n\r\0\t'):
        raise ValueError("URL não pode conter quebras de linha ou caracteres de controle")
    try:
        parsed = urlparse(v)
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise ValueError(f"Protocolo não permitido: '{parsed.scheme}'. Use: {', '.join(sorted(_ALLOWED_SCHEMES))}")
        if ".." in (parsed.path or ""):
            raise ValueError("URL contém path traversal")
        # Extra safety for file:// — reject paths outside /opt, /srv, /media, /mnt, /data, /home
        if parsed.scheme.lower() == "file":
            safe_prefixes = ("/opt/", "/srv/", "/media/", "/mnt/", "/data/", "/home/", "/var/")
            path = parsed.path
            if not any(path.startswith(p) for p in safe_prefixes):
                raise ValueError(
                    "file:// só é permitido para caminhos em: "
                    + ", ".join(safe_prefixes)
                )
    except ValueError:
        raise
    except Exception:
        raise ValueError("URL inválida")
    return v

def _validate_drm_keys(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    lines = [l.strip() for l in v.splitlines() if l.strip()]
    for line in lines:
        if ":" not in line:
            raise ValueError(f"Formato inválido: '{line[:30]}'. Use KID:KEY (hex)")
        kid, _, key = line.partition(":")
        kid = kid.strip().replace(" ", "")
        key = key.strip().replace(" ", "")
        # Zeros are valid (placeholder keys)
        if len(kid) not in (32, 64) or not _HEX_RE.match(kid):
            raise ValueError(f"KID inválido: '{kid[:32]}'. Deve ter 32 ou 64 caracteres hex")
        if len(key) not in (32, 64) or not _HEX_RE.match(key):
            raise ValueError(f"KEY inválida: '{key[:32]}'. Deve ter 32 ou 64 caracteres hex")
    return v

def _validate_rtmp(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    parsed = urlparse(v)
    if parsed.scheme.lower() not in {"rtmp", "rtmps"}:
        raise ValueError("Saída RTMP deve começar com rtmp:// ou rtmps://")
    return v

def _validate_udp(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    parsed = urlparse(v)
    if parsed.scheme.lower() not in {"udp", "rtp", "srt"}:
        raise ValueError("Saída UDP deve começar com udp://, rtp:// ou srt://")
    return v

def _validate_proxy(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    if len(v) > 500:
        raise ValueError("Proxy URL muito longa (máx 500 caracteres)")
    try:
        parsed = urlparse(v)
        if parsed.scheme.lower() not in _PROXY_SCHEMES:
            raise ValueError(
                f"Protocolo de proxy não permitido: '{parsed.scheme}'. "
                f"Use: {', '.join(sorted(_PROXY_SCHEMES))}"
            )
        if not parsed.hostname:
            raise ValueError("Proxy deve ter um hostname")
        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            raise ValueError(f"Porta de proxy inválida: {port}")
    except ValueError:
        raise
    except Exception:
        raise ValueError("Proxy URL inválida")
    return v

def _validate_backup_urls(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    for line in v.splitlines():
        line = line.strip()
        if line:
            _validate_stream_url(line)
    return v


# ── Streams ───────────────────────────────────────────────────────────────────

class StreamBase(BaseModel):
    name:             str = Field(..., min_length=1, max_length=100)
    url:              str
    drm_type:         str = "none"
    drm_keys:         Optional[str] = None   # "KID:KEY\nKID:KEY\n..." (CDM format)
    drm_kid:          Optional[str] = None   # legacy single KID
    drm_key:          Optional[str] = None   # legacy single KEY
    stream_type:      str = "live"
    video_codec:      str = "libx264"
    video_preset:     str = "ultrafast"
    video_crf:        int = Field(26, ge=0, le=51)
    video_maxrate:    str = ""
    video_resolution: str = "original"
    audio_codec:      str = "aac"
    audio_bitrate:    str = "128k"
    hls_time:         int = Field(4, ge=1, le=10)
    hls_list_size:    int = Field(8, ge=3, le=30)   # 8×4s = 32s on disk — enough for live buffering
    buffer_seconds:   int = Field(20, ge=5, le=120)
    output_rtmp:      Optional[str] = None
    output_udp:       Optional[str] = None
    output_qualities: Optional[str] = None   # comma-separated ABR qualities, e.g. "1080p,720p,480p"
    audio_track:      int = Field(0, ge=0, le=9)  # audio track index (0=first)
    proxy:            Optional[str] = None   # http://user:pass@host:port or socks5://host:port
    user_agent:       Optional[str] = None   # custom User-Agent header
    backup_urls:      Optional[str] = None   # newline-separated fallback URLs (failover/balance)
    category:         Optional[str] = None   # free-form grouping tag, e.g. "Esportes"
    channel_num:      Optional[int] = Field(None, ge=1, le=99999)  # user-assigned channel number
    enabled:          bool = True

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        if any(c in v for c in '\n\r\0\t'):
            raise ValueError("Nome não pode conter quebras de linha, tabs ou caracteres nulos")
        return v.strip()

    @field_validator("url")
    @classmethod
    def check_url(cls, v): return _validate_stream_url(v)

    @field_validator("drm_keys")
    @classmethod
    def check_drm_keys(cls, v): return _validate_drm_keys(v)

    @field_validator("output_rtmp")
    @classmethod
    def check_rtmp(cls, v): return _validate_rtmp(v)

    @field_validator("output_udp")
    @classmethod
    def check_udp(cls, v): return _validate_udp(v)

    @field_validator("output_qualities")
    @classmethod
    def check_output_qualities(cls, v):
        if not v:
            return v
        valid = {"360p", "480p", "720p", "1080p"}
        for q in [x.strip() for x in v.split(",") if x.strip()]:
            if q not in valid:
                raise ValueError(f"Qualidade inválida: '{q}'. Use: {', '.join(sorted(valid))}")
        return v

    @field_validator("proxy")
    @classmethod
    def check_proxy(cls, v): return _validate_proxy(v)

    @field_validator("user_agent")
    @classmethod
    def check_user_agent(cls, v):
        if v:
            if len(v) > 500:
                raise ValueError("User-Agent muito longo (máx 500 caracteres)")
            if any(c in v for c in ('\x00', '\n', '\r')):
                raise ValueError("User-Agent contém caracteres de controle inválidos")
        return v

    @field_validator("backup_urls")
    @classmethod
    def check_backup_urls(cls, v): return _validate_backup_urls(v)

class StreamCreate(StreamBase):
    id: str = Field(..., min_length=2, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')

class StreamUpdate(StreamBase):
    name:    Optional[str] = None
    url:     Optional[str] = None
    enabled: Optional[bool] = None

class StreamOut(StreamBase):
    id:          str
    channel_num: Optional[int] = None
    created_at:  datetime
    updated_at:  datetime
    status:      str = "stopped"   # injected at runtime from HLS manager
    class Config: from_attributes = True
