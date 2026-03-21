"""
backend/backup.py — Sistema de backup/restore profissional do aistra-stream.

Módulo isolado: sem dependências de FastAPI, SQLAlchemy engine ou auth.
Recebe db: AsyncSession como parâmetro — testável sem banco real.

Funções públicas:
    create_full_backup(db, dest_path)  → int (tamanho em bytes)
    restore_from_zip(db, zip_path)     → dict {created, updated, skipped}
    apply_backup_retention(base, n)    → None
"""
import hashlib
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Chunk de leitura para streaming de logos (256 KB)
BACKUP_CHUNK = 256 * 1024

# Limite máximo de upload (2 GB)
BACKUP_MAX_UPLOAD = 2 * 1024 ** 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def model_to_dict(obj) -> dict:
    """Serialize a SQLAlchemy ORM row to a plain dict (ISO date strings)."""
    row: dict = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        row[col.name] = v
    return row


# ── Criação de backup ─────────────────────────────────────────────────────────

async def create_full_backup(
    db: AsyncSession,
    dest_path: str,
    logos_base: str,
    *,
    list_streams_fn,
    list_users_fn,
    list_categories_fn,
    load_settings_fn,
) -> int:
    """Write a complete ZIP backup directly to *dest_path* via atomic temp rename.

    Archive layout:
      manifest.json   — version, timestamp, counts, SHA-256 per-file checksums
      streams.json    — all streams
      users.json      — all users (password_hash included — full disaster recovery)
      categories.json — all categories
      settings.json   — all settings (telegram_bot_token cleared for safety)
      logos/          — all logo image files (streamed chunk-by-chunk)

    Returns the final file size in bytes.
    No intermediate in-memory copy of the ZIP — writes directly to disk.
    Atomic: uses temp file + os.replace() so a crash never leaves a partial file.
    """
    streams    = await list_streams_fn(db)
    users_list = await list_users_fn(db)
    cats       = await list_categories_fn(db)
    settings   = await load_settings_fn(db)

    safe_settings = dict(settings)
    if safe_settings.get("telegram_bot_token"):
        safe_settings["telegram_bot_token"] = ""

    streams_json  = json.dumps([model_to_dict(s) for s in streams],    ensure_ascii=False, indent=2)
    users_json    = json.dumps([model_to_dict(u) for u in users_list], ensure_ascii=False, indent=2)
    cats_json     = json.dumps([model_to_dict(c) for c in cats],       ensure_ascii=False, indent=2)
    settings_json = json.dumps(safe_settings,                          ensure_ascii=False, indent=2)

    manifest = {
        "version": 2,
        "format": "aistra-zip-backup",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "streams":    len(streams),
            "users":      len(users_list),
            "categories": len(cats),
            "settings":   len(safe_settings),
        },
        "checksums": {
            "streams.json":    _sha256(streams_json),
            "users.json":      _sha256(users_json),
            "categories.json": _sha256(cats_json),
            "settings.json":   _sha256(settings_json),
        },
    }
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)

    tmp_path = dest_path + ".tmp"
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr("manifest.json",   manifest_json)
            zf.writestr("streams.json",    streams_json)
            zf.writestr("users.json",      users_json)
            zf.writestr("categories.json", cats_json)
            zf.writestr("settings.json",   settings_json)
            # Stream logo files — zipfile.ZipFile.write() already reads in chunks internally
            if os.path.isdir(logos_base):
                for fname in sorted(os.listdir(logos_base)):
                    fpath = os.path.join(logos_base, fname)
                    if os.path.isfile(fpath):
                        zf.write(fpath, f"logos/{fname}")
        os.replace(tmp_path, dest_path)   # atomic rename
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return os.path.getsize(dest_path)


# ── Restore ───────────────────────────────────────────────────────────────────

