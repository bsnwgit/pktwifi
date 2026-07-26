"""
/api/clients/* — WiFi client (station) inventory + roam/association history.
"""
from __future__ import annotations

import json

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.dependencies import CurrentUser

router = APIRouter()


# wifi_clients stores which radio a client is attached to (radio_id) but not
# that radio's channel — join radios so callers can break clients out by
# channel, not just band. LEFT JOIN because radio_id can be NULL (a
# collector that doesn't attribute clients to any radio at all).
_CLIENT_SELECT = """
    SELECT wc.*, r.channel AS channel, r.channel_width_mhz AS channel_width_mhz
    FROM wifi_clients wc
    LEFT JOIN radios r ON r.id = wc.radio_id
"""


def _client_out(row) -> dict:
    return {
        "id": row["id"],
        "mac_address": row["mac_address"],
        "access_point_id": row["access_point_id"],
        "radio_id": row["radio_id"],
        "hostname": row["hostname"],
        "ip_address": row["ip_address"],
        "ssid": row["ssid"],
        "band": row["band"],
        "channel": row["channel"],
        "channel_width_mhz": row["channel_width_mhz"],
        "protocol": row["protocol"],
        "rssi_dbm": row["rssi_dbm"],
        "snr_db": row["snr_db"],
        "tx_rate_mbps": row["tx_rate_mbps"],
        "rx_rate_mbps": row["rx_rate_mbps"],
        "connected_at": row["connected_at"],
        "last_seen": row["last_seen"],
    }


def _list_filters(access_point_id: int | None, ssid: str | None, search: str | None) -> tuple[str, list]:
    where = " WHERE 1=1"
    params: list = []
    if access_point_id is not None:
        where += " AND wc.access_point_id = ?"
        params.append(access_point_id)
    if ssid:
        where += " AND wc.ssid = ?"
        params.append(ssid)
    if search:
        where += " AND (wc.hostname LIKE ? OR wc.mac_address LIKE ? OR wc.ip_address LIKE ? OR wc.ssid LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like, like])
    return where, params


@router.get("")
async def list_clients(
    user: CurrentUser,
    access_point_id: int | None = None,
    ssid: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    db: aiosqlite.Connection = Depends(get_db),
):
    where, params = _list_filters(access_point_id, ssid, search)
    query = _CLIENT_SELECT + where + " ORDER BY wc.last_seen DESC"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params = params + [limit, offset]
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    return [_client_out(r) for r in rows]


@router.get("/count")
async def count_clients(
    user: CurrentUser,
    access_point_id: int | None = None,
    ssid: str | None = None,
    search: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    where, params = _list_filters(access_point_id, ssid, search)
    async with db.execute("SELECT COUNT(*) AS total FROM wifi_clients wc" + where, params) as cur:
        row = await cur.fetchone()
    return {"total": row["total"]}


@router.get("/{mac_address}")
async def get_client(mac_address: str, user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute(_CLIENT_SELECT + " WHERE wc.mac_address = ?", (mac_address,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
    return _client_out(row)


@router.get("/{mac_address}/events")
async def get_client_events(mac_address: str, user: CurrentUser, limit: int = 100, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute(
        "SELECT * FROM client_events WHERE mac_address = ? ORDER BY ts DESC LIMIT ?",
        (mac_address, limit),
    ) as cur:
        rows = await cur.fetchall()
    out = []
    for r in rows:
        try:
            details = json.loads(r["details_json"])
        except (ValueError, TypeError):
            details = {}
        out.append({
            "id": r["id"], "event_type": r["event_type"],
            "from_ap_id": r["from_ap_id"], "to_ap_id": r["to_ap_id"],
            "details": details, "ts": r["ts"],
        })
    return out
