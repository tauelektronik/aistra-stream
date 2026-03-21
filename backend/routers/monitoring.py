"""Monitoring router: /api/server/stats + /health + /metrics + /stream/{id}/hls/* + thumbnail + player-config."""
import asyncio
import logging
import os
import re
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.crud import get_stream, list_streams
from backend.database import get_db
from backend.hls_manager import hls_manager, HLS_BASE, _send_telegram
from backend.state import DISK_WARN_PCT, METRICS_TOKEN, server_stats_cache

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_QUALITY_RE   = re.compile(r'^(360p|480p|720p|1080p)$')
_VALID_SEGMENT_RE   = re.compile(r'^seg\d{1,7}\.ts$')
_VALID_STREAM_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,50}$')


def _query_nvidia_smi() -> dict | None:
    """Run nvidia-smi synchronously (called via executor — never on event loop)."""
    import subprocess as _sp
    try:
        r = _sp.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,utilization.encoder,utilization.decoder,"
             "memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            if len(parts) >= 7:
                return {
                    "name":            parts[0],
                    "utilization_pct": int(parts[1]),
                    "enc_pct":         int(parts[2]),
                    "dec_pct":         int(parts[3]),
                    "memory_used_mb":  int(parts[4]),
                    "memory_total_mb": int(parts[5]),
                    "temperature_c":   int(parts[6]),
                }
    except Exception:
        pass
    return None


def _get_cpu_name() -> str:
    """Return CPU model name — tries wmic on Windows, /proc/cpuinfo on Linux."""
    import platform, subprocess as _sp
    try:
        if platform.system() == "Windows":
            r = _sp.run(["wmic", "cpu", "get", "name", "/value"],
                        capture_output=True, text=True, timeout=3)
            for line in r.stdout.splitlines():
                if line.startswith("Name="):
                    return line.split("=", 1)[1].strip()
        else:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return __import__("platform").processor() or "CPU"


_DISK_ALERT_COOLDOWN_S = 6 * 3600   # send Telegram disk alert at most once every 6 hours
_last_disk_alert_t: float = 0        # module-level timestamp of last Telegram disk alert


