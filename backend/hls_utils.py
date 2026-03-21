"""
hls_utils.py — Funções utilitárias puras para o HLS Manager.

Extraído de hls_manager.py para reduzir o tamanho do arquivo.
Não contém dependências async, config complexa ou imports circulares.
"""
import logging
import os
import re
import socket

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

# Log rotation — truncate log files when they exceed this size
_MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB

# ABR quality presets
_QUALITY_PRESETS = {
    "1080p": {"scale": "1920:-2", "vbr": "4500k", "abr": "192k"},
    "720p":  {"scale": "1280:-2", "vbr": "2800k", "abr": "128k"},
    "480p":  {"scale": "854:-2",  "vbr": "1400k", "abr": "96k"},
    "360p":  {"scale": "640:-2",  "vbr": "800k",  "abr": "96k"},
}

# Ban detection patterns
# Matched against last lines of ffmpeg / n_m3u8dl logs after a crash.
_BAN_PATTERNS: list[tuple[re.Pattern, int]] = [
    (re.compile(r'HTTP error 403|403 Forbidden|403 forbidden',          re.I), 403),
    # n_m3u8dl .NET exception format (Disney+/CDN auth failure)
    (re.compile(r'status code does not indicate success: 403',          re.I), 403),
    (re.compile(r'x-dss-token.*failure|dss.token.*fail',               re.I), 403),
    (re.compile(r'HTTP error 429|429 Too Many|rate.?limit',             re.I), 429),
    (re.compile(r'HTTP error 451',                                      re.I), 451),
    (re.compile(r'HTTP error 407|407 Proxy',                            re.I), 407),
    (re.compile(r'not authorized|unauthorized|401 Unauthorized',        re.I), 401),
    (re.compile(r'Access [Dd]enied|access_denied',                      re.I), 403),
    (re.compile(r'Subscription expired|subscription.*invalid',          re.I), 403),
    (re.compile(r'\bIP.{0,20}block|block.{0,10}IP\b',                  re.I), 403),
    (re.compile(r'\bbanned\b',                                          re.I), 403),
    (re.compile(r'geographic.?block|geo.?block|not available in your',  re.I), 451),
    (re.compile(r'Invalid token|token.*expired|token.*invalid',         re.I), 401),
    (re.compile(r'DRM.{0,30}error|license.*denied|key.*not.*found',     re.I), 403),
]
_BAN_COOLDOWN_S = int(os.getenv("BAN_COOLDOWN_S", "1800"))  # 30 min before retrying a banned URL


# ── Funções utilitárias ───────────────────────────────────────────────────────

def _open_log(path: str):
    """Open log in append mode; truncate first if file exceeds _MAX_LOG_BYTES."""
    try:
        if os.path.exists(path) and os.path.getsize(path) > _MAX_LOG_BYTES:
            open(path, "wb").close()
    except OSError as e:
        logger.warning("Could not truncate log %s: %s", path, e)
    return open(path, "ab")


def _alloc_port() -> int:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        if not p:
            raise OSError("OS returned port 0")
        return p
    except Exception as exc:
        raise OSError(f"Cannot allocate ephemeral port: {exc}") from exc


def _safe_id(stream_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)


def _height_from_resolution(res: str) -> int:
    if not res or res == "original":
        return 0
    try:
        return int(res.split("x")[1])
    except Exception:
        return 0


def _parse_progress_file(path: str) -> dict:
    """Read the last block from a ffmpeg -progress file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read()
        # Split into blocks separated by "progress=continue" or "progress=end"
        blocks = re.split(r'progress=(?:continue|end)', content)
        if not blocks:
            return {}
        last = blocks[-2] if len(blocks) >= 2 else blocks[-1]
        result = {}
        for line in last.strip().splitlines():
            line = line.strip()
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
        return result
    except Exception:
        return {}


def _parse_stats_from_log(path: str) -> dict:
    """Fallback: parse latest ffmpeg progress line from log file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
        # frame= 1234 fps= 30 q=26.0 size=   1234kB time=00:00:41.20 bitrate=2456.7kbits/s
        for line in reversed(tail.splitlines()):
            m = re.search(r'frame=\s*(\d+).*fps=\s*([\d.]+).*bitrate=\s*([\d.]+)kbits/s', line)
            if m:
                return {
                    "frame":   m.group(1),
                    "fps":     m.group(2),
                    "bitrate": m.group(3) + "kbits/s",
                }
        return {}
    except Exception:
        return {}


