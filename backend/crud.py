"""
CRUD operations for User and Stream models.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from typing import List, Optional

from backend.models import User, Stream
from backend.auth import hash_password
from backend.schemas import UserCreate, UserUpdate, StreamCreate, StreamUpdate


# ── Users ────────────────────────────────────────────────────────────────────

async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()

async def list_users(db: AsyncSession) -> List[User]:
    result = await db.execute(select(User).order_by(User.id))
    return list(result.scalars().all())

async def create_user(db: AsyncSession, data: UserCreate) -> User:
    user = User(
        username      = data.username,
        password_hash = hash_password(data.password),
        email         = data.email,
        role          = data.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def update_user(db: AsyncSession, user_id: int, data: UserUpdate) -> Optional[User]:
    user = await get_user(db, user_id)
    if not user:
        return None
    if data.email    is not None: user.email  = data.email
    if data.role     is not None: user.role   = data.role
    if data.active   is not None: user.active = data.active
    if data.password is not None: user.password_hash = hash_password(data.password)
    await db.commit()
    await db.refresh(user)
    return user

async def delete_user(db: AsyncSession, user_id: int) -> bool:
    user = await get_user(db, user_id)
    if not user:
        return False
    await db.delete(user)
    await db.commit()
    return True


# ── Streams ───────────────────────────────────────────────────────────────────

async def list_streams(db: AsyncSession) -> List[Stream]:
    result = await db.execute(select(Stream).order_by(Stream.name))
    return list(result.scalars().all())

async def get_stream(db: AsyncSession, stream_id: str) -> Optional[Stream]:
    result = await db.execute(select(Stream).where(Stream.id == stream_id))
    return result.scalar_one_or_none()

async def create_stream(db: AsyncSession, data: StreamCreate) -> Stream:
    stream = Stream(**data.model_dump())
    db.add(stream)
    await db.commit()
    await db.refresh(stream)
    return stream

async def update_stream(db: AsyncSession, stream_id: str, data: StreamUpdate) -> Optional[Stream]:
    stream = await get_stream(db, stream_id)
    if not stream:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(stream, field, value)
    await db.commit()
    await db.refresh(stream)
    return stream

async def delete_stream(db: AsyncSession, stream_id: str) -> bool:
    stream = await get_stream(db, stream_id)
    if not stream:
        return False
    await db.delete(stream)
    await db.commit()
    return True
