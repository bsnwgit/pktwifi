"""
Radio and RF widgets: overview, channel utilisation, noise floor, trends, spectrum and signal scope.
"""
from __future__ import annotations

import html

from fastapi.responses import HTMLResponse

from app.api.widgets._common import _ap_name, _bars, _empty, _fmt_n, _gone, _line_chart, _needs, _page, _rows, _since, router
from app.wifi.freshness import client_is_current, radio_is_current


# ── Radio Overview widget ─────────────────────────────────────────────────────
@router.get("/radio_overview", response_class=HTMLResponse, include_in_schema=False)
async def widget_radio_overview():
    rows = await _rows(
        f"""SELECT ap.name AS ap_name, r.band, r.channel, r.channel_width_mhz,
                  r.tx_power_dbm, r.utilization_pct, r.noise_floor_dbm, r.client_count
           FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
           WHERE {radio_is_current()}
           ORDER BY r.utilization_pct DESC, ap.name LIMIT 60"""
    )
    if rows:
        trs = "".join(
            f"<tr><td>{html.escape(str(r['ap_name']))}</td><td>{html.escape(str(r.get('band') or ''))}</td>"
            f"<td>{r.get('channel') if r.get('channel') is not None else '—'}"
            f"{('/' + str(r['channel_width_mhz'])) if r.get('channel_width_mhz') else ''}</td>"
            f"<td>{_fmt_n(r['tx_power_dbm']) + ' dBm' if r.get('tx_power_dbm') is not None else '—'}</td>"
            f"<td>{_fmt_n(r['utilization_pct']) + '%' if r.get('utilization_pct') is not None else '—'}</td>"
            f"<td>{_fmt_n(r['noise_floor_dbm']) + ' dBm' if r.get('noise_floor_dbm') is not None else '—'}</td>"
            f"<td>{r.get('client_count') or 0}</td></tr>"
            for r in rows
        )
        body = ("<table><thead><tr><th>AP</th><th>Band</th><th>Ch/W</th><th>TX</th>"
                "<th>Util</th><th>Noise</th><th>Clients</th></tr></thead>"
                f"<tbody>{trs}</tbody></table>")
    else:
        body = _empty('No radios discovered on any access point')
    return HTMLResponse(_page("Radio Overview", body))


# ── Channel Utilization widget ────────────────────────────────────────────────
@router.get("/channel_utilization", response_class=HTMLResponse, include_in_schema=False)
async def widget_channel_utilization():
    rows = await _rows(
        f"""SELECT ap.name AS ap_name, r.band, r.channel, r.utilization_pct
           FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
           WHERE r.utilization_pct IS NOT NULL AND {radio_is_current()}
           ORDER BY r.utilization_pct DESC LIMIT 25"""
    )
    body = _bars([
        (f"{r['ap_name']} · {r.get('band') or ''}{(' ch' + str(r['channel'])) if r.get('channel') else ''}",
         float(r["utilization_pct"] or 0), f"{float(r['utilization_pct'] or 0):.0f}%")
        for r in rows
    ]) if rows else _empty('No radio is reporting channel utilization')
    return HTMLResponse(_page("Channel Utilization", body))


# ── Noise Floor widget ────────────────────────────────────────────────────────
@router.get("/noise_floor", response_class=HTMLResponse, include_in_schema=False)
async def widget_noise_floor():
    # Noise floor is negative dBm — closer to zero is worse, so rank descending.
    rows = await _rows(
        f"""SELECT ap.name AS ap_name, r.band, r.noise_floor_dbm
           FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
           WHERE r.noise_floor_dbm IS NOT NULL AND {radio_is_current()}
           ORDER BY r.noise_floor_dbm DESC LIMIT 25"""
    )
    if rows:
        # Bars scale on distance from a -100 dBm floor so the worst radio is longest.
        body = _bars([
            (f"{r['ap_name']} · {r.get('band') or ''}",
             max(0.0, 100.0 + float(r["noise_floor_dbm"])), f"{float(r['noise_floor_dbm']):.0f} dBm")
            for r in rows
        ], color="#f87171")
    else:
        body = _empty('No radio is reporting a noise floor')
    return HTMLResponse(_page("Noise Floor", body))


# ── Radio Trend widget (chart) ────────────────────────────────────────────────
_RADIO_METRICS = {
    "utilization_pct", "client_count", "noise_floor_dbm",
    "retry_pct", "crc_error_pct", "tx_power_dbm",
}


