"""
test_visual.py — Testes das funcionalidades de detecção visual e validação de schemas.

Não requer banco de dados, FastAPI em execução, ffmpeg, nem rede.

Cobre:
  1.  _analyze_frame_sync — frame normal (ok)
  2.  _analyze_frame_sync — tela totalmente preta (black)
  3.  _analyze_frame_sync — frame congelado (frozen) — mesmo conteúdo
  4.  _analyze_frame_sync — frame ligeiramente diferente não é frozen
  5.  _analyze_frame_sync — arquivo inexistente retorna unknown
  6.  StreamCreate — URL HTTP válida aceita
  7.  StreamCreate — protocolo inválido rejeitado
  8.  StreamCreate — path traversal na URL rejeitado
  9.  StreamCreate — URL com quebra de linha rejeitada
  10. StreamCreate — DRM keys formato correto aceito
  11. StreamCreate — DRM keys formato inválido (sem ':') rejeitado
  12. StreamCreate — DRM keys KID hex inválido rejeitado
  13. StreamCreate — proxy HTTP/HTTPS válido aceito
  14. StreamCreate — proxy sem hostname rejeitado
  15. StreamCreate — output_qualities válido aceito
  16. StreamCreate — output_qualities inválido rejeitado
  17. StreamCreate — user_agent com controle char rejeitado
  18. _YT_RE — detecta URL YouTube watch
  19. _YT_RE — detecta URL YouTube youtu.be
  20. _YT_RE — não detecta URL não-YouTube

Execute:
  python -m pytest tests/test_visual.py -v
  ou
  python tests/test_visual.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers para gerar imagens JPEG sintéticas sem depender de ffmpeg
# ─────────────────────────────────────────────────────────────────────────────

def _make_jpeg(path: str, brightness: int, noise: int = 0):
    """Cria um JPEG 64×64 com brilho uniforme + ruído opcional (0–255 por pixel)."""
    from PIL import Image
    import random
    pixels = []
    for _ in range(64 * 64):
        v = brightness + random.randint(-noise, noise)
        v = max(0, min(255, v))
        pixels.append((v, v, v))
    img = Image.new("RGB", (64, 64))
    img.putdata(pixels)
    img.save(path, "JPEG", quality=95)


# ─────────────────────────────────────────────────────────────────────────────
# 1–5  _analyze_frame_sync
# ─────────────────────────────────────────────────────────────────────────────

from backend.hls_manager import _analyze_frame_sync


def test_analyze_frame_ok():
    """Frame com brilho médio normal → status 'ok'."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        path = f.name
    try:
        _make_jpeg(path, brightness=120)
        status, data = _analyze_frame_sync(path, None)
        assert status == "ok"
        assert len(data) == 32 * 32   # 1024 bytes grayscale 32×32
    finally:
        os.unlink(path)


def test_analyze_frame_black():
    """Frame totalmente preto (brilho 0) → status 'black'."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        path = f.name
    try:
        _make_jpeg(path, brightness=0)
        status, data = _analyze_frame_sync(path, None)
        assert status == "black"
    finally:
        os.unlink(path)


def test_analyze_frame_frozen_exact_same():
    """Mesmo conteúdo exato duas vezes → status 'frozen'."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        path = f.name
    try:
        _make_jpeg(path, brightness=120, noise=0)  # sem ruído = determinístico
        status1, data1 = _analyze_frame_sync(path, None)
        assert status1 == "ok"
        # Segunda chamada com os mesmos dados de pixel
        status2, data2 = _analyze_frame_sync(path, data1)
        assert status2 == "frozen"
    finally:
        os.unlink(path)


