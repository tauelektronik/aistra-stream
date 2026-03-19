"""
HLS Session Manager — aistra-stream
Handles all streaming pipelines:
  • CENC-CTR (n_m3u8dl + FIFO + ffmpeg)
  • Plain HTTP/HTTPS (ffmpeg direct)
Background cleanup kills sessions idle for >60 s.
"""
import asyncio
import glob
import logging
import os
import re
import shutil
import socket
from typing import Optional

logger = logging.getLogger(__name__)

HLS_BASE  = os.getenv("HLS_BASE",  "/tmp/aistra_stream_hls")
PIPE_BASE = os.getenv("PIPE_BASE", "/tmp/aistra_stream_pipes")
TMP_BASE  = os.getenv("TMP_BASE",  "/tmp/aistra_stream_tmp")

N_M3U8DL    = os.getenv("N_M3U8DL",    "/usr/local/bin/n_m3u8dl")
MP4DECRYPT  = os.getenv("MP4DECRYPT",  "/usr/local/bin/mp4decrypt")
FFMPEG      = os.getenv("FFMPEG",      "/usr/bin/ffmpeg")
FFMPEG7     = os.getenv("FFMPEG7",     "/usr/local/bin/ffmpeg7")

# ABR quality presets: video bitrate / audio bitrate / scale filter
_QUALITY_PRESETS = {
    "1080p": {"scale": "1920:-2", "vbr": "4500k", "abr": "192k"},
    "720p":  {"scale": "1280:-2", "vbr": "2800k", "abr": "128k"},
    "480p":  {"scale": "854:-2",  "vbr": "1400k", "abr": "96k"},
    "360p":  {"scale": "640:-2",  "vbr": "800k",  "abr": "96k"},
}


