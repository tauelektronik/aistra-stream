"""
JWT authentication helpers.
"""
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

SECRET_KEY = os.getenv("SECRET_KEY", "")
ALGORITHM  = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "1440"))

# ── Startup validation ────────────────────────────────────────────────────────

_WEAK_KEYS = {"", "change-me-in-production-use-long-random-string",
              "change-me-to-a-long-random-string", "secret", "dev"}

if SECRET_KEY in _WEAK_KEYS or len(SECRET_KEY) < 32:
    if os.getenv("AISTRA_INSECURE_KEY"):
        # Allow in dev with explicit opt-in
        import logging
        logging.getLogger(__name__).warning(
            "SECRET_KEY não definido ou fraco — usando modo inseguro (dev only)!"
        )
        SECRET_KEY = "dev-insecure-key-do-not-use-in-production-32ch"
    else:
        print(
            "\n[ERRO CRÍTICO] SECRET_KEY não definido ou muito fraco.\n"
            "Gere uma chave segura com:\n"
            "  python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "E defina em /opt/aistra-stream/.env como SECRET_KEY=<valor>\n",
            file=sys.stderr
        )
        sys.exit(1)

# ── Crypto ────────────────────────────────────────────────────────────────────

pwd_context   = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependency: current user ─────────────────────────────────────────

from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend import crud


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    payload = decode_token(token)
    username: str = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Token sem subject")
    user = await crud.get_user_by_username(db, username)
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Usuário não encontrado ou inativo")
    return user


async def require_admin(user=Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return user


async def require_operator(user=Depends(get_current_user)):
    if user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acesso restrito a operadores")
    return user
