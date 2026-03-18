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


def _alloc_port() -> int:
    """Grab a free ephemeral UDP port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _safe_id(stream_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)


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
        urls = [stream.url]
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
            "-map", "0:v:0?", "-map", "0:a:0?",
            "-c:v", "copy", "-c:a", "copy",
            "-f", "hls",
            "-hls_time",         str(stream.hls_time),
            "-hls_list_size",    str(stream.hls_list_size),
            "-hls_flags",        "append_list",
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

        # Choose ffmpeg binary
        ff_bin = FFMPEG7 if os.path.exists(FFMPEG7) else FFMPEG

        ff_args = [
            ff_bin, "-hide_banner",
            "-fflags",      "+genpts+discardcorrupt+igndts",
            "-err_detect",  "ignore_err",
            "-analyzeduration", "3000000",
            "-probesize",       "5000000",
        ]
        # User-Agent must come before -i (HTTP input option)
        if stream.user_agent:
            ff_args += ["-user_agent", stream.user_agent]

        ff_args += ["-i", url]   # use the rotated URL
        ff_args += ["-map", "0:v:0?", "-map", "0:a:0?"]
        ff_args += _build_ffmpeg_video_args(stream)
        ff_args += _build_ffmpeg_audio_args(stream)

        hls_out = (
            f"[f=hls:hls_time={stream.hls_time}:hls_list_size={stream.hls_list_size}"
            f":hls_flags=append_list"
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
                "-hls_flags",        "append_list",
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