def test_analyze_frame_not_frozen_when_changed():
    """Frame com conteúdo diferente não é marcado como frozen."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        path = f.name
    try:
        _make_jpeg(path, brightness=120)
        _, prev_data = _analyze_frame_sync(path, None)

        _make_jpeg(path, brightness=200)    # conteúdo completamente diferente
        status, _ = _analyze_frame_sync(path, prev_data)
        assert status != "frozen"
    finally:
        os.unlink(path)


def test_analyze_frame_missing_file():
    """Arquivo inexistente → status 'unknown', dados vazios."""
    status, data = _analyze_frame_sync("/tmp/nao_existe_xyz.jpg", None)
    assert status == "unknown"
    assert data == b""


# ─────────────────────────────────────────────────────────────────────────────
# 6–17  Validadores Pydantic — StreamCreate
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import ValidationError
from backend.schemas import StreamCreate

_BASE = dict(
    id="test-stream",
    name="Test",
    url="http://example.com/stream.m3u8",
)


def test_schema_valid_http_url():
    s = StreamCreate(**_BASE)
    assert s.url == "http://example.com/stream.m3u8"


def test_schema_invalid_protocol_rejected():
    with pytest.raises(ValidationError) as exc:
        StreamCreate(**{**_BASE, "url": "ftp://example.com/stream.m3u8"})
    assert "Protocolo não permitido" in str(exc.value)


def test_schema_path_traversal_in_url_rejected():
    with pytest.raises(ValidationError) as exc:
        StreamCreate(**{**_BASE, "url": "http://example.com/../../../etc/passwd"})
    assert "path traversal" in str(exc.value).lower()


def test_schema_url_with_newline_rejected():
    with pytest.raises(ValidationError):
        StreamCreate(**{**_BASE, "url": "http://example.com/stream\nhttp://evil.com"})


def test_schema_drm_keys_valid():
    keys = "0102030405060708090a0b0c0d0e0f10:aabbccddeeff00112233445566778899"
    s = StreamCreate(**{**_BASE, "drm_keys": keys})
    assert s.drm_keys == keys


def test_schema_drm_keys_no_colon_rejected():
    with pytest.raises(ValidationError) as exc:
        StreamCreate(**{**_BASE, "drm_keys": "invalidsemcolon"})
    assert "KID:KEY" in str(exc.value)


def test_schema_drm_keys_invalid_hex_rejected():
    with pytest.raises(ValidationError) as exc:
        StreamCreate(**{**_BASE, "drm_keys": "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ:aabbccddeeff00112233445566778899"})
    assert "KID inválido" in str(exc.value)


def test_schema_proxy_valid():
    s = StreamCreate(**{**_BASE, "proxy": "http://proxy.example.com:3128"})
    assert "proxy.example.com" in s.proxy


def test_schema_proxy_no_hostname_rejected():
    with pytest.raises(ValidationError) as exc:
        StreamCreate(**{**_BASE, "proxy": "http://:3128"})
    assert "hostname" in str(exc.value)


def test_schema_output_qualities_valid():
    s = StreamCreate(**{**_BASE, "output_qualities": "1080p,720p,480p"})
    assert s.output_qualities == "1080p,720p,480p"


def test_schema_output_qualities_invalid_rejected():
    with pytest.raises(ValidationError) as exc:
        StreamCreate(**{**_BASE, "output_qualities": "4K,1080p"})
    assert "Qualidade inválida" in str(exc.value)


def test_schema_user_agent_control_char_rejected():
    with pytest.raises(ValidationError):
        StreamCreate(**{**_BASE, "user_agent": "Mozilla/5.0\x00injected"})


# ─────────────────────────────────────────────────────────────────────────────
# 18–20  YouTube URL detection regex (_YT_RE)
# ─────────────────────────────────────────────────────────────────────────────

from backend.hls_manager import _YT_RE


def test_yt_re_detects_watch_url():
    assert _YT_RE.search("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is not None


def test_yt_re_detects_short_url():
    assert _YT_RE.search("https://youtu.be/dQw4w9WgXcQ") is not None


def test_yt_re_does_not_match_non_youtube():
    assert _YT_RE.search("https://www.twitch.tv/channel") is None
    assert _YT_RE.search("http://example.com/video.mp4") is None


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=str(Path(__file__).parent.parent),
    )
    sys.exit(result.returncode)
