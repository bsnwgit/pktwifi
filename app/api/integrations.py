"""
/api/integrations/* — pktWiFi acting as a suite-token CLIENT of sibling
pkt* apps (pktsnmp, pktflow, pktlog, pktpcap), so it can reuse data those
apps already collect instead of re-polling it. This is separate from
/api/suite/*, which is the INBOUND side (pktHub calling into pktWiFi).

Setup: on the sibling app, open Settings -> Integrations -> pktHub
Integration and copy its suite token, then paste the app's base_url and
that token here.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import CurrentUser, AdminUser
from app.integrations.suite_client import SuiteClient

router = APIRouter()

_APPS = ("pktsnmp", "pktflow", "pktlog", "pktpcap")


class IntegrationRequest(BaseModel):
    base_url: str
    suite_token: str
    enabled: bool = True


def _out(r) -> dict:
    return {
        "app_name": r["app_name"], "base_url": r["base_url"],
        "has_token": bool(r["suite_token"]), "enabled": bool(r["enabled"]),
        "health_status": r["health_status"], "last_health_check": r["last_health_check"],
    }


@router.get("")
async def list_integrations(user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM integrations ORDER BY app_name") as cur:
        rows = await cur.fetchall()
    existing = {r["app_name"] for r in rows}
    out = [_out(r) for r in rows]
    for app_name in _APPS:
        if app_name not in existing:
            out.append({"app_name": app_name, "base_url": "", "has_token": False,
                        "enabled": False, "health_status": "unknown", "last_health_check": None})
    return sorted(out, key=lambda x: x["app_name"])


@router.put("/{app_name}")
async def set_integration(app_name: str, body: IntegrationRequest, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    if app_name not in _APPS:
        raise HTTPException(status_code=400, detail=f"app_name must be one of {_APPS}")
    await db.execute(
        """INSERT INTO integrations (app_name, base_url, suite_token, enabled, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(app_name) DO UPDATE SET
             base_url = excluded.base_url, suite_token = excluded.suite_token,
             enabled = excluded.enabled, updated_at = excluded.updated_at""",
        (app_name, body.base_url.rstrip("/"), body.suite_token, int(body.enabled)),
    )
    await db.commit()
    async with db.execute("SELECT * FROM integrations WHERE app_name = ?", (app_name,)) as cur:
        row = await cur.fetchone()
    return _out(row)


@router.post("/{app_name}/test")
async def test_integration(app_name: str, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM integrations WHERE app_name = ?", (app_name,)) as cur:
        row = await cur.fetchone()
    if not row or not row["base_url"]:
        raise HTTPException(status_code=400, detail="Integration is not configured yet")

    client = SuiteClient(row["base_url"], row["suite_token"])
    healthy, detail = await client.health_check()
    status_str = "ok" if healthy else "error"
    await db.execute(
        "UPDATE integrations SET health_status = ?, last_health_check = datetime('now') WHERE app_name = ?",
        (status_str, app_name),
    )
    await db.commit()
    return {"healthy": healthy, "detail": detail}


@router.get("/pktsnmp/access-points")
async def pktsnmp_access_points(user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    """Pull the device inventory from pktsnmp so WAPs it already polls can be
    imported/cross-referenced here instead of being re-discovered."""
    from app.integrations.pktsnmp_client import PktSnmpClient
    async with db.execute(
        "SELECT base_url, suite_token FROM integrations WHERE app_name = 'pktsnmp' AND enabled = 1"
    ) as cur:
        row = await cur.fetchone()
    if not row or not row["base_url"]:
        raise HTTPException(status_code=503, detail="pktsnmp integration is not configured")
    client = PktSnmpClient(row["base_url"], row["suite_token"])
    return await client.get_devices()
