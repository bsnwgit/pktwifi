"""
Alert event, client event, RF-metrics history and stale-radio auto-cleanup.

Runs once per day. Deletes resolved alert_events, client_events and
radio_metrics rows older than the configured retention windows (defaults:
90 days for alert events, 90 for client events, 30 for RF metric history), and
radios that no poll has reported for the configured time (default 30 days).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import aiosqlite

from app.config import get_settings

log = logging.getLogger("pktwifi.cleanup")
settings = get_settings()

_CLEANUP_INTERVAL = 86_400  # once per day


class AlertCleanup:
    _instance: "Optional[AlertCleanup]" = None

    def __init__(self, interval_seconds: int = _CLEANUP_INTERVAL):
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        AlertCleanup._instance = self
        self._task = asyncio.create_task(self._run_loop())
        log.info(f"Alert cleanup started (interval={self._interval}s)")

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
                await run_cleanup_now(settings.db_path)
            except Exception as e:
                log.error(f"Alert cleanup error: {e}")
            await asyncio.sleep(self._interval)


async def run_cleanup_now(db_path: str) -> dict:
    """Delete resolved alert_events, client_events and radio_metrics rows past their retention
    window, and radios no poll has reported for too long. Shared by the scheduled loop and the
    manual "Run Cleanup Now" button."""
    async with aiosqlite.connect(db_path) as db:
        # Without this a deleted radio would leave its metrics rows behind and
        # keep pointing clients at it, instead of cascading and clearing them.
        await db.execute("PRAGMA foreign_keys=ON")

        async def _setting(key: str, default: int) -> int:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
            if not row:
                return default
            try:
                days = int(json.loads(row[0]))
            except (ValueError, TypeError):
                return default
            # "-0 days" and "--5 days" would match every row, so a retention of
            # nothing or less is not honoured; the default stands instead.
            return days if days >= 1 else default

        alert_retention_days = await _setting("alert_event_retention_days", 90)
        metrics_retention_days = await _setting("radio_metrics_retention_days", 30)
        client_event_retention_days = await _setting("client_event_retention_days", 90)
        stale_radio_retention_days = await _setting("stale_radio_retention_days", 30)

        result = await db.execute(
            "DELETE FROM alert_events WHERE resolved = 1 AND created_at < datetime('now', ?)",
            (f"-{alert_retention_days} days",),
        )
        alerts_deleted = result.rowcount

        result = await db.execute(
            "DELETE FROM radio_metrics WHERE ts < datetime('now', ?)",
            (f"-{metrics_retention_days} days",),
        )
        metrics_deleted = result.rowcount

        result = await db.execute(
            "DELETE FROM client_events WHERE ts < datetime('now', ?)",
            (f"-{client_event_retention_days} days",),
        )
        client_events_deleted = result.rowcount

        # A poll rewrites updated_at on every radio a controller still reports, so
        # one that has gone this long unreported is gone (an access point that now
        # reports other bands, or no longer reports at all). Its metrics rows go
        # with it; clients keep their row and lose only the pointer to the radio.
        result = await db.execute(
            "DELETE FROM radios WHERE updated_at < datetime('now', ?)",
            (f"-{stale_radio_retention_days} days",),
        )
        stale_radios_deleted = result.rowcount

        await db.commit()

    if alerts_deleted or metrics_deleted or client_events_deleted or stale_radios_deleted:
        log.info(
            f"Cleanup: removed {alerts_deleted} resolved alerts (>{alert_retention_days}d), "
            f"{metrics_deleted} radio_metrics rows (>{metrics_retention_days}d), "
            f"{client_events_deleted} client events (>{client_event_retention_days}d), "
            f"{stale_radios_deleted} radios not reported (>{stale_radio_retention_days}d)"
        )
    return {
        "alerts_deleted": alerts_deleted,
        "metrics_deleted": metrics_deleted,
        "client_events_deleted": client_events_deleted,
        "stale_radios_deleted": stale_radios_deleted,
        "alert_retention_days": alert_retention_days,
        "metrics_retention_days": metrics_retention_days,
        "client_event_retention_days": client_event_retention_days,
        "stale_radio_retention_days": stale_radio_retention_days,
    }
