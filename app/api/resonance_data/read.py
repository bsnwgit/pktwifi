"""
The read operations, and the budget that keeps every answer small and quick.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import aiosqlite
from fastapi import Depends, Path, Query

from app.api.resonance_data._common import AlertSeverity, ApStatus, Band, DATA_PREFIX, LogLevel, router
from app.api.resonance_data.errors import ErrorResponse, ResonanceDataError, _ERRORS
from app.api.resonance_data.models import AccessPoint, AccessPointList, AlertEventList, AlertRuleList, AppLogResult, CollectorList, RadioList, WifiClientList, WifiSummary
from app.api.resonance_data.session import SessionUser
from app.database import get_db
from app.sqlutil import Where
from app.wifi.freshness import client_is_current, radio_is_current


# ── Operations ────────────────────────────────────────────────────────────────
#
# Every summary and description here is written for a reader who has never seen
# pktWiFi, because that is literally what chooses between them: a model picks an
# operation from these sentences and nothing else. "Search logs" would leave it
# guessing between the certificate inventory and the app's own diagnostics,
# which are two entirely different questions asked with almost the same words.

# One page is capped well below what the SPA allows. The panel's results are
# read back to a person in a conversation, so a hundred rows is already past the
# point of being an answer, and a model handed five hundred narrows nothing. The
# maxima are deliberately above what always fits — _fit() reports the cut, and a
# caller that wants density should be able to ask for it.
_SEARCH_DEFAULT, _SEARCH_MAX = 25, 100


_LIST_DEFAULT, _LIST_MAX = 50, 200


# Resonance truncates a result over 20 KB and tells the model it did. That turns
# a clean page into JSON that stops mid-record, so the cut is made here instead,
# where it can leave the envelope intact and say what happened in a field the
# model can act on. 18 KB leaves headroom for transport framing.
_RESULT_BUDGET_BYTES = 18_000


# Resonance gives up on a call after 20 seconds and tells the person the
# application did not answer. Answering at 15 with something they can act on
# beats going quiet at 20.
_CALL_TIMEOUT_SECONDS = 15


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, default=str).encode("utf-8"))


def _fit(payload: dict, items_key: str) -> dict:
    """Trim a page to the byte budget, and record that it had to.

    Always keeps at least one item: an empty page for one oversized record is a
    worse answer than an oversized one, and the caller can still see `total`.
    """
    items = list(payload.get(items_key) or [])
    # Price the envelope with the two fields this adds, so adding them cannot
    # push a result that just fitted back over the line.
    envelope = dict(payload)
    envelope[items_key] = []
    envelope["returned"] = len(items)
    envelope["truncated_for_size"] = True
    budget = _RESULT_BUDGET_BYTES - _encoded_size(envelope)

    kept: list = []
    used = 0
    for item in items:
        size = _encoded_size(item) + 1   # + the separating comma
        if kept and used + size > budget:
            break
        kept.append(item)
        used += size

    payload[items_key] = kept
    payload["returned"] = len(kept)
    payload["truncated_for_size"] = len(kept) < len(items)
    return payload


async def _in_time(awaitable, what: str):
    """Bound a query so a slow one is answered rather than abandoned."""
    try:
        return await asyncio.wait_for(awaitable, _CALL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise ResonanceDataError(
            status_code=504,
            detail=(
                f"pktWiFi took longer than {_CALL_TIMEOUT_SECONDS} seconds to {what}. "
                "Narrow the time range, or filter by status, CA or name."
            ),
        ) from exc


@router.get(
    f"{DATA_PREFIX}/summary",
    operation_id="getWifiSummary",
    summary="Counts across the whole wireless estate",
    description=(
        "One small result answering 'how are we doing' — how many access points exist and how "
        "many are online, how many rogues have been seen, how many clients are associated, how "
        "many radios, SSIDs and sites are configured, how many collectors are enabled, and how "
        "many alerts are outstanding. Ask this before listAccessPoints when the question is "
        "about totals rather than about particular access points."
    ),
    response_model=WifiSummary,
    responses=_ERRORS,
)
async def get_wifi_summary(
    _user: dict = SessionUser,
    db: aiosqlite.Connection = Depends(get_db),
):
    async def _count(query: str) -> int:
        async with db.execute(query) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    return {
        "access_points": await _count("SELECT COUNT(*) FROM access_points"),
        "access_points_online": await _count(
            "SELECT COUNT(*) FROM access_points WHERE status = 'online'"
        ),
        "rogue_access_points": await _count(
            "SELECT COUNT(*) FROM access_points WHERE is_rogue = 1"
        ),
        "clients": await _count(
            f"SELECT COUNT(*) FROM wifi_clients c JOIN access_points ap ON ap.id = c.access_point_id "
            f"WHERE {client_is_current()}"
        ),
        "radios": await _count(
            f"SELECT COUNT(*) FROM radios r JOIN access_points ap ON ap.id = r.access_point_id "
            f"WHERE {radio_is_current()}"
        ),
        "ssids": await _count("SELECT COUNT(*) FROM ssids"),
        "sites": await _count("SELECT COUNT(*) FROM sites"),
        "collectors": await _count("SELECT COUNT(*) FROM collectors"),
        "collectors_enabled": await _count("SELECT COUNT(*) FROM collectors WHERE enabled = 1"),
        "unacknowledged_alerts": await _count("SELECT COUNT(*) FROM alert_events WHERE acked = 0"),
    }


@router.get(
    f"{DATA_PREFIX}/access-points",
    operation_id="listAccessPoints",
    summary="List the access points",
    description=(
        "The access points pktWiFi knows about — where each is, what it is, whether it is "
        "answering, and how many clients are on it. Set rogue_only for access points that are "
        "not ours, which is a security question rather than a capacity one. Every filter is "
        "optional and they combine with AND. Returns at most `limit` access points plus the "
        "total that matched."
    ),
    response_model=AccessPointList,
    responses=_ERRORS,
)
async def list_access_points(
    _user: dict = SessionUser,
    status: Optional[ApStatus] = Query(None, description="Only access points in this state."),
    site: Optional[str] = Query(None, max_length=120, description="Only access points at this site."),
    rogue_only: bool = Query(False, description="Only access points flagged as not ours."),
    search: Optional[str] = Query(
        None, max_length=200, description="Substring of the name, MAC, address or model."
    ),
    limit: int = Query(
        _SEARCH_DEFAULT, ge=1, le=_SEARCH_MAX,
        description=f"How many to return. Default {_SEARCH_DEFAULT}, maximum {_SEARCH_MAX}.",
    ),
    offset: int = Query(0, ge=0, description="How many to skip, for paging."),
    db: aiosqlite.Connection = Depends(get_db),
):
    w = Where()
    if status:
        w.add("a.status = ?", status)
    if site:
        w.add("a.site = ?", site)
    if rogue_only:
        w.add("a.is_rogue = 1")
    if search:
        like = f"%{search}%"
        w.add("(a.name LIKE ? OR a.mac_address LIKE ? OR a.ip_address LIKE ? OR a.model LIKE ?)", *([like] * 4))
    where = w.sql

    async with db.execute(f"SELECT COUNT(*) FROM access_points a {where}", w.params) as cur:
        total = (await cur.fetchone())[0]

    async with db.execute(
        f"""SELECT a.id, a.name, a.mac_address, a.ip_address, a.vendor, a.model,
                   a.firmware_version, a.site, a.floor, a.status, a.is_rogue,
                   a.uptime_seconds, a.collector_id, a.last_seen,
                   (SELECT COUNT(*) FROM wifi_clients c WHERE c.access_point_id = a.id AND {client_is_current(ap='a')})
                       AS client_count
            FROM access_points a
            {where}
            ORDER BY a.name
            LIMIT ? OFFSET ?""",
        w.with_params(limit, offset),
    ) as cur:
        rows = await cur.fetchall()

    aps = []
    for r in rows:
        d = dict(r)
        d["is_rogue"] = bool(d.get("is_rogue"))
        aps.append(d)

    return _fit(
        {"total": total, "limit": limit, "offset": offset, "access_points": aps},
        "access_points",
    )


@router.get(
    f"{DATA_PREFIX}/access-points/{{ap_id}}",
    operation_id="getAccessPoint",
    summary="Read one access point in full",
    description=(
        "Everything pktWiFi records about a single access point, by the id listAccessPoints "
        "returned. Use this after a search when the question is about one AP in particular — "
        "its firmware, its uptime, how many clients it is carrying."
    ),
    response_model=AccessPoint,
    responses={**_ERRORS, 404: {"model": ErrorResponse, "description": "No access point with that id."}},
)
async def get_access_point(
    ap_id: int = Path(description="Id of the access point, as returned by listAccessPoints."),
    _user: dict = SessionUser,
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        f"""SELECT a.id, a.name, a.mac_address, a.ip_address, a.vendor, a.model,
                  a.firmware_version, a.site, a.floor, a.status, a.is_rogue,
                  a.uptime_seconds, a.collector_id, a.last_seen,
                  (SELECT COUNT(*) FROM wifi_clients c WHERE c.access_point_id = a.id AND {client_is_current(ap='a')})
                      AS client_count
           FROM access_points a WHERE a.id = ?""",
        (ap_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise ResonanceDataError(status_code=404, detail=f"There is no access point {ap_id}.")
    d = dict(row)
    d["is_rogue"] = bool(d.get("is_rogue"))
    return d


@router.get(
    f"{DATA_PREFIX}/clients",
    operation_id="listWifiClients",
    summary="List associated wireless clients",
    description=(
        "The clients pktWiFi last saw associated, with the access point and SSID each is on and "
        "how good their radio link is. This is the 'why is that laptop slow on wifi' answer: "
        "rssi_dbm closer to zero is stronger and below -70 is poor, snr_db under 20 is poor. "
        "Weakest signal first when no other order is implied. Every filter is optional."
    ),
    response_model=WifiClientList,
    responses=_ERRORS,
)
async def list_wifi_clients(
    _user: dict = SessionUser,
    access_point_id: Optional[int] = Query(None, description="Only clients on this access point."),
    ssid: Optional[str] = Query(None, max_length=120, description="Only clients on this SSID."),
    band: Optional[Band] = Query(None, description="Only clients on this band, in GHz."),
    weak_signal_only: bool = Query(
        False, description="Only clients at or below -70 dBm — the ones actually having a bad time."
    ),
    search: Optional[str] = Query(
        None, max_length=200, description="Substring of the MAC, hostname or address."
    ),
    limit: int = Query(
        _SEARCH_DEFAULT, ge=1, le=_SEARCH_MAX,
        description=f"How many to return. Default {_SEARCH_DEFAULT}, maximum {_SEARCH_MAX}.",
    ),
    offset: int = Query(0, ge=0, description="How many to skip, for paging."),
    db: aiosqlite.Connection = Depends(get_db),
):
    w = Where()
    if access_point_id is not None:
        w.add("c.access_point_id = ?", access_point_id)
    if ssid:
        w.add("c.ssid = ?", ssid)
    if band:
        # The filter says 5, the table stores 5GHz.
        w.add("c.band = ?", f"{band}GHz")
    if weak_signal_only:
        w.add("c.rssi_dbm IS NOT NULL AND c.rssi_dbm <= -70")
    if search:
        like = f"%{search}%"
        w.add("(c.mac_address LIKE ? OR c.hostname LIKE ? OR c.ip_address LIKE ?)", *([like] * 3))
    # Only clients on air now; the tables keep rows a poll no longer reports.
    w.add(client_is_current(ap="a"))
    where = w.sql

    async with db.execute(
        f"SELECT COUNT(*) FROM wifi_clients c JOIN access_points a ON a.id = c.access_point_id {where}",
        w.params,
    ) as cur:
        total = (await cur.fetchone())[0]

    async with db.execute(
        f"""SELECT c.id, c.mac_address, c.hostname, c.ip_address, c.ssid, c.band,
                   c.protocol, c.rssi_dbm, c.snr_db, c.tx_rate_mbps, c.rx_rate_mbps,
                   c.access_point_id, c.connected_at, c.last_seen,
                   a.name AS access_point_name
            FROM wifi_clients c
            JOIN access_points a ON a.id = c.access_point_id
            {where}
            ORDER BY c.rssi_dbm ASC
            LIMIT ? OFFSET ?""",
        w.with_params(limit, offset),
    ) as cur:
        rows = await cur.fetchall()

    return _fit(
        {"total": total, "limit": limit, "offset": offset, "clients": [dict(r) for r in rows]},
        "clients",
    )


@router.get(
    f"{DATA_PREFIX}/radios",
    operation_id="listRadios",
    summary="List access-point radios, with channel and congestion",
    description=(
        "One row per radio: its band, channel, width, transmit power, how busy the channel is "
        "and what the noise floor looks like. This is the 'is the 2.4 band congested' and 'what "
        "channel is that AP on' answer — utilization_pct sustained above 50 is congestion. "
        "Busiest first."
    ),
    response_model=RadioList,
    responses=_ERRORS,
)
async def list_radios(
    _user: dict = SessionUser,
    access_point_id: Optional[int] = Query(None, description="Only radios on this access point."),
    band: Optional[Band] = Query(None, description="Only radios on this band, in GHz."),
    db: aiosqlite.Connection = Depends(get_db),
):
    w = Where()
    if access_point_id is not None:
        w.add("r.access_point_id = ?", access_point_id)
    if band:
        w.add("r.band = ?", f"{band}GHz")
    w.add(radio_is_current(ap="a"))
    where = w.sql

    async with db.execute(
        f"""SELECT r.id, r.access_point_id, r.band, r.channel, r.channel_width_mhz,
                   r.tx_power_dbm, r.utilization_pct, r.noise_floor_dbm, r.client_count,
                   r.updated_at, a.name AS access_point_name
            FROM radios r
            JOIN access_points a ON a.id = r.access_point_id
            {where}
            ORDER BY r.utilization_pct DESC""",
        w.params,
    ) as cur:
        rows = await cur.fetchall()
    radios = [dict(r) for r in rows]
    return _fit({"total": len(radios), "radios": radios}, "radios")


@router.get(
    f"{DATA_PREFIX}/collectors",
    operation_id="listCollectors",
    summary="List the collectors pktWiFi polls",
    description=(
        "Where pktWiFi's data comes from — which controller each collector talks to, whether it "
        "is enabled, when it last ran and why it failed if it did. A collector that stopped "
        "polling explains every access point going quiet at once, so read this before "
        "concluding the wireless itself is down. No controller credential is returned."
    ),
    response_model=CollectorList,
    responses=_ERRORS,
)
async def list_collectors(
    _user: dict = SessionUser,
    db: aiosqlite.Connection = Depends(get_db),
):
    # config_json holds the controller credentials and is deliberately not selected.
    async with db.execute(
        "SELECT id, name, collector_type, enabled, status, poll_interval_sec, "
        "last_poll_at, last_error FROM collectors ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()
    collectors = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d.get("enabled"))
        collectors.append(d)
    return _fit({"total": len(collectors), "collectors": collectors}, "collectors")


@router.get(
    f"{DATA_PREFIX}/alerts/events",
    operation_id="listAlertEvents",
    summary="List alerts that have fired",
    description=(
        "Individual firings of pktWiFi's alert rules — an access point going offline, a rogue "
        "appearing, a channel saturating — newest first. This is what to read for 'what is "
        "wrong' or 'what happened overnight'. An event with acked false is one nobody has looked "
        "at yet; active true means the condition still holds."
    ),
    response_model=AlertEventList,
    responses=_ERRORS,
)
async def list_alert_events(
    _user: dict = SessionUser,
    unacked_only: bool = Query(False, description="Only events nobody has acknowledged yet."),
    active_only: bool = Query(False, description="Only events whose condition still holds."),
    severity: Optional[AlertSeverity] = Query(None, description="Only events raised at this severity."),
    access_point_id: Optional[int] = Query(None, description="Only events about this access point."),
    since: Optional[str] = Query(None, description="Only events fired at or after this time. ISO 8601."),
    until: Optional[str] = Query(None, description="Only events fired at or before this time. ISO 8601."),
    limit: int = Query(
        _SEARCH_DEFAULT, ge=1, le=_SEARCH_MAX,
        description=f"How many to return. Default {_SEARCH_DEFAULT}, maximum {_SEARCH_MAX}.",
    ),
    offset: int = Query(0, ge=0, description="How many to skip, for paging."),
    db: aiosqlite.Connection = Depends(get_db),
):
    w = Where()
    if unacked_only:
        w.add("e.acked = 0")
    if active_only:
        w.add("e.active = 1")
    if severity:
        w.add("e.severity = ?", severity)
    if access_point_id is not None:
        w.add("e.access_point_id = ?", access_point_id)
    if since:
        # created_at is written by SQLite's datetime('now') — space separated,
        # no 'Z' — so both sides go through datetime() to compare like for like.
        w.add("e.created_at >= datetime(?)", since)
    if until:
        w.add("e.created_at <= datetime(?)", until)
    where = w.sql

    async with db.execute(f"SELECT COUNT(*) FROM alert_events e {where}", w.params) as cur:
        total = (await cur.fetchone())[0]

    async with db.execute(
        f"""SELECT e.id, e.rule_id, e.access_point_id, e.client_mac, e.severity, e.message,
                   e.value, e.threshold, e.active, e.acked, e.acked_by, e.acked_at,
                   e.resolved, e.resolved_at, e.created_at, r.name AS rule_name
            FROM alert_events e
            LEFT JOIN alert_rules r ON r.id = e.rule_id
            {where}
            ORDER BY e.created_at DESC
            LIMIT ? OFFSET ?""",
        w.with_params(limit, offset),
    ) as cur:
        rows = await cur.fetchall()

    events = []
    for r in rows:
        d = dict(r)
        for flag in ("active", "acked", "resolved"):
            d[flag] = bool(d.get(flag))
        events.append(d)

    return _fit({"total": total, "limit": limit, "offset": offset, "events": events}, "events")


@router.get(
    f"{DATA_PREFIX}/alerts/rules",
    operation_id="listAlertRules",
    summary="List the configured alert rules",
    description=(
        "The rules an administrator has set up, whether each is switched on, what it watches and "
        "at what threshold. Rules are the configuration; listAlertEvents is what they have "
        "actually fired. Read this to answer 'are we even watching for that'. Switching a rule "
        "is not something the assistant can do in pktWiFi — that is an administrator's to do in "
        "the interface."
    ),
    response_model=AlertRuleList,
    responses=_ERRORS,
)
async def list_alert_rules(
    _user: dict = SessionUser,
    enabled_only: bool = Query(False, description="Only rules that are currently switched on."),
    db: aiosqlite.Connection = Depends(get_db),
):
    where = "WHERE enabled = 1" if enabled_only else ""
    async with db.execute(
        f"SELECT id, name, condition_type, threshold, severity, enabled, created_at, channels "
        f"FROM alert_rules {where} ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()
    rules = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d.get("enabled"))
        # Stored as a JSON array; hand it over decoded rather than as a string
        # the reader would have to parse itself.
        try:
            parsed = json.loads(d.get("channels") or "[]")
        except (ValueError, TypeError):
            parsed = []
        d["channels"] = parsed if isinstance(parsed, list) else []
        rules.append(d)
    return _fit({"total": len(rules), "rules": rules}, "rules")


@router.get(
    f"{DATA_PREFIX}/app-log",
    operation_id="searchApplicationLog",
    summary="Search pktWiFi's own diagnostic log",
    description=(
        "pktWiFi's internal log — what the application itself did and any errors it hit. This is "
        "NOT wireless data: for access points use listAccessPoints, for clients use "
        "listWifiClients, and for alert firings use listAlertEvents. Read this to answer 'why "
        "did the controller poll stop'. Newest first."
    ),
    response_model=AppLogResult,
    responses=_ERRORS,
)
async def search_application_log(
    _user: dict = SessionUser,
    level: Optional[LogLevel] = Query(None, description="Only lines at this level."),
    logger: Optional[str] = Query(
        None, max_length=120, description="Only lines from loggers with this prefix."
    ),
    search: Optional[str] = Query(None, max_length=200, description="Substring of the message."),
    since: Optional[str] = Query(None, description="Only lines at or after this time. ISO 8601."),
    until: Optional[str] = Query(None, description="Only lines at or before this time. ISO 8601."),
    limit: int = Query(
        _SEARCH_DEFAULT, ge=1, le=_SEARCH_MAX,
        description=f"How many to return. Default {_SEARCH_DEFAULT}, maximum {_SEARCH_MAX}.",
    ),
    offset: int = Query(0, ge=0, description="How many to skip, for paging."),
    db: aiosqlite.Connection = Depends(get_db),
):
    w = Where()
    if level:
        w.add("level = ?", level)
    if logger:
        w.add("logger LIKE ?", f"{logger}%")
    if search:
        w.add("message LIKE ?", f"%{search}%")
    if since:
        w.add("created_at >= ?", since)
    if until:
        w.add("created_at <= ?", until)
    where = w.sql

    async with db.execute(f"SELECT COUNT(*) FROM app_logs {where}", w.params) as cur:
        total = (await cur.fetchone())[0]

    async with db.execute(
        f"SELECT id, level, logger, message, created_at FROM app_logs {where} "
        "ORDER BY id DESC LIMIT ? OFFSET ?",
        w.with_params(limit, offset),
    ) as cur:
        rows = await cur.fetchall()

    return _fit(
        {"total": total, "limit": limit, "offset": offset, "records": [dict(r) for r in rows]},
        "records",
    )
