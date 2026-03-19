"""
aistra-stream — FastAPI main application
Streaming panel with MySQL auth, per-stream HLS delivery.
"""
import asyncio
import logging
import os
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import (
    create_access_token, get_current_user, require_admin, require_operator,
    verify_password,
)
from backend.crud import (
    create_stream, create_user, delete_stream, delete_user, get_stream,
    get_user_by_username, list_streams, list_users, update_stream, update_user,
)
from backend.database import get_db, init_db
from backend.hls_manager import hls_manager, HLS_BASE
from backend.schemas import (
    LoginRequest, StreamCreate, StreamOut, StreamUpdate,
    TokenResponse, UserCreate, UserOut, UserUpdate,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
audit = logging.getLogger("aistra.audit")   # separate audit trail

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


# ── Simple in-memory rate limiter for login ───────────────────────────────────

_login_attempts: dict = defaultdict(list)   # ip → [timestamps]
LOGIN_LIMIT   = int(os.getenv("LOGIN_RATE_LIMIT", "10"))   # attempts
LOGIN_WINDOW  = int(os.getenv("LOGIN_RATE_WINDOW", "60"))  # seconds

def _check_rate_limit(ip: str):
    now = time.monotonic()
    attempts = [t for t in _login_attempts[ip] if now - t < LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    if len(attempts) >= LOGIN_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Muitas tentativas. Tente novamente em {LOGIN_WINDOW}s.",
        )
    _login_attempts[ip].append(now)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    hls_manager.startup_cleanup()
    hls_manager.start_background_cleanup()
    await _ensure_default_admin()
    # Apply persisted settings
    _s = _load_settings()
    if _s.get("telegram_bot_token"):
        hls_manager.TELEGRAM_BOT_TOKEN = _s["telegram_bot_token"]
    if _s.get("telegram_chat_id"):
        hls_manager.TELEGRAM_CHAT_ID = _s["telegram_chat_id"]
    logger.info("aistra-stream started")
    yield


async def _ensure_default_admin():
    """Create default admin user if no users exist."""
    from backend.database import AsyncSessionLocal
    from backend.schemas import UserCreate as UC
    async with AsyncSessionLocal() as db:
        users = await list_users(db)
        if not users:
            await create_user(db, UC(username="admin", password="admin123", role="admin"))
            logger.warning("=" * 60)
            logger.warning("CONTA PADRÃO CRIADA: admin / admin123")
            logger.warning("TROQUE A SENHA IMEDIATAMENTE!")
            logger.warning("=" * 60)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="aistra-stream",
    version="1.0.0",
    lifespan=lifespan,
    # Hide docs in production (optional — set AISTRA_SHOW_DOCS=1 to enable)
    docs_url="/docs" if os.getenv("AISTRA_SHOW_DOCS") else None,
    redoc_url=None,
    openapi_url="/openapi.json" if os.getenv("AISTRA_SHOW_DOCS") else None,
)

# CORS — configurable via env (comma-separated list)
# Default: allow same-origin + localhost dev server
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()] or [
    "http://localhost:5173",   # Vite dev server
    "http://localhost:8001",   # Local production
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
)


# ── Security headers middleware ───────────────────────────────────────────────

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Rate limit by IP
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    _check_rate_limit(client_ip)

    user = await get_user_by_username(db, body.username)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
    if not user.active:
        raise HTTPException(status_code=403, detail="Usuário desativado")
    token = create_access_token({"sub": user.username, "role": user.role})
    return TokenResponse(access_token=token)


@app.get("/auth/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return user


# ── User management (admin only) ─────────────────────────────────────────────

@app.get("/api/users", response_model=list[UserOut])
async def api_list_users(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    return await list_users(db)


@app.post("/api/users", response_model=UserOut, status_code=201)
async def api_create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_admin),
):
    existing = await get_user_by_username(db, body.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username já existe")
    user = await create_user(db, body)
    audit.info("USER_CREATE actor=%s target=%s role=%s ip=%s",
               actor.username, body.username, body.role,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    return user


@app.put("/api/users/{user_id}", response_model=UserOut)
async def api_update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    user = await update_user(db, user_id, body)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return user


@app.delete("/api/users/{user_id}", status_code=204)
async def api_delete_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_admin),
):
    if not await delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    audit.info("USER_DELETE actor=%s target_id=%s ip=%s",
               actor.username, user_id,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))


