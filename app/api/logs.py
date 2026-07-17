"""
/api/logs/* — pktWiFi's own application log (app_logs table), plus a
pass-through to pktLog for AP/controller syslog correlation when that
integration is configured.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.dependencies import CurrentUser

router = APIRouter()


@router.get("")
async def list_app_logs(
    user: CurrentUser,
    level: str | None = None,
    limit: int = 200,
    db: aiosqlite.Connection = Depends(get_db),
):
    query = "SELECT * FROM app_logs WHERE 1=1"
    params: list = []
    if level:
        query += " AND level = ?"
        params.append(level.upper())
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    return [
        {
            "id": r["id"], "level": r["level"], "logger": r["logger"],
            "message": r["message"], "exc_info": r["exc_info"], "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.get("/pktlog")
async def pktlog_syslogs(
    user: CurrentUser,
    mac_address: str | None = None,
    limit: int = 200,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Proxy AP/controller syslog entries from pktLog, if that integration is configured."""
    from app.integrations.pktlog_client import PktLogClient
    async with db.execute(
        "SELECT base_url, suite_token FROM integrations WHERE app_name = 'pktlog' AND enabled = 1"
    ) as cur:
        row = await cur.fetchone()
    if not row or not row["base_url"]:
        raise HTTPException(status_code=503, detail="pktLog integration is not configured")

    client = PktLogClient(row["base_url"], row["suite_token"])
    return await client.get_wifi_logs(mac_address=mac_address, limit=limit)