async def _server_stats_updater():
    """Background task: refresh server stats every 5 seconds."""
    global _last_disk_alert_t
    import psutil

    psutil.cpu_percent(interval=None)          # prime total CPU counter
    psutil.cpu_percent(percpu=True)            # prime per-core counter

    _net_prev_bytes = psutil.net_io_counters()
    loop = asyncio.get_running_loop()

    # Collect once-only static info
    _cpu_name = await loop.run_in_executor(None, _get_cpu_name)

    while True:
        await asyncio.sleep(5)
        try:
            cpu_pct      = psutil.cpu_percent(interval=None)
            cpu_per_core = psutil.cpu_percent(percpu=True)
            cpu_freq     = psutil.cpu_freq()
            mem          = psutil.virtual_memory()
            swap         = psutil.swap_memory()
            disk         = psutil.disk_usage("/")

            # CPU temperature (Linux: coretemp/k10temp; Windows: usually unavailable)
            cpu_temp = None
            try:
                temps = psutil.sensors_temperatures()
                for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                    if key in temps and temps[key]:
                        cpu_temp = round(temps[key][0].current, 1)
                        break
            except Exception:
                pass

            net_cur         = psutil.net_io_counters()
            net_up_bps      = max(0, (net_cur.bytes_sent - _net_prev_bytes.bytes_sent) // 5)
            net_down_bps    = max(0, (net_cur.bytes_recv - _net_prev_bytes.bytes_recv) // 5)
            _net_prev_bytes = net_cur

            # nvidia-smi is blocking — run in thread pool to avoid stalling event loop
            gpu = await loop.run_in_executor(None, _query_nvidia_smi)

            server_stats_cache.update({
                "cpu_pct":            round(cpu_pct, 1),
                "cpu_per_core":       [round(v, 1) for v in cpu_per_core],
                "cpu_name":           _cpu_name,
                "cpu_freq_mhz":       round(cpu_freq.current) if cpu_freq else 0,
                "cpu_temp_c":         cpu_temp,
                "mem_used_gb":        round(mem.used   / 1024 ** 3, 2),
                "mem_total_gb":       round(mem.total  / 1024 ** 3, 2),
                "mem_pct":            round(mem.percent, 1),
                "mem_swap_pct":       round(swap.percent, 1),
                "mem_swap_used_gb":   round(swap.used  / 1024 ** 3, 2),
                "mem_swap_total_gb":  round(swap.total / 1024 ** 3, 2),
                "disk_used_gb":       round(disk.used  / 1024 ** 3, 1),
                "disk_total_gb":      round(disk.total / 1024 ** 3, 1),
                "disk_pct":           round(disk.percent, 1),
                "net_up_mbps":        round(net_up_bps   / 1024 ** 2, 3),
                "net_down_mbps":      round(net_down_bps / 1024 ** 2, 3),
                "net_up_total_gb":    round(net_cur.bytes_sent / 1024 ** 3, 2),
                "net_down_total_gb":  round(net_cur.bytes_recv / 1024 ** 3, 2),
                "gpu":                gpu,
            })
            # Disk space warning — log always, Telegram at most once per 6 hours
            if disk.percent >= DISK_WARN_PCT:
                free_gb  = (disk.total - disk.used) / 1024 ** 3
                total_gb = disk.total / 1024 ** 3
                logger.warning(
                    "DISK SPACE LOW: %.1f%% used (%.1f GB free of %.1f GB) — "
                    "consider cleaning recordings or expanding storage",
                    disk.percent, free_gb, total_gb,
                )
                now = time.time()
                if now - _last_disk_alert_t >= _DISK_ALERT_COOLDOWN_S:
                    _last_disk_alert_t = now
                    asyncio.create_task(_send_telegram(
                        f"⚠️ *Disco quase cheio!*\n"
                        f"Uso: *{disk.percent:.1f}%* "
                        f"({free_gb:.1f} GB livres de {total_gb:.1f} GB)\n"
                        f"Considere limpar gravações antigas ou expandir o armazenamento."
                    ))
        except Exception as _e:
            logger.debug("server_stats_updater error: %s", _e)


@router.get("/api/server/stats")
async def server_stats(_=Depends(get_current_user)):
    """Return cached server stats (updated every 5 s by background task)."""
    if not server_stats_cache:
        return {"error": "Stats ainda sendo coletadas, tente novamente em 5s"}
    return server_stats_cache


@router.get("/health", include_in_schema=False)
async def health(db: AsyncSession = Depends(get_db)):
    streams = await list_streams(db)
    running = 0
    for s in streams:
        if await hls_manager.get_status(s.id) == "running":
            running += 1
    return {"status": "ok", "streams_total": len(streams), "streams_running": running}


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(request: Request, db: AsyncSession = Depends(get_db)):
    """Expose metrics in Prometheus text format.

    If METRICS_TOKEN is set, requires 'Authorization: Bearer <token>'.
    Otherwise open (firewall-protect in prod).

    Scrape config example (with token):
      - job_name: aistra-stream
        static_configs:
          - targets: ['your-server:8001']
        authorization:
          credentials: <your-METRICS_TOKEN>
    """
    if METRICS_TOKEN:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != METRICS_TOKEN:
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
    streams = await list_streams(db)
    streams_total = len(streams)
    statuses = await asyncio.gather(*[hls_manager.get_status(s.id) for s in streams])
    streams_running = sum(1 for st in statuses if st == "running")
    streams_error   = sum(1 for st in statuses if st == "error")
    streams_stopped = streams_total - streams_running - streams_error

    c = server_stats_cache
    lines: list[str] = []

    def g(name: str, help_: str, value, labels: str = "") -> None:
        """Append a gauge metric line."""
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} gauge")
        lbl = f"{{{labels}}}" if labels else ""
        lines.append(f"{name}{lbl} {value}")

    # ── Stream counts ──
    g("aistra_streams_total",   "Total number of configured streams",  streams_total)
    g("aistra_streams_running", "Streams currently running",           streams_running)
    g("aistra_streams_stopped", "Streams currently stopped",           streams_stopped)
    g("aistra_streams_error",   "Streams in error state",              streams_error)

    # ── CPU ──
    if c:
        g("aistra_cpu_usage_percent",    "Overall CPU usage %",         c.get("cpu_pct", 0))
        g("aistra_cpu_frequency_mhz",    "Current CPU frequency MHz",   c.get("cpu_freq_mhz", 0))
        if c.get("cpu_temp_c") is not None:
            g("aistra_cpu_temperature_celsius", "CPU temperature °C",   c["cpu_temp_c"])
        for i, pct in enumerate(c.get("cpu_per_core", [])):
            lines.append(f'aistra_cpu_core_usage_percent{{core="{i}"}} {pct}')

        # ── Memory ──
        g("aistra_memory_used_bytes",      "RAM used bytes",           round(c.get("mem_used_gb", 0) * 1024**3))
        g("aistra_memory_total_bytes",     "RAM total bytes",          round(c.get("mem_total_gb", 0) * 1024**3))
        g("aistra_memory_usage_percent",   "RAM usage %",              c.get("mem_pct", 0))
        g("aistra_swap_usage_percent",     "Swap usage %",             c.get("mem_swap_pct", 0))

        # ── Disk ──
        g("aistra_disk_used_bytes",        "Disk used bytes",          round(c.get("disk_used_gb", 0) * 1024**3))
        g("aistra_disk_total_bytes",       "Disk total bytes",         round(c.get("disk_total_gb", 0) * 1024**3))
        g("aistra_disk_usage_percent",     "Disk usage %",             c.get("disk_pct", 0))

        # ── Network ──
        g("aistra_network_upload_mbps",    "Network upload Mbps",      c.get("net_up_mbps", 0))
        g("aistra_network_download_mbps",  "Network download Mbps",    c.get("net_down_mbps", 0))
        g("aistra_network_sent_bytes",     "Total bytes sent",         round(c.get("net_up_total_gb", 0) * 1024**3))
        g("aistra_network_recv_bytes",     "Total bytes received",     round(c.get("net_down_total_gb", 0) * 1024**3))

        # ── GPU ──
        gpu = c.get("gpu")
        if gpu:
            g("aistra_gpu_usage_percent",      "GPU utilisation %",        gpu.get("utilization_pct", 0))
            g("aistra_gpu_encoder_percent",    "GPU encoder utilisation %", gpu.get("enc_pct", 0))
            g("aistra_gpu_decoder_percent",    "GPU decoder utilisation %", gpu.get("dec_pct", 0))
            g("aistra_gpu_memory_used_bytes",  "GPU memory used bytes",     round(gpu.get("memory_used_mb", 0) * 1024**2))
            g("aistra_gpu_memory_total_bytes", "GPU memory total bytes",    round(gpu.get("memory_total_mb", 0) * 1024**2))
            g("aistra_gpu_temperature_celsius","GPU temperature °C",        gpu.get("temperature_c", 0))

    # ── Per-stream restart counts ──
    lines.append("# HELP aistra_stream_restart_count Watchdog restart count per stream")
    lines.append("# TYPE aistra_stream_restart_count counter")
    for s in streams:
        rc = hls_manager._restart_counts.get(s.id, 0)
        lines.append(f'aistra_stream_restart_count{{stream="{s.id}"}} {rc}')

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4; charset=utf-8")


# ── HLS delivery ──────────────────────────────────────────────────────────────

@router.get("/stream/{stream_id}/hls/stream.m3u8")
async def stream_hls_master_playlist(
    stream_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Master playlist — triggers ffmpeg HLS session. Requires DB lookup."""
    if not _VALID_STREAM_ID_RE.match(stream_id):
        return Response(content="Stream não encontrado", status_code=404)
    stream = await get_stream(db, stream_id)
    if not stream or not stream.enabled:
        return Response(content="Stream não encontrado", status_code=404)
    hls_dir, err = await hls_manager.get_hls_dir(stream)
    if err:
        return Response(content=f"Erro ao iniciar stream: {err}", status_code=503)
    playlist = os.path.join(hls_dir, "stream.m3u8")
    # Timeout: at least 60 s, or 2× the stream's buffer_seconds (CENC/transcode can be slow)
    wait_secs = max(60, getattr(stream, "buffer_seconds", 20) * 2)
    for _ in range(wait_secs):
        if os.path.exists(playlist) and os.path.getsize(playlist) > 0:
            break
        await asyncio.sleep(1.0)
    if not os.path.exists(playlist) or os.path.getsize(playlist) == 0:
        return Response(content="Playlist não disponível ainda", status_code=503)
    hls_manager.touch(stream_id)
    return FileResponse(playlist, media_type="application/vnd.apple.mpegurl",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@router.get("/stream/{stream_id}/hls/{segment:path}")
async def stream_hls_files(
    stream_id: str,
    segment: str,
    request: Request,
):
    """HLS segments and quality sub-playlists — no DB lookup for high concurrency."""
    if not _VALID_STREAM_ID_RE.match(stream_id):
        return Response(content="Não encontrado", status_code=404)
    if ".." in segment:
        return Response(content="Não encontrado", status_code=404)
    parts = segment.split("/")
    if len(parts) > 2:
        return Response(content="Não encontrado", status_code=404)

    sub_quality = None
    filename = parts[-1]
    if len(parts) == 2:
        sub_quality = parts[0]
        if not _VALID_QUALITY_RE.match(sub_quality):
            return Response(content="Não encontrado", status_code=404)

    # ── Quality variant playlists (e.g. 720p/stream.m3u8) ────────────────────
    if filename == "stream.m3u8":
        if not sub_quality:
            return Response(content="Não encontrado", status_code=404)
        q_playlist = os.path.join(HLS_BASE, stream_id, sub_quality, "stream.m3u8")
        if not os.path.exists(q_playlist) or os.path.getsize(q_playlist) == 0:
            return Response(content="Playlist de qualidade não disponível", status_code=404)
        hls_manager.touch(stream_id)
        return FileResponse(q_playlist, media_type="application/vnd.apple.mpegurl",
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    # ── Segments ──────────────────────────────────────────────────────────────
    if not _VALID_SEGMENT_RE.match(filename):
        return Response(content="Não encontrado", status_code=404)
    base = os.path.join(HLS_BASE, stream_id)
    filepath = os.path.join(base, sub_quality, filename) if sub_quality else os.path.join(base, filename)
    # Resolve symlinks and verify the file stays inside HLS_BASE
    real_base = os.path.realpath(HLS_BASE)
    real_fp   = os.path.realpath(filepath)
    if not real_fp.startswith(real_base + os.sep):
        return Response(content="Não encontrado", status_code=404)
    if not os.path.exists(real_fp):
        return Response(content="Segmento não encontrado", status_code=404)
    hls_manager.touch(stream_id)
    try:
        return FileResponse(real_fp, media_type="video/mp2t", headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return Response(content="Segmento não encontrado", status_code=404)


@router.get("/api/streams/{stream_id}/thumbnail")
async def api_stream_thumbnail(
    stream_id: str,
    _=Depends(get_current_user),
):
    """Capture and return the latest thumbnail (JPEG) for a stream."""
    from backend.hls_manager import THUMBNAILS_BASE
    sid        = re.sub(r"[^a-zA-Z0-9_-]", "_", stream_id)
    thumb_path = os.path.join(THUMBNAILS_BASE, f"{sid}.jpg")

    if os.path.exists(thumb_path) and time.time() - os.path.getmtime(thumb_path) < 10:
        return FileResponse(thumb_path, media_type="image/jpeg",
                            headers={"Cache-Control": "no-cache"})

    path = await hls_manager.capture_thumbnail(stream_id)
    if not path or not os.path.exists(path):
        raise __import__("fastapi").HTTPException(status_code=404, detail="Thumbnail não disponível")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})


@router.get("/api/streams/{stream_id}/player-config")
async def player_config(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    s = await get_stream(db, stream_id)
    if not s:
        raise __import__("fastapi").HTTPException(status_code=404)
    buf        = s.buffer_seconds
    seg        = s.hls_time
    sync_count = max(2, round(buf / seg))
    return {
        "hlsUrl":                      f"/stream/{stream_id}/hls/stream.m3u8",
        "liveSyncDurationCount":       sync_count,
        "liveMaxLatencyDurationCount": sync_count * 3,
        "maxBufferLength":             max(60, buf * 2),
        "maxMaxBufferLength":          max(120, buf * 4),
        "lowLatencyMode":              False,
        "backBufferLength":            0,
        "startFragPrefetch":           True,
    }