def _scan_log_for_ban(log_path: str, tail_lines: int = 80) -> tuple[bool, int]:
    """Read last `tail_lines` of a log file and return (ban_detected, http_code)."""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # Read last ~8KB (enough for 80 lines)
            f.seek(max(0, size - 8192))
            chunk = f.read().decode("utf-8", errors="replace")
        lines = chunk.splitlines()[-tail_lines:]
        text  = "\n".join(lines)
        for pattern, code in _BAN_PATTERNS:
            if pattern.search(text):
                return True, code
    except OSError:
        pass
    return False, 0


def _build_ffmpeg_video_args(stream) -> list:
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
    args += ["-force_key_frames", f"expr:gte(t,n_forced*{stream.hls_time})"]
    return args


def _build_ffmpeg_audio_args(stream) -> list:
    if stream.audio_codec == "copy":
        return ["-c:a", "copy"]
    return ["-c:a", stream.audio_codec, "-b:a", stream.audio_bitrate, "-ar", "48000"]


def _build_ffmpeg_multi_quality_args(
    stream, hls_dir: str, url: str, qualities: list[str],
    ffmpeg: str, ffmpeg7: str,
) -> list:
    ff_bin = ffmpeg7 if os.path.exists(ffmpeg7) else ffmpeg
    n = len(qualities)

    splits = "".join(f"[v{i}]" for i in range(n))
    scales = "; ".join(
        f"[v{i}]scale={_QUALITY_PRESETS[q]['scale']}[v{i}out]"
        for i, q in enumerate(qualities)
    )
    fc = f"[0:v]split={n}{splits}; {scales}"

    args = [
        ff_bin, "-hide_banner",
        "-fflags",          "+genpts+discardcorrupt",
        "-err_detect",      "ignore_err",
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

    audio_idx = getattr(stream, "audio_track", 0)
    for i in range(n):
        args += ["-map", f"[v{i}out]", "-map", f"0:a:{audio_idx}?"]

    preset = stream.video_preset if stream.video_codec != "copy" else "ultrafast"
    args += ["-c:v", "libx264", "-preset", preset]
    for i, q in enumerate(qualities):
        vbr     = _QUALITY_PRESETS[q]["vbr"]
        bufsize = str(int(vbr.replace("k", "")) * 2) + "k"
        args += [f"-b:v:{i}", vbr, f"-maxrate:v:{i}", vbr, f"-bufsize:v:{i}", bufsize]

    args += ["-c:a", "aac"]
    for i, q in enumerate(qualities):
        args += [f"-b:a:{i}", _QUALITY_PRESETS[q]["abr"], f"-ar:a:{i}", "48000"]

    for q in qualities:
        os.makedirs(os.path.join(hls_dir, q), exist_ok=True)

    vsm = " ".join(f"v:{i},a:{i},name:{q}" for i, q in enumerate(qualities))
    args += [
        "-var_stream_map",       vsm,
        "-master_pl_name",       "stream.m3u8",
        "-f",                    "hls",
        "-hls_time",             str(stream.hls_time),
        "-hls_list_size",        str(stream.hls_list_size),
        "-hls_flags",            "delete_segments+omit_endlist",
        "-hls_segment_filename", os.path.join(hls_dir, "%v", "seg%05d.ts"),
        os.path.join(hls_dir, "%v", "stream.m3u8"),
    ]
    return args