def _alloc_port() -> int:
    """Grab a free ephemeral UDP port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _safe_id(stream_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)


def _height_from_resolution(res: str) -> int:
    """Return target height from resolution string, e.g. '1280x720' → 720. 0 = auto."""
    if not res or res == "original":
        return 0
    try:
        return int(res.split("x")[1])
    except Exception:
        return 0


YTDLP         = os.getenv("YTDLP",          "/usr/local/bin/yt-dlp")
YTDLP_COOKIES = os.getenv("YTDLP_COOKIES", "/opt/youtube_cookies.txt")

_YT_RE = re.compile(
    r'(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?.*v=|live/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)


async def _resolve_youtube_url(url: str, target_height: int) -> str:
    """Use yt-dlp to extract direct stream URL from a YouTube URL."""
    import subprocess as _sp

    if target_height:
        fmt = f"best[height<={target_height}][ext=mp4]/best[height<={target_height}]/best"
    else:
        fmt = "best[ext=mp4]/best"

    def _run():
        try:
            cmd = [YTDLP, "-g", "-f", fmt, "--no-playlist"]
            if YTDLP_COOKIES and os.path.exists(YTDLP_COOKIES):
                cmd += ["--cookies", YTDLP_COOKIES]
            cmd.append(url)
            result = _sp.run(
                cmd,
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
                if lines:
                    logger.info("yt-dlp resolved %d URL(s) for %s", len(lines), url)
                    return lines[0]   # video URL (audio merged by ffmpeg)
            logger.warning("yt-dlp failed: %s", result.stderr[:300])
            return url
        except Exception as exc:
            logger.warning("yt-dlp error: %s", exc)
            return url

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run)


async def _resolve_hls_variant(url: str, target_height: int) -> str:
    """
    If *url* is an HLS master playlist, return the variant URL closest to
    *target_height*. Falls back to *url* unchanged on any error or if the
    response is already a variant/TS stream.
    """
    import urllib.request as _req
    import urllib.parse   as _urlparse

    def _fetch() -> str:
        try:
            req = _req.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with _req.urlopen(req, timeout=12) as resp:
                final_url = resp.url          # URL after HTTP redirects
                raw       = resp.read(65536)  # read first 64 KB — enough for any playlist
            text = raw.decode("utf-8", errors="replace")
            if "#EXTM3U" not in text or "#EXT-X-STREAM-INF" not in text:
                return final_url   # already a variant playlist or not HLS

            variants: list[tuple[int, str]] = []   # (height, abs_url)
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF:"):
                    m = re.search(r"RESOLUTION=\d+x(\d+)", line)
                    if m and i + 1 < len(lines):
                        h      = int(m.group(1))
                        rel    = lines[i + 1].strip()
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

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


def _build_ffmpeg_video_args(stream) -> list:
    """Return ffmpeg video encoding arguments based on stream config."""
    codec = stream.video_codec
    if codec == "copy":
        return ["-c:v", "copy"]
    args = ["-c:v", codec]
    if codec == "libx264":
        args += ["-preset", stream.video_preset, "-crf", str(stream.video_crf)]
    elif codec == "h264_nvenc":
        args += ["-preset", "p4", "-rc", "vbr", "-cq", str(stream.video_crf)]
    if stream.video_maxrate:
        bsz = str(int(stream.video_maxrate.replace("k", "")) * 2) + "k"
        args += ["-maxrate", stream.video_maxrate, "-bufsize", bsz]
    if stream.video_resolution not in ("", "original"):
        w, h = stream.video_resolution.split("x") if "x" in stream.video_resolution else (stream.video_resolution, -2)
        args += ["-vf", f"scale={w}:{h}"]
    # Force keyframe at every segment boundary so each segment is self-contained
    args += ["-force_key_frames", f"expr:gte(t,n_forced*{stream.hls_time})"]
    return args


def _build_ffmpeg_audio_args(stream) -> list:
    if stream.audio_codec == "copy":
        return ["-c:a", "copy"]
    return ["-c:a", stream.audio_codec, "-b:a", stream.audio_bitrate, "-ar", "48000"]


def _build_ffmpeg_multi_quality_args(stream, hls_dir: str, url: str, qualities: list[str]) -> list:
    """Build ffmpeg args for multi-quality ABR HLS output using filter_complex split+scale."""
    ff_bin = FFMPEG7 if os.path.exists(FFMPEG7) else FFMPEG
    n = len(qualities)

    # filter_complex: split input video into N copies and scale each
    splits = "".join(f"[v{i}]" for i in range(n))
    scales = "; ".join(
        f"[v{i}]scale={_QUALITY_PRESETS[q]['scale']}[v{i}out]"
        for i, q in enumerate(qualities)
    )
    fc = f"[0:v]split={n}{splits}; {scales}"

    args = [
        ff_bin, "-hide_banner",
        "-fflags",      "+genpts+discardcorrupt",
        "-err_detect",  "ignore_err",
        "-analyzeduration", "3000000",
        "-probesize",       "5000000",
        "-reconnect",           "1",
        "-reconnect_at_eof",    "1",
        "-reconnect_streamed",  "1",
        "-reconnect_delay_max", "5",
        "-allowed_extensions",  "ALL",
    ]
    if stream.user_agent:
        args += ["-user_agent", stream.user_agent]
    args += ["-i", url, "-filter_complex", fc]

    # Map: video_i, audio for each quality
    audio_idx = getattr(stream, "audio_track", 0)
    for i in range(n):
        args += ["-map", f"[v{i}out]", "-map", f"0:a:{audio_idx}?"]

    # Video encoding — libx264 (copy can't scale)
    preset = stream.video_preset if stream.video_codec != "copy" else "ultrafast"
    args += ["-c:v", "libx264", "-preset", preset]
    for i, q in enumerate(qualities):
        vbr = _QUALITY_PRESETS[q]["vbr"]
        bufsize = str(int(vbr.replace("k", "")) * 2) + "k"
        args += [f"-b:v:{i}", vbr, f"-maxrate:v:{i}", vbr, f"-bufsize:v:{i}", bufsize]

    # Audio encoding
    args += ["-c:a", "aac"]
    for i, q in enumerate(qualities):
        args += [f"-b:a:{i}", _QUALITY_PRESETS[q]["abr"], f"-ar:a:{i}", "48000"]

    # Create subdirectories
    for q in qualities:
        os.makedirs(os.path.join(hls_dir, q), exist_ok=True)

    # var_stream_map uses quality names so %v → e.g. "720p"
    vsm = " ".join(f"v:{i},a:{i},name:{q}" for i, q in enumerate(qualities))
    args += [
        "-var_stream_map", vsm,
        "-master_pl_name", "stream.m3u8",
        "-f", "hls",
        "-hls_time",      str(stream.hls_time),
        "-hls_list_size", str(stream.hls_list_size),
        "-hls_flags",     "delete_segments+independent_segments",
        "-hls_segment_filename", os.path.join(hls_dir, "%v", "seg%05d.ts"),
        os.path.join(hls_dir, "%v", "stream.m3u8"),
    ]
    return args


class HLSManager:
    def __init__(self):
        self._sessions: dict = {}   # stream_id → session dict
        self._url_idx:  dict = {}   # stream_id → current URL index (failover/balance)
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    # ── Public API ───────────────────────────────────────────────────────────

    def start_background_cleanup(self):
        """Call once from FastAPI startup event."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("HLS manager: background cleanup started")

    async def stop_session(self, stream_id: str):
        async with self._lock:
            self._url_idx.pop(stream_id, None)   # reset failover index on explicit stop
            await self._kill_session(stream_id)

    async def get_status(self, stream_id: str) -> str:
        sess = self._sessions.get(stream_id)
        if not sess:
            return "stopped"
        if sess["proc"].returncode is None:
            return "running"
        return "error"

    def _get_active_url(self, stream) -> tuple[str, list]:
        """Return (active_url, all_urls) using round-robin index from backup_urls."""
        urls = [stream.url.strip()]
        if stream.backup_urls:
            for u in stream.backup_urls.splitlines():
                u = u.strip()
                if u and u not in urls:
                    urls.append(u)
        idx = self._url_idx.get(stream.id, 0) % len(urls)
        return urls[idx], urls

    async def get_hls_dir(self, stream, force_restart: bool = False) -> tuple[str, Optional[str]]:
        """Return (hls_dir, error). Starts or reuses a session."""
        sid = stream.id

        async with self._lock:
            sess = self._sessions.get(sid)
            if sess and not force_restart:
                if sess["proc"].returncode is None:
                    sess["last_touch"] = asyncio.get_event_loop().time()
                    return sess["hls_dir"], None
                # Process died — advance URL index (failover) before restarting
                _, urls = self._get_active_url(stream)
                self._url_idx[sid] = (self._url_idx.get(sid, 0) + 1) % len(urls)
                logger.info("Stream %s: process died, rotating to URL index %d/%d",
                            sid, self._url_idx[sid], len(urls))
                await self._kill_session(sid)

            hls_dir = os.path.join(HLS_BASE, sid)
            os.makedirs(hls_dir, exist_ok=True)

            active_url, _ = self._get_active_url(stream)
            is_cenc = (stream.drm_type == "cenc-ctr") and (
                stream.drm_keys or (stream.drm_kid and stream.drm_key)
            )
            try:
                if is_cenc:
                    sess = await self._start_cenc_session(stream, hls_dir, active_url)
                else:
                    sess = await self._start_http_session(stream, hls_dir, active_url)
            except Exception as exc:
                logger.error("HLS start failed for %s: %s", sid, exc)
                return hls_dir, str(exc)

            self._sessions[sid] = sess
            return hls_dir, None

    def touch(self, stream_id: str):
        """Update last_touch to prevent cleanup."""
        sess = self._sessions.get(stream_id)
        if sess:
            sess["last_touch"] = asyncio.get_event_loop().time()

    # ── Startup cleanup ──────────────────────────────────────────────────────

    @staticmethod
    def startup_cleanup():
        """Kill orphan processes and clear temp dirs on server start."""
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
        logger.info("Startup cleanup done")

    # ── CENC pipeline: n_m3u8dl → FIFO → ffmpeg ──────────────────────────────

    async def _start_cenc_session(self, stream, hls_dir: str, url: str) -> dict:
        sid     = _safe_id(stream.id)
        os.makedirs(PIPE_BASE, exist_ok=True)

        fifo_path = os.path.join(PIPE_BASE, f"{sid}.ts")
        if os.path.exists(fifo_path):
            os.unlink(fifo_path)
        os.mkfifo(fifo_path)

        tmp_cwd = os.path.join(TMP_BASE, sid)
        shutil.rmtree(tmp_cwd, ignore_errors=True)
        os.makedirs(tmp_cwd, exist_ok=True)

        clean_url = url.split("#")[0]   # use the rotated URL

        # Build --key args: support multi-key CDM format (drm_keys) and legacy single key
        key_pairs = []
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
            "--ffmpeg-binary-path", FFMPEG,
            "--save-dir", PIPE_BASE,
            "--save-name", sid,
        ]

        n_log = open(f"/tmp/n_m3u8dl_{sid}.log", "ab")
        n_proc = await asyncio.create_subprocess_exec(
            *n_args,
            cwd=tmp_cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=n_log,
        )

        # ffmpeg must open FIFO BEFORE n_m3u8dl writes to it
        playlist = os.path.join(hls_dir, "stream.m3u8")
        ff_args  = [
            FFMPEG, "-hide_banner",
            "-fflags", "+genpts+discardcorrupt",
            "-err_detect", "ignore_err",
            "-i", fifo_path,
            "-map", "0:v:0?", "-map", f"0:a:{stream.audio_track}?",
            "-c:v", "copy", "-c:a", "copy",
            "-f", "hls",
            "-hls_time",         str(stream.hls_time),
            "-hls_list_size",    str(stream.hls_list_size),
            "-hls_flags",        "delete_segments",
            "-hls_segment_filename", os.path.join(hls_dir, "seg%05d.ts"),
            playlist,
        ]
        ff_log  = open(f"/tmp/ffmpeg_{sid}.log", "ab")
        ff_proc = await asyncio.create_subprocess_exec(
            *ff_args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=ff_log,
        )

        return {
            "proc":       ff_proc,
            "extra_proc": n_proc,
            "hls_dir":    hls_dir,
            "fifo_path":  fifo_path,
            "ff_log":     ff_log,
            "extra_log":  n_log,
            "last_touch": asyncio.get_event_loop().time(),
        }

    # ── HTTP pipeline: ffmpeg direct ─────────────────────────────────────────

    async def _start_http_session(self, stream, hls_dir: str, url: str) -> dict:
        sid      = _safe_id(stream.id)
        playlist = os.path.join(hls_dir, "stream.m3u8")

        # Multi-quality ABR mode
        qualities = [q.strip() for q in (stream.output_qualities or "").split(",") if q.strip()]
        if qualities:
            ff_args = _build_ffmpeg_multi_quality_args(stream, hls_dir, url, qualities)
        else:
            # Single-quality mode
            active_url = url
            target_h = _height_from_resolution(stream.video_resolution)

            # YouTube URLs: use yt-dlp to extract direct stream URL
            if _YT_RE.search(url):
                active_url = await _resolve_youtube_url(url, target_h or 720)
            # For copy mode + explicit resolution: resolve the best HLS variant URL first
            elif stream.video_codec == "copy" and target_h:
                active_url = await _resolve_hls_variant(url, target_h)

            ff_bin = FFMPEG7 if os.path.exists(FFMPEG7) else FFMPEG
            is_yt  = _YT_RE.search(url)

            ff_args = [
                ff_bin, "-hide_banner",
                "-fflags",      "+genpts+discardcorrupt+igndts",
                "-err_detect",  "ignore_err",
                "-analyzeduration", "3000000",
                "-probesize",       "5000000",
            ]
            # reconnect flags only for HLS/HTTP streams, not yt-dlp direct URLs
            if not is_yt:
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

            hls_out = (
                f"[f=hls:hls_time={stream.hls_time}:hls_list_size={stream.hls_list_size}"
                f":hls_flags=delete_segments"
                f":hls_segment_filename={os.path.join(hls_dir, 'seg%05d.ts')}]{playlist}"
            )
            extra_outputs = []
            if stream.output_rtmp:
                extra_outputs.append(f"[f=flv]{stream.output_rtmp}")
            if stream.output_udp:
                extra_outputs.append(f"[f=mpegts]{stream.output_udp}")

            if extra_outputs:
                ff_args += ["-f", "tee", "|".join([hls_out] + extra_outputs)]
            else:
                ff_args += [
                    "-f", "hls",
                    "-hls_time",         str(stream.hls_time),
                    "-hls_list_size",    str(stream.hls_list_size),
                    "-hls_flags",        "delete_segments",
                    "-hls_segment_filename", os.path.join(hls_dir, "seg%05d.ts"),
                    playlist,
                ]

        # Build env: inject proxy vars (works for all protocols via ffmpeg's libavformat)
        env = os.environ.copy()
        if stream.proxy:
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env[key] = stream.proxy

        ff_log  = open(f"/tmp/ffmpeg_{sid}.log", "ab")
        ff_proc = await asyncio.create_subprocess_exec(
            *ff_args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=ff_log,
            env=env,
        )

        return {
            "proc":       ff_proc,
            "extra_proc": None,
            "hls_dir":    hls_dir,
            "fifo_path":  None,
            "ff_log":     ff_log,
            "extra_log":  None,
            "last_touch": asyncio.get_event_loop().time(),
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
            shutil.rmtree(sess["hls_dir"], ignore_errors=True)
        except Exception: pass
        logger.info("HLS session killed: %s", stream_id)

    # ── Background cleanup ───────────────────────────────────────────────────

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(30)
            now   = asyncio.get_event_loop().time()
            stale = [sid for sid, s in list(self._sessions.items())
                     if now - s.get("last_touch", now) > 60]
            for sid in stale:
                logger.info("HLS cleanup: idle session %s", sid)
                async with self._lock:
                    await self._kill_session(sid)


# Singleton
hls_manager = HLSManager()
