"""Settings router: /api/settings GET/PUT."""
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_admin
from backend.crud import load_settings_db, save_settings_db
from backend.database import get_db
from backend.hls_manager import hls_manager

logger = logging.getLogger(__name__)

router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SETTINGS_FILE_LEGACY = os.getenv(
    "AISTRA_SETTINGS_FILE",
    str(_PROJECT_ROOT / "data" / "settings.json"),
)


async def _migrate_settings_from_file(db):
    """One-time migration: import settings.json into the DB if the file exists.
    Runs on every startup but is a no-op once the file is removed/renamed.
    """
    if not os.path.exists(_SETTINGS_FILE_LEGACY):
        return
    try:
        with open(_SETTINGS_FILE_LEGACY) as f:
            data = json.load(f)
        if data:
            existing = await load_settings_db(db)
            merged = {**data, **existing}   # DB values take priority if already set
            await save_settings_db(db, merged)
            # Rename the file so migration doesn't run again
            os.rename(_SETTINGS_FILE_LEGACY, _SETTINGS_FILE_LEGACY + ".migrated")
            logger.info("Settings migrated from %s to DB", _SETTINGS_FILE_LEGACY)
    except Exception as exc:
        logger.warning("Settings migration from file failed: %s", exc)


@router.get("/api/settings")
async def api_get_settings(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Return current app settings (admin only)."""
    s = await load_settings_db(db)
    masked = dict(s)
    if masked.get("telegram_bot_token"):
        t = str(masked["telegram_bot_token"])
        masked["telegram_bot_token"] = t[:8] + "***" if len(t) > 8 else "***"
    return masked


@router.put("/api/settings")
async def api_save_settings(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Save app settings (admin only)."""
    current = await load_settings_db(db)
    # Don't overwrite token if masked placeholder was sent
    if str(body.get("telegram_bot_token", "")).endswith("***"):
        body["telegram_bot_token"] = current.get("telegram_bot_token", "")
    current.update(body)
    await save_settings_db(db, current)
    # Push Telegram config into hls_manager at runtime
    if "telegram_bot_token" in current:
        hls_manager.TELEGRAM_BOT_TOKEN = str(current.get("telegram_bot_token", ""))
    if "telegram_chat_id" in current:
        hls_manager.TELEGRAM_CHAT_ID = str(current.get("telegram_chat_id", ""))
    return {"ok": True}
