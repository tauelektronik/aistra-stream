"""Users router: /api/users CRUD."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user, require_admin
from backend.crud import create_user, delete_user, get_user_by_username, list_users, update_user
from backend.database import get_db
from backend.schemas import UserCreate, UserOut, UserUpdate

audit = logging.getLogger("aistra.audit")

router = APIRouter()


@router.get("/api/users", response_model=list[UserOut])
async def api_list_users(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    return await list_users(db)


@router.post("/api/users", response_model=UserOut, status_code=201)
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


@router.put("/api/users/{user_id}", response_model=UserOut)
async def api_update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_admin),
):
    user = await update_user(db, user_id, body)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    audit.info("USER_UPDATE actor=%s target_id=%d fields=%s ip=%s",
               actor.username, user_id, list(body.model_fields_set),
               request.headers.get("X-Forwarded-For", getattr(request.client, "host", "-")))
    return user


@router.delete("/api/users/{user_id}", status_code=204)
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
