"""Backup router: /api/backup/* + legacy /api/settings/backup."""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend import backup as _bkp
from backend.auth import require_admin
from backend.crud import (
    create_category,
    create_stream,
    get_category_by_name,
    get_stream,
    get_user_by_username,
    list_streams,
    list_users,
    load_settings_db,
    list_categories,
    save_settings_db,
    update_stream,
)
from backend.database import get_db
from backend.state import BACKUPS_BASE, LOGOS_BASE

audit = logging.getLogger("aistra.audit")

router = APIRouter()

_BACKUP_MAX_UPLOAD = _bkp.BACKUP_MAX_UPLOAD   # 2 GB hard cap for uploaded ZIPs


def _model_to_dict(obj) -> dict:
    return _bkp.model_to_dict(obj)


async def _create_full_backup(db: AsyncSession, dest_path: str) -> int:
    """Delegate to backend.backup.create_full_backup (see that module for full docs)."""
    return await _bkp.create_full_backup(
        db, dest_path, LOGOS_BASE,
        list_streams_fn    = list_streams,
        list_users_fn      = list_users,
        list_categories_fn = list_categories,
        load_settings_fn   = load_settings_db,
    )


async def _apply_backup_retention(retention: int):
    _bkp.apply_backup_retention(BACKUPS_BASE, retention)


async def _restore_from_zip(db: AsyncSession, zip_path: str) -> dict:
    """Delegate to backend.backup.restore_from_zip (see that module for full docs)."""
    from backend.models import User as _UserModel
    from backend.schemas import StreamCreate, StreamUpdate, CategoryCreate

    async def _create_user_raw(db, row):
        u = _UserModel(**row)
        db.add(u)
        await db.commit()

    async def _update_user_raw(db, existing, row):
        for field in ("email", "role", "active", "password_hash"):
            if field in row:
                setattr(existing, field, row[field])
        await db.commit()

    try:
        return await _bkp.restore_from_zip(
            db, zip_path, LOGOS_BASE,
            get_stream_fn          = get_stream,
            create_stream_fn       = create_stream,
            update_stream_fn       = update_stream,
            get_user_fn            = get_user_by_username,
            create_user_raw_fn     = _create_user_raw,
            update_user_raw_fn     = _update_user_raw,
            get_category_fn        = get_category_by_name,
            create_category_fn     = create_category,
            load_settings_fn       = load_settings_db,
            save_settings_fn       = save_settings_db,
            stream_schema_create   = StreamCreate,
            stream_schema_update   = StreamUpdate,
            category_schema_create = CategoryCreate,
        )
    except ValueError as exc:
        status = 422 if "checksum" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc))


# ── Backup endpoints ──────────────────────────────────────────────────────────

@router.post("/api/backup/create", status_code=201)
async def api_backup_create(
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_admin),
):
    """Create a manual full-backup ZIP and store it on the server."""
    ts       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"manual_{ts}.zip"
    path     = os.path.join(BACKUPS_BASE, filename)
    size     = await _create_full_backup(db, path)
    audit.info("BACKUP_CREATE actor=%s file=%s size=%d", actor.username, filename, size)
    return {"filename": filename, "size": size}


@router.get("/api/backup/list")
async def api_backup_list(_=Depends(require_admin)):
    """List all stored backup files with metadata."""
    files = []
    for p in sorted(Path(BACKUPS_BASE).glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = p.stat()
        files.append({
            "filename":   p.name,
            "size":       stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "type":       "auto" if p.name.startswith("auto_") else "manual",
        })
    return files


@router.get("/api/backup/download/{filename}")
async def api_backup_download(filename: str, _=Depends(require_admin)):
    """Download a backup ZIP file (streamed — safe for large files)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    path = os.path.join(BACKUPS_BASE, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Backup não encontrado")
    return FileResponse(path, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.delete("/api/backup/{filename}", status_code=204)
async def api_backup_delete(filename: str, actor=Depends(require_admin)):
    """Delete a backup file from the server."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    path = os.path.join(BACKUPS_BASE, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Backup não encontrado")
    os.unlink(path)
    audit.info("BACKUP_DELETE actor=%s file=%s", actor.username, filename)


@router.post("/api/backup/restore/{filename}", status_code=200)
async def api_backup_restore_stored(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_admin),
):
    """Restore from a stored backup file (reads from disk — no RAM load)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    path = os.path.join(BACKUPS_BASE, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Backup não encontrado")
    result = await _restore_from_zip(db, path)
    audit.info("BACKUP_RESTORE actor=%s file=%s result=%s ip=%s",
               actor.username, filename, result,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    return result


@router.post("/api/backup/restore-upload", status_code=200)
async def api_backup_restore_upload(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_admin),
):
    """Restore by uploading a backup ZIP.
    Upload is streamed to a temp file first — no full-file load into RAM.
    Safe for backups up to 2 GB.
    """
    # Stream upload to a temp file in BACKUPS_BASE (same filesystem → fast rename)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=BACKUPS_BASE)
    written = 0
    try:
        with os.fdopen(tmp_fd, "wb") as tmp_fh:
            while True:
                chunk = await file.read(_bkp.BACKUP_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > _BACKUP_MAX_UPLOAD:
                    raise HTTPException(status_code=413,
                                        detail=f"Arquivo muito grande (máx {_BACKUP_MAX_UPLOAD // 1024**3} GB)")
                tmp_fh.write(chunk)
        result = await _restore_from_zip(db, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    audit.info("BACKUP_RESTORE_UPLOAD actor=%s size=%d result=%s ip=%s",
               actor.username, written, result,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    return result


# ── Legacy JSON backup endpoint (kept for compatibility) ──────────────────────

@router.get("/api/settings/backup")
async def api_backup_legacy(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Legacy: export as JSON (use /api/backup/create for full ZIP backup)."""
    streams      = await list_streams(db)
    settings     = await load_settings_db(db)
    safe_settings = dict(settings)
    if safe_settings.get("telegram_bot_token"):
        safe_settings["telegram_bot_token"] = ""
    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "streams": [_model_to_dict(s) for s in streams],
        "settings": safe_settings,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="aistra-backup.json"'},
    )


@router.post("/api/settings/restore", status_code=200)
async def api_restore_legacy(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_admin),
):
    """Legacy: restore from JSON backup (use /api/backup/restore-upload for ZIP)."""
    import logging as _logging
    _logger = _logging.getLogger(__name__)
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
            for ts_field in ("created_at", "updated_at"):
                row.pop(ts_field, None)
            existing = await get_stream(db, sid)
            if existing:
                from backend.schemas import StreamUpdate as SU
                await update_stream(db, sid, SU(**{k: v for k, v in row.items() if k != "id"}))
                updated += 1
            else:
                from backend.schemas import StreamCreate as SC
                await create_stream(db, SC(**row))
                created += 1
        except Exception as exc:
            _logger.warning("Restore: skipped stream %s: %s", sid, exc)
            skipped += 1

    if body.get("settings"):
        current  = await load_settings_db(db)
        imported = dict(body["settings"])
        if not imported.get("telegram_bot_token"):
            imported.pop("telegram_bot_token", None)
        current.update(imported)
        await save_settings_db(db, current)

    audit.info("RESTORE actor=%s created=%d updated=%d skipped=%d ip=%s",
               actor.username, created, updated, skipped,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    return {"created": created, "updated": updated, "skipped": skipped}
