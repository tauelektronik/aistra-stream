"""Shared mutable state and environment-derived constants used across routers."""
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

LOGOS_BASE         = os.getenv("LOGOS_BASE",   str(_PROJECT_ROOT / "logos"))
BACKUPS_BASE       = os.getenv("BACKUPS_BASE", str(_PROJECT_ROOT / "backups"))
DISK_WARN_PCT      = int(os.getenv("DISK_WARN_PERCENT", "90"))
METRICS_TOKEN      = os.getenv("METRICS_TOKEN", "")
LOG_RETENTION_DAYS = int(os.getenv("CONNECTION_LOG_RETENTION_DAYS", "90"))
REC_RETENTION_DAYS = int(os.getenv("RECORDING_RETENTION_DAYS", "0"))

# Updated every 5s by _server_stats_updater background task in main.py
server_stats_cache: dict = {}
