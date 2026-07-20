"""
/api/collectors/* — configure and manage WiFi data collectors (generic SNMP
poller + vendor controller API integrations).
"""
from __future__ import annotations

import json

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import CurrentUser, AdminUser
from app.wifi.collectors.registry import COLLECTOR_TYPES
from app.wifi.collectors.crypto import encrypt_config, decrypt_config

router = APIRouter()


class CollectorRequest(BaseModel):
    name: str
    collector_type: str
    config: dict = {}
    poll_interval_sec: int = 60
    enabled: bool = True


def _collector_out(r, reveal_config: bool = False) -> dict:
    out = {
        "id": r["id"], "name": r["name"], "collector_type": r["collector_type"],
        "poll_interval_sec": r["poll_interval_sec"], "enabled": bool(r["enabled"]),
        "status": r["status"], "last_poll_at": r["last_poll_at"],
        "last_error": r["last_error"], "created_at": r["created_at"],
    }
    if reveal_config:
        try:
            out["config"] = decrypt_config(r["config_json"])
        except Exception:
            out["config"] = {}
    return out


@router.get("/types")
async def list_collector_types(user: CurrentUser):
    """Available collector plugins and whether each is fully implemented yet."""
    return [
        {"type": key, "label": meta["label"], "implemented": meta["implemented"],
         "fields": meta["fields"]}
        for key, meta in COLLECTOR_TYPES.items()
    ]


@router.get("")
async def list_collectors(user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM collectors ORDER BY name") as cur:
        rows = await cur.fetchall()
    return [_collector_out(r) for r in rows]


@router.get("/{collector_id}")
async def get_collector(collector_id: int, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    """Admin-only — includes decrypted config so it can be edited in the UI."""
    async with db.execute("SELECT * FROM collectors WHERE id = ?", (collector_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Collector not found")
    return _collector_out(row, reveal_config=True)


@router.post("", status_code=201)
async def create_collector(body: CollectorRequest, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    if body.collector_type not in COLLECTOR_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown collector_type '{body.collector_type}'")
    cur = await db.execute(
        """INSERT INTO collectors (name, collector_type, config_json, poll_interval_sec, enabled)
           VALUES (?, ?, ?, ?, ?) RETURNING *""",
        (body.name, body.collector_type, encrypt_config(body.config), body.poll_interval_sec, int(body.enabled)),
    )
    row = await cur.fetchone()
    await db.commit()
    return _collector_out(row)


@router.patch("/{collector_id}")
async def update_collector(collector_id: int, body: CollectorRequest, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT id FROM collectors WHERE id = ?", (collector_id,)) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Collector not found")
    await db.execute(
        """UPDATE collectors SET name = ?, collector_type = ?, config_json = ?,
           poll_interval_sec = ?, enabled = ? WHERE id = ?""",
        (body.name, body.collector_type, encrypt_config(body.config), body.poll_interval_sec,
         int(body.enabled), collector_id),
    )
    await db.commit()
    async with db.execute("SELECT * FROM collectors WHERE id = ?", (collector_id,)) as cur:
        row = await cur.fetchone()
    return _collector_out(row)


@router.delete("/{collector_id}", status_code=204)
async def delete_collector(collector_id: int, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    await db.execute("DELETE FROM collectors WHERE id = ?", (collector_id,))
    await db.commit()


@router.post("/{collector_id}/poll-now")
async def poll_now(collector_id: int, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM collectors WHERE id = ?", (collector_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Collector not found")

    from app.wifi.collectors.registry import get_collector_instance
    collector = get_collector_instance(row["collector_type"], decrypt_config(row["config_json"]))
    if collector is None:
        raise HTTPException(status_code=400, detail="Collector type is not implemented yet")
    try:
        result = await collector.poll()
    except Exception as exc:
        # Some exceptions (e.g. httpx.ConnectTimeout) have an empty str() —
        # always include the exception type name so the user never sees a
        # blank error message.
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        await db.execute(
            "UPDATE collectors SET status = 'error', last_error = ?, last_poll_at = datetime('now') WHERE id = ?",
            (detail, collector_id),
        )
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Poll failed: {detail}")

    await db.execute(
        "UPDATE collectors SET status = 'ok', last_error = NULL, last_poll_at = datetime('now') WHERE id = ?",
        (collector_id,),
    )
    await db.commit()
    return {"status": "ok", "access_points": len(result.access_points), "clients": len(result.clients)}
