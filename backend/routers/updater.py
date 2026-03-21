import os
import subprocess
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/update", tags=["update"])

# Caminho raiz do projeto (2 níveis acima de backend/routers/)
PROJECT_DIR = str(Path(__file__).parent.parent.parent)
UPDATE_LOG  = "/tmp/aistra-update.log"
REPO        = "tauelektronik/aistra-stream"


def _local_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


async def _github_latest(gh_token: str) -> dict | None:
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"https://api.github.com/repos/{REPO}/commits/main",
                headers=headers,
            )
            if r.status_code == 200:
                d = r.json()
                return {
                    "sha":     d["sha"],
                    "message": d["commit"]["message"].split("\n")[0][:100],
                    "date":    d["commit"]["author"]["date"],
                    "author":  d["commit"]["author"]["name"],
                }
    except Exception:
        pass
    return None


@router.get("/check")
async def check_updates(_=Depends(require_admin)):
    local = _local_commit()
    short = local[:7] if local else "desconhecido"
    gh_token = os.getenv("GH_TOKEN", "")

    if not gh_token:
        return {
            "current":            short,
            "update_available":   None,
            "gh_token_configured": False,
            "message": "GH_TOKEN não configurado — adicione GH_TOKEN=ghp_xxxx ao .env e reinicie o serviço.",
        }

    remote = await _github_latest(gh_token)
    if remote is None:
        return {
            "current":            short,
            "update_available":   None,
            "gh_token_configured": True,
            "message": "Falha ao consultar GitHub API — verifique o GH_TOKEN.",
        }

    update_available = local != remote["sha"]
    return {
        "current":             short,
        "current_full":        local,
        "latest":              remote["sha"][:7],
        "latest_full":         remote["sha"],
        "latest_message":      remote["message"],
        "latest_date":         remote["date"],
        "latest_author":       remote["author"],
        "update_available":    update_available,
        "gh_token_configured": True,
    }


@router.post("/apply")
async def apply_update(_=Depends(require_admin)):
    gh_token = os.getenv("GH_TOKEN", "")
    if not gh_token:
        raise HTTPException(
            400,
            "GH_TOKEN não configurado em .env. "
            "Adicione GH_TOKEN=ghp_xxxx, reinicie o serviço e tente novamente.",
        )

    update_sh = os.path.join(PROJECT_DIR, "update.sh")
    if not os.path.isfile(update_sh):
        raise HTTPException(500, "update.sh não encontrado no diretório do projeto.")

    # Limpa log anterior
    try:
        open(UPDATE_LOG, "w").close()
    except Exception:
        pass

    # Dispara processo desanexado — sobrevive ao restart do serviço
    script = (
        f"sleep 2 && "
        f"GH_TOKEN={gh_token} bash {update_sh} >> {UPDATE_LOG} 2>&1"
    )
    subprocess.Popen(
        ["bash", "-c", script],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    logger.info("Update triggered by admin user — subprocess spawned")
    return {
        "status":  "started",
        "message": "Atualização iniciada. O painel ficará offline ~30s durante o restart.",
        "log_url": "/api/update/log",
    }


@router.get("/log")
async def get_update_log(_=Depends(require_admin)):
    try:
        with open(UPDATE_LOG, "r", errors="replace") as f:
            lines = f.readlines()
        return {"lines": lines[-100:], "total": len(lines)}
    except FileNotFoundError:
        return {"lines": [], "total": 0}
