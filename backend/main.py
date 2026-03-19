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

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
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
    list_categories, get_category, get_category_by_name,
    create_category, update_category, delete_category, assign_streams_to_category,
)
from backend.database import get_db, init_db
from backend.hls_manager import hls_manager, HLS_BASE
from backend.schemas import (
    LoginRequest, StreamCreate, StreamOut, StreamUpdate,
    TokenResponse, UserCreate, UserOut, UserUpdate,
    CategoryCreate, CategoryOut, CategoryUpdate,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
audit = logging.getLogger("aistra.audit")   # separate audit trail

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
LOGOS_BASE    = os.getenv("LOGOS_BASE", "/tmp/aistra_logos")


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


async def _login_attempts_cleanup():
    """Background task: purge expired IP entries every 5 minutes.
    Prevents unbounded growth when many different IPs probe the login endpoint.
    """
    while True:
        await asyncio.sleep(300)
        now   = time.monotonic()
        stale = [ip for ip, ts in list(_login_attempts.items())
                 if not any(now - t < LOGIN_WINDOW for t in ts)]
        for ip in stale:
            _login_attempts.pop(ip, None)
        if stale:
            logger.debug("Rate limiter: purged %d stale IP entries", len(stale))


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(LOGOS_BASE, exist_ok=True)
    await init_db()
    hls_manager.startup_cleanup()
    hls_manager.start_background_cleanup()
    asyncio.create_task(_server_stats_updater())
    asyncio.create_task(_login_attempts_cleanup())
    await _ensure_default_admin()
    # Apply persisted settings
    _s = _load_settings()
    if _s.get("telegram_bot_token"):
        hls_manager.TELEGRAM_BOT_TOKEN = _s["telegram_bot_token"]
    if _s.get("telegram_chat_id"):
        hls_manager.TELEGRAM_CHAT_ID = _s["telegram_chat_id"]
    logger.info("aistra-stream started")
    yield
    await hls_manager.shutdown()
    logger.info("aistra-stream stopped")


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
    if not user or not verify_password(body.password, user.password_hash) or not user.active:
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
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
    try:
        deleted = await delete_user(db, user_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not deleted:
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
    out.status = await hls_manager.get_status(s.id)  # always "stopped" post-kill, but consistent
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

# Default: PROJECT_DIR/data/settings.json (persistent across reboots).
# Override with AISTRA_SETTINGS_FILE env var if needed.
_PROJECT_ROOT  = Path(__file__).parent.parent
_SETTINGS_FILE = os.getenv(
    "AISTRA_SETTINGS_FILE",
    str(_PROJECT_ROOT / "data" / "settings.json"),
)

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
    os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
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


# ── Categories ────────────────────────────────────────────────────────────────

@app.get("/api/categories", response_model=list[CategoryOut])
async def api_list_categories(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    return await list_categories(db)


@app.post("/api/categories", response_model=CategoryOut, status_code=201)
async def api_create_category(
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    existing = await get_category_by_name(db, body.name)
    if existing:
        raise HTTPException(status_code=400, detail="Categoria já existe com esse nome")
    return await create_category(db, body)


@app.put("/api/categories/{cat_id}", response_model=CategoryOut)
async def api_update_category(
    cat_id: int,
    body: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    # If renaming, update category + all streams atomically in one transaction
    from sqlalchemy import update as sa_update
    from backend.models import Stream as StreamModel
    cat = await get_category(db, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    old_name = cat.name
    if body.name is not None:
        cat.name = body.name
    # Rename streams in the same transaction (before commit)
    if body.name and body.name != old_name:
        await db.execute(
            sa_update(StreamModel)
            .where(StreamModel.category == old_name)
            .values(category=body.name)
        )
    await db.commit()
    await db.refresh(cat)
    return cat


@app.delete("/api/categories/{cat_id}", status_code=204)
async def api_delete_category(
    cat_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    if not await delete_category(db, cat_id):
        raise HTTPException(status_code=404, detail="Categoria não encontrada")


@app.post("/api/categories/{cat_id}/logo")
async def api_upload_logo(
    cat_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    """Upload logo image for a category (PNG/JPG/SVG/WEBP, max 2MB)."""
    cat = await get_category(db, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    # Validate type (header) + size + magic bytes (prevents MIME spoofing)
    allowed = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
    content_type = file.content_type or ""
    if content_type not in allowed:
        raise HTTPException(status_code=400, detail="Tipo inválido. Use PNG, JPG, WEBP ou SVG.")

    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo muito grande (máx 2MB)")

    # Magic byte validation — rejects files with a spoofed Content-Type header
    def _valid_image_magic(b: bytes) -> bool:
        if b[:8] == b"\x89PNG\r\n\x1a\n":                    return True  # PNG
        if b[:3] == b"\xff\xd8\xff":                          return True  # JPEG
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":          return True  # WEBP
        if b[:6] in (b"GIF87a", b"GIF89a"):                  return True  # GIF
        head = b[:512].lstrip()  # SVG is text — tolerate BOM / leading whitespace
        if any(head.startswith(p) for p in (b"<svg", b"<?xml", b"<!DOCTYPE svg")): return True
        return False

    if not _valid_image_magic(data):
        raise HTTPException(status_code=400, detail="Arquivo não reconhecido como imagem válida.")

    ext = content_type.split("/")[-1].replace("svg+xml", "svg")
    filename = f"cat_{cat_id}.{ext}"
    # Remove old logo if different extension
    for old in [f for f in os.listdir(LOGOS_BASE) if f.startswith(f"cat_{cat_id}.")]:
        try: os.unlink(os.path.join(LOGOS_BASE, old))
        except OSError: pass

    path = os.path.join(LOGOS_BASE, filename)
    with open(path, "wb") as f:
        f.write(data)

    cat.logo_path = filename
    await db.commit()
    return {"logo_path": filename}


@app.delete("/api/categories/{cat_id}/logo", status_code=204)
async def api_delete_logo(
    cat_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    cat = await get_category(db, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    if cat.logo_path:
        try: os.unlink(os.path.join(LOGOS_BASE, cat.logo_path))
        except OSError: pass
        cat.logo_path = None
        await db.commit()


@app.get("/api/categories/{cat_id}/logo")
async def api_get_logo(
    cat_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    cat = await get_category(db, cat_id)
    if not cat or not cat.logo_path:
        raise HTTPException(status_code=404, detail="Logo não encontrado")
    path = os.path.join(LOGOS_BASE, cat.logo_path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    media = "image/svg+xml" if cat.logo_path.endswith(".svg") else "image/jpeg"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "max-age=3600"})


@app.post("/api/categories/{cat_id}/streams")
async def api_assign_streams(
    cat_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    """Assign list of stream IDs to this category (replaces current assignment)."""
    cat = await get_category(db, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    stream_ids = body.get("stream_ids", [])
    if not isinstance(stream_ids, list):
        raise HTTPException(status_code=400, detail="stream_ids deve ser uma lista")
    count = await assign_streams_to_category(db, cat.name, stream_ids)
    return {"assigned": count, "category": cat.name}


# ── Server stats — background cache (updated every 5 s) ──────────────────────
# Avoids holding a 0.5 s sleep inside the HTTP request handler, which would
# block the connection and degrade performance under concurrent polling.

_server_stats_cache: dict = {}


def _query_nvidia_smi() -> dict | None:
    """Run nvidia-smi synchronously (called via executor — never on event loop)."""
    import subprocess as _sp
    try:
        r = _sp.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            if len(parts) >= 5:
                return {
                    "name":            parts[0],
                    "utilization_pct": int(parts[1]),
                    "memory_used_mb":  int(parts[2]),
                    "memory_total_mb": int(parts[3]),
                    "temperature_c":   int(parts[4]),
                }
    except Exception:
        pass
    return None


async def _server_stats_updater():
    """Background task: refresh server stats every 5 seconds."""
    import psutil

    psutil.cpu_percent(interval=None)   # prime the CPU counter

    _net_prev_bytes = psutil.net_io_counters()
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(5)
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            mem     = psutil.virtual_memory()
            disk    = psutil.disk_usage("/")

            net_cur         = psutil.net_io_counters()
            net_up_bps      = max(0, (net_cur.bytes_sent - _net_prev_bytes.bytes_sent) // 5)
            net_down_bps    = max(0, (net_cur.bytes_recv - _net_prev_bytes.bytes_recv) // 5)
            _net_prev_bytes = net_cur

            # nvidia-smi is blocking — run in thread pool to avoid stalling event loop
            gpu = await loop.run_in_executor(None, _query_nvidia_smi)

            _server_stats_cache.update({
                "cpu_pct":       round(cpu_pct, 1),
                "mem_used_gb":   round(mem.used   / 1024 ** 3, 1),
                "mem_total_gb":  round(mem.total  / 1024 ** 3, 1),
                "mem_pct":       round(mem.percent, 1),
                "disk_used_gb":  round(disk.used  / 1024 ** 3, 1),
                "disk_total_gb": round(disk.total / 1024 ** 3, 1),
                "disk_pct":      round(disk.percent, 1),
                "net_up_mbps":   round(net_up_bps   / 1024 ** 2, 2),
                "net_down_mbps": round(net_down_bps / 1024 ** 2, 2),
                "gpu":           gpu,
            })
        except Exception as _e:
            logger.debug("server_stats_updater error: %s", _e)


@app.get("/api/server/stats")
async def server_stats(_=Depends(get_current_user)):
    """Return cached server stats (updated every 5 s by background task)."""
    if not _server_stats_cache:
        return {"error": "Stats ainda sendo coletadas, tente novamente em 5s"}
    return _server_stats_cache


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health(db: AsyncSession = Depends(get_db)):
    streams = await list_streams(db)
    running = 0
    for s in streams:
        if await hls_manager.get_status(s.id) == "running":
            running += 1
    return {"status": "ok", "streams_total": len(streams), "streams_running": running}


# ── HLS delivery ──────────────────────────────────────────────────────────────

_VALID_QUALITY_RE  = re.compile(r'^(360p|480p|720p|1080p)$')
_VALID_SEGMENT_RE  = re.compile(r'^seg\d{1,7}\.ts$')
_VALID_STREAM_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,50}$')


@app.get("/stream/{stream_id}/hls/stream.m3u8")
async def stream_hls_master_playlist(
    stream_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Master playlist — triggers ffmpeg HLS session. Requires DB lookup."""
    if not _VALID_STREAM_ID_RE.match(stream_id):
        return Response(content="Stream não encontrado", status_code=404)
    stream = await get_stream(db, stream_id)
    if not stream or not stream.enabled:
        return Response(content="Stream não encontrado", status_code=404)
    hls_dir, err = await hls_manager.get_hls_dir(stream)
    if err:
        return Response(content=f"Erro ao iniciar stream: {err}", status_code=503)
    playlist = os.path.join(hls_dir, "stream.m3u8")
    # Timeout: at least 60 s, or 2× the stream's buffer_seconds (CENC/transcode can be slow)
    wait_secs = max(60, getattr(stream, "buffer_seconds", 20) * 2)
    for _ in range(wait_secs):
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
    if not _VALID_STREAM_ID_RE.match(stream_id):
        return Response(content="Não encontrado", status_code=404)
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
    # Resolve symlinks and verify the file stays inside HLS_BASE
    real_base = os.path.realpath(HLS_BASE)
    real_fp   = os.path.realpath(filepath)
    if not real_fp.startswith(real_base + os.sep):
        return Response(content="Não encontrado", status_code=404)
    if not os.path.exists(real_fp):
        return Response(content="Segmento não encontrado", status_code=404)
    hls_manager.touch(stream_id)
    try:
        return FileResponse(real_fp, media_type="video/mp2t", headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return Response(content="Segmento não encontrado", status_code=404)


# ── Stats, live log, recording, thumbnail ────────────────────────────────────

@app.get("/api/streams/{stream_id}/stats")
async def api_stream_stats(
    stream_id: str,
    _=Depends(get_current_user),
):
    """Return real-time ffmpeg stats (bitrate, fps, uptime, ban status)."""
    return await hls_manager.get_stats(stream_id)


@app.get("/api/streams/{stream_id}/ban")
async def api_stream_ban_status(
    stream_id: str,
    _=Depends(get_current_user),
):
    """Return ban status for a stream."""
    return hls_manager.get_ban_status(stream_id)


@app.post("/api/streams/{stream_id}/ban/clear", status_code=200)
async def api_stream_ban_clear(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
):
    """Clear ban state and retry stream from scratch."""
    s = await get_stream(db, stream_id)
    if not s:
        raise HTTPException(status_code=404, detail="Stream não encontrado")
    hls_manager.clear_ban(stream_id)
    await hls_manager.stop_session(stream_id)
    audit.info("BAN_CLEAR actor=%s stream=%s", actor.username, stream_id)
    return {"ok": True, "message": "Ban limpo. Stream será reiniciado na próxima requisição."}


@app.get("/api/streams/{stream_id}/log/live")
async def api_stream_log_live(
    stream_id: str,
    request: Request,
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
            if await request.is_disconnected():
                break
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
    path      = os.path.join(RECORDINGS_BASE, filename)
    real_base = os.path.realpath(RECORDINGS_BASE)
    real_path = os.path.realpath(path)
    if not real_path.startswith(real_base + os.sep):
        raise HTTPException(status_code=400, detail="Nome inválido")
    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(real_path, media_type="video/mp4",
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
