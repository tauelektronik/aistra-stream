"""
HLS Session Manager — aistra-stream
Handles all streaming pipelines:
  • CENC-CTR (n_m3u8dl + FIFO + ffmpeg)
  • Plain HTTP/HTTPS (ffmpeg direct)
  • YouTube (yt-dlp + ffmpeg)

Background tasks:
  • Watchdog: auto-restart dead sessions (configurable retries + delay)
  • Cleanup: kill idle sessions after 60 s
"""
import asyncio
import glob
import json
import logging
import os
import re
import shutil
import socket
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

from backend.hls_utils import (
    _open_log, _alloc_port, _safe_id, _height_from_resolution,
    _parse_progress_file, _parse_stats_from_log, _scan_log_for_ban,
    _build_ffmpeg_video_args, _build_ffmpeg_audio_args, _build_ffmpeg_multi_quality_args,
    _MAX_LOG_BYTES, _QUALITY_PRESETS, _BAN_PATTERNS, _BAN_COOLDOWN_S,
)

HLS_BASE        = os.getenv("HLS_BASE",        "/tmp/aistra_stream_hls")
PIPE_BASE       = os.getenv("PIPE_BASE",       "/tmp/aistra_stream_pipes")
TMP_BASE        = os.getenv("TMP_BASE",        "/tmp/aistra_stream_tmp")
RECORDINGS_BASE = os.getenv("RECORDINGS_BASE", "/tmp/aistra_recordings")
THUMBNAILS_BASE = os.getenv("THUMBNAILS_BASE", "/tmp/aistra_thumbnails")

N_M3U8DL   = os.getenv("N_M3U8DL",   "/usr/local/bin/n_m3u8dl")
MP4DECRYPT = os.getenv("MP4DECRYPT", "/usr/local/bin/mp4decrypt")
FFMPEG     = os.getenv("FFMPEG",     "/usr/bin/ffmpeg")
FFMPEG7    = os.getenv("FFMPEG7",    "/usr/local/bin/ffmpeg7")

YTDLP         = os.getenv("YTDLP",          "/usr/local/bin/yt-dlp")
YTDLP_COOKIES = os.getenv("YTDLP_COOKIES", "/opt/youtube_cookies.txt")

# Watchdog settings
MAX_RESTARTS      = int(os.getenv("HLS_MAX_RESTARTS",      "5"))
WATCHDOG_INTERVAL = int(os.getenv("HLS_WATCHDOG_INTERVAL", "10"))
RESTART_DELAY_S   = int(os.getenv("HLS_RESTART_DELAY",     "15"))
STABLE_RUN_S      = int(os.getenv("HLS_STABLE_RUN",        "60"))  # reset count after this many seconds running
STALL_CHECKS      = int(os.getenv("HLS_STALL_CHECKS",       "3"))  # consecutive 0-bitrate polls before restart
YT_REFRESH_H      = float(os.getenv("HLS_YT_REFRESH_H",   "4.0")) # proactive YouTube URL refresh (hours)

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")

