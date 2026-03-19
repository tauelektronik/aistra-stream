"""
CRUD operations for User and Stream models.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from typing import List, Optional

from backend.models import User, Stream, Category
from backend.auth import hash_password
from backend.schemas import UserCreate, UserUpdate, StreamCreate, StreamUpdate, CategoryCreate, CategoryUpdate


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
    d = data.model_dump()
    # Auto-assign channel_num if not provided (max existing + 1)
    if d.get("channel_num") is None:
        result = await db.execute(select(func.max(Stream.channel_num)))
        max_num = result.scalar_one_or_none() or 0
        d["channel_num"] = max_num + 1
    stream = Stream(**d)
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


# ── Categories ────────────────────────────────────────────────────────────────

async def list_categories(db: AsyncSession) -> List[Category]:
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())

async def get_category(db: AsyncSession, cat_id: int) -> Optional[Category]:
    result = await db.execute(select(Category).where(Category.id == cat_id))
    return result.scalar_one_or_none()

async def get_category_by_name(db: AsyncSession, name: str) -> Optional[Category]:
    result = await db.execute(select(Category).where(Category.name == name))
    return result.scalar_one_or_none()

async def create_category(db: AsyncSession, data: CategoryCreate) -> Category:
    cat = Category(name=data.name)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat

async def update_category(db: AsyncSession, cat_id: int, data: CategoryUpdate) -> Optional[Category]:
    cat = await get_category(db, cat_id)
    if not cat:
        return None
    if data.name is not None:
        cat.name = data.name
    await db.commit()
    await db.refresh(cat)
    return cat

async def delete_category(db: AsyncSession, cat_id: int) -> bool:
    cat = await get_category(db, cat_id)
    if not cat:
        return False
    # Batch-unassign streams that belong to this category
    await db.execute(update(Stream).where(Stream.category == cat.name).values(category=None))
    await db.delete(cat)
    await db.commit()
    return True

async def assign_streams_to_category(db: AsyncSession, cat_name: str, stream_ids: List[str]) -> int:
    """Set category=cat_name for given stream_ids, clear for others in that category."""
    # Batch-clear old assignments for this category that are not in the new list
    await db.execute(
        update(Stream)
        .where(Stream.category == cat_name, Stream.id.not_in(stream_ids) if stream_ids else Stream.id.isnot(None))
        .values(category=None)
    )
    # Batch-assign new ones
    if stream_ids:
        await db.execute(
            update(Stream).where(Stream.id.in_(stream_ids)).values(category=cat_name)
        )
    await db.commit()
    return len(stream_ids)