@router.get("/radio_trend", response_class=HTMLResponse, include_in_schema=False)
async def widget_radio_trend(
    ap_id: int | None = None, radio_id: int | None = None,
    metric: str = "utilization_pct", hours: int = 6,
):
    if not radio_id:
        return HTMLResponse(_page("Radio Trend", _needs('Select an access point and radio')))
    if ap_id and await _ap_name(ap_id) is None:
        return HTMLResponse(_page("Radio Trend", _gone(f"Access point {ap_id}")))
    # Allow-list the column — it is interpolated into the SELECT, and a metric
    # name arrives from the widget's saved config.
    if metric not in _RADIO_METRICS:
        metric = "utilization_pct"

    hours = max(1, min(int(hours or 6), 720))
    rows  = await _rows(
        f"SELECT ts, {metric} AS v FROM radio_metrics "
        "WHERE radio_id = ? AND ts >= ? AND "
        f"{metric} IS NOT NULL ORDER BY ts ASC LIMIT 2000",
        (radio_id, _since(hours)),
    )
    if not rows:
        return HTMLResponse(_page("Radio Trend", _empty('No samples in window')))

    band = await _rows("SELECT band FROM radios WHERE id = ?", (radio_id,))
    label = f"{band[0]['band']} {metric}" if band else metric
    body  = _line_chart([(label, [r["v"] for r in rows])])
    return HTMLResponse(_page(f"{label} — last {hours}h", body))