# ── Stream CRUD ───────────────────────────────────────────────────────────────

@app.get("/api/streams", response_model=list[StreamOut])
async def api_list_streams(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    streams = await list_streams(db)
    result  = []
    for s in streams:
        out        = StreamOut.model_validate(s)
        out.status = await hls_manager.get_status(s.id)
        result.append(out)
    return result


@app.get("/api/streams/export.m3u")
async def export_m3u(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Export all enabled streams as an M3U playlist (HLS URLs)."""
    streams = await list_streams(db)
    base_url = str(request.base_url).rstrip("/")
    lines = ["#EXTM3U"]
    for s in streams:
        if not s.enabled:
            continue
        group = s.category or "Sem Categoria"
        lines.append(f'#EXTINF:-1 tvg-id="{s.id}" tvg-name="{s.name}" group-title="{group}",{s.name}')
        lines.append(f"{base_url}/stream/{s.id}/hls/stream.m3u8")
    content = "\r\n".join(lines) + "\r\n"
    return Response(content, media_type="application/x-mpegurl",
                    headers={"Content-Disposition": "attachment; filename=\"aistra.m3u\""})


@app.post("/api/streams", response_model=StreamOut, status_code=201)
async def api_create_stream(
    body: StreamCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
):
    existing = await get_stream(db, body.id)
    if existing:
        raise HTTPException(status_code=400, detail="ID de stream já existe")
    s   = await create_stream(db, body)
    out = StreamOut.model_validate(s)
    out.status = "stopped"
    audit.info("STREAM_CREATE actor=%s id=%s name=%s ip=%s",
               actor.username, body.id, body.name,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    return out


@app.get("/api/streams/{stream_id}", response_model=StreamOut)
async def api_get_stream(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    s = await get_stream(db, stream_id)
    if not s:
        raise HTTPException(status_code=404, detail="Stream não encontrado")
    out        = StreamOut.model_validate(s)
    out.status = await hls_manager.get_status(s.id)
    return out


@app.put("/api/streams/{stream_id}", response_model=StreamOut)
async def api_update_stream(
    stream_id: str,
    body: StreamUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    s = await update_stream(db, stream_id, body)
    if not s:
        raise HTTPException(status_code=404, detail="Stream não encontrado")
    await hls_manager.stop_session(stream_id)
    out        = StreamOut.model_validate(s)
    out.status = "stopped"
    return out


@app.delete("/api/streams/{stream_id}", status_code=204)
async def api_delete_stream(
    stream_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
):
    await hls_manager.stop_session(stream_id)
    # Cascade: delete thumbnail
    from backend.hls_manager import THUMBNAILS_BASE
    sid = re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)
    thumb = os.path.join(THUMBNAILS_BASE, f"{sid}.jpg")
    if os.path.exists(thumb):
        try:
            os.unlink(thumb)
        except OSError:
            pass
    if not await delete_stream(db, stream_id):
        raise HTTPException(status_code=404, detail="Stream não encontrado")
    audit.info("STREAM_DELETE actor=%s id=%s ip=%s",
               actor.username, stream_id,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))


@app.post("/api/streams/{stream_id}/stop", status_code=200)
async def api_stop_stream(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    await hls_manager.stop_session(stream_id)
    return {"status": "stopped"}


@app.get("/api/streams/{stream_id}/log")
async def api_stream_log(
    stream_id: str,
    lines: int = 100,
    _=Depends(require_operator),
):
    """Return last N lines of the ffmpeg log for a stream (max 500)."""
    import re as _re
    lines = max(1, min(lines, 500))   # cap at 500 lines
    safe = _re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)
    log_path = f"/tmp/ffmpeg_{safe}.log"
    if not os.path.exists(log_path):
        return {"log": ""}
    with open(log_path, "rb") as f:
        content = f.read().decode("utf-8", errors="replace")
    tail = "\n".join(content.splitlines()[-lines:])
    return {"log": tail}


# ── App settings ──────────────────────────────────────────────────────────────

_SETTINGS_FILE = os.getenv("AISTRA_SETTINGS_FILE", "/tmp/aistra_settings.json")

def _load_settings() -> dict:
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE) as f:
                import json
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_settings(data: dict):
    import json
    tmp = _SETTINGS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _SETTINGS_FILE)


@app.get("/api/settings")
async def api_get_settings(_=Depends(require_admin)):
    """Return current app settings (admin only)."""
    s = _load_settings()
    # Never expose secrets — mask token
    masked = dict(s)
    if masked.get("telegram_bot_token"):
        t = masked["telegram_bot_token"]
        masked["telegram_bot_token"] = t[:8] + "***" if len(t) > 8 else "***"
    return masked


@app.put("/api/settings")
async def api_save_settings(body: dict, _=Depends(require_admin)):
    """Save app settings (admin only)."""
    current = _load_settings()
    # Don't overwrite token if masked placeholder was sent
    if body.get("telegram_bot_token", "").endswith("***"):
        body["telegram_bot_token"] = current.get("telegram_bot_token", "")
    current.update(body)
    _save_settings(current)
    # Push Telegram config into hls_manager at runtime
    if "telegram_bot_token" in current:
        hls_manager.TELEGRAM_BOT_TOKEN = current.get("telegram_bot_token", "")
    if "telegram_chat_id" in current:
        hls_manager.TELEGRAM_CHAT_ID = current.get("telegram_chat_id", "")
    return {"ok": True}


# ── Backup / Restore ──────────────────────────────────────────────────────────

@app.get("/api/settings/backup")
async def api_backup(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Export all streams + app settings as a JSON backup (admin only)."""
    import json as _json
    from datetime import timezone

    streams = await list_streams(db)
    streams_data = []
    for s in streams:
        row = {}
        for col in s.__table__.columns:
            v = getattr(s, col.name)
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            row[col.name] = v
        streams_data.append(row)

    settings = _load_settings()
    # Mask Telegram token in backup to avoid leaking secrets — user must re-enter
    masked_settings = dict(settings)
    if masked_settings.get("telegram_bot_token"):
        masked_settings["telegram_bot_token"] = ""

    payload = {
        "version": 1,
        "exported_at": __import__("datetime").datetime.now(timezone.utc).isoformat(),
        "streams": streams_data,
        "settings": masked_settings,
    }
    content = _json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=\"aistra-backup.json\""},
    )


