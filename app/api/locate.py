"""
/api/locate/* — where clients are on a floor plan.

A client is placed from the signal APs on the floor heard it at (see
app/wifi/locate.py for how, and how rough that is). Only rows the latest poll
of each AP wrote count, by the same rule the rest of the app uses
(app/wifi/freshness.py). Today collectors report only the AP a client is
joined to, so most clients are placed at their AP with a ring; a collector that
reports more APs per client sharpens this with no change here.
"""
from __future__ import annotations

import re
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db
from app.dependencies import CurrentUser
from app.wifi.freshness import client_is_current, signal_is_current
from app.wifi.locate import Anchor, locate
from app.wifi.rf import signal_class

router = APIRouter()

_MAC_RE = re.compile(r"^[0-9A-Fa-f:.\-]{11,17}$")
_MAX_CLIENTS = 5000
_MAX_TRAIL_POINTS = 500


def _round(v: Optional[float], places: int = 1) -> Optional[float]:
    return None if v is None else round(v, places)


@router.get("/floors/{floor_id}")
async def locate_floor(
    floor_id: int,
    user: CurrentUser,
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute("SELECT * FROM floors WHERE id = ?", (floor_id,)) as cur:
        floor = await cur.fetchone()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    scale = floor["scale_px_per_m"]
    bounds = (floor["image_w"], floor["image_h"]) if floor["image_w"] and floor["image_h"] else None

    async with db.execute(
        """SELECT id, name, status, x_px, y_px FROM access_points
            WHERE floor_id = ? AND x_px IS NOT NULL AND y_px IS NOT NULL ORDER BY name""",
        (floor_id,),
    ) as cur:
        aps = await cur.fetchall()
    placed = {r["id"]: r for r in aps}

    # Every current signal row for an AP placed on this floor, grouped by client.
    heard: dict[str, list[Anchor]] = {}
    async with db.execute(
        f"""SELECT s.client_mac, s.rssi_dbm, ap.x_px, ap.y_px
              FROM client_ap_signals s
              JOIN access_points ap ON ap.id = s.access_point_id
             WHERE ap.floor_id = ? AND ap.x_px IS NOT NULL AND ap.y_px IS NOT NULL
               AND {signal_is_current('s', 'ap')}""",
        (floor_id,),
    ) as cur:
        for r in await cur.fetchall():
            heard.setdefault(r["client_mac"], []).append(Anchor(r["x_px"], r["y_px"], r["rssi_dbm"]))

    # Current clients joined to an AP on this floor.
    async with db.execute(
        f"""SELECT c.mac_address, c.hostname, c.ip_address, c.ssid, c.band, c.rssi_dbm,
                   c.last_seen, c.access_point_id, ap.name AS ap_name
              FROM wifi_clients c
              JOIN access_points ap ON ap.id = c.access_point_id
             WHERE ap.floor_id = ? AND {client_is_current('c', 'ap')}
             ORDER BY c.mac_address LIMIT ?""",
        (floor_id, _MAX_CLIENTS),
    ) as cur:
        clients = await cur.fetchall()

    out = []
    for c in clients:
        ap = placed.get(c["access_point_id"])
        if ap is None:
            continue        # its AP is on this floor but has no position yet
        assoc = Anchor(ap["x_px"], ap["y_px"], c["rssi_dbm"]) if c["rssi_dbm"] is not None else None
        fix = locate(heard.get(c["mac_address"], []), assoc, scale, bounds)
        if fix is not None:
            x, y, accuracy_m, method, anchors = fix.x_px, fix.y_px, fix.accuracy_m, fix.method, fix.anchors
        else:
            # Joined to a placed AP but no signal to reason from: the AP is the
            # only honest position, and its accuracy is unknown.
            x, y, accuracy_m, method, anchors = ap["x_px"], ap["y_px"], None, "associated", 1
        out.append({
            "mac_address": c["mac_address"],
            "hostname": c["hostname"],
            "ip_address": c["ip_address"],
            "ssid": c["ssid"],
            "band": c["band"],
            "rssi_dbm": c["rssi_dbm"],
            "signal_class": signal_class(c["rssi_dbm"]) if c["rssi_dbm"] is not None else None,
            "access_point_id": c["access_point_id"],
            "access_point_name": c["ap_name"],
            "x_px": _round(x),
            "y_px": _round(y),
            "accuracy_m": _round(accuracy_m),
            "accuracy_px": _round(accuracy_m * scale) if accuracy_m is not None and scale else None,
            "method": method,
            "anchors": anchors,
            "last_seen": c["last_seen"],
        })

    # Current clients whose AP has no position on any floor: counted so the page
    # can say how many it cannot draw.
    async with db.execute(
        f"""SELECT COUNT(*) AS n FROM wifi_clients c
              JOIN access_points ap ON ap.id = c.access_point_id
             WHERE (ap.floor_id IS NULL OR ap.x_px IS NULL OR ap.y_px IS NULL)
               AND {client_is_current('c', 'ap')}""",
    ) as cur:
        unplaced = (await cur.fetchone())["n"]

    return {
        "floor": {
            "id": floor["id"], "name": floor["name"], "site_id": floor["site_id"],
            "image_w": floor["image_w"], "image_h": floor["image_h"],
            "scale_px_per_m": scale, "has_plan": bool(floor["image_path"]),
        },
        "access_points": [
            {"id": a["id"], "name": a["name"], "status": a["status"], "x_px": a["x_px"], "y_px": a["y_px"]}
            for a in aps
        ],
        "clients": out,
        "unplaced_clients": unplaced,
    }


@router.get("/clients/{mac}/trail")
async def client_trail(
    mac: str,
    user: CurrentUser,
    hours: int = Query(default=24, ge=1, le=168),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Where a client has been joined, oldest first, from its associate and roam
    events. Points on a floor carry that floor's id so the page can break the
    line where the client changed floor."""
    if not _MAC_RE.match(mac):
        raise HTTPException(status_code=422, detail="Not a MAC address")
    async with db.execute(
        """SELECT e.ts, e.event_type, ap.id AS ap_id, ap.name AS ap_name,
                  ap.floor_id, f.name AS floor_name, ap.x_px, ap.y_px
             FROM client_events e
             JOIN access_points ap ON ap.id = e.to_ap_id
             LEFT JOIN floors f ON f.id = ap.floor_id
            WHERE e.mac_address = ? AND e.event_type IN ('associate', 'roam')
              AND e.ts >= datetime('now', ?)
            ORDER BY e.ts DESC LIMIT ?""",
        (mac, f"-{int(hours)} hours", _MAX_TRAIL_POINTS),
    ) as cur:
        rows = await cur.fetchall()
    points = [
        {
            "ts": r["ts"], "event_type": r["event_type"],
            "access_point_id": r["ap_id"], "access_point_name": r["ap_name"],
            "floor_id": r["floor_id"], "floor_name": r["floor_name"],
            "x_px": r["x_px"], "y_px": r["y_px"],
        }
        for r in reversed(rows)
    ]
    return {"mac_address": mac, "hours": hours, "points": points}