# ── Airtime by Band widget (chart) ────────────────────────────────────────────
@router.get("/airtime_trend", response_class=HTMLResponse, include_in_schema=False)
async def widget_airtime_trend(hours: int = 6):
    hours  = max(1, min(int(hours or 6), 720))
    bucket = max(60, (hours * 3600) // 120)
    rows = await _rows(
        """SELECT (CAST(strftime('%s', m.ts) AS INTEGER) / ?) AS b, r.band AS band,
                  AVG(m.utilization_pct) AS util
           FROM radio_metrics m JOIN radios r ON r.id = m.radio_id
           WHERE m.ts >= ? AND m.utilization_pct IS NOT NULL
             AND r.band IN ('2.4GHz','5GHz','6GHz')
           GROUP BY b, r.band ORDER BY b""",
        (bucket, _since(hours)),
    )
    if not rows:
        return HTMLResponse(_page("Airtime by Band", _empty('No radio reported utilization in this window')))
    buckets = sorted({r["b"] for r in rows})
    series = []
    for band in ("2.4GHz", "5GHz", "6GHz"):
        have = {r["b"]: r["util"] for r in rows if r["band"] == band}
        if not have:
            continue
        # Carry the last reading across a gap (and the first one back to the
        # start) so every band spans the same buckets.
        first = have[min(have)]
        vals, last = [], first
        for b in buckets:
            last = have.get(b, last)
            vals.append(float(last))
        series.append((band, vals))
    body = _line_chart(series, fmt=lambda v: f"{v:.0f}%")
    return HTMLResponse(_page(f"Airtime by Band — last {hours}h", body))


# ── RF Spectrum widget ────────────────────────────────────────────────────────
@router.get("/rf_spectrum", response_class=HTMLResponse, include_in_schema=False)
async def widget_rf_spectrum():
    from app.wifi.rf import BANDS, band_axis, occupied_span
    rows = await _rows(
        f"""SELECT ap.name AS ap_name, r.band, r.channel, r.channel_width_mhz, r.utilization_pct
           FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
           WHERE r.band IN ('2.4GHz','5GHz','6GHz') AND {radio_is_current()}"""
    )
    placed = []
    for r in rows:
        span = occupied_span(r["band"], r["channel"], r["channel_width_mhz"])
        if span:
            placed.append({**r, **span})
    if not placed:
        return HTMLResponse(_page("RF Spectrum", _empty('No radio has a usable channel')))

    colors = {"2.4GHz": "#fb923c", "5GHz": "#60a5fa", "6GHz": "#a78bfa"}
    W, LANE, GAP = 600, 96, 22
    lanes, y0 = [], 0
    for band in BANDS:
        mine = [p for p in placed if p["band"] == band]
        if not mine:
            continue
        ax = band_axis(band)
        lo, hi = ax["lo_mhz"], ax["hi_mhz"]
        X = lambda mhz: (mhz - lo) / (hi - lo) * W
        base = y0 + LANE
        parts = [f'<text x="0" y="{y0 + 9}" font-size="10" fill="#94a3b8">{html.escape(band)}</text>',
                 f'<line x1="0" y1="{base}" x2="{W}" y2="{base}" stroke="#334155"/>']
        for t in ax["ticks"]:
            if t["major"]:
                x = X(t["mhz"])
                parts.append(f'<line x1="{x:.1f}" y1="{base}" x2="{x:.1f}" y2="{base + 4}" stroke="#475569"/>'
                             f'<text x="{x:.1f}" y="{base + 14}" font-size="8" text-anchor="middle" fill="#64748b">{t["channel"]}</text>')
        for p in mine:
            util = p["utilization_pct"]
            h = max(4.0, (float(util) if util is not None else 8.0) / 100 * (LANE - 18))
            x, w = X(p["lo_mhz"]), max(2.0, X(p["hi_mhz"]) - X(p["lo_mhz"]))
            dash = ' stroke-dasharray="3 2" stroke="#e2e8f0" stroke-width="1"' \
                if (p["approximate"] or not p["width_reported"] or util is None) else ""
            tip = f'{p["ap_name"]} · ch {p["channel"]} · ' + (f'{float(util):.0f}%' if util is not None else 'no utilization')
            parts.append(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{w:.1f}" height="{h:.1f}" '
                         f'fill="{colors[band]}" fill-opacity="0.35"{dash}><title>{html.escape(tip)}</title></rect>')
        lanes.append("".join(parts))
        y0 += LANE + GAP
    body = (f'<svg viewBox="0 0 {W} {y0}" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">'
            f'{"".join(lanes)}</svg>'
            '<div style="font-size:10px;color:#64748b;margin-top:6px">height = channel utilization · '
            'dashed = width not reported, position approximate or no utilization</div>')
    return HTMLResponse(_page("RF Spectrum", body))


# ── Signal Scope widget ───────────────────────────────────────────────────────
@router.get("/signal_scope", response_class=HTMLResponse, include_in_schema=False)
async def widget_signal_scope():
    import math
    import zlib
    from app.wifi.rf import SIGNAL_FAIR_DBM, SIGNAL_GOOD_DBM
    rows = await _rows(
        f"""SELECT ap.id AS ap_id, ap.name AS ap_name, c.rssi_dbm, c.mac_address
           FROM wifi_clients c JOIN access_points ap ON ap.id = c.access_point_id
           WHERE c.rssi_dbm IS NOT NULL AND {client_is_current()}"""
    )
    if not rows:
        return HTMLResponse(_page("Signal Scope", _empty('No client is reporting a signal')))
    by_ap: dict[int, list[dict]] = {}
    for r in rows:
        by_ap.setdefault(r["ap_id"], []).append(r)
    ranked = sorted(by_ap.values(), key=lambda m: (-len(m), m[0]["ap_name"]))[:16]

    CX = CY = 200
    R_CORE, R_MAX, STRONG, WEAK = 20, 150, -30, -95
    rng = lambda v: R_CORE + (R_MAX - R_CORE) * (STRONG - max(WEAK, min(STRONG, v))) / (STRONG - WEAK)
    n = len(ranked)
    parts = []
    for dbm, lbl in ((SIGNAL_GOOD_DBM, "good"), (SIGNAL_FAIR_DBM, "fair")):
        parts.append(f'<circle cx="{CX}" cy="{CY}" r="{rng(dbm):.1f}" fill="none" stroke="#334155" '
                     f'stroke-dasharray="2 4"/><text x="{CX + 3}" y="{CY - rng(dbm) - 2:.1f}" '
                     f'font-size="7" fill="#64748b">{dbm} dBm</text>')
    for i, members in enumerate(ranked):
        a0, a1 = 360 * i / n, 360 * (i + 1) / n
        mid = math.radians((a0 + a1) / 2)
        sx, sy = CX + R_MAX * math.sin(math.radians(a0)), CY - R_MAX * math.cos(math.radians(a0))
        parts.append(f'<line x1="{CX}" y1="{CY}" x2="{sx:.1f}" y2="{sy:.1f}" stroke="#1e293b"/>')
        lx, ly = CX + (R_MAX + 14) * math.sin(mid), CY - (R_MAX + 14) * math.cos(mid)
        name = str(members[0]["ap_name"])
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="8" text-anchor="middle" fill="#94a3b8">'
                     f'{html.escape(name[:14])} · {len(members)}</text>')
        for j, c in enumerate(sorted(members, key=lambda m: m["rssi_dbm"])[:120]):
            # Where a client sits around its sector means nothing; it is spread
            # out only so the dots do not stack.
            frac = ((zlib.crc32(f'{c["mac_address"]}|{i}'.encode()) % 1000) / 1000) * 0.8 + 0.1
            ang = math.radians(a0 + (a1 - a0) * frac)
            r = rng(float(c["rssi_dbm"]))
            col = ("#4ade80" if c["rssi_dbm"] >= SIGNAL_GOOD_DBM
                   else "#fbbf24" if c["rssi_dbm"] >= SIGNAL_FAIR_DBM else "#f87171")
            parts.append(f'<circle cx="{CX + r * math.sin(ang):.1f}" cy="{CY - r * math.cos(ang):.1f}" r="2.2" fill="{col}"/>')
    body = ('<svg viewBox="0 0 400 400" style="width:100%;height:100%;max-height:100%" '
            f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>')
    return HTMLResponse(_page("Signal Scope", body))
