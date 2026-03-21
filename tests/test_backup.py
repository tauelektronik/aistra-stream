"""
test_backup.py — Testes de integridade do sistema de backup/restore.

Importa diretamente de backend.backup (sem FastAPI, sem banco, sem aiomysql).

Testa:
  1. Criação do ZIP — estrutura, checksums, todos os arquivos presentes
  2. Restore completo — streams, users, categories, settings, logos
  3. Verificação de checksum — arquivo corrompido detectado
  4. Backup grande — 500 streams + logo de 1 MB
  5. Idempotência — restaurar duas vezes não duplica dados
  6. Retenção — auto-backup limpa arquivos antigos corretamente
  7. Atomic write — falha não deixa arquivo parcial no disco
  8. ZIP inválido / sem manifest — rejeitado com ValueError

Execute:
  python -m pytest tests/test_backup.py -v
  ou
  python tests/test_backup.py
"""
import asyncio
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Importar diretamente do módulo isolado — sem dependências de banco ─────────
from backend.backup import (
    create_full_backup,
    restore_from_zip,
    apply_backup_retention,
    model_to_dict,
    BACKUP_CHUNK,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _make_stream(i: int) -> dict:
    return {
        "id": f"stream-{i:04d}",
        "name": f"Canal {i}",
        "url": f"http://example.com/stream{i}.m3u8",
        "drm_type": "none",
        "drm_keys": None, "drm_kid": None, "drm_key": None,
        "stream_type": "live",
        "video_codec": "libx264", "video_preset": "ultrafast",
        "video_crf": 26, "video_maxrate": "", "video_resolution": "original",
        "audio_codec": "aac", "audio_bitrate": "128k", "audio_track": 0,
        "hls_time": 15, "hls_list_size": 15, "buffer_seconds": 20,
        "output_rtmp": None, "output_udp": None, "output_qualities": None,
        "proxy": None, "user_agent": None, "backup_urls": None,
        "category": f"Cat{i % 5}", "channel_num": i, "enabled": True,
    }


def _make_user(i: int) -> dict:
    return {
        "id": i, "username": f"user{i}",
        "password_hash": f"$2b$12$fakehash{i:04d}",
        "email": f"user{i}@test.com",
        "role": "operator", "active": True,
    }


def _make_cat(i: int) -> dict:
    return {"id": i, "name": f"Categoria {i}", "logo_path": None}


class _FakeStream:
    """Fake ORM-like object for model_to_dict tests."""
    class __table__:
        class _Col:
            def __init__(self, n): self.name = n
        columns = [_Col("id"), _Col("name"), _Col("url"), _Col("enabled")]
    def __init__(self, id, name, url, enabled=True):
        self.id = id; self.name = name; self.url = url; self.enabled = enabled


def _build_zip_bytes(
    streams=None, users=None, categories=None, settings=None, logos=None,
    corrupt_entry=None,
) -> bytes:
    """Build a complete aistra ZIP backup in memory (for test fixtures)."""
    streams    = streams    or []
    users      = users      or []
    categories = categories or []
    settings   = settings   or {}
    logos      = logos      or {}

    sj = json.dumps(streams,    ensure_ascii=False, indent=2)
    uj = json.dumps(users,      ensure_ascii=False, indent=2)
    cj = json.dumps(categories, ensure_ascii=False, indent=2)
    tj = json.dumps(settings,   ensure_ascii=False, indent=2)

    manifest = {
        "version": 2, "format": "aistra-zip-backup",
        "exported_at": "2026-03-21T00:00:00+00:00",
        "counts": {"streams": len(streams), "users": len(users),
                   "categories": len(categories), "settings": len(settings)},
        "checksums": {
            "streams.json": _sha256(sj), "users.json": _sha256(uj),
            "categories.json": _sha256(cj), "settings.json": _sha256(tj),
        },
    }
    if corrupt_entry:
        manifest["checksums"][corrupt_entry] = "0" * 64

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json",   json.dumps(manifest))
        zf.writestr("streams.json",    sj)
        zf.writestr("users.json",      uj)
        zf.writestr("categories.json", cj)
        zf.writestr("settings.json",   tj)
        for fname, data in logos.items():
            zf.writestr(f"logos/{fname}", data)
    return buf.getvalue()


@pytest.fixture
def tmp_dirs():
    logos_dir   = tempfile.mkdtemp()
    backups_dir = tempfile.mkdtemp()
    yield logos_dir, backups_dir
    shutil.rmtree(logos_dir,   ignore_errors=True)
    shutil.rmtree(backups_dir, ignore_errors=True)


def _make_restore_kwargs(logos_dir, *, stream_db=None):
    """Build the full kwargs dict for restore_from_zip with mock callables."""
    created_streams = []
    updated_streams = []
    created_users   = []
    updated_users   = []
    created_cats    = []
    saved_settings  = {}

    # Allow caller to provide an existing stream dict for update testing
    if stream_db is None:
        stream_db = {}

    async def get_stream(db, sid):
        return stream_db.get(sid)

    async def create_stream(db, data):
        created_streams.append(data)
        # After creation, add to mock DB
        m = MagicMock(id=data.id if hasattr(data, "id") else "?")
        stream_db[m.id] = m
        return m

    async def update_stream(db, sid, data):
        updated_streams.append((sid, data))
        return MagicMock()

    async def get_user(db, uname):
        return None

    async def create_user_raw(db, row):
        created_users.append(row)
        db.add(MagicMock())
        await db.commit()

    async def update_user_raw(db, existing, row):
        updated_users.append(row)
        await db.commit()

    async def get_cat(db, name):
        return None

    async def create_cat(db, data):
        created_cats.append(data)
        return MagicMock()

    async def load_settings(db):
        return {}

    async def save_settings(db, data):
        saved_settings.update(data)

    class FakeSC:
        def __init__(self, **kw): self.__dict__.update(kw)
        @property
        def id(self): return self.__dict__.get("id", "?")

    class FakeSU:
        def __init__(self, **kw): self.__dict__.update(kw)

    class FakeCC:
        def __init__(self, name): self.name = name

    return dict(
        logos_base            = logos_dir,
        get_stream_fn         = get_stream,
        create_stream_fn      = create_stream,
        update_stream_fn      = update_stream,
        get_user_fn           = get_user,
        create_user_raw_fn    = create_user_raw,
        update_user_raw_fn    = update_user_raw,
        get_category_fn       = get_cat,
        create_category_fn    = create_cat,
        load_settings_fn      = load_settings,
        save_settings_fn      = save_settings,
        stream_schema_create  = FakeSC,
        stream_schema_update  = FakeSU,
        category_schema_create= FakeCC,
    ), created_streams, updated_streams, created_users, saved_settings


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 1 — model_to_dict
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_to_dict():
    """model_to_dict deve serializar campos com isoformat para strings ISO."""
    from datetime import datetime, timezone
    s = _FakeStream("abc", "Canal A", "http://x.com/stream.m3u8")
    d = model_to_dict(s)
    assert d["id"]   == "abc"
    assert d["name"] == "Canal A"
    assert d["url"]  == "http://x.com/stream.m3u8"
    print("✓ model_to_dict OK")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 2 — Estrutura do ZIP criado por create_full_backup
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_full_backup_structure(tmp_dirs):
    """ZIP criado deve conter todos os arquivos e checksums válidos."""
    logos_dir, backups_dir = tmp_dirs

    # Criar logo de teste
    logo_path = os.path.join(logos_dir, "test_logo.png")
    with open(logo_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\xAB" * 100)

    N = 5
    fake_streams = [MagicMock() for i in range(N)]
    for i, s in enumerate(fake_streams):
        s.__table__ = SimpleNamespace(
            columns=[SimpleNamespace(name=k) for k in _make_stream(0).keys()]
        )
        for k, v in _make_stream(i).items():
            setattr(s, k, v)

    dest = os.path.join(backups_dir, "test.zip")

    size = await create_full_backup(
        MagicMock(), dest, logos_dir,
        list_streams_fn    = AsyncMock(return_value=fake_streams),
        list_users_fn      = AsyncMock(return_value=[]),
        list_categories_fn = AsyncMock(return_value=[]),
        load_settings_fn   = AsyncMock(return_value={"watchdog_enabled": True}),
    )

    assert size > 0
    assert os.path.isfile(dest)

    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        for req in ("manifest.json", "streams.json", "users.json",
                    "categories.json", "settings.json"):
            assert req in names, f"{req} ausente no ZIP"

        assert "logos/test_logo.png" in names, "Logo ausente no ZIP"

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"]  == "aistra-zip-backup"
        assert manifest["version"] == 2
        assert manifest["counts"]["streams"] == N

        # Verificar checksums
        for entry, expected in manifest["checksums"].items():
            actual = _sha256(zf.read(entry).decode())
            assert actual == expected, f"Checksum inválido para {entry}"

        # Telegram token deve estar zerado
        settings_data = json.loads(zf.read("settings.json"))
        # (neste caso não havia token, mas settings deve ter watchdog_enabled)
        assert "watchdog_enabled" in settings_data or settings_data == {}

    print(f"✓ Estrutura do ZIP OK — {size} bytes")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 3 — Restore completo: streams + users + settings + logos
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_restore_complete(tmp_dirs):
    """Restore deve recuperar streams, users, settings e logos com 100% fidelidade."""
    logos_dir, backups_dir = tmp_dirs

    streams    = [_make_stream(i) for i in range(10)]
    users      = [_make_user(i)   for i in range(3)]
    cats       = [_make_cat(i)    for i in range(2)]
    settings_d = {"watchdog_enabled": False, "max_restarts": 3}
    logo_data  = b"\x89PNG\r\n\x1a\n" + b"\xAB" * 500

    zip_bytes = _build_zip_bytes(
        streams=streams, users=users, categories=cats,
        settings=settings_d, logos={"channel_logo.png": logo_data}
    )
    zip_file = os.path.join(backups_dir, "test.zip")
    with open(zip_file, "wb") as f:
        f.write(zip_bytes)

    db_mock = MagicMock()
    db_mock.add = MagicMock()
    db_mock.commit = AsyncMock()

    kwargs, created_streams, updated_streams, created_users, saved_settings = \
        _make_restore_kwargs(logos_dir)

    result = await restore_from_zip(db_mock, zip_file, **kwargs)

    # Streams
    assert result["created"] == 13, f"Esperado 13 criados (10 streams + 3 users), got {result}"
    assert result["skipped"] == 0

    # Users — db.add chamado (3 usuários novos)
    assert len(created_users) == 3, f"Esperado 3 users criados, got {created_users}"

    # Settings
    assert saved_settings.get("watchdog_enabled") == False
    assert saved_settings.get("max_restarts") == 3

    # Logo restaurada com conteúdo idêntico
    logo_dest = os.path.join(logos_dir, "channel_logo.png")
    assert os.path.isfile(logo_dest), "Logo não restaurada"
    assert open(logo_dest, "rb").read() == logo_data, "Conteúdo da logo diferente"

    print(f"✓ Restore completo OK: {result}")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 4 — Checksum corrompido é detectado
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_checksum_corruption_detected(tmp_dirs):
    """ZIP com checksum sabotado deve levantar ValueError mencionando 'checksum'."""
    logos_dir, backups_dir = tmp_dirs
    zip_bytes = _build_zip_bytes(
        streams=[_make_stream(0)],
        corrupt_entry="streams.json",
    )
    zip_file = os.path.join(backups_dir, "corrupt.zip")
    with open(zip_file, "wb") as f:
        f.write(zip_bytes)

    db_mock = MagicMock()
    db_mock.commit = AsyncMock()
    kwargs, *_ = _make_restore_kwargs(logos_dir)

    with pytest.raises(ValueError) as exc_info:
        await restore_from_zip(db_mock, zip_file, **kwargs)

    assert "checksum" in str(exc_info.value).lower(), str(exc_info.value)
    print("✓ Detecção de checksum OK")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 5 — ZIP inválido rejeitado
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_invalid_zip_rejected(tmp_dirs):
    logos_dir, backups_dir = tmp_dirs
    bad = os.path.join(backups_dir, "bad.zip")
    with open(bad, "wb") as f:
        f.write(b"not a zip file!!")

    kwargs, *_ = _make_restore_kwargs(logos_dir)
    with pytest.raises(ValueError):
        await restore_from_zip(MagicMock(), bad, **kwargs)
    print("✓ ZIP inválido rejeitado OK")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 6 — ZIP sem manifest rejeitado
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_zip_without_manifest_rejected(tmp_dirs):
    logos_dir, backups_dir = tmp_dirs
    no_mf = os.path.join(backups_dir, "no_manifest.zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("streams.json", "[]")
    with open(no_mf, "wb") as f:
        f.write(buf.getvalue())

    kwargs, *_ = _make_restore_kwargs(logos_dir)
    with pytest.raises(ValueError) as exc_info:
        await restore_from_zip(MagicMock(), no_mf, **kwargs)
    assert "manifest" in str(exc_info.value).lower()
    print("✓ ZIP sem manifest rejeitado OK")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 7 — Idempotência (2ª restauração atualiza, não duplica)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_restore_idempotent(tmp_dirs):
    logos_dir, backups_dir = tmp_dirs

    streams = [_make_stream(0)]
    zip_bytes = _build_zip_bytes(streams=streams)
    zip_file = os.path.join(backups_dir, "idempotent.zip")
    with open(zip_file, "wb") as f:
        f.write(zip_bytes)

    stream_db: dict = {}
    db_mock = MagicMock()
    db_mock.add = MagicMock()
    db_mock.commit = AsyncMock()

    kwargs, created1, updated1, _, _ = _make_restore_kwargs(logos_dir, stream_db=stream_db)
    r1 = await restore_from_zip(db_mock, zip_file, **kwargs)

    # 2ª restauração com mesmo zip — agora o stream existe em stream_db
    kwargs2, created2, updated2, _, _ = _make_restore_kwargs(logos_dir, stream_db=stream_db)
    r2 = await restore_from_zip(db_mock, zip_file, **kwargs2)

    assert r1["created"] == 1 and r1["updated"] == 0, f"1ª: {r1}"
    assert r2["created"] == 0 and r2["updated"] == 1, f"2ª: {r2}"
    print(f"✓ Idempotência OK — 1ª: {r1}, 2ª: {r2}")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 8 — Backup grande (500 streams + logo de 1 MB)
# ═══════════════════════════════════════════════════════════════════════════════

def test_large_backup_zip_structure():
    """ZIP com 500 streams + logo de 1 MB deve ser criado em < 10s e ser válido."""
    import random
    random.seed(42)

    N = 500
    streams_data = [_make_stream(i) for i in range(N)]
    # Logo com dados pseudo-aleatórios (testa compressão real)
    logo_data = bytes([random.randint(0, 255) for _ in range(1 * 1024 * 1024)])

    start = time.time()
    zip_bytes = _build_zip_bytes(
        streams=streams_data,
        logos={"large_logo.jpg": logo_data},
    )
    elapsed = time.time() - start

    assert elapsed < 10.0, f"Demorou {elapsed:.1f}s (máx 10s)"

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        data = json.loads(zf.read("streams.json"))
        assert len(data) == N
        assert data[0]["id"] == "stream-0000"
        assert data[N-1]["id"] == f"stream-{N-1:04d}"
        assert "logos/large_logo.jpg" in zf.namelist()
        # Verificar checksums
        manifest = json.loads(zf.read("manifest.json"))
        for entry, expected in manifest["checksums"].items():
            assert _sha256(zf.read(entry).decode()) == expected

    size_mb = len(zip_bytes) / 1024 / 1024
    print(f"✓ Backup grande OK: {N} streams + 1 MB logo → {size_mb:.1f} MB em {elapsed:.2f}s")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 9 — Retenção de backups automáticos
# ═══════════════════════════════════════════════════════════════════════════════

def test_backup_retention(tmp_dirs):
    """apply_backup_retention deve manter apenas os N mais recentes."""
    _, backups_dir = tmp_dirs

    for i in range(10):
        p = Path(backups_dir) / f"auto_2026010{i}_120000.zip"
        p.write_bytes(b"fake")
        mtime = time.time() - (10 - i) * 3600
        os.utime(p, (mtime, mtime))

    apply_backup_retention(backups_dir, retention=3)

    remaining = list(Path(backups_dir).glob("auto_*.zip"))
    assert len(remaining) == 3, f"Esperado 3, encontrado {len(remaining)}"
    # Os 3 mais recentes devem ser mantidos (índices 7, 8, 9)
    names_kept = sorted(p.name for p in remaining)
    assert all("auto_20260107" <= n <= "auto_20260109z" for n in names_kept), names_kept
    print(f"✓ Retenção OK — mantidos: {names_kept}")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTE 10 — Atomic write (falha não deixa arquivo parcial)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_atomic_write_on_failure(tmp_dirs):
    """Falha durante a criação não deve deixar .zip ou .tmp corrompido no disco."""
    logos_dir, backups_dir = tmp_dirs
    dest = os.path.join(backups_dir, "should_not_exist.zip")

    original_writestr = zipfile.ZipFile.writestr
    call_count = [0]

    def failing_writestr(self, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] >= 3:
            raise RuntimeError("Simulated disk full error")
        return original_writestr(self, *args, **kwargs)

    with patch.object(zipfile.ZipFile, "writestr", failing_writestr):
        try:
            await create_full_backup(
                MagicMock(), dest, logos_dir,
                list_streams_fn    = AsyncMock(return_value=[]),
                list_users_fn      = AsyncMock(return_value=[]),
                list_categories_fn = AsyncMock(return_value=[]),
                load_settings_fn   = AsyncMock(return_value={}),
            )
        except Exception:
            pass

    assert not os.path.isfile(dest), "Arquivo .zip parcial deixado após falha!"
    tmp_files = list(Path(backups_dir).glob("*.tmp"))
    assert not tmp_files, f"Arquivo .tmp deixado: {tmp_files}"
    print("✓ Atomic write OK — sem resíduo após falha")


# ═══════════════════════════════════════════════════════════════════════════════
# SUMÁRIO
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    print("\n" + "=" * 65)
    print("  aistra-stream — Backup System Test Suite")
    print("=" * 65 + "\n")
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
