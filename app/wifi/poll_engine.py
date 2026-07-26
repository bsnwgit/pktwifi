"""
app/wifi/poll_engine.py
------------------------
Background loop that polls every enabled collector on its own configured
interval, persists what it returns (access points, radios, RF metric
history, clients, roam events), and records collector health.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiosqlite

from app.wifi.collectors.base import PollResult
from app.wifi.collectors.crypto import decrypt_config, decrypt_str
from app.wifi.collectors.registry import get_collector_instance

log = logging.getLogger("pktwifi.poll_engine")

_TICK_SECONDS = 15


async def resolve_credential(db: aiosqlite.Connection, config: dict) -> dict:
    """If a controller's config references a saved credential (credential_id,
    set via the Settings -> Credentials picker instead of typing auth inline),
    decrypt it and merge the resulting auth fields into the config the
    collector actually reads. Keeps individual collectors as pure functions of
    a flat config dict — credential resolution happens once, centrally, here,
    so the same logic covers both the scheduled poller and the manual
    "Poll Now" button (app/api/collectors.py) instead of duplicating it in
    each. A no-op for any config without a credential_id."""
    credential_id = config.get("credential_id")
    if not credential_id:
        return config
    async with db.execute("SELECT * FROM credentials WHERE id = ?", (int(credential_id),)) as cur:
        row = await cur.fetchone()
    if not row:
        raise ValueError(f"Credential id {credential_id} not found — check Settings -> Credentials")
    cred = dict(row)
    resolved = dict(config)
    t = cred["cred_type"]
    if t == "userpass":
        resolved["username"] = cred["username"]
        resolved["password"] = decrypt_str(cred["password_enc"])
    elif t == "api_key":
        resolved["api_key"] = decrypt_str(cred["api_key_enc"])
    elif t == "snmp_v2c":
        resolved["version"] = "v2c"
        resolved["community"] = decrypt_str(cred["community_enc"])
    elif t == "snmp_v3":
        resolved["version"] = "v3"
        resolved["username"] = cred["username"]
        resolved["auth_protocol"] = cred["auth_protocol"]
        resolved["auth_password"] = decrypt_str(cred["auth_password_enc"])
        resolved["priv_protocol"] = cred["priv_protocol"]
        resolved["priv_password"] = decrypt_str(cred["priv_password_enc"])
    return resolved


async def _persist(db: aiosqlite.Connection, collector_id: int, result: PollResult) -> None:
    for ap in result.access_points:
        cur = await db.execute(
            """INSERT INTO access_points
               (collector_id, external_id, name, mac_address, ip_address, vendor, model,
                firmware_version, site, floor, status, is_rogue, uptime_seconds, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(collector_id, external_id) DO UPDATE SET
                 name=excluded.name, mac_address=excluded.mac_address, ip_address=excluded.ip_address,
                 vendor=excluded.vendor, model=excluded.model, firmware_version=excluded.firmware_version,
                 site=excluded.site, floor=excluded.floor, status=excluded.status,
                 is_rogue=excluded.is_rogue, uptime_seconds=excluded.uptime_seconds,
                 last_seen=datetime('now')
               RETURNING id""",
            (collector_id, ap.external_id, ap.name, ap.mac_address, ap.ip_address, ap.vendor, ap.model,
             ap.firmware_version, ap.site, ap.floor, ap.status, int(ap.is_rogue), ap.uptime_seconds),
        )
        ap_row = await cur.fetchone()
        ap_id = ap_row[0]

        for radio in ap.radios:
            cur = await db.execute(
                """INSERT INTO radios
                   (access_point_id, band, channel, channel_width_mhz, tx_power_dbm,
                    utilization_pct, noise_floor_dbm, client_count, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(access_point_id, band) DO UPDATE SET
                     channel=excluded.channel, channel_width_mhz=excluded.channel_width_mhz,
                     tx_power_dbm=excluded.tx_power_dbm, utilization_pct=excluded.utilization_pct,
                     noise_floor_dbm=excluded.noise_floor_dbm, client_count=excluded.client_count,
                     updated_at=datetime('now')
                   RETURNING id""",
                (ap_id, radio.band, radio.channel, radio.channel_width_mhz, radio.tx_power_dbm,
                 radio.utilization_pct, radio.noise_floor_dbm, radio.client_count),
            )
            radio_row = await cur.fetchone()
            radio_id = radio_row[0]

            await db.execute(
                """INSERT INTO radio_metrics
                   (radio_id, channel, channel_width_mhz, tx_power_dbm, utilization_pct,
                    noise_floor_dbm, client_count, tx_bytes, rx_bytes, retry_pct, crc_error_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (radio_id, radio.channel, radio.channel_width_mhz, radio.tx_power_dbm,
                 radio.utilization_pct, radio.noise_floor_dbm, radio.client_count,
                 radio.tx_bytes, radio.rx_bytes, radio.retry_pct, radio.crc_error_pct),
            )

            for client in radio.clients:
                async with db.execute(
                    "SELECT access_point_id, connected_at FROM wifi_clients WHERE mac_address = ?",
                    (client.mac_address,),
                ) as ccur:
                    prev = await ccur.fetchone()
                prev_ap_id = prev[0] if prev else None
                # Prefer a real connected_at freshly reported by the collector
                # (e.g. UniFi's Integration API — updates correctly across a
                # roam/reconnect) over whatever was already stored; fall back
                # to the existing value, and only invent "now" (via the SQL
                # COALESCE below) for a client never seen before by a
                # collector that doesn't report one at all (generic SNMP,
                # Meraki, UniFi userpass mode).
                connected_at = client.connected_at or (prev[1] if prev else None)

                await db.execute(
                    """INSERT INTO wifi_clients
                       (mac_address, access_point_id, radio_id, hostname, ip_address, ssid, band,
                        protocol, rssi_dbm, snr_db, tx_rate_mbps, rx_rate_mbps, connected_at, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(datetime(?), datetime('now')), datetime('now'))
                       ON CONFLICT(mac_address) DO UPDATE SET
                         access_point_id=excluded.access_point_id, radio_id=excluded.radio_id,
                         hostname=excluded.hostname, ip_address=excluded.ip_address, ssid=excluded.ssid,
                         band=excluded.band, protocol=excluded.protocol, rssi_dbm=excluded.rssi_dbm,
                         snr_db=excluded.snr_db, tx_rate_mbps=excluded.tx_rate_mbps, rx_rate_mbps=excluded.rx_rate_mbps,
                         connected_at=excluded.connected_at,
                         last_seen=datetime('now')""",
                    (client.mac_address, ap_id, radio_id, client.hostname, client.ip_address, client.ssid,
                     radio.band, client.protocol, client.rssi_dbm, client.snr_db,
                     client.tx_rate_mbps, client.rx_rate_mbps, connected_at),
                )

                event_type = None
                if prev_ap_id is None:
                    event_type = "associate"
                elif prev_ap_id != ap_id:
                    event_type = "roam"

                if event_type:
                    await db.execute(
                        "INSERT INTO client_events (mac_address, event_type, from_ap_id, to_ap_id) VALUES (?, ?, ?, ?)",
                        (client.mac_address, event_type, prev_ap_id, ap_id),
                    )

    # Full-replace semantics per poll: an AP this collector stored before but
    # didn't report this time no longer exists on the controller (renamed,
    # removed, or — as with the pre-fix UniFi filter — was never an AP at
    # all). Radios/metrics cascade via FK; wifi_clients rows are SET NULL.
    seen_ids = [ap.external_id for ap in result.access_points]
    placeholders = ",".join("?" * len(seen_ids))
    await db.execute(
        f"DELETE FROM access_points WHERE collector_id = ? AND external_id NOT IN ({placeholders})"
        if seen_ids else "DELETE FROM access_points WHERE collector_id = ?",
        (collector_id, *seen_ids),
    )
    await db.commit()


class PollEngine:
    _instance: "Optional[PollEngine]" = None

    def __init__(self, alert_engine=None) -> None:
        self.alert_engine = alert_engine
        self._task: Optional[asyncio.Task] = None
        self._db_path: str = ""

    async def start(self, db_path: str) -> None:
        PollEngine._instance = self
        self._db_path = db_path
        self._task = asyncio.create_task(self._run_loop())

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
                await self._tick()
            except Exception as exc:
                log.error(f"Poll engine tick error: {exc}")
            await asyncio.sleep(_TICK_SECONDS)

    async def _tick(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # SQLite defaults foreign_keys off per-connection — without this,
            # the stale-AP cleanup in _persist wouldn't cascade to radios.
            await db.execute("PRAGMA foreign_keys=ON")
            async with db.execute(
                """SELECT * FROM collectors WHERE enabled = 1 AND
                   (last_poll_at IS NULL OR
                    last_poll_at < datetime('now', '-' || poll_interval_sec || ' seconds'))"""
            ) as cur:
                due = await cur.fetchall()
            for row in due:
                await self._poll_one(db, row)

    async def _poll_one(self, db: aiosqlite.Connection, row: aiosqlite.Row) -> None:
        try:
            config = await resolve_credential(db, decrypt_config(row["config_json"]))
        except ValueError as exc:
            log.warning(f"Collector '{row['name']}' credential resolution failed: {exc}")
            await db.execute(
                "UPDATE collectors SET status = 'error', last_error = ?, last_poll_at = datetime('now') WHERE id = ?",
                (str(exc), row["id"]),
            )
            await db.commit()
            return
        collector = get_collector_instance(row["collector_type"], config)
        if collector is None:
            return
        try:
            result = await collector.poll()
            await _persist(db, row["id"], result)
            await db.execute(
                "UPDATE collectors SET status = 'ok', last_error = NULL, last_poll_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        except Exception as exc:
            log.warning(f"Collector '{row['name']}' poll failed: {exc}")
            await db.execute(
                "UPDATE collectors SET status = 'error', last_error = ?, last_poll_at = datetime('now') WHERE id = ?",
                (str(exc), row["id"]),
            )
        await db.commit()
