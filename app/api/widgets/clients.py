"""
Client widgets: counts, bands, SSIDs, signal health, events and the trend chart.
"""
from __future__ import annotations

import html

import aiosqlite
from fastapi.responses import HTMLResponse

from app.api.widgets._common import _DB, _ap_name, _bars, _empty, _fmt_n, _fmt_ts, _gone, _line_chart, _needs, _note_err, _page, _rows, _since, router
from app.wifi.freshness import client_is_current, radio_is_current


# ── Client Count widget (per-AP, dynamic) ────────────────────────────────────
@router.get("/client_count", response_class=HTMLResponse, include_in_schema=False)
async def widget_client_count(ap_id: int | None = None):
    if not ap_id:
        return HTMLResponse(_page("Client Count", _needs('Select an access point')))

    ap_name = await _ap_name(ap_id)
    if ap_name is None:
        return HTMLResponse(_page("Client Count", _gone(f"Access point {ap_id}")))

    bands = []
    try:
        async with aiosqlite.connect(_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""SELECT r.band, r.client_count
                    FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
                    WHERE r.access_point_id = ? AND {radio_is_current()} ORDER BY r.band""",
                (ap_id,),
            ) as cur:
                bands = [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        _note_err(exc)

    total = sum(b["client_count"] or 0 for b in bands)
    tiles = "".join(
        f'<div class="tile"><div class="tile-label">{html.escape(str(b["band"]))}</div><div class="tile-value">{b["client_count"] or 0}</div></div>'
        for b in bands
    ) or _empty('No radios discovered on any access point')
    body = (
        f'<div style="margin-bottom:8px;color:#64748b;font-size:11px">{html.escape(str(ap_name))}</div>'
        f'<div class="tile-row"><div class="tile"><div class="tile-label">Total Clients</div><div class="tile-value">{total}</div></div></div>'
        f'<div class="tile-row">{tiles}</div>'
    )
    return HTMLResponse(_page("Client Count", body))


# ── Clients by Band widget ────────────────────────────────────────────────────
@router.get("/clients_by_band", response_class=HTMLResponse, include_in_schema=False)
async def widget_clients_by_band():
    rows = await _rows(
        "SELECT COALESCE(NULLIF(band,''),'unknown') AS band, COUNT(*) AS n "
        "FROM wifi_clients c JOIN access_points ap ON ap.id = c.access_point_id "
        f"WHERE {client_is_current()} GROUP BY band ORDER BY n DESC"
    )
    body = _bars([(r["band"], r["n"], str(r["n"])) for r in rows]) \
        if rows else _empty('No clients are currently associated')
    return HTMLResponse(_page("Clients by Band", body))


# ── Clients by SSID widget ────────────────────────────────────────────────────
@router.get("/clients_by_ssid", response_class=HTMLResponse, include_in_schema=False)
async def widget_clients_by_ssid():
    rows = await _rows(
        "SELECT COALESCE(NULLIF(ssid,''),'unknown') AS ssid, COUNT(*) AS n "
        "FROM wifi_clients c JOIN access_points ap ON ap.id = c.access_point_id "
        f"WHERE {client_is_current()} GROUP BY ssid ORDER BY n DESC LIMIT 20"
    )
    body = _bars([(r["ssid"], r["n"], str(r["n"])) for r in rows]) \
        if rows else _empty('No clients are currently associated')
    return HTMLResponse(_page("Clients by SSID", body))


# ── Client Signal Health widget ───────────────────────────────────────────────
@router.get("/client_health", response_class=HTMLResponse, include_in_schema=False)
async def widget_client_health():
    rows = await _rows(
        f"""SELECT c.hostname, c.mac_address, c.ssid, c.band, c.rssi_dbm, c.snr_db,
                  c.tx_rate_mbps, ap.name AS ap_name
           FROM wifi_clients c JOIN access_points ap ON ap.id = c.access_point_id
           WHERE c.rssi_dbm IS NOT NULL AND {client_is_current()} ORDER BY c.rssi_dbm ASC LIMIT 40"""
    )
    if rows:
        def _sig(rssi) -> str:
            r = float(rssi)
            if r >= -65:
                return '<span class="badge bg">GOOD</span>'
            if r >= -75:
                return '<span class="badge by">FAIR</span>'
            return '<span class="badge br">POOR</span>'

        trs = "".join(
            f"<tr><td>{html.escape(str(r.get('hostname') or r.get('mac_address') or ''))}</td>"
            f"<td>{html.escape(str(r.get('ap_name') or ''))}</td>"
            f"<td>{html.escape(str(r.get('ssid') or ''))}</td>"
            f"<td>{_sig(r['rssi_dbm'])} {float(r['rssi_dbm']):.0f}</td>"
            f"<td>{_fmt_n(r['snr_db']) if r.get('snr_db') is not None else '—'}</td>"
            f"<td>{_fmt_n(r['tx_rate_mbps']) if r.get('tx_rate_mbps') is not None else '—'}</td></tr>"
            for r in rows
        )
        body = ("<table><thead><tr><th>Client</th><th>AP</th><th>SSID</th><th>RSSI</th>"
                "<th>SNR</th><th>TX Mbps</th></tr></thead>"
                f"<tbody>{trs}</tbody></table>")
    else:
        body = _empty('No client is reporting signal strength')
    return HTMLResponse(_page("Client Signal Health", body))


# ── Client Events widget ──────────────────────────────────────────────────────
@router.get("/client_events", response_class=HTMLResponse, include_in_schema=False)
async def widget_client_events():
    rows = await _rows(
        """SELECT e.ts, e.mac_address, e.event_type,
                  f.name AS from_ap, t.name AS to_ap
           FROM client_events e
           LEFT JOIN access_points f ON f.id = e.from_ap_id
           LEFT JOIN access_points t ON t.id = e.to_ap_id
           ORDER BY e.ts DESC LIMIT 40"""
    )
    if rows:
        def _evt(t: str) -> str:
            t = (t or "").lower()
            if t in ("deauth", "auth_fail"):
                return f'<span class="badge br">{html.escape(t.upper())}</span>'
            if t == "roam":
                return '<span class="badge by">ROAM</span>'
            return f'<span class="badge bn">{html.escape(t.upper())}</span>'

        trs = "".join(
            f"<tr><td>{html.escape(_fmt_ts(r['ts']))}</td><td>{html.escape(str(r['mac_address']))}</td>"
            f"<td>{_evt(r['event_type'])}</td>"
            f"<td>{html.escape(str(r.get('from_ap') or '—'))} → {html.escape(str(r.get('to_ap') or '—'))}</td></tr>"
            for r in rows
        )
        body = ("<table><thead><tr><th>Time</th><th>Client</th><th>Event</th><th>AP</th></tr></thead>"
                f"<tbody>{trs}</tbody></table>")
    else:
        body = _empty('No client events')
    return HTMLResponse(_page("Client Events", body))


# ── Client Trend widget (chart) ───────────────────────────────────────────────
@router.get("/client_trend", response_class=HTMLResponse, include_in_schema=False)
async def widget_client_trend(hours: int = 6):
    hours = max(1, min(int(hours or 6), 720))
    # Sum across radios per sample bucket — radio_metrics holds one row per radio.
    rows = await _rows(
        """SELECT substr(ts, 1, 16) AS bucket, SUM(client_count) AS n
           FROM radio_metrics WHERE ts >= ? AND client_count IS NOT NULL
           GROUP BY bucket ORDER BY bucket ASC LIMIT 2000""",
        (_since(hours),),
    )
    body = _line_chart([("Clients", [r["n"] for r in rows])])
    return HTMLResponse(_page(f"Client Trend — last {hours}h", body))
