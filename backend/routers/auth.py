"""Auth router: /auth/login, /auth/me, /api/connection-logs."""
import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import (
    create_access_token,
    get_current_user,
    require_admin,
    verify_password,
)
from backend.crud import get_user_by_username
from backend.database import get_db
from backend.models import ConnectionLog, LoginAttemptRL
from backend.schemas import LoginRequest, TokenResponse, UserOut

audit = logging.getLogger("aistra.audit")

router = APIRouter()

# ── DB-backed rate limiter ─────────────────────────────────────────────────────

LOGIN_LIMIT  = int(__import__("os").getenv("LOGIN_RATE_LIMIT",  "10"))
LOGIN_WINDOW = int(__import__("os").getenv("LOGIN_RATE_WINDOW", "60"))


async def _check_rate_limit_db(ip: str, db: AsyncSession):
    """Raise 429 if ip made >= LOGIN_LIMIT attempts in the last LOGIN_WINDOW seconds.
    Records this attempt in the DB regardless.
    Survives restarts and works with multiple workers.
    """
    window_start = datetime.now(timezone.utc) - timedelta(seconds=LOGIN_WINDOW)
    result = await db.execute(
        sa.select(sa.func.count(LoginAttemptRL.id))
        .where(LoginAttemptRL.ip == ip, LoginAttemptRL.attempted_at >= window_start)
    )
    count = result.scalar() or 0
    # Record attempt first so even the rejected request counts
    db.add(LoginAttemptRL(ip=ip, attempted_at=datetime.now(timezone.utc)))
    await db.commit()
    if count >= LOGIN_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Muitas tentativas. Tente novamente em {LOGIN_WINDOW}s.",
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Rate limit by IP
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    if "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()
    await _check_rate_limit_db(client_ip, db)

    ua = request.headers.get("User-Agent", "")[:500]
    user = await get_user_by_username(db, body.username)
    ok = bool(user and verify_password(body.password, user.password_hash) and user.active)

    # Always record the attempt
    db.add(ConnectionLog(username=body.username, ip=client_ip, user_agent=ua, success=ok))
    await db.commit()

    if not ok:
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
    token = create_access_token({"sub": user.username, "role": user.role})
    return TokenResponse(access_token=token)


@router.get("/api/connection-logs")
async def api_connection_logs(
    limit: int = 200,
    username: str | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    q = sa.select(ConnectionLog).order_by(ConnectionLog.created_at.desc()).limit(min(limit, 1000))
    if username:
        q = q.where(ConnectionLog.username == username)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "username": r.username,
            "ip": r.ip,
            "user_agent": r.user_agent,
            "success": r.success,
            "created_at": r.created_at.isoformat() + "Z",
        }
        for r in rows
    ]


@router.delete("/api/connection-logs", status_code=204)
async def api_clear_connection_logs(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    await db.execute(sa.delete(ConnectionLog))
    await db.commit()


@router.get("/auth/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return user
