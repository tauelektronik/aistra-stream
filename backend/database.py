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
    """Create all tables on startup."""
    from backend.models import User, Stream  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
