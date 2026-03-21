"""Categories router: /api/categories + logo."""
import asyncio
import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user, require_operator
from backend.crud import (
    assign_streams_to_category,
    create_category,
    delete_category,
    get_category,
    get_category_by_name,
    list_categories,
    update_category,
)
from backend.database import get_db
from backend.schemas import CategoryCreate, CategoryOut, CategoryUpdate
from backend.state import LOGOS_BASE

audit = logging.getLogger("aistra.audit")

router = APIRouter()


@router.get("/api/categories", response_model=list[CategoryOut])
async def api_list_categories(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    return await list_categories(db)


@router.post("/api/categories", response_model=CategoryOut, status_code=201)
async def api_create_category(
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    existing = await get_category_by_name(db, body.name)
    if existing:
        raise HTTPException(status_code=400, detail="Categoria já existe com esse nome")
    return await create_category(db, body)


@router.put("/api/categories/{cat_id}", response_model=CategoryOut)
async def api_update_category(
    cat_id: int,
    body: CategoryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
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
    audit.info("CATEGORY_UPDATE actor=%s id=%d name=%s→%s ip=%s",
               actor.username, cat_id, old_name, cat.name,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    return cat


@router.delete("/api/categories/{cat_id}", status_code=204)
async def api_delete_category(
    cat_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_operator),
):
    cat = await get_category(db, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    # Remove logo from disk before deleting the record
    if cat.logo_path:
        try:
            os.unlink(os.path.join(LOGOS_BASE, cat.logo_path))
        except OSError:
            pass
    await delete_category(db, cat_id)
    audit.info("CATEGORY_DELETE actor=%s id=%d ip=%s",
               actor.username, cat_id,
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))


@router.post("/api/categories/{cat_id}/logo")
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

    ext = content_type.split(";")[0].strip().split("/")[-1].replace("svg+xml", "svg")
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


@router.put("/api/categories/{cat_id}/logo-url", status_code=200)
async def api_set_logo_url(
    cat_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    """Download logo from a remote URL and save locally (avoids CORS issues)."""
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL não pode ser vazia")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL deve começar com http:// ou https://")
    if len(url) > 2000:
        raise HTTPException(status_code=400, detail="URL muito longa")
    cat = await get_category(db, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    def _download():
        req = _urlreq.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/*,*/*",
        })
        with _urlreq.urlopen(req, timeout=15) as resp:
            ct = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
            if not ct.startswith("image/"):
                raise ValueError(f"Resposta não é imagem: {ct}")
            data = resp.read(5 * 1024 * 1024)  # max 5MB
        return data, ct

    try:
        loop = asyncio.get_event_loop()
        data, content_type = await loop.run_in_executor(None, _download)
    except _urlerr.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Erro HTTP ao baixar imagem: {e.code}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Não foi possível baixar a imagem: {e}")

    ext = content_type.split("/")[-1].replace("svg+xml", "svg")
    if ext not in ("jpeg", "jpg", "png", "webp", "gif", "svg"):
        ext = "jpg"
    filename = f"cat_{cat_id}.{ext}"
    # Remove old logo files for this category
    for old in [f for f in os.listdir(LOGOS_BASE) if f.startswith(f"cat_{cat_id}.")]:
        try: os.unlink(os.path.join(LOGOS_BASE, old))
        except OSError: pass
    with open(os.path.join(LOGOS_BASE, filename), "wb") as f:
        f.write(data)
    cat.logo_path = filename
    await db.commit()
    return {"logo_path": filename}


@router.delete("/api/categories/{cat_id}/logo", status_code=204)
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


@router.get("/api/categories/{cat_id}/logo")
async def api_get_logo(
    cat_id: int,
    db: AsyncSession = Depends(get_db),
):
    cat = await get_category(db, cat_id)
    if not cat or not cat.logo_path:
        raise HTTPException(status_code=404, detail="Logo não encontrado")
    path = os.path.join(LOGOS_BASE, cat.logo_path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    ext = cat.logo_path.rsplit(".", 1)[-1].lower()
    media_types = {"svg": "image/svg+xml", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}
    media = media_types.get(ext, "image/jpeg")
    return FileResponse(path, media_type=media, headers={"Cache-Control": "max-age=3600"})


@router.post("/api/categories/{cat_id}/streams")
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