_YT_RE = re.compile(
    r'(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?.*v=|live/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)


# ── Telegram ──────────────────────────────────────────────────────────────────

async def _send_telegram(message: str) -> None:
    """Fire-and-forget Telegram notification. Silently ignores errors."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    def _post():
        try:
            url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = f"chat_id={TELEGRAM_CHAT_ID}&text={urllib.request.quote(message)}&parse_mode=HTML"
            req  = urllib.request.Request(url, data=data.encode(), method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            urllib.request.urlopen(req, timeout=8)
        except Exception as exc:
            logger.debug("Telegram send failed: %s", exc)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _post)


# ── YouTube URL resolver ───────────────────────────────────────────────────────

_NEEDS_LOGIN     = "__NEEDS_LOGIN__"     # sentinel: yt-dlp requires login, no cookies configured
_COOKIES_EXPIRED = "__COOKIES_EXPIRED__"  # sentinel: cookies provided but expired/invalid


async def _resolve_youtube_url(url: str, target_height: int,
                                cookies_content: str | None = None) -> str:
    """Resolve a YouTube URL to a direct stream URL via yt-dlp.

    Returns _NEEDS_LOGIN if YouTube requires auth and no cookies are configured.
    Returns _COOKIES_EXPIRED if cookies are configured but expired/invalid.
    cookies_content: Netscape-format cookie string (per-stream override).
    """
    import subprocess as _sp
    import tempfile as _tmp

    if target_height:
        # Sem [ext=mp4]: lives usam .ts/DASH — o filtro de extensão descartava a live
        fmt = f"best[height<={target_height}]/best"
    else:
        fmt = "best"

    def _run():
        tmp_cookie_path = None
        try:
            # -q suprime "--- live ---" e outros textos de status do yt-dlp no stdout
            # android/android_testsuite: não exigem n-challenge nem PO Token
            cmd = [
                YTDLP, "-g", "-f", fmt, "--no-playlist", "-q",
                "--extractor-args", "youtube:player_client=android,android_testsuite,android_vr",
            ]

            # Per-stream cookies take priority over global cookie file
            if cookies_content and cookies_content.strip():
                tmp = _tmp.NamedTemporaryFile(mode="w", suffix=".txt",
                                              prefix="yt_cookies_", delete=False)
                tmp.write(cookies_content)
                tmp.close()
                tmp_cookie_path = tmp.name
                cmd += ["--cookies", tmp_cookie_path]
            elif YTDLP_COOKIES and os.path.exists(YTDLP_COOKIES):
                cmd += ["--cookies", YTDLP_COOKIES]

            cmd.append(url)
            result = _sp.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                # Aceitar apenas linhas que são URLs válidas (ignora "--- live ---" etc.)
                lines = [l.strip() for l in result.stdout.strip().splitlines()
                         if l.strip().startswith("http")]
                if lines:
                    logger.info("yt-dlp resolved %d URL(s) for %s", len(lines), url)
                    return lines[0]

            stderr = result.stderr
            if "Sign in to confirm" in stderr or "bot" in stderr.lower():
                if cookies_content and cookies_content.strip():
                    logger.warning("yt-dlp: cookies expired/invalid for %s", url)
                    return _COOKIES_EXPIRED
                logger.warning("yt-dlp: YouTube requires login for %s", url)
                return _NEEDS_LOGIN

            logger.warning("yt-dlp failed: %s", stderr[:300])
            return url
        except Exception as exc:
            logger.warning("yt-dlp error: %s", exc)
            return url
        finally:
            if tmp_cookie_path:
                try:
                    os.unlink(tmp_cookie_path)
                except OSError:
                    pass

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run)


# ── Frame analysis (Pillow-based computer vision) ─────────────────────────────

def _analyze_frame_sync(img_path: str, prev_data: bytes | None) -> tuple[str, bytes]:
    """Analyze a thumbnail JPEG for visual anomalies.

    Returns (status, pixel_data_for_next_comparison) where status is:
      "ok"       — normal video content
      "black"    — average brightness below threshold (black frame / off-air)
      "frozen"   — less than 2% of pixels changed vs previous thumbnail
      "unknown"  — PIL unavailable or image unreadable
    """
    try:
        from PIL import Image  # soft import — Pillow may not be installed
        img  = Image.open(img_path).convert("L").resize((32, 32))
        data = bytes(img.getdata())   # 1024 bytes, grayscale 32×32
        mean = sum(data) / len(data)

        if mean < 10:                 # average brightness < 10/255 → black
            return "black", data

        if prev_data and len(prev_data) == len(data):
            changed = sum(1 for a, b in zip(data, prev_data) if abs(int(a) - int(b)) > 10)
            if changed < len(data) * 0.02:   # < 2% pixels changed → frozen
                return "frozen", data

        return "ok", data
    except Exception:
        return "unknown", b""


# ── HLS variant selector ──────────────────────────────────────────────────────

async def _resolve_hls_variant(url: str, target_height: int) -> str:
    import urllib.parse as _urlparse

    def _fetch() -> str:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                final_url = resp.url
                raw       = resp.read(65536)
            text = raw.decode("utf-8", errors="replace")
            if "#EXTM3U" not in text or "#EXT-X-STREAM-INF" not in text:
                return final_url

            variants: list[tuple[int, str]] = []
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF:"):
                    m = re.search(r"RESOLUTION=\d+x(\d+)", line)
                    if m and i + 1 < len(lines):
                        h   = int(m.group(1))
                        rel = lines[i + 1].strip()
                        if rel and not rel.startswith("#"):
                            variants.append((h, _urlparse.urljoin(final_url, rel)))
            if not variants:
                return final_url
            variants.sort(key=lambda v: abs(v[0] - target_height))
            chosen_h, chosen_url = variants[0]
            logger.info("HLS variant selected: %dp (target %dp) from %d variants",
                        chosen_h, target_height, len(variants))
            return chosen_url
        except Exception as exc:
            logger.warning("HLS variant resolve failed (%s) — using original URL", exc)
            return url

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


# ── HLSManager ────────────────────────────────────────────────────────────────

class HLSManager:
    def __init__(self):
        self._sessions:        dict = {}   # stream_id → session dict
        self._url_idx:         dict = {}   # stream_id → current URL index
        self._restart_counts:  dict = {}   # stream_id → consecutive restart count
        self._last_restart:    dict = {}   # stream_id → timestamp of last restart
        self._stall_counts:    dict = {}   # stream_id → consecutive zero-bitrate poll count
        self._ban_status:      dict = {}   # stream_id → {detected, http_code, url, at, count}
        self._ban_url_cooldown: dict = {}  # "stream_id:url_idx" → timestamp of ban (per URL)
        self._recordings:      dict = {}   # stream_id → {proc, path, started_at, duration_s, label, auto_task}
        self._schedules:       dict = {}   # sched_id  → {stream_id, start_at, duration_s, label, created_at}
        self._autoplay:        set  = set()  # stream_ids that must stay running (never idle-killed, infinite restarts)
        self._starting:        set  = set()  # stream_ids currently being spawned (prevents duplicate starts)
        self._needs_login:     set  = set()  # stream_ids blocked by YouTube login requirement
        self._cookies_expired: set  = set()  # stream_ids with expired/invalid YouTube cookies
        self._frame_status:    dict = {}  # stream_id → "ok"|"black"|"frozen"|"no_signal"|"unknown"
        self._prev_thumb_data: dict = {}  # stream_id → bytes (32×32 grayscale pixels for comparison)
        self._lock            = asyncio.Lock()
        self._cleanup_task:   Optional[asyncio.Task] = None
        self._watchdog_task:  Optional[asyncio.Task] = None
        self._schedule_task:  Optional[asyncio.Task] = None
        self._thumb_task:     Optional[asyncio.Task] = None
        self._schedules_file  = os.path.join(RECORDINGS_BASE, "_schedules.json")
        self._load_schedules()

    # ── Public API ───────────────────────────────────────────────────────────

    def start_background_cleanup(self):
        """Call once from FastAPI startup event."""
        self._cleanup_task   = asyncio.create_task(self._cleanup_loop())
        self._watchdog_task  = asyncio.create_task(self._watchdog_loop())
        self._schedule_task  = asyncio.create_task(self._schedule_loop())
        self._thumb_task     = asyncio.create_task(self._thumbnail_monitor_loop())
        logger.info("HLS manager: background cleanup + watchdog + scheduler + thumb-monitor started")

    async def shutdown(self):
        """Cancel background tasks and kill all active sessions. Call on app shutdown."""
        for task in (self._cleanup_task, self._watchdog_task, self._schedule_task, self._thumb_task):
            if task and not task.done():
                task.cancel()
        tasks = [t for t in (self._cleanup_task, self._watchdog_task, self._schedule_task, self._thumb_task) if t]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Kill all running sessions gracefully
        async with self._lock:
            for sid in list(self._sessions):
                await self._kill_session(sid)
        logger.info("HLS manager: shutdown complete")

    async def stop_session(self, stream_id: str):
        async with self._lock:
            self._url_idx.pop(stream_id, None)
            self._restart_counts.pop(stream_id, None)
            self._last_restart.pop(stream_id, None)
            self._stall_counts.pop(stream_id, None)
            self._starting.discard(stream_id)
            self._needs_login.discard(stream_id)
            self._cookies_expired.discard(stream_id)
            self._frame_status.pop(stream_id, None)
            self._prev_thumb_data.pop(stream_id, None)
            await self._kill_session(stream_id)

    def cleanup_stream_data(self, stream_id: str):
        """Remove all on-disk artifacts and in-memory state for a deleted stream.
        Call after stop_session() when the stream is permanently deleted.
        """
        sid = _safe_id(stream_id)
        # Remove HLS directory
        hls_dir = os.path.join(HLS_BASE, stream_id)
        if os.path.isdir(hls_dir):
            try:
                shutil.rmtree(hls_dir, ignore_errors=True)
            except OSError:
                pass
        # Remove log and progress files
        for path in (
            f"/tmp/ffmpeg_{sid}.log",
            f"/tmp/n_m3u8dl_{sid}.log",
            f"/tmp/ffmpeg_progress_{sid}.txt",
        ):
            try:
                os.unlink(path)
            except OSError:
                pass
        # Clear ban state, URL cooldowns, autoplay flag, needs_login
        self._ban_status.pop(stream_id, None)
        keys = [k for k in self._ban_url_cooldown if k.startswith(f"{stream_id}:")]
        for k in keys:
            self._ban_url_cooldown.pop(k, None)
        self._autoplay.discard(stream_id)
        self._needs_login.discard(stream_id)
        self._cookies_expired.discard(stream_id)
        self._frame_status.pop(stream_id, None)
        self._prev_thumb_data.pop(stream_id, None)

    async def get_status(self, stream_id: str) -> str:
        sess = self._sessions.get(stream_id)
        if not sess:
            return "stopped"
        if sess["proc"].returncode is None:
            return "running"
        return "error"

    def get_ban_status(self, stream_id: str) -> dict:
        """Return ban info for a stream. Empty dict = no ban detected."""
        return dict(self._ban_status.get(stream_id, {}))

    def clear_ban(self, stream_id: str):
        """Clear ban state and URL cooldowns for a stream so it can be retried."""
        self._ban_status.pop(stream_id, None)
        keys = [k for k in self._ban_url_cooldown if k.startswith(f"{stream_id}:")]
        for k in keys:
            self._ban_url_cooldown.pop(k, None)
        self._url_idx.pop(stream_id, None)   # reset URL rotation
        self._restart_counts.pop(stream_id, None)
        logger.info("Ban cleared for stream %s", stream_id)

    def enable_autoplay(self, stream_id: str):
        """Mark a stream as autoplay: keep it running indefinitely (no idle-kill, infinite restarts)."""
        self._autoplay.add(stream_id)
        self._restart_counts.pop(stream_id, None)   # reset counter so watchdog restarts immediately

    def disable_autoplay(self, stream_id: str):
        """Remove a stream from autoplay mode."""
        self._autoplay.discard(stream_id)

    def _get_active_url(self, stream) -> tuple[str, list]:
        urls = [stream.url.strip()]
        if stream.backup_urls:
            for u in stream.backup_urls.splitlines():
                u = u.strip()
                if u and u not in urls:
                    urls.append(u)
        idx = self._url_idx.get(stream.id, 0) % len(urls)
        return urls[idx], urls

    async def get_hls_dir(self, stream, force_restart: bool = False) -> tuple[str, Optional[str]]:
        """Return (hls_dir, error). Starts or reuses a session.

        Lock is held only for the fast check/cleanup phases.
        The slow ffmpeg/yt-dlp spawn runs outside the lock to avoid blocking
        other concurrent stream starts.
        """
        sid = stream.id

        # ── Phase 1: check existing session / cleanup (fast, under lock) ─────
        async with self._lock:
            if sid in self._starting:
                # Another coroutine is already spawning this stream — return hls_dir
                # optimistically; the caller will wait for the playlist anyway.
                return os.path.join(HLS_BASE, sid), None

            sess = self._sessions.get(sid)
            if sess and not force_restart:
                if sess["proc"].returncode is None:
                    sess["last_touch"] = time.monotonic()
                    return sess["hls_dir"], None
                # Process died — rotate URL for failover
                _, urls = self._get_active_url(stream)
                self._url_idx[sid] = (self._url_idx.get(sid, 0) + 1) % len(urls)
                logger.info("Stream %s: process died, rotating to URL index %d/%d",
                            sid, self._url_idx[sid], len(urls))
                await self._kill_session(sid)
            elif sess and force_restart:
                await self._kill_session(sid)

            hls_dir    = os.path.join(HLS_BASE, sid)
            active_url, _ = self._get_active_url(stream)
            is_cenc    = (stream.drm_type == "cenc_ctr") and (
                stream.drm_keys or (stream.drm_kid and stream.drm_key)
            )
            self._starting.add(sid)   # prevent duplicate concurrent starts

        os.makedirs(hls_dir, exist_ok=True)

        # ── Phase 2: spawn ffmpeg (slow — outside lock) ───────────────────────
        try:
            if is_cenc:
                sess = await self._start_cenc_session(stream, hls_dir, active_url)
            else:
                sess = await self._start_http_session(stream, hls_dir, active_url)
        except Exception as exc:
            logger.error("HLS start failed for %s: %s", sid, exc)
            async with self._lock:
                self._starting.discard(sid)
            return hls_dir, str(exc)

        # ── Phase 3: store session (fast, under lock) ─────────────────────────
        now = time.monotonic()
        sess["stream"]     = stream
        sess["started_at"] = now
        sess["last_touch"] = now
        async with self._lock:
            self._starting.discard(sid)
            self._sessions[sid] = sess
        return hls_dir, None

    def touch(self, stream_id: str):
        sess = self._sessions.get(stream_id)
        if sess:
            sess["last_touch"] = time.monotonic()

    async def get_stats(self, stream_id: str) -> dict:
        """Return latest ffmpeg stats for a stream."""
        sid      = _safe_id(stream_id)
        prog     = f"/tmp/ffmpeg_progress_{sid}.txt"
        data     = _parse_progress_file(prog)
        if not data:
            data = _parse_stats_from_log(f"/tmp/ffmpeg_{sid}.log")

        sess    = self._sessions.get(stream_id)
        running = sess is not None and sess["proc"].returncode is None

        # If no active session, treat as running when progress file is fresh (< 30 s)
        if not running and data:
            try:
                mtime = os.path.getmtime(prog)
                if time.time() - mtime < 30:
                    running = True
            except OSError:
                pass

        # Uptime: prefer session start time; fall back to out_time_us from progress
        started = sess["started_at"] if sess else None
        if started:
            uptime = int(time.monotonic() - started)
        else:
            try:
                uptime = int(int(data.get("out_time_us", 0) or 0) / 1_000_000)
            except (ValueError, TypeError):
                uptime = 0

        def _safe_int(v, default=0):
            try: return int(v or default)
            except (ValueError, TypeError): return default

        fps          = data.get("fps",   "0")
        bitrate      = data.get("bitrate", "")
        frame        = data.get("frame",  "0")
        speed        = (data.get("speed", "") or "").strip()
        drop_frames  = _safe_int(data.get("drop_frames", 0))
        dup_frames   = _safe_int(data.get("dup_frames",  0))
        total_size_b = _safe_int(data.get("total_size",  0))

        # Parse bitrate ("12345.6kbits/s", "N/A", or plain number)
        bitrate_kbps = 0.0
        if bitrate and bitrate != "N/A":
            m = re.search(r"([\d.]+)", bitrate)
            if m:
                val = float(m.group(1))
                bitrate_kbps = val if val < 100000 else val / 1000

        ban = self._ban_status.get(stream_id, {})
        return {
            "running":        running,
            "uptime_s":       uptime,
            "fps":            fps,
            "bitrate_kbps":   round(bitrate_kbps, 1),
            "frame":          frame,
            "speed":          speed,
            "drop_frames":    drop_frames,
            "dup_frames":     dup_frames,
            "total_size_mb":  round(total_size_b / 1024 / 1024, 1) if total_size_b else 0,
            "ban_detected":   ban.get("detected", False),
            "ban_http_code":  ban.get("http_code", 0),
            "ban_count":      ban.get("count", 0),
            "ban_at":         ban.get("at", None),
            "restart_count":  self._restart_counts.get(stream_id, 0),
            "max_restarts":   MAX_RESTARTS,
            "needs_login":       stream_id in self._needs_login,
            "cookies_expired":   stream_id in self._cookies_expired,
            "frame_status":      self._frame_status.get(stream_id, "unknown"),
        }

    # ── Recording ────────────────────────────────────────────────────────────

    async def start_recording(
        self,
        stream_id: str,
        duration_s: Optional[int] = None,
        label: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """Start recording the HLS stream to an .mp4 file.

        Args:
            stream_id:  Stream identifier.
            duration_s: Stop recording after this many seconds (None = indefinite).
            label:      Optional tag embedded in the output filename.
        """
        if stream_id in self._recordings:
            rec = self._recordings[stream_id]
            if rec["proc"].returncode is None:
                return rec["path"], None  # already recording

        os.makedirs(RECORDINGS_BASE, exist_ok=True)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        sid = _safe_id(stream_id)
        lbl = f"_{_safe_id(label)}" if label else ""
        path = os.path.join(RECORDINGS_BASE, f"{sid}{lbl}_{ts}.mp4")

        # Read from HLS output directory
        hls_dir  = os.path.join(HLS_BASE, stream_id)
        playlist = os.path.join(hls_dir, "stream.m3u8")
        if not os.path.exists(playlist):
            return "", "Stream não está rodando"

        ff_args = [
            FFMPEG, "-hide_banner", "-y",
            "-fflags", "+discardcorrupt",
            "-i", playlist,
            "-map", "0:v:0",        # first video stream
            "-map", "0:a:0",        # first audio stream
            "-c:v", "copy",         # video passthrough (no re-encode)
            "-c:a", "aac",          # re-encode audio — avoids ADTS/BSF issues
            "-b:a", "192k",
            "-avoid_negative_ts", "make_zero",
            # Fragmented MP4: writes moov atoms incrementally so the file is
            # always valid even if recording is stopped before natural end.
            "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        ]
        if duration_s:
            ff_args += ["-t", str(duration_s)]
        ff_args.append(path)

        log  = _open_log(f"/tmp/ffmpeg_rec_{sid}.log")
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *ff_args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=log,
            ),
            timeout=15,
        )

        # Background task that removes the entry once ffmpeg finishes naturally
        async def _on_done():
            try:
                await proc.wait()
            finally:
                entry = self._recordings.get(stream_id)
                if entry and entry.get("proc") is proc:
                    self._recordings.pop(stream_id, None)
                    try:
                        log.close()
                    except Exception:
                        pass

        auto_task = asyncio.create_task(_on_done())

        self._recordings[stream_id] = {
            "proc":       proc,
            "path":       path,
            "log":        log,
            "started_at": datetime.now().isoformat(),
            "duration_s": duration_s,
            "label":      label or "",
            "auto_task":  auto_task,
        }
        logger.info("Recording started for %s → %s (duration=%s)", stream_id, path, duration_s)
        return path, None

    async def stop_recording(self, stream_id: str) -> Optional[str]:
        """Stop recording; returns the output file path."""
        rec = self._recordings.pop(stream_id, None)
        if not rec:
            return None
        # Cancel the auto-done task
        task = rec.get("auto_task")
        if task and not task.done():
            task.cancel()
        proc = rec["proc"]
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        try:
            rec["log"].close()
        except Exception:
            pass
        logger.info("Recording stopped for %s → %s", stream_id, rec["path"])
        return rec["path"]

    def get_recording_status(self, stream_id: str) -> Optional[dict]:
        rec = self._recordings.get(stream_id)
        if not rec:
            return None
        running = rec["proc"].returncode is None
        size    = 0
        try:
            size = os.path.getsize(rec["path"])
        except Exception:
            pass
        return {
            "recording":  running,
            "path":       rec["path"],
            "filename":   os.path.basename(rec["path"]),
            "started_at": rec["started_at"],
            "size_bytes": size,
            "duration_s": rec.get("duration_s"),
            "label":      rec.get("label", ""),
        }

    # ── Schedule persistence ─────────────────────────────────────────────────

    def _load_schedules(self):
        try:
            if os.path.isfile(self._schedules_file):
                with open(self._schedules_file, "r") as f:
                    self._schedules = json.load(f)
                logger.info("Loaded %d schedule(s) from %s", len(self._schedules), self._schedules_file)
        except Exception as exc:
            logger.warning("Could not load schedules: %s", exc)

    def _save_schedules(self):
        try:
            os.makedirs(RECORDINGS_BASE, exist_ok=True)
            with open(self._schedules_file, "w") as f:
                json.dump(self._schedules, f, indent=2)
        except Exception as exc:
            logger.warning("Could not save schedules: %s", exc)

    def add_schedule(
        self,
        stream_id: str,
        start_at: float,         # Unix timestamp
        duration_s: Optional[int],
        label: str = "",
        repeat: str = "none",    # none / daily / weekly
    ) -> str:
        sched_id = str(uuid.uuid4())[:8]
        self._schedules[sched_id] = {
            "stream_id":  stream_id,
            "start_at":   start_at,
            "duration_s": duration_s,
            "label":      label,
            "repeat":     repeat,
            "created_at": time.time(),
        }
        self._save_schedules()
        logger.info("Schedule %s added: stream=%s start_at=%s repeat=%s", sched_id, stream_id, start_at, repeat)
        return sched_id

    def remove_schedule(self, sched_id: str) -> bool:
        if sched_id not in self._schedules:
            return False
        del self._schedules[sched_id]
        self._save_schedules()
        logger.info("Schedule %s removed", sched_id)
        return True

    def list_schedules(self, stream_id: Optional[str] = None) -> list:
        result = []
        for sid, s in self._schedules.items():
            if stream_id and s["stream_id"] != stream_id:
                continue
            result.append({"id": sid, **s})
        result.sort(key=lambda x: x.get("start_at", 0))
        return result

    # ── Schedule background loop ─────────────────────────────────────────────

    async def _schedule_loop(self):
        """Check every 30 s for schedules that are due and fire them."""
        while True:
            await asyncio.sleep(30)
            now = time.time()
            to_fire = [
                (sid, dict(s))
                for sid, s in list(self._schedules.items())
                if s.get("start_at", float("inf")) <= now
            ]
            for sched_id, sched in to_fire:
                stream_id  = sched["stream_id"]
                duration_s = sched.get("duration_s")
                label      = sched.get("label") or "sched"
                repeat     = sched.get("repeat", "none")

                logger.info(
                    "Schedule %s fired: stream=%s duration=%s repeat=%s",
                    sched_id, stream_id, duration_s, repeat,
                )
                path, err = await self.start_recording(stream_id, duration_s=duration_s, label=label)
                if err:
                    logger.warning("Schedule %s: could not start recording for %s: %s", sched_id, stream_id, err)
                else:
                    logger.info("Schedule %s: recording started → %s", sched_id, path)

                # Advance or remove
                if repeat == "daily" and sched_id in self._schedules:
                    self._schedules[sched_id]["start_at"] += 86400
                elif repeat == "weekly" and sched_id in self._schedules:
                    self._schedules[sched_id]["start_at"] += 7 * 86400
                else:
                    self._schedules.pop(sched_id, None)

                self._save_schedules()

    @staticmethod
    def list_recordings(stream_id: Optional[str] = None) -> list[dict]:
        sid     = _safe_id(stream_id) if stream_id else None
        pattern = os.path.join(RECORDINGS_BASE, f"{sid}_*.mp4" if sid else "*.mp4")
        files   = []
        for path in sorted(glob.glob(pattern), reverse=True):
            try:
                stat = os.stat(path)
                files.append({
                    "filename":     os.path.basename(path),
                    "path":         path,
                    "size_bytes":   stat.st_size,
                    "created_at":   datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "stream_id":    os.path.basename(path).rsplit("_", 2)[0] if sid is None else stream_id,
                })
            except Exception:
                pass
        return files

    # ── Thumbnails ───────────────────────────────────────────────────────────

    async def capture_thumbnail(self, stream_id: str) -> Optional[str]:
        """Capture a JPEG thumbnail from the latest HLS segment."""
        sid     = _safe_id(stream_id)
        hls_dir = os.path.join(HLS_BASE, stream_id)
        os.makedirs(THUMBNAILS_BASE, exist_ok=True)
        out_path = os.path.join(THUMBNAILS_BASE, f"{sid}.jpg")

        # Find latest segment
        segs = sorted(glob.glob(os.path.join(hls_dir, "seg*.ts")))
        # For multi-quality, check subdirs too
        if not segs:
            for q in ("720p", "1080p", "480p", "360p"):
                segs = sorted(glob.glob(os.path.join(hls_dir, q, "seg*.ts")))
                if segs:
                    break
        if not segs:
            return None

        seg = segs[-1]

        def _run():
            import subprocess as _sp
            try:
                result = _sp.run([
                    FFMPEG, "-hide_banner", "-y",
                    "-i", seg,
                    "-vframes", "1",
                    "-q:v", "3",
                    "-vf", "scale=320:-2",
                    out_path,
                ], capture_output=True, timeout=10)
                return out_path if result.returncode == 0 and os.path.exists(out_path) else None
            except Exception:
                return None

        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, _run)
        if path:
            prev  = self._prev_thumb_data.get(stream_id)
            status, thumb_data = await loop.run_in_executor(
                None, _analyze_frame_sync, path, prev
            )
            self._frame_status[stream_id]    = status
            self._prev_thumb_data[stream_id] = thumb_data
        return path

    async def _thumbnail_monitor_loop(self):
        """Background task: capture and analyze thumbnails every 30 s for all running streams."""
        await asyncio.sleep(15)   # stagger start so watchdog runs first
        while True:
            for sid in list(self._sessions):
                try:
                    if self._sessions[sid]["proc"].returncode is None:
                        await self.capture_thumbnail(sid)
                except Exception as exc:
                    logger.debug("Thumbnail monitor %s: %s", sid, exc)
            await asyncio.sleep(30)

    # ── Startup cleanup ──────────────────────────────────────────────────────

    @staticmethod
    def startup_cleanup():
        import subprocess as sp
        for cmd in [
            ["pkill", "-9", "-f", HLS_BASE],
            ["pkill", "-9", "-f", PIPE_BASE],
            ["pkill", "-9", "n_m3u8dl"],
            ["pkill", "-9", "tsdecrypt"],
        ]:
            try: sp.run(cmd, capture_output=True)
            except Exception: pass
        for d in (HLS_BASE, TMP_BASE):
            shutil.rmtree(d, ignore_errors=True)
        for f in glob.glob(f"{PIPE_BASE}/*.ts"):
            try: os.unlink(f)
            except Exception: pass
        # Clean up leftover ffmpeg log/progress files from previous run
        for pattern in ("/tmp/ffmpeg_*.log", "/tmp/ffmpeg_progress_*.txt", "/tmp/ffmpeg_rec_*.log"):
            for f in glob.glob(pattern):
                try: os.unlink(f)
                except Exception: pass
        logger.info("Startup cleanup done")
        # Validate critical binaries on startup so failures are visible immediately
        for binary, name in [(FFMPEG, "ffmpeg"), (N_M3U8DL, "n_m3u8dl"),
                              (YTDLP, "yt-dlp"), (MP4DECRYPT, "mp4decrypt")]:
            if not os.path.isfile(binary):
                logger.warning("Binary NOT FOUND: %s → %s  (some features disabled)", name, binary)
            elif not os.access(binary, os.X_OK):
                logger.warning("Binary NOT EXECUTABLE: %s → %s  (check permissions)", name, binary)
            else:
                logger.info("Binary OK: %-12s → %s", name, binary)

    # ── CENC pipeline: n_m3u8dl → FIFO → ffmpeg ──────────────────────────────

    async def _start_cenc_session(self, stream, hls_dir: str, url: str) -> dict:
        sid = _safe_id(stream.id)

        if not os.path.isfile(N_M3U8DL):
            raise RuntimeError(
                f"Binário DRM não encontrado: {N_M3U8DL}. "
                "Reinstale com suporte DRM: bash install.sh (sem --no-drm)."
            )
        if not os.path.isfile(MP4DECRYPT):
            raise RuntimeError(
                f"Binário DRM não encontrado: {MP4DECRYPT}. "
                "Reinstale com suporte DRM: bash install.sh (sem --no-drm)."
            )

        os.makedirs(PIPE_BASE, exist_ok=True)

        # Remove all leftover files/pipes for this stream ID so n_m3u8dl
        # does not append ".copy" suffix to output names on restart
        import glob as _glob
        for _f in _glob.glob(os.path.join(PIPE_BASE, f"{sid}.*")):
            try: os.unlink(_f)
            except Exception: pass

        fifo_path = os.path.join(PIPE_BASE, f"{sid}.ts")
        os.mkfifo(fifo_path)

        tmp_cwd = os.path.join(TMP_BASE, sid)
        shutil.rmtree(tmp_cwd, ignore_errors=True)
        os.makedirs(tmp_cwd, exist_ok=True)

        clean_url  = url.split("#")[0]
        key_pairs  = []
        if stream.drm_keys:
            for line in stream.drm_keys.splitlines():
                line = line.strip()
                if ":" in line and len(line) >= 33:
                    kid, _, key = line.partition(":")
                    kid = kid.strip().replace(" ", "").lower()
                    key = key.strip().replace(" ", "").lower()
                    if kid and key:
                        key_pairs.append(f"{kid}:{key}")
        if not key_pairs and stream.drm_kid and stream.drm_key:
            key_pairs.append(f"{stream.drm_kid}:{stream.drm_key}")

        n_args = [
            N_M3U8DL, clean_url,
            "-sv", "res=1280*:for=best",
            "-sa", "best",
            "--no-ansi-color",
        ]
        for kp in key_pairs:
            n_args += ["--key", kp]
        if stream.user_agent:
            n_args += ["--header", f"User-Agent:{stream.user_agent}"]
        if stream.proxy:
            n_args += ["--custom-proxy", stream.proxy]
        n_args += [
            "--decryption-binary-path", MP4DECRYPT,
            "--live-real-time-merge",
            "--live-pipe-mux",
            "--ffmpeg-binary-path",   FFMPEG,
            "--save-dir",             PIPE_BASE,
            "--save-name",            sid,
        ]

        n_log  = _open_log(f"/tmp/n_m3u8dl_{sid}.log")
        n_proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *n_args,
                cwd=tmp_cwd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=n_log,
            ),
            timeout=15,
        )

        playlist = os.path.join(hls_dir, "stream.m3u8")
        prog_path = f"/tmp/ffmpeg_progress_{sid}.txt"
        ff_args  = [
            FFMPEG, "-hide_banner",
            "-fflags",    "+genpts+discardcorrupt",
            "-err_detect", "ignore_err",
            "-i", fifo_path,
            "-map", "0:v:0?", "-map", f"0:a:{stream.audio_track}?",
            "-c:v", "copy", "-c:a", "copy",
            "-progress", prog_path,
            "-f", "hls",
            "-hls_time",             str(stream.hls_time),
            "-hls_list_size",        str(stream.hls_list_size),
            "-hls_flags",            "delete_segments+omit_endlist",
            "-hls_segment_filename", os.path.join(hls_dir, "seg%05d.ts"),
            playlist,
        ]
        ff_log = _open_log(f"/tmp/ffmpeg_{sid}.log")
        try:
            ff_proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *ff_args,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=ff_log,
                ),
                timeout=15,
            )
        except Exception:
            # ffmpeg spawn failed — kill n_m3u8dl and clean up FIFO
            try: n_proc.kill()
            except Exception: pass
            try: n_log.close()
            except Exception: pass
            try: ff_log.close()
            except Exception: pass
            try: os.unlink(fifo_path)
            except Exception: pass
            try: shutil.rmtree(tmp_cwd, ignore_errors=True)
            except Exception: pass
            raise

        return {
            "proc":       ff_proc,
            "extra_proc": n_proc,
            "hls_dir":    hls_dir,
            "fifo_path":  fifo_path,
            "tmp_cwd":    tmp_cwd,
            "ff_log":     ff_log,
            "extra_log":  n_log,
            "prog_path":  prog_path,
        }

    # ── HTTP pipeline: ffmpeg direct ─────────────────────────────────────────

    async def _start_http_session(self, stream, hls_dir: str, url: str) -> dict:
        sid      = _safe_id(stream.id)
        playlist = os.path.join(hls_dir, "stream.m3u8")

        # VOD: file:// → local path
        is_vod     = stream.stream_type == "vod" or url.startswith("file://")
        local_path = None
        if url.startswith("file://"):
            local_path = url[7:]   # strip "file://"
            if not os.path.isfile(local_path):
                raise FileNotFoundError(f"Arquivo não encontrado: {local_path}")

        qualities = [q.strip() for q in (stream.output_qualities or "").split(",") if q.strip()]
        if qualities:
            ff_args = _build_ffmpeg_multi_quality_args(stream, hls_dir, local_path or url, qualities, ffmpeg=FFMPEG, ffmpeg7=FFMPEG7)
        else:
            active_url = local_path or url
            target_h   = _height_from_resolution(stream.video_resolution)

            if not local_path:
                if _YT_RE.search(url):
                    yt_cookies = getattr(stream, "yt_cookies", None)
                    active_url = await _resolve_youtube_url(url, target_h or 720,
                                                            cookies_content=yt_cookies)
                    if active_url == _COOKIES_EXPIRED:
                        self._cookies_expired.add(stream.id)
                        self._needs_login.discard(stream.id)
                        return hls_dir, "Cookies do YouTube expirados. Exporte novos cookies do navegador e cole nas configurações do stream."
                    if active_url == _NEEDS_LOGIN:
                        self._needs_login.add(stream.id)
                        self._cookies_expired.discard(stream.id)
                        return hls_dir, "YouTube requer login. Cole os cookies do navegador nas configurações do stream."
                    self._needs_login.discard(stream.id)
                    self._cookies_expired.discard(stream.id)
                elif stream.video_codec == "copy" and target_h:
                    active_url = await _resolve_hls_variant(url, target_h)

            ff_bin = FFMPEG7 if os.path.exists(FFMPEG7) else FFMPEG
            is_yt  = _YT_RE.search(url)

            ff_args = [
                ff_bin, "-hide_banner",
                "-fflags",          "+genpts+discardcorrupt+igndts",
                "-err_detect",      "ignore_err",
                "-analyzeduration", "3000000",
                "-probesize",       "5000000",
            ]
            # VOD: loop the file
            if is_vod and local_path:
                ff_args += ["-stream_loop", "-1"]
            elif not is_yt:
                ff_args += [
                    "-reconnect",            "1",
                    "-reconnect_at_eof",     "1",
                    "-reconnect_streamed",   "1",
                    "-reconnect_delay_max",  "5",
                    "-allowed_extensions",   "ALL",
                ]
            if stream.user_agent:
                ff_args += ["-user_agent", stream.user_agent]
            ff_args += ["-i", active_url]
            ff_args += ["-map", "0:v:0?", "-map", f"0:a:{stream.audio_track}?"]
            ff_args += _build_ffmpeg_video_args(stream)
            ff_args += _build_ffmpeg_audio_args(stream)

        prog_path = f"/tmp/ffmpeg_progress_{sid}.txt"

        if qualities:
            # multi-quality: ff_args already complete — inject -progress before output
            # Find the last positional arg (the output pattern) and inject before it
            ff_args = ff_args[:-1] + ["-progress", prog_path] + [ff_args[-1]]
        else:
            hls_out = (
                f"[f=hls:hls_time={stream.hls_time}:hls_list_size={stream.hls_list_size}"
                f":hls_flags=delete_segments+omit_endlist"
                f":hls_segment_filename={os.path.join(hls_dir, 'seg%05d.ts')}]{playlist}"
            )
            extra_outputs = []
            if stream.output_rtmp:
                extra_outputs.append(f"[f=flv]{stream.output_rtmp}")
            if stream.output_udp:
                extra_outputs.append(f"[f=mpegts]{stream.output_udp}")

            if extra_outputs:
                ff_args += ["-progress", prog_path,
                            "-f", "tee", "|".join([hls_out] + extra_outputs)]
            else:
                ff_args += [
                    "-progress",             prog_path,
                    "-f",                    "hls",
                    "-hls_time",             str(stream.hls_time),
                    "-hls_list_size",        str(stream.hls_list_size),
                    "-hls_flags",            "delete_segments+omit_endlist",
                    "-hls_segment_filename", os.path.join(hls_dir, "seg%05d.ts"),
                    playlist,
                ]

        env = os.environ.copy()
        if stream.proxy:
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env[key] = stream.proxy

        ff_log  = _open_log(f"/tmp/ffmpeg_{sid}.log")
        try:
            ff_proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *ff_args,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=ff_log,
                    env=env,
                ),
                timeout=15,
            )
        except Exception:
            try: ff_log.close()
            except Exception: pass
            raise

        return {
            "proc":       ff_proc,
            "extra_proc": None,
            "hls_dir":    hls_dir,
            "fifo_path":  None,
            "ff_log":     ff_log,
            "extra_log":  None,
            "prog_path":  prog_path,
        }

    # ── Session kill ─────────────────────────────────────────────────────────

    async def _kill_session(self, stream_id: str):
        sess = self._sessions.pop(stream_id, None)
        if not sess:
            return
        for key in ("proc", "extra_proc"):
            try:
                p = sess.get(key)
                if p and p.returncode is None:
                    p.kill()
            except Exception: pass
        for key in ("ff_log", "extra_log"):
            try:
                f = sess.get(key)
                if f: f.close()
            except Exception: pass
        try:
            fp = sess.get("fifo_path")
            if fp: os.unlink(fp)
        except Exception: pass
        try:
            tc = sess.get("tmp_cwd")
            if tc:
                shutil.rmtree(tc, ignore_errors=True)
        except Exception: pass
        try:
            shutil.rmtree(sess["hls_dir"], ignore_errors=True)
        except Exception: pass
        logger.info("HLS session killed: %s", stream_id)

    # ── Background cleanup ───────────────────────────────────────────────────

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(30)
            now   = time.monotonic()
            stale = [
                sid for sid, s in list(self._sessions.items())
                if now - s.get("last_touch", now) > 60
                and sid not in self._autoplay   # never idle-kill autoplay streams
            ]
            for sid in stale:
                logger.info("HLS cleanup: idle session %s", sid)
                try:
                    async with self._lock:
                        await self._kill_session(sid)
                except Exception as exc:
                    logger.error("HLS cleanup error for %s: %s", sid, exc)

    # ── Watchdog (auto-restart + stall detection + YouTube refresh) ──────────

    async def _watchdog_loop(self):
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            now = time.monotonic()

            to_restart: list[tuple[str, object, int, str]] = []  # (sid, stream, count, reason)

            for sid, sess in list(self._sessions.items()):
                proc    = sess["proc"]
                stream  = sess.get("stream")
                started = sess.get("started_at", now)
                uptime  = now - started

                # ── Process still running ─────────────────────────────────
                if proc.returncode is None:
                    # Reset restart count after stable run
                    if uptime > STABLE_RUN_S and self._restart_counts.get(sid, 0) > 0:
                        logger.info("Stream %s: stable for %ds — reset restart count", sid, STABLE_RUN_S)
                        self._restart_counts[sid] = 0
                        self._stall_counts[sid]   = 0

                    # ── Stall detection: zero bitrate for N consecutive polls ──
                    if stream and uptime > 30:   # skip first 30s (startup)
                        stats = _parse_progress_file(f"/tmp/ffmpeg_progress_{_safe_id(sid)}.txt")
                        if not stats:
                            stats = _parse_stats_from_log(f"/tmp/ffmpeg_{_safe_id(sid)}.log")
                        kbps = 0.0
                        if stats.get("bitrate"):
                            m = re.search(r"([\d.]+)", stats["bitrate"])
                            if m:
                                v = float(m.group(1))
                                kbps = v if v < 100000 else v / 1000
                        if kbps < 1.0:
                            cnt = self._stall_counts.get(sid, 0) + 1
                            self._stall_counts[sid] = cnt
                            if cnt >= STALL_CHECKS:
                                logger.warning("Stream %s: stalled (%d consecutive 0-bitrate polls)", sid, cnt)
                                last_restart = self._last_restart.get(sid, 0)
                                if now - last_restart >= RESTART_DELAY_S:
                                    count = self._restart_counts.get(sid, 0)
                                    if count < MAX_RESTARTS:
                                        to_restart.append((sid, stream, count, "stall"))
                        else:
                            self._stall_counts[sid] = 0

                    # ── Segment freshness: detect source offline even when ffmpeg runs ──
                    if stream and uptime > 60:
                        hls_dir  = os.path.join(HLS_BASE, sid)
                        segs     = glob.glob(os.path.join(hls_dir, "seg*.ts"))
                        if not segs:
                            for _q in ("720p", "1080p", "480p", "360p"):
                                segs = glob.glob(os.path.join(hls_dir, _q, "seg*.ts"))
                                if segs:
                                    break
                        if segs:
                            latest_age = time.time() - os.path.getmtime(max(segs, key=os.path.getmtime))
                            hls_time_s = getattr(stream, "hls_time", 15)
                            if latest_age > hls_time_s * 3:
                                self._frame_status[sid] = "no_signal"
                            elif self._frame_status.get(sid) == "no_signal":
                                self._frame_status.pop(sid, None)

                    # ── YouTube proactive URL refresh ─────────────────────
                    if stream and _YT_RE.search(getattr(stream, "url", "")):
                        yt_refresh_s = YT_REFRESH_H * 3600
                        if uptime > yt_refresh_s:
                            logger.info("Stream %s: YouTube URL refresh after %.1fh", sid, uptime / 3600)
                            last_restart = self._last_restart.get(sid, 0)
                            if now - last_restart >= RESTART_DELAY_S:
                                count = self._restart_counts.get(sid, 0)
                                to_restart.append((sid, stream, count, "yt_refresh"))

                    continue  # still running — done

                # ── Process dead ──────────────────────────────────────────
                last_touch = sess.get("last_touch", 0)
                if now - last_touch > 120:
                    continue   # idle — cleanup will handle it
                count = self._restart_counts.get(sid, 0)
                if count >= MAX_RESTARTS and sid not in self._autoplay:
                    if count == MAX_RESTARTS:
                        logger.warning("Stream %s: max restarts (%d) reached, giving up", sid, MAX_RESTARTS)
                        self._restart_counts[sid] = MAX_RESTARTS + 1
                    continue
                # Autoplay streams: reset counter so they restart indefinitely
                if sid in self._autoplay and count >= MAX_RESTARTS:
                    logger.info("Stream %s: autoplay — resetting restart count (was %d)", sid, count)
                    self._restart_counts[sid] = 0
                    count = 0
                last_restart = self._last_restart.get(sid, 0)
                if now - last_restart < RESTART_DELAY_S:
                    continue   # too soon

                # ── Ban detection: scan logs before deciding restart reason ─
                if stream:
                    ssid = _safe_id(sid)
                    ban_detected, ban_code = False, 0
                    for log_path in [f"/tmp/ffmpeg_{ssid}.log", f"/tmp/n_m3u8dl_{ssid}.log"]:
                        detected, code = _scan_log_for_ban(log_path)
                        if detected:
                            ban_detected, ban_code = True, code
                            break

                    if ban_detected:
                        # Record ban per (stream_id, url_idx) with timestamp
                        cur_idx  = self._url_idx.get(sid, 0)
                        ban_key  = f"{sid}:{cur_idx}"
                        self._ban_url_cooldown[ban_key] = now

                        prev = self._ban_status.get(sid, {})
                        self._ban_status[sid] = {
                            "detected":  True,
                            "http_code": ban_code,
                            "at":        now,
                            "count":     prev.get("count", 0) + 1,
                        }
                        logger.warning(
                            "Stream %s: BAN DETECTED (HTTP %d) on URL index %d",
                            sid, ban_code, cur_idx,
                        )
                        # Rotate to next URL immediately, skipping banned ones
                        _, urls = self._get_active_url(stream)
                        next_idx = (cur_idx + 1) % len(urls)
                        # Find first URL not in cooldown
                        found = False
                        for i in range(len(urls)):
                            candidate = (cur_idx + 1 + i) % len(urls)
                            ckey = f"{sid}:{candidate}"
                            banned_at = self._ban_url_cooldown.get(ckey, 0)
                            if now - banned_at > _BAN_COOLDOWN_S:
                                next_idx = candidate
                                found = True
                                break
                        self._url_idx[sid] = next_idx
                        reason = "ban"
                        if not found:
                            logger.warning("Stream %s: ALL URLs banned — waiting cooldown", sid)
                            reason = "ban_all"
                        to_restart.append((sid, stream, count, reason))
                        continue

                    to_restart.append((sid, stream, count, "crash"))

            for sid, stream, count, reason in to_restart:
                reason_label = {
                    "crash":      "reiniciado (crash)",
                    "stall":      "reiniciado (stream travado)",
                    "yt_refresh": "URL YouTube atualizada",
                    "ban":        "reiniciado (URL banida — trocando para backup)",
                    "ban_all":    "TODAS as URLs banidas — aguardando cooldown",
                }.get(reason, reason)

                logger.info("Watchdog: %s stream %s (attempt %d/%d)", reason_label, sid, count + 1, MAX_RESTARTS)
                if reason not in ("yt_refresh", "ban_all"):
                    self._restart_counts[sid] = count + 1
                self._last_restart[sid]   = now
                self._stall_counts[sid]   = 0

                # Skip restart if all URLs are banned (waiting cooldown)
                if reason == "ban_all":
                    ban_info = self._ban_status.get(sid, {})
                    asyncio.create_task(_send_telegram(
                        f"🚫 <b>aistra-stream — BAN DETECTADO</b>\n"
                        f"Stream: <code>{sid}</code>\n"
                        f"HTTP: <b>{ban_info.get('http_code', '?')}</b>\n"
                        f"Todas as URLs estão banidas.\n"
                        f"Aguardando cooldown de {_BAN_COOLDOWN_S // 60} min."
                    ))
                    continue

                try:
                    await self.get_hls_dir(stream, force_restart=(reason in ("yt_refresh", "ban")))
                    logger.info("Watchdog: stream %s %s OK", sid, reason_label)
                    if reason == "ban":
                        ban_info = self._ban_status.get(sid, {})
                        asyncio.create_task(_send_telegram(
                            f"🚫 <b>aistra-stream — BAN DETECTADO</b>\n"
                            f"Stream: <code>{sid}</code>\n"
                            f"HTTP: <b>{ban_info.get('http_code', '?')}</b>\n"
                            f"Trocando para URL backup (tentativa {count+1})."
                        ))
                    else:
                        asyncio.create_task(_send_telegram(
                            f"🔄 <b>aistra-stream</b>\n"
                            f"Stream <code>{sid}</code> {reason_label}"
                            + (f" (tentativa {count+1}/{MAX_RESTARTS})" if reason == "crash" else "")
                        ))
                except Exception as exc:
                    logger.error("Watchdog: restart failed for %s: %s", sid, exc)
                    if reason != "yt_refresh":
                        asyncio.create_task(_send_telegram(
                            f"❌ <b>aistra-stream</b>\n"
                            f"Falha ao reiniciar stream <code>{sid}</code>: {exc}"
                        ))


# Singleton
hls_manager = HLSManager()
