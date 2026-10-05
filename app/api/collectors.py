"""
/api/collectors/* — configure and manage WiFi data collectors (generic SNMP
poller + vendor controller API integrations).
"""
from __future__ import annotations

import json
import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import CurrentUser, AdminUser
from app.wifi.collectors.registry import COLLECTOR_TYPES
from app.wifi.collectors.crypto import encrypt_config, decrypt_config

log = logging.getLogger("pktwifi.api.collectors")

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
            log.warning("collector %s: stored config could not be read", r["id"], exc_info=True)
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
    # Same check create does. Without it an edit could set a type no plugin
    # answers to, which the poll engine can only refuse.
    if body.collector_type not in COLLECTOR_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown collector_type '{body.collector_type}'")
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
    """Poll now and store the result, exactly as a scheduled poll does — the
    same code, the same empty-result protection, the same concurrency cap."""
    async with db.execute("SELECT * FROM collectors WHERE id = ?", (collector_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Collector not found")

    from app.wifi import poll_engine
    engine = poll_engine.PollEngine._instance
    if engine is not None and not engine.try_claim(collector_id):
        raise HTTPException(status_code=409, detail="This collector is already being polled — try again in a moment")
    try:
        await db.execute(f"PRAGMA busy_timeout={poll_engine._DB_BUSY_TIMEOUT_MS}")
        try:
            if engine is not None:
                async with engine.slots:
                    result = await poll_engine.poll_and_store(db, row)
            else:
                result = await poll_engine.poll_and_store(db, row)
        except poll_engine.PollFailed as exc:
            if exc.config:
                raise HTTPException(status_code=400, detail=exc.detail)
            raise HTTPException(status_code=502, detail=f"Poll failed: {exc.detail}")
    finally:
        if engine is not None:
            engine.release(collector_id)
    return {"status": "ok", "access_points": len(result.access_points), "clients": len(result.clients)}
