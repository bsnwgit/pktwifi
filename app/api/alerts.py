"""
/api/alerts/* — alert rule configuration + alert event feed.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import CurrentUser, AnalystUser, AdminUser

router = APIRouter()

_CONDITION_TYPES = {
    "ap_down", "high_channel_util", "low_snr",
    "high_retry_rate", "high_client_count", "rogue_ap",
}


class RuleRequest(BaseModel):
    name: str
    condition_type: str
    threshold: float | None = None
    severity: str = "warning"
    enabled: bool = True


def _rule_out(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "condition_type": r["condition_type"],
        "threshold": r["threshold"], "severity": r["severity"],
        "enabled": bool(r["enabled"]), "created_at": r["created_at"],
    }


def _event_out(r) -> dict:
    return {
        "id": r["id"], "rule_id": r["rule_id"], "access_point_id": r["access_point_id"],
        "client_mac": r["client_mac"], "severity": r["severity"], "message": r["message"],
        "value": r["value"], "threshold": r["threshold"], "active": bool(r["active"]),
        "acked": bool(r["acked"]), "acked_by": r["acked_by"], "acked_at": r["acked_at"],
        "resolved": bool(r["resolved"]), "auto_resolved": bool(r["auto_resolved"]),
        "resolved_at": r["resolved_at"], "created_at": r["created_at"],
    }


# -- Rules ---------------------------------------------------------------------

@router.get("/rules")
async def list_rules(user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM alert_rules ORDER BY name") as cur:
        rows = await cur.fetchall()
    return [_rule_out(r) for r in rows]


@router.post("/rules", status_code=201)
async def create_rule(body: RuleRequest, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    if body.condition_type not in _CONDITION_TYPES:
        raise HTTPException(status_code=400, detail=f"condition_type must be one of {sorted(_CONDITION_TYPES)}")
    cur = await db.execute(
        """INSERT INTO alert_rules (name, condition_type, threshold, severity, enabled)
           VALUES (?, ?, ?, ?, ?) RETURNING *""",
        (body.name, body.condition_type, body.threshold, body.severity, int(body.enabled)),
    )
    row = await cur.fetchone()
    await db.commit()
    return _rule_out(row)


@router.patch("/rules/{rule_id}")
async def update_rule(rule_id: int, body: RuleRequest, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT id FROM alert_rules WHERE id = ?", (rule_id,)) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Rule not found")
    await db.execute(
        """UPDATE alert_rules SET name = ?, condition_type = ?, threshold = ?, severity = ?, enabled = ?
           WHERE id = ?""",
        (body.name, body.condition_type, body.threshold, body.severity, int(body.enabled), rule_id),
    )
    await db.commit()
    async with db.execute("SELECT * FROM alert_rules WHERE id = ?", (rule_id,)) as cur:
        row = await cur.fetchone()
    return _rule_out(row)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    await db.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
    await db.commit()


# -- Events ----------------------------------------------------------------------

@router.get("/events")
async def list_events(
    user: CurrentUser,
    active: bool | None = None,
    acked: bool | None = None,
    limit: int = 200,
    since: str | None = None,
    until: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    query = "SELECT * FROM alert_events WHERE 1=1"
    params: list = []
    if active is not None:
        query += " AND active = ?"
        params.append(int(active))
    if acked is not None:
        query += " AND acked = ?"
        params.append(int(acked))
    if since:
        # created_at is stored via SQLite's datetime('now') (space-separated,
        # no 'Z'/offset) — wrap the incoming ISO string in datetime() too so
        # the comparison is format-normalized on both sides.
        query += " AND created_at >= datetime(?)"
        params.append(since)
    if until:
        query += " AND created_at <= datetime(?)"
        params.append(until)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    return [_event_out(r) for r in rows]


@router.post("/events/{event_id}/ack")
async def ack_event(event_id: int, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    await db.execute(
        "UPDATE alert_events SET acked = 1, acked_by = ?, acked_at = datetime('now') WHERE id = ?",
        (user["username"], event_id),
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/events/ack-all")
async def ack_all_events(user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    await db.execute(
        "UPDATE alert_events SET acked = 1, acked_by = ?, acked_at = datetime('now') WHERE acked = 0",
        (user["username"],),
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/events/{event_id}/resolve")
async def resolve_event(event_id: int, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    await db.execute(
        "UPDATE alert_events SET active = 0, resolved = 1, resolved_at = datetime('now') WHERE id = ?",
        (event_id,),
    )
    await db.commit()
    return {"status": "ok"}