async def restore_from_zip(
    db: AsyncSession,
    zip_path: str,
    logos_base: str,
    *,
    get_stream_fn,
    create_stream_fn,
    update_stream_fn,
    get_user_fn,
    create_user_raw_fn,
    update_user_raw_fn,
    get_category_fn,
    create_category_fn,
    load_settings_fn,
    save_settings_fn,
    stream_schema_create,
    stream_schema_update,
    category_schema_create,
) -> dict:
    """Restore all data from a ZIP backup file.

    Reads directly from disk — never loads the full ZIP into RAM.
    Verifies SHA-256 checksums when present in manifest.
    Restores: streams, users (with password_hash), categories, settings, logos.

    Returns {"created": int, "updated": int, "skipped": int}.
    Raises ValueError on invalid/corrupt ZIP.
    """
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except Exception as exc:
        raise ValueError(f"Arquivo ZIP inválido ou corrompido: {exc}") from exc

    try:
        names = zf.namelist()

        if "manifest.json" not in names:
            raise ValueError("ZIP não contém manifest.json — não é um backup aistra")

        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("format") != "aistra-zip-backup":
            raise ValueError("Formato de backup não reconhecido (campo 'format' inválido)")

        checksums = manifest.get("checksums", {})

        def _read_verified(entry: str):
            raw = zf.read(entry).decode()
            if entry in checksums:
                got = _sha256(raw)
                if got != checksums[entry]:
                    raise ValueError(f"Checksum inválido para {entry} — arquivo corrompido em trânsito ou em disco")
            return json.loads(raw)

        created = updated = skipped = 0

        # ── Streams ──
        if "streams.json" in names:
            for row in _read_verified("streams.json"):
                sid = row.get("id")
                if not sid:
                    skipped += 1
                    continue
                try:
                    for ts_field in ("created_at", "updated_at"):
                        row.pop(ts_field, None)
                    existing = await get_stream_fn(db, sid)
                    if existing:
                        await update_stream_fn(db, sid, stream_schema_update(**{k: v for k, v in row.items() if k != "id"}))
                        updated += 1
                    else:
                        await create_stream_fn(db, stream_schema_create(**row))
                        created += 1
                except Exception as exc:
                    logger.warning("Restore stream %s: %s", sid, exc)
                    skipped += 1

        # ── Users ──
        if "users.json" in names:
            for row in _read_verified("users.json"):
                uname = row.get("username")
                if not uname:
                    skipped += 1
                    continue
                try:
                    row.pop("created_at", None)
                    existing = await get_user_fn(db, uname)
                    if existing:
                        await update_user_raw_fn(db, existing, row)
                        updated += 1
                    else:
                        row.pop("id", None)
                        await create_user_raw_fn(db, row)
                        created += 1
                except Exception as exc:
                    logger.warning("Restore user %s: %s", uname, exc)
                    skipped += 1

        # ── Categories ──
        if "categories.json" in names:
            for row in _read_verified("categories.json"):
                if not row.get("name"):
                    continue
                try:
                    row.pop("created_at", None)
                    existing = await get_category_fn(db, row["name"])
                    if not existing:
                        await create_category_fn(db, category_schema_create(name=row["name"]))
                    elif row.get("logo_path") and not existing.logo_path:
                        existing.logo_path = row["logo_path"]
                        await db.commit()
                except Exception as exc:
                    logger.warning("Restore category %s: %s", row.get("name"), exc)

        # ── Settings ──
        if "settings.json" in names:
            imported = _read_verified("settings.json")
            current  = await load_settings_fn(db)
            if not imported.get("telegram_bot_token"):
                imported.pop("telegram_bot_token", None)
            current.update(imported)
            await save_settings_fn(db, current)

        # ── Logos — streamed chunk-by-chunk ──
        os.makedirs(logos_base, exist_ok=True)
        for name in names:
            if name.startswith("logos/") and not name.endswith("/"):
                fname = os.path.basename(name)
                if not fname:
                    continue
                dest = os.path.join(logos_base, fname)
                with zf.open(name) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst, BACKUP_CHUNK)

    finally:
        zf.close()

    return {"created": created, "updated": updated, "skipped": skipped}


# ── Retenção ──────────────────────────────────────────────────────────────────

def apply_backup_retention(backups_base: str, retention: int):
    """Delete oldest auto_*.zip files, keeping the `retention` most recent.
    Continues past individual deletion errors (does not stop on first failure).
    """
    files = sorted(
        Path(backups_base).glob("auto_*.zip"),
        key=lambda p: p.stat().st_mtime,
    )
    while len(files) > retention:
        f = files.pop(0)
        try:
            f.unlink()
            logger.debug("Retention: deleted %s", f.name)
        except OSError as exc:
            logger.warning("Retention: could not delete %s: %s", f, exc)
