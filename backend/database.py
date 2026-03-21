"""
MySQL/MariaDB async connection via SQLAlchemy + aiomysql.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

_DB_DEFAULT = "mysql+aiomysql://aistra:aistra123@localhost:3306/aistra_stream"
DB_URL = os.getenv("DATABASE_URL", _DB_DEFAULT)
if DB_URL == _DB_DEFAULT:
    import logging as _log
    _log.getLogger(__name__).warning(
        "DATABASE_URL not set — using default credentials. "
        "Set DATABASE_URL in .env for production."
    )

engine = create_async_engine(
    DB_URL,
    echo=False,
    pool_pre_ping=True,   # re-validates idle connections before use
    pool_size=10,
    pool_recycle=3600,    # recycle connections every 1h (MariaDB drops after 8h inactivity)
    pool_timeout=30,      # raise after 30s if no connection available
    max_overflow=5,       # allow up to 15 total connections under peak load
)
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
    from backend.models import User, Stream, Category, ConnectionLog, Setting, LoginAttemptRL  # noqa: F401
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
        # v1.2 — bump hls defaults
        "UPDATE streams SET hls_time=15 WHERE hls_time=4",
        "UPDATE streams SET hls_list_size=15 WHERE hls_list_size=8",
        # v1.3 — multi-key DRM, network/proxy fields, ABR output
        "ALTER TABLE streams ADD COLUMN drm_keys TEXT NULL",
        "ALTER TABLE streams ADD COLUMN audio_track INT NOT NULL DEFAULT 0",
        "ALTER TABLE streams ADD COLUMN output_rtmp VARCHAR(500) NULL",
        "ALTER TABLE streams ADD COLUMN output_udp VARCHAR(200) NULL",
        "ALTER TABLE streams ADD COLUMN output_qualities VARCHAR(50) NULL",
        "ALTER TABLE streams ADD COLUMN proxy VARCHAR(500) NULL",
        "ALTER TABLE streams ADD COLUMN user_agent VARCHAR(500) NULL",
        "ALTER TABLE streams ADD COLUMN backup_urls TEXT NULL",
        "ALTER TABLE streams ADD COLUMN category VARCHAR(100) NULL",
        # v1.4 — fix drm_type ENUM to use underscore (cenc_ctr not cenc-ctr)
        "ALTER TABLE streams MODIFY COLUMN drm_type ENUM('none','cenc_ctr') NOT NULL DEFAULT 'none'",
        "UPDATE streams SET drm_type='cenc_ctr' WHERE drm_type='cenc-ctr'",
        # v1.5 — performance indexes for common query patterns
        "ALTER TABLE streams ADD INDEX idx_streams_name (name)",
        "ALTER TABLE streams ADD INDEX idx_streams_enabled (enabled)",
        "ALTER TABLE streams ADD INDEX idx_streams_category (category)",
        "ALTER TABLE streams ADD INDEX idx_streams_updated (updated_at)",
        "ALTER TABLE users ADD INDEX idx_users_role (role)",
        "ALTER TABLE users ADD INDEX idx_users_active (active)",
        "ALTER TABLE connection_logs ADD INDEX idx_connlogs_ip (ip)",
        "ALTER TABLE connection_logs ADD INDEX idx_connlogs_success (success)",
        # v1.6 — per-stream YouTube cookies for yt-dlp authentication
        "ALTER TABLE streams ADD COLUMN yt_cookies TEXT NULL",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(sa.text(sql))
            except Exception:
                pass  # column already exists — safe to ignore