@app.post("/api/settings/restore", status_code=200)
async def api_restore(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_admin),
):
    """Import streams + settings from a previously exported JSON backup (admin only)."""
    import json as _json

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    if body.get("version") != 1:
        raise HTTPException(status_code=400, detail="Formato de backup não reconhecido (version != 1)")

    created = updated = skipped = 0

    for row in body.get("streams", []):
        sid = row.get("id")
        if not sid:
            skipped += 1
            continue
        try:
            # Strip non-model fields and datetimes — let ORM handle timestamps
            for ts_field in ("created_at", "updated_at"):
                row.pop(ts_field, None)
            existing = await get_stream(db, sid)
            if existing:
                from backend.schemas import StreamUpdate as SU
                data = SU(**{k: v for k, v in row.items() if k != "id"})
                await update_stream(db, sid, data)
                updated += 1
            else:
                from backend.schemas import StreamCreate as SC
                data = SC(**row)
                await create_stream(db, data)
                created += 1
        except Exception as exc:
            logger.warning("Restore: skipped stream %s: %s", sid, exc)
            skipped += 1

    if body.get("settings"):
        current = _load_settings()
        # Don't overwrite token with empty string from backup — keep existing
        imported = dict(body["settings"])
        if not imported.get("telegram_bot_token"):
            imported.pop("telegram_bot_token", None)
        current.update(imported)
        _save_settings(current)

    audit.info("RESTORE actor=%s created=%d updated=%d skipped=%d ip=%s",
               actor.username, created, updated, skipped,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))

    return {"created": created, "updated": updated, "skipped": skipped}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health(db: AsyncSession = Depends(get_db)):
    streams = await list_streams(db)
    running = sum(1 for s in streams if hls_manager._sessions.get(s.id) is not None)
    return {"status": "ok", "streams_total": len(streams), "streams_running": running}


