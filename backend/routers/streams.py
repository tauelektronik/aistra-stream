"""Streams router: /api/streams CRUD + start/stop/log/ban + M3U."""
import logging
import os
import re

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user, require_operator
from backend.crud import (
    create_stream, delete_stream, get_stream, list_streams, update_stream,
)
from backend.database import get_db
from backend.hls_manager import hls_manager, HLS_BASE
from backend.schemas import StreamCreate, StreamOut, StreamUpdate

audit = logging.getLogger("aistra.audit")

router = APIRouter()


@router.get("/api/streams", response_model=list[StreamOut])
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


@router.get("/api/streams/export.m3u")
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


@router.post("/api/streams/import-m3u")
async def api_import_m3u(
    file: UploadFile = File(...),
    overwrite: bool = False,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
    request: Request = None,
):
    """Import streams from an M3U/M3U8 playlist file.
    Parses #EXTINF entries and creates streams in bulk.
    overwrite=true updates existing streams; false skips duplicates.
    """
    import re as _re

    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    def _slugify(name: str) -> str:
        s = name.lower().strip()
        s = _re.sub(r"[^a-z0-9\s_-]", "", s)
        s = _re.sub(r"\s+", "-", s)
        s = _re.sub(r"-+", "-", s).strip("-")
        return s[:50] or "stream"

    created = skipped = updated = errors = 0
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("#EXTINF"):
            i += 1
            continue

        # Find the URL (next non-empty, non-comment line)
        url = ""
        j = i + 1
        while j < len(lines):
            candidate = lines[j].strip()
            if candidate and not candidate.startswith("#"):
                url = candidate
                break
            j += 1
        i = j + 1

        if not url:
            errors += 1
            continue

        # Parse attributes from #EXTINF line
        tvg_id    = _re.search(r'tvg-id=["\']([^"\']*)["\']',    line)
        tvg_name  = _re.search(r'tvg-name=["\']([^"\']*)["\']',  line)
        group     = _re.search(r'group-title=["\']([^"\']*)["\']', line)
        # Channel name after the last comma
        comma_pos = line.rfind(",")
        display_name = line[comma_pos + 1:].strip() if comma_pos != -1 else ""

        name     = (tvg_name.group(1) if tvg_name else display_name) or display_name or "Canal"
        name     = name[:100].strip()
        category = group.group(1).strip()[:100] if group else None

        # Build a safe ID
        raw_id = tvg_id.group(1).strip() if tvg_id else ""
        if not raw_id or not _re.fullmatch(r"[a-zA-Z0-9_-]{2,50}", raw_id):
            raw_id = _slugify(name)
        stream_id = raw_id[:50] or "stream"

        # Validate URL (reuse existing validator)
        try:
            from backend.schemas import _validate_stream_url
            _validate_stream_url(url)
        except Exception:
            errors += 1
            continue

        existing = await get_stream(db, stream_id)
        if existing:
            if overwrite:
                from backend.schemas import StreamUpdate as SU
                patch = SU(name=name, url=url, category=category or existing.category)
                await update_stream(db, stream_id, patch)
                updated += 1
            else:
                skipped += 1
            continue

        # Create new stream
        from backend.schemas import StreamCreate as SC
        try:
            await create_stream(db, SC(id=stream_id, name=name, url=url, category=category))
            created += 1
        except Exception:
            errors += 1

    audit.info("M3U_IMPORT actor=%s created=%d updated=%d skipped=%d errors=%d ip=%s",
               actor.username, created, updated, skipped, errors,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")) if request else "-")
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


@router.post("/api/streams", response_model=StreamOut, status_code=201)
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


@router.get("/api/streams/{stream_id}", response_model=StreamOut)
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


@router.put("/api/streams/{stream_id}", response_model=StreamOut)
async def api_update_stream(
    stream_id: str,
    body: StreamUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
):
    was_running = (await hls_manager.get_status(stream_id)) == "running"
    s = await update_stream(db, stream_id, body)
    if not s:
        raise HTTPException(status_code=404, detail="Stream não encontrado")
    await hls_manager.stop_session(stream_id)
    if was_running and s.enabled:
        await hls_manager.get_hls_dir(s, force_restart=True)
    audit.info("STREAM_UPDATE actor=%s id=%s restarted=%s ip=%s",
               actor.username, stream_id, was_running,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    out        = StreamOut.model_validate(s)
    out.status = await hls_manager.get_status(s.id)
    return out


@router.delete("/api/streams/{stream_id}", status_code=204)
async def api_delete_stream(
    stream_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
):
    await hls_manager.stop_session(stream_id)
    hls_manager.cleanup_stream_data(stream_id)
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


@router.post("/api/streams/{stream_id}/start", status_code=200)
async def api_start_stream(
    stream_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
):
    """Enable autoplay: start the stream and keep it running indefinitely."""
    s = await get_stream(db, stream_id)
    if not s:
        raise HTTPException(status_code=404, detail="Stream não encontrado")
    # Persist enabled=True
    from backend.schemas import StreamUpdate as _SU
    await update_stream(db, stream_id, _SU(enabled=True))
    # Mark autoplay before starting (so watchdog/cleanup respect it immediately)
    hls_manager.enable_autoplay(stream_id)
    hls_dir, err = await hls_manager.get_hls_dir(s)
    if err:
        import logging as _logging
        _logging.getLogger(__name__).warning("api_start_stream: get_hls_dir error for %s: %s", stream_id, err)
    audit.info("STREAM_START actor=%s id=%s ip=%s",
               actor.username, stream_id,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    return {"status": "running", "enabled": True}


@router.post("/api/streams/{stream_id}/stop", status_code=200)
async def api_stop_stream(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    """Disable autoplay and stop the stream."""
    from backend.schemas import StreamUpdate as _SU
    await update_stream(db, stream_id, _SU(enabled=False))
    hls_manager.disable_autoplay(stream_id)
    await hls_manager.stop_session(stream_id)
    return {"status": "stopped", "enabled": False}


@router.get("/api/streams/{stream_id}/log")
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


@router.get("/api/streams/{stream_id}/stats")
async def api_stream_stats(
    stream_id: str,
    _=Depends(get_current_user),
):
    """Return real-time ffmpeg stats (bitrate, fps, uptime, ban status)."""
    return await hls_manager.get_stats(stream_id)


@router.get("/api/streams/{stream_id}/ban")
async def api_stream_ban_status(
    stream_id: str,
    _=Depends(get_current_user),
):
    """Return ban status for a stream."""
    return hls_manager.get_ban_status(stream_id)


@router.post("/api/streams/{stream_id}/ban/clear", status_code=200)
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


@router.get("/api/streams/{stream_id}/log/live")
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
