"""
app/alerts/engine.py
--------------------
Lightweight WiFi alert engine. Runs on an interval, evaluates enabled
alert_rules against the current state of access_points / radios /
wifi_clients, and opens/keeps-open/auto-resolves alert_events.

Supported condition_type values:
  ap_down            - an access point's last_seen is older than `threshold` minutes
  high_channel_util   - a radio's utilization_pct exceeds `threshold`
  low_snr             - a client's snr_db falls below `threshold`
  high_retry_rate     - a radio's latest retry_pct exceeds `threshold`
  high_client_count   - a radio's client_count exceeds `threshold`
  rogue_ap            - an access point has is_rogue = 1 (set by a collector
                         or a future dedicated rogue-scan feature)

This intentionally does not attempt to replicate pktSNMP's much larger
generic OID-threshold engine (app/alerts/engine.py there) — WiFi's v1 alert
surface is a small, fixed set of conditions, not arbitrary user-defined OIDs.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiosqlite

from app.config import get_settings

log = logging.getLogger("pktwifi.alerts")

_EVAL_INTERVAL = 30  # seconds


class AlertEngine:
    _instance: "Optional[AlertEngine]" = None

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._db_path: str = ""

    async def start(self, db_path: str) -> None:
        AlertEngine._instance = self
        self._db_path = db_path
        self._task = asyncio.create_task(self._run_loop())
        log.info("Alert engine started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._evaluate()
            except Exception as e:
                log.error(f"Alert engine evaluation error: {e}")
            await asyncio.sleep(_EVAL_INTERVAL)

    async def _evaluate(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM alert_rules WHERE enabled = 1") as cur:
                rules = await cur.fetchall()

            for rule in rules:
                handler = _HANDLERS.get(rule["condition_type"])
                if handler:
                    await handler(db, rule)
            await db.commit()


async def _fire_or_keep(db: aiosqlite.Connection, rule, access_point_id=None, client_mac=None,
                         message: str = "", value: Optional[float] = None):
    """Open a new alert_event if one isn't already active for this rule+target."""
    async with db.execute(
        """SELECT id FROM alert_events
           WHERE rule_id = ? AND active = 1
             AND access_point_id IS ? AND client_mac IS ?""",
        (rule["id"], access_point_id, client_mac),
    ) as cur:
        existing = await cur.fetchone()
    if existing:
        return
    await db.execute(
        """INSERT INTO alert_events
           (rule_id, access_point_id, client_mac, severity, message, value, threshold, active)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
        (rule["id"], access_point_id, client_mac, rule["severity"], message, value, rule["threshold"]),
    )


async def _auto_resolve(db: aiosqlite.Connection, rule, still_bad_ap_ids: set, still_bad_macs: set):
    """Auto-resolve active alerts for this rule whose target is no longer in violation."""
    async with db.execute(
        "SELECT id, access_point_id, client_mac FROM alert_events WHERE rule_id = ? AND active = 1",
        (rule["id"],),
    ) as cur:
        active = await cur.fetchall()
    for row in active:
        ap_ok = row["access_point_id"] is None or row["access_point_id"] not in still_bad_ap_ids
        mac_ok = row["client_mac"] is None or row["client_mac"] not in still_bad_macs
        if ap_ok and mac_ok:
            await db.execute(
                """UPDATE alert_events SET active = 0, resolved = 1, auto_resolved = 1,
                   resolved_at = datetime('now') WHERE id = ?""",
                (row["id"],),
            )


async def _check_ap_down(db: aiosqlite.Connection, rule) -> None:
    minutes = rule["threshold"] or 5
    async with db.execute(
        """SELECT id, name, last_seen FROM access_points
           WHERE last_seen IS NULL OR last_seen < datetime('now', ?)""",
        (f"-{int(minutes)} minutes",),
    ) as cur:
        down = await cur.fetchall()
    bad_ids = set()
    for ap in down:
        bad_ids.add(ap["id"])
        await _fire_or_keep(db, rule, access_point_id=ap["id"],
                             message=f"Access point '{ap['name']}' has not reported in over {int(minutes)} minutes")
    await _auto_resolve(db, rule, bad_ids, set())


async def _check_high_channel_util(db: aiosqlite.Connection, rule) -> None:
    threshold = rule["threshold"] or 80
    async with db.execute(
        """SELECT r.access_point_id AS ap_id, a.name AS ap_name, r.band, r.utilization_pct
           FROM radios r JOIN access_points a ON a.id = r.access_point_id
           WHERE r.utilization_pct >= ?""",
        (threshold,),
    ) as cur:
        rows = await cur.fetchall()
    bad_ids = set()
    for r in rows:
        bad_ids.add(r["ap_id"])
        await _fire_or_keep(db, rule, access_point_id=r["ap_id"], value=r["utilization_pct"],
                             message=f"{r['ap_name']} ({r['band']}) channel utilization at {r['utilization_pct']:.0f}%")
    await _auto_resolve(db, rule, bad_ids, set())


async def _check_low_snr(db: aiosqlite.Connection, rule) -> None:
    threshold = rule["threshold"] or 15
    async with db.execute(
        "SELECT mac_address, hostname, snr_db FROM wifi_clients WHERE snr_db IS NOT NULL AND snr_db <= ?",
        (threshold,),
    ) as cur:
        rows = await cur.fetchall()
    bad_macs = set()
    for c in rows:
        bad_macs.add(c["mac_address"])
        label = c["hostname"] or c["mac_address"]
        await _fire_or_keep(db, rule, client_mac=c["mac_address"], value=c["snr_db"],
                             message=f"Client {label} has low SNR ({c['snr_db']:.0f} dB)")
    await _auto_resolve(db, rule, set(), bad_macs)


async def _check_high_retry_rate(db: aiosqlite.Connection, rule) -> None:
    threshold = rule["threshold"] or 15
    async with db.execute(
        """SELECT r.access_point_id AS ap_id, a.name AS ap_name, r.band, m.retry_pct
           FROM radio_metrics m
           JOIN radios r ON r.id = m.radio_id
           JOIN access_points a ON a.id = r.access_point_id
           WHERE m.id IN (SELECT MAX(id) FROM radio_metrics GROUP BY radio_id)
             AND m.retry_pct >= ?""",
        (threshold,),
    ) as cur:
        rows = await cur.fetchall()
    bad_ids = set()
    for r in rows:
        bad_ids.add(r["ap_id"])
        await _fire_or_keep(db, rule, access_point_id=r["ap_id"], value=r["retry_pct"],
                             message=f"{r['ap_name']} ({r['band']}) retry rate at {r['retry_pct']:.0f}%")
    await _auto_resolve(db, rule, bad_ids, set())


async def _check_high_client_count(db: aiosqlite.Connection, rule) -> None:
    threshold = rule["threshold"] or 50
    async with db.execute(
        """SELECT r.access_point_id AS ap_id, a.name AS ap_name, r.band, r.client_count
           FROM radios r JOIN access_points a ON a.id = r.access_point_id
           WHERE r.client_count >= ?""",
        (threshold,),
    ) as cur:
        rows = await cur.fetchall()
    bad_ids = set()
    for r in rows:
        bad_ids.add(r["ap_id"])
        await _fire_or_keep(db, rule, access_point_id=r["ap_id"], value=r["client_count"],
                             message=f"{r['ap_name']} ({r['band']}) has {r['client_count']} associated clients")
    await _auto_resolve(db, rule, bad_ids, set())


async def _check_rogue_ap(db: aiosqlite.Connection, rule) -> None:
    async with db.execute("SELECT id, name FROM access_points WHERE is_rogue = 1") as cur:
        rows = await cur.fetchall()
    bad_ids = set()
    for ap in rows:
        bad_ids.add(ap["id"])
        await _fire_or_keep(db, rule, access_point_id=ap["id"],
                             message=f"Rogue access point detected: '{ap['name']}'")
    await _auto_resolve(db, rule, bad_ids, set())


_HANDLERS = {
    "ap_down": _check_ap_down,
    "high_channel_util": _check_high_channel_util,
    "low_snr": _check_low_snr,
    "high_retry_rate": _check_high_retry_rate,
    "high_client_count": _check_high_client_count,
    "rogue_ap": _check_rogue_ap,
}
