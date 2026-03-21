"""
test_core.py — Testes unitários das funções críticas do backend.

Não requer banco de dados, FastAPI em execução nem drivers MySQL.
Testa a lógica diretamente usando as mesmas bibliotecas do backend.

Cobre:
  1.  bcrypt — hash e verificação de senha corretos
  2.  bcrypt — senha errada rejeitada
  3.  JWT — round-trip (encode → decode preserva claims)
  4.  JWT — token expirado rejeitado
  5.  JWT — token adulterado rejeitado
  6.  hls_manager._safe_id — sanitização de stream IDs
  7.  hls_manager._safe_id — chars válidos preservados
  8.  hls_manager._height_from_resolution — parse correto
  9.  hls_manager._height_from_resolution — valores inválidos retornam 0
  10. path traversal — '..' bloqueado
  11. path traversal — chars especiais bloqueados
  12. path traversal — nome válido aceito dentro do diretório base
  13. recording retention — arquivos antigos deletados, novos preservados
  14. recording retention — RECORDING_RETENTION_DAYS=0 não deleta nada
  15. Prometheus format — linhas HELP/TYPE/valor para cada métrica

Execute:
  python -m pytest tests/test_core.py -v
  ou
  python tests/test_core.py
"""
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi import HTTPException
from passlib.context import CryptContext
from jose import JWTError, jwt

# ── constantes usadas nos testes ───────────────────────────────────────────
_SECRET  = "ci-test-secret-key-32-chars-minimum-ok"
_ALG     = "HS256"
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─────────────────────────────────────────────────────────────────────────────
# helpers locais (mesma lógica de backend.auth, sem importar o módulo inteiro)
# ─────────────────────────────────────────────────────────────────────────────

def _hash(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def _verify(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def _make_token(data: dict, expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=1440))
    payload["exp"] = expire
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _SECRET, algorithms=[_ALG])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")


# ─────────────────────────────────────────────────────────────────────────────
# 1–2  bcrypt
# ─────────────────────────────────────────────────────────────────────────────

def test_bcrypt_correct_password():
    h = _hash("minha_senha_secreta")
    assert _verify("minha_senha_secreta", h) is True


def test_bcrypt_wrong_password():
    h = _hash("correta")
    assert _verify("errada", h) is False


# ─────────────────────────────────────────────────────────────────────────────
# 3–5  JWT
# ─────────────────────────────────────────────────────────────────────────────

def test_jwt_round_trip():
    token = _make_token({"sub": "operador", "role": "operator"})
    payload = _decode_token(token)
    assert payload["sub"] == "operador"
    assert payload["role"] == "operator"


