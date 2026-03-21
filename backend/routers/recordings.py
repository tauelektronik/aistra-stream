"""Recordings router: /api/streams/{id}/record + /api/recordings/*."""
import logging
import os
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from backend.auth import get_current_user, require_operator
from backend.database import get_db
from backend.hls_manager import hls_manager

audit = logging.getLogger("aistra.audit")

router = APIRouter()


class RecordBody(BaseModel):
    duration_s: Optional[int] = None    # seconds; None = indefinite
    label:      Optional[str] = None    # tag embedded in filename


class ScheduleCreate(BaseModel):
    stream_id:  str
    start_at:   float               # Unix timestamp
    duration_s: Optional[int] = None
    label:      Optional[str] = None
    repeat:     str = "none"        # none / daily / weekly


def _resolve_recording_path(filename: str) -> str:
    """Validate filename and return the real path. Raises HTTPException on error."""
    if re.search(r"[^a-zA-Z0-9_\-.]", filename) or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome inválido")
    from backend.hls_manager import RECORDINGS_BASE
    path      = os.path.join(RECORDINGS_BASE, filename)
    real_base = os.path.realpath(RECORDINGS_BASE)
    real_path = os.path.realpath(path)
    if not real_path.startswith(real_base + os.sep):
        raise HTTPException(status_code=400, detail="Nome inválido")
    return real_path


@router.post("/api/streams/{stream_id}/record")
async def api_start_recording(
    stream_id: str,
    body: RecordBody = Body(default=RecordBody()),
    _=Depends(require_operator),
):
    path, err = await hls_manager.start_recording(
        stream_id,
        duration_s=body.duration_s,
        label=body.label,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"recording": True, "filename": os.path.basename(path)}


@router.delete("/api/streams/{stream_id}/record", status_code=200)
async def api_stop_recording(
    stream_id: str,
    _=Depends(require_operator),
):
    path = await hls_manager.stop_recording(stream_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Gravação não iniciada")
    return {"recording": False, "filename": os.path.basename(path)}


@router.get("/api/streams/{stream_id}/record/status")
async def api_recording_status(
    stream_id: str,
    _=Depends(get_current_user),
):
    status = hls_manager.get_recording_status(stream_id)
    return status or {"recording": False}


@router.get("/api/recordings")
async def api_list_recordings(
    stream_id: str = "",
    _=Depends(require_operator),
):
    return hls_manager.list_recordings(stream_id or None)


@router.get("/api/recordings/schedules")
async def api_list_schedules(
    stream_id: str = "",
    _=Depends(require_operator),
):
    return hls_manager.list_schedules(stream_id or None)


@router.post("/api/recordings/schedules", status_code=201)
async def api_add_schedule(
    body: ScheduleCreate,
    _=Depends(require_operator),
):
    sched_id = hls_manager.add_schedule(
        body.stream_id,
        body.start_at,
        body.duration_s,
        body.label or "",
        body.repeat,
    )
    return {"id": sched_id}


@router.delete("/api/recordings/schedules/{sched_id}", status_code=204)
async def api_delete_schedule(
    sched_id: str,
    _=Depends(require_operator),
):
    ok = hls_manager.remove_schedule(sched_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")


@router.get("/api/recordings/{filename}")
async def api_download_recording(
    filename: str,
    _=Depends(require_operator),
):
    real_path = _resolve_recording_path(filename)
    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(real_path, media_type="video/mp4",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.delete("/api/recordings/{filename}", status_code=204)
async def api_delete_recording(
    filename: str,
    actor=Depends(require_operator),
):
    real_path = _resolve_recording_path(filename)
    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    os.remove(real_path)
    audit.info("RECORDING_DELETE actor=%s filename=%s", actor.username, filename)
