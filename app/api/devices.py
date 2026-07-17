"""
/api/devices/* — access point inventory (the core WiFi asset in pktWiFi).
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import CurrentUser, AnalystUser

router = APIRouter()


class CreateApRequest(BaseModel):
    name: str
    mac_address: str | None = None
    ip_address: str | None = None
    vendor: str | None = None
    model: str | None = None
    site: str | None = None
    floor: str | None = None


class UpdateApRequest(BaseModel):
    name: str | None = None
    site: str | None = None
    floor: str | None = None
    is_rogue: bool | None = None


def _ap_out(row) -> dict:
    return {
        "id": row["id"],
        "collector_id": row["collector_id"],
        "external_id": row["external_id"],
        "name": row["name"],
        "mac_address": row["mac_address"],
        "ip_address": row["ip_address"],
        "vendor": row["vendor"],
        "model": row["model"],
        "firmware_version": row["firmware_version"],
        "site": row["site"],
        "floor": row["floor"],
        "status": row["status"],
        "is_rogue": bool(row["is_rogue"]),
        "uptime_seconds": row["uptime_seconds"],
        "last_seen": row["last_seen"],
        "created_at": row["created_at"],
    }


@router.get("/summary")
async def devices_summary(user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online,
             SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) AS offline,
             SUM(CASE WHEN is_rogue = 1 THEN 1 ELSE 0 END) AS rogue
           FROM access_points"""
    ) as cur:
        row = await cur.fetchone()
    async with db.execute(
        "SELECT vendor, COUNT(*) AS count FROM access_points GROUP BY vendor ORDER BY count DESC"
    ) as cur:
        by_vendor = await cur.fetchall()
    async with db.execute("SELECT COALESCE(SUM(client_count), 0) AS total FROM radios") as cur:
        clients = await cur.fetchone()
    return {
        "total": row["total"] or 0,
        "online": row["online"] or 0,
        "offline": row["offline"] or 0,
        "rogue": row["rogue"] or 0,
        "by_vendor": [{"vendor": r["vendor"] or "unknown", "count": r["count"]} for r in by_vendor],
        "total_clients": clients["total"] or 0,
    }


@router.get("")
async def list_access_points(
    user: CurrentUser,
    status: str | None = None,
    site: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    query = "SELECT * FROM access_points WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if site:
        query += " AND site = ?"
        params.append(site)
    query += " ORDER BY name"
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    return [_ap_out(r) for r in rows]


@router.get("/{ap_id}")
async def get_access_point(ap_id: int, user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM access_points WHERE id = ?", (ap_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Access point not found")
    out = _ap_out(row)
    async with db.execute("SELECT * FROM radios WHERE access_point_id = ? ORDER BY band", (ap_id,)) as cur:
        radios = await cur.fetchall()
    out["radios"] = [
        {
            "id": r["id"], "band": r["band"], "channel": r["channel"],
            "channel_width_mhz": r["channel_width_mhz"], "tx_power_dbm": r["tx_power_dbm"],
            "utilization_pct": r["utilization_pct"], "noise_floor_dbm": r["noise_floor_dbm"],
            "client_count": r["client_count"], "updated_at": r["updated_at"],
        }
        for r in radios
    ]
    return out


@router.post("", status_code=201)
async def create_access_point(body: CreateApRequest, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute(
        """INSERT INTO access_points (name, mac_address, ip_address, vendor, model, site, floor)
           VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *""",
        (body.name, body.mac_address, body.ip_address, body.vendor, body.model, body.site, body.floor),
    )
    row = await cur.fetchone()
    await db.commit()
    return _ap_out(row)


@router.patch("/{ap_id}")
async def update_access_point(ap_id: int, body: UpdateApRequest, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM access_points WHERE id = ?", (ap_id,)) as cur:
        existing = await cur.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Access point not found")

    name = body.name if body.name is not None else existing["name"]
    site = body.site if body.site is not None else existing["site"]
    floor = body.floor if body.floor is not None else existing["floor"]
    is_rogue = int(body.is_rogue) if body.is_rogue is not None else existing["is_rogue"]

    await db.execute(
        "UPDATE access_points SET name = ?, site = ?, floor = ?, is_rogue = ? WHERE id = ?",
        (name, site, floor, is_rogue, ap_id),
    )
    await db.commit()
    async with db.execute("SELECT * FROM access_points WHERE id = ?", (ap_id,)) as cur:
        row = await cur.fetchone()
    return _ap_out(row)


@router.delete("/{ap_id}", status_code=204)
async def delete_access_point(ap_id: int, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    await db.execute("DELETE FROM access_points WHERE id = ?", (ap_id,))
    await db.commit()
