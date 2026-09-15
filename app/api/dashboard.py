"""
/api/dashboard — everything the Dashboard page draws, in one read.

One request instead of one per panel, so every instrument on the page
describes the same moment rather than a handful of requests landing a poll
apart and disagreeing with each other.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.dependencies import CurrentUser
from app.wifi.poll_engine import _TICK_SECONDS
from app.wifi.rf import (
    BANDS, SIGNAL_FAIR_DBM, SIGNAL_GOOD_DBM,
    band_axis, occupied_span, signal_class, wifi_generation,
)

router = APIRouter()

# ── What "current" means ──────────────────────────────────────────────────────
# radios and wifi_clients are snapshots that get upserted and never expire: a
# band a controller stops reporting keeps its last client_count, and a client
# that leaves keeps its row with an ageing last_seen. Summed as they stand, both
# get counted — on a live estate that nearly doubled the connected-client
# figure. A row is current when the poll that last reported its access point
# also wrote it; the slack only covers the seconds a large poll takes to persist.
_FRESH = "-60 seconds"

# ── Trend buckets ─────────────────────────────────────────────────────────────
# (window up to N hours, bucket seconds). A bucket must also be wider than the
# longest gap between two polls, or some buckets miss a radio altogether and the
# summed client line saws up and down while nothing on air has changed.
_BASE_STEPS = ((1, 60), (6, 300), (24, 900), (168, 3600))
_STEPS      = (60, 120, 300, 600, 900, 1800, 3600, 7200)

# The alert engine's own threshold when a high_channel_util rule leaves it blank.
_DEFAULT_HOT_PCT = 80

# Ranked panels show this many and fold the rest together.
_TOP_APS   = 8
_TOP_SSIDS = 8
_SCOPE_APS = 16
_SCOPE_CAP = 60   # clients drawn per signal-scope sector

_NO_SSID = "Not reported"


def _round(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _step_for(hours: int, slowest_poll_sec: int) -> int:
    base = next(step for limit, step in _BASE_STEPS if hours <= limit)
    floor = 1.5 * (slowest_poll_sec + _TICK_SECONDS) if slowest_poll_sec else 0
    return next((s for s in _STEPS if s >= max(base, floor)), _STEPS[-1])


def _sector(ap_id: int | None, name: str, members: list[dict]) -> dict:
    """One signal-scope sector. Past the cap, an even stride through the
    RSSI-sorted clients keeps the sector's shape — trimming either end would
    make that AP look stronger or weaker than it is."""
    ordered = sorted(members, key=lambda c: c["rssi_dbm"])
    if len(ordered) > _SCOPE_CAP:
        stride = len(ordered) / _SCOPE_CAP
        ordered = [ordered[int(i * stride)] for i in range(_SCOPE_CAP)]
    return {
        "ap_id": ap_id,
        "ap_name": name,
        "clients": len(members),
        "points": [
            {"label": c["hostname"] or c["mac_address"], "rssi_dbm": c["rssi_dbm"],
             "band": c["band"], "ssid": c["ssid"]}
            for c in ordered
        ],
    }


@router.get("")
async def dashboard(
    user: CurrentUser,
    hours: int = Query(6, ge=1, le=168),
    db: aiosqlite.Connection = Depends(get_db),
):
    now = int(datetime.now(timezone.utc).timestamp())
    window = f"-{hours} hours"

    # ── Estate ────────────────────────────────────────────────────────────────
    async with db.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'online'  THEN 1 ELSE 0 END) AS online,
                  SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) AS offline,
                  SUM(CASE WHEN is_rogue = 1       THEN 1 ELSE 0 END) AS rogue
           FROM access_points"""
    ) as cur:
        aps = await cur.fetchone()
    ap_total, ap_online, ap_offline = aps["total"] or 0, aps["online"] or 0, aps["offline"] or 0

    async with db.execute(
        """SELECT id, name, collector_type, enabled, status, poll_interval_sec, last_poll_at
           FROM collectors ORDER BY name"""
    ) as cur:
        collectors = [{**dict(r), "enabled": bool(r["enabled"])} for r in await cur.fetchall()]
    slowest_poll = max((c["poll_interval_sec"] for c in collectors if c["enabled"]), default=0)

    # "Hot" is the utilisation the enabled high_channel_util rule alerts at, so
    # this page and the Alerts page agree on which radios are too busy.
    async with db.execute(
        "SELECT threshold FROM alert_rules WHERE condition_type = 'high_channel_util' AND enabled = 1"
    ) as cur:
        rule_thresholds = [r["threshold"] or _DEFAULT_HOT_PCT for r in await cur.fetchall()]
    hot_pct = min(rule_thresholds, default=_DEFAULT_HOT_PCT)

    # ── Radios on air ─────────────────────────────────────────────────────────
    async with db.execute(
        """SELECT r.id, r.band, r.channel, r.channel_width_mhz, r.utilization_pct, r.client_count,
                  ap.id AS ap_id, ap.name AS ap_name, ap.site, ap.status AS ap_status
           FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
           WHERE r.updated_at >= datetime(ap.last_seen, ?)""",
        (_FRESH,),
    ) as cur:
        radios = [dict(r) for r in await cur.fetchall()]

    clients_by_band: Counter = Counter()
    per_ap: dict[int, dict] = {}
    placed: list[dict] = []
    unplaced = 0
    for r in radios:
        count = r["client_count"] or 0
        on_air = r["band"] in BANDS  # anything else is a client tally, not a radio
        clients_by_band[r["band"] if on_air else "unknown"] += count

        ap = per_ap.setdefault(r["ap_id"], {
            "id": r["ap_id"], "name": r["ap_name"], "site": r["site"],
            "status": r["ap_status"], "clients": 0, "peak_util_pct": None,
        })
        ap["clients"] += count
        util = r["utilization_pct"]
        if util is not None and (ap["peak_util_pct"] is None or util > ap["peak_util_pct"]):
            ap["peak_util_pct"] = util

        if on_air:
            span = occupied_span(r["band"], r["channel"], r["channel_width_mhz"])
            if span is None:
                unplaced += 1
            else:
                placed.append({
                    "id": r["id"], "ap_id": r["ap_id"], "ap_name": r["ap_name"],
                    "ap_status": r["ap_status"], "band": r["band"], "channel": r["channel"],
                    "utilization_pct": util, "clients": count, **span,
                })

    measured = [r for r in radios if r["band"] in BANDS and r["utilization_pct"] is not None]
    peak = max(measured, key=lambda r: r["utilization_pct"], default=None)

    # ── Clients on air ────────────────────────────────────────────────────────
    async with db.execute(
        """SELECT c.mac_address, c.hostname, c.ssid, c.band, c.protocol, c.rssi_dbm,
                  ap.id AS ap_id, ap.name AS ap_name
           FROM wifi_clients c JOIN access_points ap ON ap.id = c.access_point_id
           WHERE c.last_seen >= datetime(ap.last_seen, ?)""",
        (_FRESH,),
    ) as cur:
        clients = [dict(r) for r in await cur.fetchall()]

    generations = Counter(wifi_generation(c["protocol"]) for c in clients)

    ssid_totals = Counter(c["ssid"] or _NO_SSID for c in clients)
    top_ssids = {s for s, _ in ssid_totals.most_common(_TOP_SSIDS)}
    flows: Counter = Counter()
    for c in clients:
        ssid = c["ssid"] or _NO_SSID
        flows[(ssid if ssid in top_ssids else "Other SSIDs",
               c["band"] if c["band"] in BANDS else "unknown")] += 1

    rssis = sorted(c["rssi_dbm"] for c in clients if c["rssi_dbm"] is not None)
    classes = Counter(signal_class(v) for v in rssis)
    # 5 dB bins keyed by their lower edge; the two end bins take everything past them.
    bins = Counter(max(-95, min(-35, math.floor(v / 5) * 5)) for v in rssis)

    by_ap: dict[int, list[dict]] = defaultdict(list)
    for c in clients:
        if c["rssi_dbm"] is not None:
            by_ap[c["ap_id"]].append(c)
    ranked = sorted(by_ap.values(), key=lambda m: (-len(m), m[0]["ap_name"]))
    scope = [_sector(m[0]["ap_id"], m[0]["ap_name"], m) for m in ranked[:_SCOPE_APS]]
    rest = [c for m in ranked[_SCOPE_APS:] for c in m]
    if rest:
        scope.append(_sector(None, "Other access points", rest))

    # ── Trend ─────────────────────────────────────────────────────────────────
    # Within a bucket each radio's samples are averaged first and only then
    # summed, so a radio that happened to be polled twice is not counted twice.
    # The radio_id IN (...) term matches every row anyway — metrics cascade
    # with their radio — but it is what lets SQLite use the (radio_id, ts)
    # index: without it an hour's window scans the whole retention period.
    step = _step_for(hours, slowest_poll)
    async with db.execute(
        """WITH per_radio AS (
               SELECT (CAST(strftime('%s', ts) AS INTEGER) / ?) * ? AS t,
                      radio_id,
                      AVG(client_count)    AS clients,
                      AVG(utilization_pct) AS util
               FROM radio_metrics
               WHERE radio_id IN (SELECT id FROM radios) AND ts >= datetime('now', ?)
               GROUP BY t, radio_id
           )
           SELECT p.t,
                  SUM(p.clients) AS clients,
                  AVG(CASE WHEN r.band = '2.4GHz' THEN p.util END) AS util_2g,
                  AVG(CASE WHEN r.band = '5GHz'   THEN p.util END) AS util_5g,
                  AVG(CASE WHEN r.band = '6GHz'   THEN p.util END) AS util_6g
           FROM per_radio p JOIN radios r ON r.id = p.radio_id
           GROUP BY p.t ORDER BY p.t""",
        (step, step, window),
    ) as cur:
        trend = [
            {"t": r["t"], "clients": _round(r["clients"]),
             "util_2g": _round(r["util_2g"]), "util_5g": _round(r["util_5g"]), "util_6g": _round(r["util_6g"])}
            for r in await cur.fetchall()
        ]

    async with db.execute(
        "SELECT event_type, COUNT(*) AS n FROM client_events WHERE ts >= datetime('now', ?) GROUP BY event_type",
        (window,),
    ) as cur:
        events = {r["event_type"]: r["n"] for r in await cur.fetchall()}

    # ── Alerts ────────────────────────────────────────────────────────────────
    async with db.execute(
        """SELECT LOWER(severity) AS severity, acked, COUNT(*) AS n
           FROM alert_events WHERE active = 1 GROUP BY LOWER(severity), acked"""
    ) as cur:
        alert_counts = [dict(r) for r in await cur.fetchall()]
    by_severity: Counter = Counter()
    for r in alert_counts:
        by_severity[r["severity"]] += r["n"]

    async with db.execute(
        """SELECT ae.id, ae.severity, ae.message, ae.created_at, ae.acked, ap.name AS ap_name
           FROM alert_events ae LEFT JOIN access_points ap ON ap.id = ae.access_point_id
           WHERE ae.active = 1
           ORDER BY CASE LOWER(ae.severity) WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                    ae.created_at DESC
           LIMIT 6"""
    ) as cur:
        recent_alerts = [{**dict(r), "acked": bool(r["acked"])} for r in await cur.fetchall()]

    return {
        "window": {"hours": hours, "step_sec": step, "since": now - hours * 3600, "until": now},
        "access_points": {
            "total": ap_total, "online": ap_online, "offline": ap_offline,
            "unknown": ap_total - ap_online - ap_offline, "rogue": aps["rogue"] or 0,
        },
        "clients": {
            "total": sum(clients_by_band.values()),
            "detailed": len(clients),
            "by_band": [{"band": b, "clients": n} for b, n in clients_by_band.most_common() if n],
        },
        "airtime": {
            "radios": len(measured),
            "mean_pct": _round(statistics.fmean(r["utilization_pct"] for r in measured)) if measured else None,
            "peak_pct": _round(peak["utilization_pct"]) if peak else None,
            "peak_ap": peak["ap_name"] if peak else None,
            "peak_band": peak["band"] if peak else None,
            "hot_pct": hot_pct,
            "hot_radios": sum(1 for r in measured if r["utilization_pct"] >= hot_pct),
        },
        "signal": {
            "measured": len(rssis),
            "median_dbm": _round(statistics.median(rssis)) if rssis else None,
            "good": classes["good"], "fair": classes["fair"], "poor": classes["poor"],
            "good_dbm": SIGNAL_GOOD_DBM, "fair_dbm": SIGNAL_FAIR_DBM,
            "histogram": [{"dbm": b, "clients": bins[b]} for b in range(-95, -30, 5)],
        },
        "generations": [{"generation": g, "clients": n} for g, n in generations.most_common()],
        "ssid_band": [{"ssid": s, "band": b, "clients": n} for (s, b), n in flows.most_common()],
        "trend": trend,
        "spectrum": {
            "bands": [band_axis(b) for b in BANDS if any(p["band"] == b for p in placed)],
            "radios": placed,
            "unplaced": unplaced,
        },
        "scope": scope,
        "top_aps": sorted(per_ap.values(), key=lambda a: (-a["clients"], -(a["peak_util_pct"] or 0)))[:_TOP_APS],
        "collectors": [
            {k: c[k] for k in ("id", "name", "collector_type", "enabled", "status", "last_poll_at")}
            for c in collectors
        ],
        "alerts": {
            "active": sum(by_severity.values()),
            "unacked": sum(r["n"] for r in alert_counts if not r["acked"]),
            "critical": by_severity["critical"],
            "warning": by_severity["warning"],
            "info": by_severity["info"],
            "recent": recent_alerts,
        },
        "events": events,
    }
