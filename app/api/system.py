"""
/api/system/* — version info, backups, and admin diagnostics.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.dependencies import AdminUser, CurrentUser
from app.backup import run_backup_sync, list_backups_sync

router = APIRouter()


async def _delayed_restart(delay: float = 1.5) -> None:
    """Wait briefly, then exit so systemd restarts the service (Restart=on-failure)."""
    await asyncio.sleep(delay)
    os._exit(1)


@router.get("/info")
async def system_info(user: CurrentUser):
    settings = get_settings()
    return {
        "version": "0.1.0",
        "install_dir": settings.install_dir,
        "port": settings.port,
    }


@router.post("/restart")
async def restart_service(user: AdminUser):
    asyncio.create_task(_delayed_restart())
    return {"status": "restarting", "message": "Service will restart in ~2 seconds"}


@router.get("/backups")
async def list_backups(user: AdminUser):
    settings = get_settings()
    return await asyncio.to_thread(list_backups_sync, settings.db_path)


@router.post("/backups/run")
async def run_backup_now(user: AdminUser):
    settings = get_settings()
    result = await asyncio.to_thread(run_backup_sync, settings.db_path)
    if result.get("status") != "ok":
        raise HTTPException(status_code=500, detail="Backup failed")
    return result
