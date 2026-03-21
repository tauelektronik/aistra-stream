"""
aistra-stream — FastAPI main application
Streaming panel with MySQL auth, per-stream HLS delivery.
"""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.crud import create_user, list_streams, list_users, load_settings_db
from backend.database import get_db, init_db
from backend.hls_manager import hls_manager
from backend.models import ConnectionLog, LoginAttemptRL
from backend.state import (
    BACKUPS_BASE,
    LOGOS_BASE,
    LOG_RETENTION_DAYS,
    REC_RETENTION_DAYS,
)

# Import routers
from backend.routers import auth as auth_router
from backend.routers import users as users_router
from backend.routers import streams as streams_router
from backend.routers import categories as categories_router
from backend.routers import backup as backup_router
from backend.routers import recordings as recordings_router
from backend.routers import monitoring as monitoring_router
from backend.routers import settings as settings_router
from backend.routers.settings import _migrate_settings_from_file
from backend.routers.monitoring import _server_stats_updater

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"

# ── Background tasks ───────────────────────────────────────────────────────────

_LOGIN_WINDOW = int(os.getenv("LOGIN_RATE_WINDOW", "60"))


async def _rate_limit_cleanup():
    """Background task: delete expired login_attempts_rl rows every 10 minutes."""
    import sqlalchemy as _sa
    from backend.database import AsyncSessionLocal
    while True:
        await asyncio.sleep(600)
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=_LOGIN_WINDOW * 2)
            async with AsyncSessionLocal() as db:
                await db.execute(
                    _sa.delete(LoginAttemptRL).where(LoginAttemptRL.attempted_at < cutoff)
                )
                await db.commit()
        except Exception as exc:
            logger.debug("Rate-limit cleanup failed: %s", exc)


async def _recordings_cleanup():
    """Background task: delete MP4 recordings older than RECORDING_RETENTION_DAYS every 24h.
    Disabled when RECORDING_RETENTION_DAYS=0 (default).
    """
    if REC_RETENTION_DAYS <= 0:
        return
    from backend.hls_manager import RECORDINGS_BASE
    while True:
        await asyncio.sleep(86400)
        try:
            cutoff = time.time() - REC_RETENTION_DAYS * 86400
            deleted = 0
            for fname in os.listdir(RECORDINGS_BASE):
                if not fname.endswith(".mp4"):
                    continue
                fpath = os.path.join(RECORDINGS_BASE, fname)
                try:
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
                        deleted += 1
                except OSError:
                    pass
            if deleted:
                logger.info("Recordings: deleted %d files older than %d days", deleted, REC_RETENTION_DAYS)
        except Exception as exc:
            logger.warning("Recordings cleanup failed: %s", exc)


async def _connection_logs_cleanup():
    """Background task: delete connection_logs older than LOG_RETENTION_DAYS every 24h."""
    import sqlalchemy as _sa
    from backend.database import AsyncSessionLocal
    while True:
        await asyncio.sleep(86400)   # run once per day
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    _sa.delete(ConnectionLog).where(ConnectionLog.created_at < cutoff)
                )
                await db.commit()
            deleted = result.rowcount
            if deleted:
                logger.info("ConnectionLog: purged %d entries older than %d days", deleted, LOG_RETENTION_DAYS)
        except Exception as exc:
            logger.warning("ConnectionLog cleanup failed: %s", exc)


