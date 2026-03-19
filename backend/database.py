"""
MySQL/MariaDB async connection via SQLAlchemy + aiomysql.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DB_URL = os.getenv(
    "DATABASE_URL",
    "mysql+aiomysql://aistra:aistra123@localhost:3306/aistra_stream"
)

engine = create_async_engine(DB_URL, echo=False, pool_pre_ping=True, pool_size=10)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables on startup (no-op if already exist)."""
    from backend.models import User, Stream, Category  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations()


async def run_migrations():
    """Apply incremental schema changes to existing tables.
    Each ALTER is wrapped in try/except so re-runs are safe.
    Add a new block here whenever a column is added to a model.
    """
    import sqlalchemy as sa
    migrations = [
        # v1.1 — channel number per stream
        "ALTER TABLE streams ADD COLUMN channel_num INT NULL UNIQUE",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(sa.text(sql))
            except Exception:
                pass  # column already exists — safe to ignore