def test_jwt_expired_token_rejected():
    token = _make_token({"sub": "x"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(HTTPException) as exc_info:
        _decode_token(token)
    assert exc_info.value.status_code == 401


def test_jwt_tampered_token_rejected():
    token = _make_token({"sub": "admin"})
    tampered = token[:-4] + "XXXX"
    with pytest.raises(HTTPException) as exc_info:
        _decode_token(tampered)
    assert exc_info.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 6–9  hls_manager pure functions (sem dependência de DB)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_id(stream_id: str) -> str:
    """Replica exata de hls_manager._safe_id."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)


def _height_from_resolution(res: str) -> int:
    """Replica exata de hls_manager._height_from_resolution."""
    if not res or res == "original":
        return 0
    try:
        return int(res.split("x")[1])
    except Exception:
        return 0


def test_safe_id_strips_special_chars():
    # '/', '.' são substituídos por '_'
    assert _safe_id("stream/../../etc") == "stream_______etc"


def test_safe_id_allows_valid_chars():
    assert _safe_id("stream-1_OK") == "stream-1_OK"


def test_height_from_resolution_standard():
    assert _height_from_resolution("1920x1080") == 1080
    assert _height_from_resolution("1280x720") == 720


def test_height_from_resolution_invalid():
    assert _height_from_resolution("original") == 0
    assert _height_from_resolution("") == 0
    assert _height_from_resolution("not-a-resolution") == 0


# ─────────────────────────────────────────────────────────────────────────────
# 10–12  path traversal prevention (lógica de _resolve_recording_path)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_recording_path(filename: str, base: str) -> str:
    """Replica da lógica de main._resolve_recording_path com base configurável."""
    if re.search(r"[^a-zA-Z0-9_\-.]", filename) or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome inválido")
    path      = os.path.join(base, filename)
    real_base = os.path.realpath(base)
    real_path = os.path.realpath(path)
    if not real_path.startswith(real_base + os.sep):
        raise HTTPException(status_code=400, detail="Nome inválido")
    return real_path


def test_path_traversal_dotdot_blocked():
    with tempfile.TemporaryDirectory() as base:
        with pytest.raises(HTTPException) as exc_info:
            _resolve_recording_path("../../../etc/passwd", base)
        assert exc_info.value.status_code == 400


def test_path_traversal_special_chars_blocked():
    with tempfile.TemporaryDirectory() as base:
        with pytest.raises(HTTPException) as exc_info:
            _resolve_recording_path("file; rm -rf /", base)
        assert exc_info.value.status_code == 400


def test_path_traversal_valid_filename_accepted():
    with tempfile.TemporaryDirectory() as base:
        result = _resolve_recording_path("stream_abc_2026-01-01.mp4", base)
        assert os.path.realpath(base) in result
        assert "stream_abc_2026-01-01.mp4" in result


# ─────────────────────────────────────────────────────────────────────────────
# 13–14  recording retention cleanup
# ─────────────────────────────────────────────────────────────────────────────

def _make_mp4(path: str, age_days: float):
    """Cria um arquivo .mp4 fake com mtime `age_days` dias no passado."""
    with open(path, "wb") as f:
        f.write(b"\x00" * 8)
    old_mtime = time.time() - age_days * 86400
    os.utime(path, (old_mtime, old_mtime))


def _run_cleanup(rec_base: str, retention_days: int) -> int:
    """Lógica extraída de _recordings_cleanup para testar isoladamente."""
    if retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for fname in os.listdir(rec_base):
        if not fname.endswith(".mp4"):
            continue
        fpath = os.path.join(rec_base, fname)
        try:
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except OSError:
            pass
    return deleted


def test_recording_retention_deletes_old_files():
    with tempfile.TemporaryDirectory() as rec_base:
        _make_mp4(os.path.join(rec_base, "old_stream_2025.mp4"), age_days=31)
        _make_mp4(os.path.join(rec_base, "new_stream_2026.mp4"), age_days=1)
        _make_mp4(os.path.join(rec_base, "readme.txt"), age_days=100)  # não é mp4

        deleted = _run_cleanup(rec_base, retention_days=30)

        assert deleted == 1
        remaining = os.listdir(rec_base)
        assert "new_stream_2026.mp4" in remaining
        assert "old_stream_2025.mp4" not in remaining
        assert "readme.txt" in remaining  # arquivos não-mp4 não são tocados


def test_recording_retention_zero_disables_cleanup():
    with tempfile.TemporaryDirectory() as rec_base:
        _make_mp4(os.path.join(rec_base, "very_old.mp4"), age_days=9999)

        deleted = _run_cleanup(rec_base, retention_days=0)

        assert deleted == 0
        assert "very_old.mp4" in os.listdir(rec_base)


# ─────────────────────────────────────────────────────────────────────────────
# 15  Prometheus output format
# ─────────────────────────────────────────────────────────────────────────────

def test_prometheus_format():
    """A saída do /metrics deve ter linhas HELP, TYPE e valor para cada métrica."""
    lines: list[str] = []

    def g(name: str, help_: str, value, labels: str = "") -> None:
        lbl = f"{{{labels}}}" if labels else ""
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name}{lbl} {value}")

    g("aistra_streams_total",          "Total streams",   5)
    g("aistra_streams_running",        "Running streams", 3)
    g("aistra_cpu_core_usage_percent", "CPU core", 42.5, 'core="0"')

    text = "\n".join(lines)

    assert "# HELP aistra_streams_total Total streams" in text
    assert "# TYPE aistra_streams_total gauge" in text
    assert "aistra_streams_total 5" in text
    assert 'aistra_cpu_core_usage_percent{core="0"} 42.5' in text


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=str(Path(__file__).parent.parent),
    )
    sys.exit(result.returncode)