# ── HLS delivery ──────────────────────────────────────────────────────────────

_VALID_QUALITY_RE = re.compile(r'^(360p|480p|720p|1080p)$')
_VALID_SEGMENT_RE = re.compile(r'^seg\d{1,7}\.ts$')


@app.get("/stream/{stream_id}/hls/stream.m3u8")
async def stream_hls_master_playlist(
    stream_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Master playlist — triggers ffmpeg HLS session. Requires DB lookup."""
    stream = await get_stream(db, stream_id)
    if not stream or not stream.enabled:
        return Response(content="Stream não encontrado", status_code=404)
    hls_dir, err = await hls_manager.get_hls_dir(stream)
    if err:
        return Response(content=f"Erro ao iniciar stream: {err}", status_code=503)
    playlist = os.path.join(hls_dir, "stream.m3u8")
    for _ in range(30):
        if os.path.exists(playlist) and os.path.getsize(playlist) > 0:
            break
        await asyncio.sleep(1.0)
    if not os.path.exists(playlist) or os.path.getsize(playlist) == 0:
        return Response(content="Playlist não disponível ainda", status_code=503)
    hls_manager.touch(stream_id)
    return FileResponse(playlist, media_type="application/vnd.apple.mpegurl",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/stream/{stream_id}/hls/{segment:path}")
async def stream_hls_files(
    stream_id: str,
    segment: str,
    request: Request,
):
    """HLS segments and quality sub-playlists — no DB lookup for high concurrency."""
    if ".." in segment:
        return Response(content="Não encontrado", status_code=404)
    parts = segment.split("/")
    if len(parts) > 2:
        return Response(content="Não encontrado", status_code=404)

    sub_quality = None
    filename = parts[-1]
    if len(parts) == 2:
        sub_quality = parts[0]
        if not _VALID_QUALITY_RE.match(sub_quality):
            return Response(content="Não encontrado", status_code=404)

    # ── Quality variant playlists (e.g. 720p/stream.m3u8) ────────────────────
    if filename == "stream.m3u8":
        if not sub_quality:
            return Response(content="Não encontrado", status_code=404)
        q_playlist = os.path.join(HLS_BASE, stream_id, sub_quality, "stream.m3u8")
        if not os.path.exists(q_playlist) or os.path.getsize(q_playlist) == 0:
            return Response(content="Playlist de qualidade não disponível", status_code=404)
        hls_manager.touch(stream_id)
        return FileResponse(q_playlist, media_type="application/vnd.apple.mpegurl",
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    # ── Segments ──────────────────────────────────────────────────────────────
    if not _VALID_SEGMENT_RE.match(filename):
        return Response(content="Não encontrado", status_code=404)
    base = os.path.join(HLS_BASE, stream_id)
    filepath = os.path.join(base, sub_quality, filename) if sub_quality else os.path.join(base, filename)
    if not os.path.exists(filepath):
        return Response(content="Segmento não encontrado", status_code=404)
    hls_manager.touch(stream_id)
    try:
        return FileResponse(filepath, media_type="video/mp2t", headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return Response(content="Segmento não encontrado", status_code=404)


# ── Stats, live log, recording, thumbnail ────────────────────────────────────

@app.get("/api/streams/{stream_id}/stats")
async def api_stream_stats(
    stream_id: str,
    _=Depends(get_current_user),
):
    """Return real-time ffmpeg stats (bitrate, fps, uptime)."""
    return await hls_manager.get_stats(stream_id)


@app.get("/api/streams/{stream_id}/log/live")
async def api_stream_log_live(
    stream_id: str,
    _=Depends(require_operator),
):
    """Server-Sent Events: tail the ffmpeg log file in real-time."""
    safe     = re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)
    log_path = f"/tmp/ffmpeg_{safe}.log"

    async def _generator():
        pos = 0
        if os.path.exists(log_path):
            with open(log_path, "rb") as f:
                raw  = f.read()
                pos  = len(raw)
                text = raw.decode("utf-8", errors="replace")
            for line in text.splitlines()[-40:]:
                yield f"data: {line}\n\n"
        yield "data: --- live ---\n\n"
        while True:
            await asyncio.sleep(0.5)
            if not os.path.exists(log_path):
                continue
            with open(log_path, "rb") as f:
                f.seek(pos)
                chunk = f.read()
                pos   = f.tell()
            if chunk:
                for line in chunk.decode("utf-8", errors="replace").splitlines():
                    yield f"data: {line}\n\n"

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/streams/{stream_id}/record")
async def api_start_recording(
    stream_id: str,
    _=Depends(require_operator),
):
    path, err = await hls_manager.start_recording(stream_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"recording": True, "filename": os.path.basename(path)}


@app.delete("/api/streams/{stream_id}/record", status_code=200)
async def api_stop_recording(
    stream_id: str,
    _=Depends(require_operator),
):
    path = await hls_manager.stop_recording(stream_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Gravação não iniciada")
    return {"recording": False, "filename": os.path.basename(path)}


@app.get("/api/streams/{stream_id}/record/status")
async def api_recording_status(
    stream_id: str,
    _=Depends(get_current_user),
):
    status = hls_manager.get_recording_status(stream_id)
    return status or {"recording": False}


@app.get("/api/recordings")
async def api_list_recordings(
    stream_id: str = "",
    _=Depends(require_operator),
):
    return hls_manager.list_recordings(stream_id or None)


@app.get("/api/recordings/{filename}")
async def api_download_recording(
    filename: str,
    _=Depends(require_operator),
):
    if re.search(r"[^a-zA-Z0-9_\-.]", filename) or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome inválido")
    from backend.hls_manager import RECORDINGS_BASE
    path = os.path.join(RECORDINGS_BASE, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(path, media_type="video/mp4",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/streams/{stream_id}/thumbnail")
async def api_stream_thumbnail(
    stream_id: str,
    _=Depends(get_current_user),
):
    """Capture and return the latest thumbnail (JPEG) for a stream."""
    from backend.hls_manager import THUMBNAILS_BASE
    sid        = re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)
    thumb_path = os.path.join(THUMBNAILS_BASE, f"{sid}.jpg")

    if os.path.exists(thumb_path) and time.time() - os.path.getmtime(thumb_path) < 10:
        return FileResponse(thumb_path, media_type="image/jpeg",
                            headers={"Cache-Control": "no-cache"})

    path = await hls_manager.capture_thumbnail(stream_id)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Thumbnail não disponível")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})


# ── Stream player config ──────────────────────────────────────────────────────

@app.get("/api/streams/{stream_id}/player-config")
async def player_config(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    s = await get_stream(db, stream_id)
    if not s:
        raise HTTPException(status_code=404)
    buf        = s.buffer_seconds
    seg        = s.hls_time
    sync_count = max(2, round(buf / seg))
    return {
        "hlsUrl":                      f"/stream/{stream_id}/hls/stream.m3u8",
        "liveSyncDurationCount":       sync_count,
        "liveMaxLatencyDurationCount": sync_count * 3,
        "maxBufferLength":             max(60, buf * 2),
        "maxMaxBufferLength":          max(120, buf * 4),
        "lowLatencyMode":              False,
        "backBufferLength":            0,
        "startFragPrefetch":           True,
    }


# ── Serve React SPA ───────────────────────────────────────────────────────────

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return Response("Frontend não encontrado. Execute: cd frontend && npm run build", status_code=503)
