"""
/api/metrics/* — RF metrics time series (channel utilization, noise floor,
retry rate, throughput) for charting.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends

from app.database import get_db
from app.dependencies import CurrentUser

router = APIRouter()


def _point(r) -> dict:
    return {
        "ts": r["ts"], "channel": r["channel"], "channel_width_mhz": r["channel_width_mhz"],
        "tx_power_dbm": r["tx_power_dbm"], "utilization_pct": r["utilization_pct"],
        "noise_floor_dbm": r["noise_floor_dbm"], "client_count": r["client_count"],
        "tx_bytes": r["tx_bytes"], "rx_bytes": r["rx_bytes"],
        "retry_pct": r["retry_pct"], "crc_error_pct": r["crc_error_pct"],
    }


@router.get("/radios/{radio_id}")
async def radio_metrics(
    radio_id: int,
    user: CurrentUser,
    since_minutes: int = 60,
    limit: int = 500,
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        """SELECT * FROM radio_metrics
           WHERE radio_id = ? AND ts >= datetime('now', ?)
           ORDER BY ts ASC LIMIT ?""",
        (radio_id, f"-{since_minutes} minutes", limit),
    ) as cur:
        rows = await cur.fetchall()
    return [_point(r) for r in rows]


@router.get("/access-points/{ap_id}")
async def access_point_metrics(
    ap_id: int,
    user: CurrentUser,
    since_minutes: int = 60,
    db: aiosqlite.Connection = Depends(get_db),
):
    """RF metric history for every radio belonging to this AP, keyed by band."""
    async with db.execute("SELECT id, band FROM radios WHERE access_point_id = ?", (ap_id,)) as cur:
        radios = await cur.fetchall()
    out = {}
    for r in radios:
        async with db.execute(
            """SELECT * FROM radio_metrics WHERE radio_id = ? AND ts >= datetime('now', ?)
               ORDER BY ts ASC""",
            (r["id"], f"-{since_minutes} minutes"),
        ) as cur:
            rows = await cur.fetchall()
        out[r["band"]] = [_point(m) for m in rows]
    return out