async def _backup_scheduler():
    """Background task: create auto-backups on configurable interval."""
    from backend.database import AsyncSessionLocal
    from backend.routers.backup import _create_full_backup, _apply_backup_retention
    while True:
        try:
            await asyncio.sleep(3600)   # check every hour
            async with AsyncSessionLocal() as db:
                s = await load_settings_db(db)
            enabled   = bool(s.get("backup_auto_enabled", False))
            interval  = int(s.get("backup_interval_hours", 24))
            retention = int(s.get("backup_retention", 7))
            if not enabled:
                continue
            # Check if enough time has passed since last auto-backup
            auto_files = sorted(
                Path(BACKUPS_BASE).glob("auto_*.zip"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if auto_files:
                age_hours = (datetime.now(timezone.utc).timestamp() - auto_files[0].stat().st_mtime) / 3600
                if age_hours < interval:
                    continue
            ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = os.path.join(BACKUPS_BASE, f"auto_{ts}.zip")
            async with AsyncSessionLocal() as db:
                size = await _create_full_backup(db, path)
            logger.info("Auto-backup created: %s (%d KB)", path, size // 1024)
            await _apply_backup_retention(retention)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Backup scheduler error: %s", exc)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(LOGOS_BASE,   exist_ok=True)
    os.makedirs(BACKUPS_BASE, exist_ok=True)
    await init_db()
    hls_manager.startup_cleanup()
    hls_manager.start_background_cleanup()
    _stats_task    = asyncio.create_task(_server_stats_updater())
    _rl_task       = asyncio.create_task(_rate_limit_cleanup())
    _connlog_task  = asyncio.create_task(_connection_logs_cleanup())
    _rec_task      = asyncio.create_task(_recordings_cleanup())
    _backup_task   = asyncio.create_task(_backup_scheduler())
    await _ensure_default_admin()
    # Apply persisted settings from DB
    from backend.database import AsyncSessionLocal
    async with AsyncSessionLocal() as _db:
        await _migrate_settings_from_file(_db)
        _s = await load_settings_db(_db)
    if _s.get("telegram_bot_token"):
        hls_manager.TELEGRAM_BOT_TOKEN = _s["telegram_bot_token"]
    if _s.get("telegram_chat_id"):
        hls_manager.TELEGRAM_CHAT_ID = _s["telegram_chat_id"]
    logger.info("aistra-stream started")
    asyncio.create_task(_autostart_enabled_streams())
    yield
    _stats_task.cancel()
    _rl_task.cancel()
    _connlog_task.cancel()
    _rec_task.cancel()
    _backup_task.cancel()
    await asyncio.gather(_stats_task, _rl_task, _connlog_task, _rec_task, _backup_task, return_exceptions=True)
    await hls_manager.shutdown()
    logger.info("aistra-stream stopped")


async def _autostart_enabled_streams():
    """On startup, auto-start all streams that have enabled=True."""
    await asyncio.sleep(3)   # give DB + cleanup a moment to settle
    from backend.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            streams = await list_streams(db)
        enabled = [s for s in streams if getattr(s, "enabled", False)]
        if not enabled:
            return
        logger.info("Autostart: starting %d enabled stream(s)…", len(enabled))
        for s in enabled:
            try:
                hls_manager.enable_autoplay(s.id)
                hls_dir, err = await hls_manager.get_hls_dir(s)
                if err:
                    logger.warning("Autostart %s: %s", s.id, err)
                else:
                    logger.info("Autostart %s: OK", s.id)
            except Exception as exc:
                logger.warning("Autostart %s failed: %s", s.id, exc)
    except Exception as exc:
        logger.error("_autostart_enabled_streams failed: %s", exc)


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
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip() and o.strip() != "*"] or [
    "http://localhost:5173",   # Vite dev server
    "http://localhost:8001",   # Local production
]
if "*" in (os.getenv("ALLOWED_ORIGINS", "") or ""):
    logger.warning("ALLOWED_ORIGINS contained '*' — wildcard CORS rejected for security")

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


# ── Include routers ───────────────────────────────────────────────────────────

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(streams_router.router)
app.include_router(categories_router.router)
app.include_router(backup_router.router)
app.include_router(recordings_router.router)
app.include_router(monitoring_router.router)
app.include_router(settings_router.router)


# ── Serve React SPA ───────────────────────────────────────────────────────────

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return Response("Frontend não encontrado. Execute: cd frontend && npm run build", status_code=503)
