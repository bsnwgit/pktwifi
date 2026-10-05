"""
Estate-level widgets: access point status, alerts, summaries, sites, uptime, rogues and collectors.
"""
from __future__ import annotations

import html

import aiosqlite
from fastapi.responses import HTMLResponse

from app.api.widgets._common import _DB, _bars, _empty, _fmt_ts, _fmt_uptime, _note_err, _page, _rows, _status_badge, _tiles, router
from app.wifi.freshness import client_is_current, radio_is_current


# ── AP Status widget ──────────────────────────────────────────────────────────
@router.get("/ap_status", response_class=HTMLResponse, include_in_schema=False)
async def widget_ap_status():
    rows = []
    try:
        async with aiosqlite.connect(_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""SELECT ap.id, ap.name, ap.site, ap.status,
                          COALESCE((SELECT SUM(r.client_count) FROM radios r
                                    WHERE r.access_point_id = ap.id AND {radio_is_current()}), 0) AS clients
                   FROM access_points ap
                   ORDER BY CASE ap.status WHEN 'offline' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END, ap.name"""
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        _note_err(exc)

    if rows:
        trs = "".join(
            f"<tr><td>{html.escape(str(r['name']))}</td><td>{html.escape(str(r.get('site') or ''))}</td>"
            f"<td>{_status_badge(r['status'])}</td><td>{r['clients']}</td></tr>"
            for r in rows
        )
        body = (
            "<table><thead><tr><th>Access Point</th><th>Site</th><th>Status</th><th>Clients</th></tr></thead>"
            f"<tbody>{trs}</tbody></table>"
        )
    else:
        body = _empty('No access points')
    return HTMLResponse(_page("AP Status", body))


# ── Active Alerts widget ──────────────────────────────────────────────────────
@router.get("/active_alerts", response_class=HTMLResponse, include_in_schema=False)
async def widget_active_alerts():
    rows = []
    try:
        async with aiosqlite.connect(_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT ae.severity, ae.message, ae.created_at, ap.name AS ap_name
                   FROM alert_events ae LEFT JOIN access_points ap ON ap.id = ae.access_point_id
                   WHERE ae.active = 1 AND ae.acked = 0
                   ORDER BY ae.created_at DESC LIMIT 40"""
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        _note_err(exc)

    if rows:
        trs = "".join(
            f"<tr><td>{_status_badge('offline' if r['severity'] == 'critical' else 'unknown')}</td>"
            f"<td>{html.escape(str(r.get('ap_name') or ''))}</td><td>{html.escape(str(r['message']))}</td>"
            f"<td>{html.escape(str(r['created_at'])[:19].replace('T',' '))}</td></tr>"
            for r in rows
        )
        body = (
            "<table><thead><tr><th>Severity</th><th>AP</th><th>Message</th><th>Fired</th></tr></thead>"
            f"<tbody>{trs}</tbody></table>"
        )
    else:
        body = _empty('No active alerts')
    return HTMLResponse(_page("Active Alerts", body))


# ── WiFi Summary widget ───────────────────────────────────────────────────────
@router.get("/wifi_summary", response_class=HTMLResponse, include_in_schema=False)
async def widget_wifi_summary():
    ap  = await _rows(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status='online'  THEN 1 ELSE 0 END) AS online,
                  SUM(CASE WHEN status='offline' THEN 1 ELSE 0 END) AS offline,
                  SUM(CASE WHEN is_rogue=1       THEN 1 ELSE 0 END) AS rogue
           FROM access_points"""
    )
    cli = await _rows(
        f"""SELECT COUNT(*) AS clients
            FROM wifi_clients c JOIN access_points ap ON ap.id = c.access_point_id
            WHERE {client_is_current()}"""
    )
    a   = ap[0] if ap else {}
    body = _tiles([
        ("APs",     a.get("total")   or 0),
        ("Online",  a.get("online")  or 0),
        ("Offline", a.get("offline") or 0),
        ("Rogue",   a.get("rogue")   or 0),
        ("Clients", (cli[0]["clients"] if cli else 0) or 0),
    ])
    return HTMLResponse(_page("WiFi Summary", body))


# ── Alert Summary widget ──────────────────────────────────────────────────────
@router.get("/alert_summary", response_class=HTMLResponse, include_in_schema=False)
async def widget_alert_summary():
    rows   = await _rows(
        "SELECT LOWER(severity) AS sev, COUNT(*) AS n FROM alert_events "
        "WHERE active = 1 AND acked = 0 GROUP BY sev"
    )
    counts = {r["sev"]: r["n"] for r in rows}
    body   = _tiles([
        ("Active",   sum(counts.values())),
        ("Critical", counts.get("critical", 0)),
        ("Warning",  counts.get("warning", 0)),
        ("Info",     counts.get("info", 0)),
    ])
    return HTMLResponse(_page("Alert Summary", body))


# ── APs by Site widget ────────────────────────────────────────────────────────
@router.get("/aps_by_site", response_class=HTMLResponse, include_in_schema=False)
async def widget_aps_by_site():
    rows = await _rows(
        """SELECT CASE WHEN site IS NULL OR site = '' THEN 'Unassigned' ELSE site END AS site,
                  COUNT(*) AS total,
                  SUM(CASE WHEN status='offline' THEN 1 ELSE 0 END) AS offline
           FROM access_points GROUP BY site ORDER BY total DESC LIMIT 20"""
    )
    body = _bars([
        (r["site"], r["total"], f"{r['total']}" + (f" · {r['offline']}↓" if r["offline"] else ""))
        for r in rows
    ]) if rows else _empty('No access points')
    return HTMLResponse(_page("APs by Site", body))


# ── AP Uptime widget ──────────────────────────────────────────────────────────
@router.get("/ap_uptime", response_class=HTMLResponse, include_in_schema=False)
async def widget_ap_uptime():
    rows = await _rows(
        "SELECT name, uptime_seconds FROM access_points "
        "WHERE uptime_seconds IS NOT NULL ORDER BY uptime_seconds ASC LIMIT 30"
    )
    body = _bars([
        (r["name"], float(r["uptime_seconds"] or 0), _fmt_uptime(r["uptime_seconds"]))
        for r in rows
    ], color="#60a5fa") if rows else _empty('No access point is reporting uptime')
    return HTMLResponse(_page("AP Uptime", body))


# ── Rogue APs widget ──────────────────────────────────────────────────────────
@router.get("/rogue_aps", response_class=HTMLResponse, include_in_schema=False)
async def widget_rogue_aps():
    rows = await _rows(
        "SELECT name, mac_address, site, vendor, last_seen FROM access_points "
        "WHERE is_rogue = 1 ORDER BY last_seen DESC LIMIT 40"
    )
    if rows:
        trs = "".join(
            f"<tr><td>{html.escape(str(r['name']))}</td><td>{html.escape(str(r.get('mac_address') or ''))}</td>"
            f"<td>{html.escape(str(r.get('site') or ''))}</td><td>{html.escape(str(r.get('vendor') or ''))}</td>"
            f"<td>{html.escape(_fmt_ts(r.get('last_seen')))}</td></tr>"
            for r in rows
        )
        body = ("<table><thead><tr><th>Name</th><th>MAC</th><th>Site</th><th>Vendor</th><th>Last Seen</th></tr></thead>"
                f"<tbody>{trs}</tbody></table>")
    else:
        body = _empty('No rogue APs detected')
    return HTMLResponse(_page("Rogue APs", body))


# ── Collector Status widget ───────────────────────────────────────────────────
@router.get("/collector_status", response_class=HTMLResponse, include_in_schema=False)
async def widget_collector_status():
    rows = await _rows(
        "SELECT name, collector_type, enabled, status, last_poll_at, last_error "
        "FROM collectors ORDER BY name"
    )
    if rows:
        trs = "".join(
            f"<tr><td>{html.escape(str(r['name']))}</td><td>{html.escape(str(r.get('collector_type') or ''))}</td>"
            f"<td>{_status_badge(r.get('status') if r.get('enabled') else 'disabled')}</td>"
            f"<td>{html.escape(_fmt_ts(r.get('last_poll_at')))}</td>"
            f"<td>{html.escape(str(r.get('last_error') or ''))[:60]}</td></tr>"
            for r in rows
        )
        body = ("<table><thead><tr><th>Collector</th><th>Type</th><th>Status</th>"
                "<th>Last Poll</th><th>Error</th></tr></thead>"
                f"<tbody>{trs}</tbody></table>")
    else:
        body = _empty('No collectors')
    return HTMLResponse(_page("Collector Status", body))
