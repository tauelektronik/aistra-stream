"""
aistra-stream — FastAPI main application
Streaming panel with MySQL auth, per-stream HLS delivery.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
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
from backend.hls_manager import hls_manager
from backend.schemas import (
    LoginRequest, StreamCreate, StreamOut, StreamUpdate,
    TokenResponse, UserCreate, UserOut, UserUpdate,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    hls_manager.startup_cleanup()
    hls_manager.start_background_cleanup()
    await _ensure_default_admin()
    logger.info("aistra-stream started")
    yield
    # Shutdown — nothing critical needed


async def _ensure_default_admin():
    """Create default admin user if no users exist."""
    from backend.database import AsyncSessionLocal
    from backend.schemas import UserCreate as UC
    async with AsyncSessionLocal() as db:
        users = await list_users(db)
        if not users:
            await create_user(db, UC(username="admin", password="admin123", role="admin"))
            logger.info("Default admin created: admin / admin123  ← TROQUE A SENHA!")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="aistra-stream", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
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
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    existing = await get_user_by_username(db, body.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username já existe")
    return await create_user(db, body)


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
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    if not await delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="Usuário não encontrado")


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


@app.post("/api/streams", response_model=StreamOut, status_code=201)
async def api_create_stream(
    body: StreamCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    existing = await get_stream(db, body.id)
    if existing:
        raise HTTPException(status_code=400, detail="ID de stream já existe")
    s   = await create_stream(db, body)
    out = StreamOut.model_validate(s)
    out.status = "stopped"
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
    # If stream is running, restart with new config
    await hls_manager.stop_session(stream_id)
    out        = StreamOut.model_validate(s)
    out.status = "stopped"
    return out


@app.delete("/api/streams/{stream_id}", status_code=204)
async def api_delete_stream(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    await hls_manager.stop_session(stream_id)
    if not await delete_stream(db, stream_id):
        raise HTTPException(status_code=404, detail="Stream não encontrado")


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
    """Return last N lines of the ffmpeg log for a stream."""
    import re as _re
    safe = _re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)
    log_path = f"/tmp/ffmpeg_{safe}.log"
    if not os.path.exists(log_path):
        return {"log": ""}
    with open(log_path, "rb") as f:
        content = f.read().decode("utf-8", errors="replace")
    tail = "\n".join(content.splitlines()[-lines:])
    return {"log": tail}


# ── HLS delivery ──────────────────────────────────────────────────────────────

@app.get("/stream/{stream_id}/hls/{segment:path}")
async def stream_hls(
    stream_id: str,
    segment: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HLS playlist + segment delivery.
    No auth on this endpoint so player can load without token in URL.
    The m3u8 playlist request triggers (or reuses) the ffmpeg session.
    """
    stream = await get_stream(db, stream_id)
    if not stream or not stream.enabled:
        return Response(content="Stream não encontrado", status_code=404)

    # Start/reuse HLS session on playlist request
    if segment == "stream.m3u8":
        hls_dir, err = await hls_manager.get_hls_dir(stream)
        if err:
            return Response(content=f"Erro ao iniciar stream: {err}", status_code=503)
        # Wait up to 30s for the playlist to appear
        playlist = os.path.join(hls_dir, "stream.m3u8")
        for _ in range(30):
            if os.path.exists(playlist) and os.path.getsize(playlist) > 0:
                break
            await asyncio.sleep(1.0)
        if not os.path.exists(playlist) or os.path.getsize(playlist) == 0:
            return Response(content="Playlist não disponível ainda", status_code=503)
        hls_manager.touch(stream_id)
        return FileResponse(
            playlist,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    # Segment files
    if not segment.endswith(".ts"):
        return Response(content="Não encontrado", status_code=404)
    hls_dir = os.path.join("/tmp/aistra_stream_hls", stream_id)
    filepath = os.path.join(hls_dir, segment)
    if not os.path.exists(filepath):
        return Response(content="Segmento não encontrado", status_code=404)
    hls_manager.touch(stream_id)
    return FileResponse(filepath, media_type="video/mp2t",
                        headers={"Cache-Control": "no-cache"})


# ── Stream player config (for frontend) ──────────────────────────────────────

@app.get("/api/streams/{stream_id}/player-config")
async def player_config(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Return hls.js config for the given stream."""
    s = await get_stream(db, stream_id)
    if not s:
        raise HTTPException(status_code=404)
    buf         = s.buffer_seconds
    seg         = s.hls_time
    sync_count  = max(2, round(buf / seg))
    return {
        "hlsUrl":              f"/stream/{stream_id}/hls/stream.m3u8",
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
