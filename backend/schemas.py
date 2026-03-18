"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


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
    password: str = Field(..., min_length=6)
    email:    Optional[str] = None
    role:     str = "viewer"

class UserUpdate(BaseModel):
    email:    Optional[str] = None
    role:     Optional[str] = None
    active:   Optional[bool] = None
    password: Optional[str] = None


# ── Streams ───────────────────────────────────────────────────────────────────

class StreamBase(BaseModel):
    name:             str
    url:              str
    drm_type:         str = "none"
    drm_keys:         Optional[str] = None   # "KID:KEY\nKID:KEY\n..." (CDM format, multiple lines)
    drm_kid:          Optional[str] = None   # legacy single KID (still accepted)
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
    hls_list_size:    int = Field(30, ge=5, le=120)
    buffer_seconds:   int = Field(20, ge=5, le=120)
    output_rtmp:      Optional[str] = None
    output_udp:       Optional[str] = None
    enabled:          bool = True

class StreamCreate(StreamBase):
    id: str = Field(..., min_length=2, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')

class StreamUpdate(StreamBase):
    name:    Optional[str] = None
    url:     Optional[str] = None
    enabled: Optional[bool] = None

class StreamOut(StreamBase):
    id:         str
    created_at: datetime
    updated_at: datetime
    status:     str = "stopped"   # injected at runtime from HLS manager
    class Config: from_attributes = True
