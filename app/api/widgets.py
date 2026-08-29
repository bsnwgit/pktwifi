"""
pktWiFi — Widget endpoints for pktHub NOC Builder integration.

Manifest: GET /api/widgets/manifest  → list of widget definitions
Views:    GET /api/widgets/{id}      → server-rendered HTML page (iframe target)
Options:  GET /api/widgets/options/* → JSON [{value,label}] for dynamic param pickers
"""
from __future__ import annotations

import html
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

import aiosqlite
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.dependencies import require_suite_token

# These views are embedded as unauthenticated iframes by pktHub's NOC Builder,
# so they can't require a login session — but they do render internal access
# point, client and alert data, so every route on this router requires a valid
# X-Suite-Token (the trusted-proxy secret pktHub already sends on every
# proxied request).
# ── Refresh interval ──────────────────────────────────────────────────────────
# pktHub's Settings → NOC → "Widget refresh" governs how often a tile reloads
# itself. It arrives as ?refresh=<seconds> on the widget URL; captured here as a
# router dependency so the ~150 view functions need no signature change.
_REFRESH: ContextVar = ContextVar("widget_refresh", default=30)


async def _capture_refresh(request: Request) -> None:
    raw = request.query_params.get("refresh")
    try:
        _REFRESH.set(max(5, min(int(raw), 3600)) if raw else 30)
    except (TypeError, ValueError):
        _REFRESH.set(30)


router = APIRouter(dependencies=[Depends(_capture_refresh), Depends(require_suite_token)])
_s     = get_settings()
_DB    = _s.db_path

# ── Manifest ──────────────────────────────────────────────────────────────────
# `category` groups these in pktHub's NOC library picker. Every data surface the
# app renders in its own UI should have an entry here — the NOC builder can only
# offer what this list declares.
_AP_PARAM = {
    "key": "ap_id", "label": "Access Point", "type": "select",
    "options_path": "/api/widgets/options/access_points",
}
_WINDOW_PARAM = {
    "key": "hours", "label": "Window", "type": "select",
    "options": [{"value": "1", "label": "1 hour"}, {"value": "6", "label": "6 hours"},
                {"value": "24", "label": "24 hours"}, {"value": "168", "label": "7 days"}],
}

MANIFEST = [
    # ── Overview ──────────────────────────────────────────────────────────────
    {
        "id": "wifi_summary", "title": "WiFi Summary", "category": "Overview",
        "description": "Access point, client and rogue counts across the estate",
        "view_path": "/api/widgets/wifi_summary",
        "default_w": 560, "default_h": 200, "min_w": 300, "min_h": 150,
    },
    {
        "id": "alert_summary", "title": "Alert Summary", "category": "Overview",
        "description": "Active alert counts by severity",
        "view_path": "/api/widgets/alert_summary",
        "default_w": 420, "default_h": 200, "min_w": 260, "min_h": 150,
    },
    {
        "id": "aps_by_site", "title": "APs by Site", "category": "Overview",
        "description": "Access point count and offline count per site",
        "view_path": "/api/widgets/aps_by_site",
        "default_w": 480, "default_h": 320, "min_w": 280, "min_h": 200,
    },

    # ── Access Points ─────────────────────────────────────────────────────────
    {
        "id": "ap_status", "title": "AP Status", "category": "Access Points",
        "description": "All access points with site, status, and connected client count",
        "view_path": "/api/widgets/ap_status",
        "default_w": 640, "default_h": 380, "min_w": 340, "min_h": 220,
    },
    {
        "id": "ap_uptime", "title": "AP Uptime", "category": "Access Points",
        "description": "Reported uptime per access point, least stable first",
        "view_path": "/api/widgets/ap_uptime",
        "default_w": 540, "default_h": 340, "min_w": 300, "min_h": 200,
    },
    {
        "id": "rogue_aps", "title": "Rogue APs", "category": "Access Points",
        "description": "Access points flagged as rogue",
        "view_path": "/api/widgets/rogue_aps",
        "default_w": 620, "default_h": 320, "min_w": 320, "min_h": 180,
    },

    # ── Radios ────────────────────────────────────────────────────────────────
    {
        "id": "radio_overview", "title": "Radio Overview", "category": "Radios",
        "description": "Per-radio band, channel, width, power, utilization and noise",
        "view_path": "/api/widgets/radio_overview",
        "default_w": 780, "default_h": 400, "min_w": 380, "min_h": 220,
    },
    {
        "id": "channel_utilization", "title": "Channel Utilization", "category": "Radios",
        "description": "Busiest radios by channel utilization",
        "view_path": "/api/widgets/channel_utilization",
        "default_w": 540, "default_h": 340, "min_w": 300, "min_h": 200,
    },
    {
        "id": "noise_floor", "title": "Noise Floor", "category": "Radios",
        "description": "Radios with the highest noise floor",
        "view_path": "/api/widgets/noise_floor",
        "default_w": 540, "default_h": 340, "min_w": 300, "min_h": 200,
    },

    # ── Clients ───────────────────────────────────────────────────────────────
    {
        "id": "client_count", "title": "Client Count", "category": "Clients",
        "description": "Connected client count by radio band for one access point",
        "view_path": "/api/widgets/client_count",
        "default_w": 460, "default_h": 300, "min_w": 280, "min_h": 180,
        "params": [_AP_PARAM],
    },
    {
        "id": "clients_by_band", "title": "Clients by Band", "category": "Clients",
        "description": "Connected client distribution across radio bands",
        "view_path": "/api/widgets/clients_by_band",
        "default_w": 440, "default_h": 280, "min_w": 260, "min_h": 170,
    },
    {
        "id": "clients_by_ssid", "title": "Clients by SSID", "category": "Clients",
        "description": "Connected client distribution across SSIDs",
        "view_path": "/api/widgets/clients_by_ssid",
        "default_w": 480, "default_h": 300, "min_w": 280, "min_h": 180,
    },
    {
        "id": "client_health", "title": "Client Signal Health", "category": "Clients",
        "description": "Clients bucketed by signal strength, weakest listed first",
        "view_path": "/api/widgets/client_health",
        "default_w": 620, "default_h": 360, "min_w": 320, "min_h": 200,
    },
    {
        "id": "client_events", "title": "Client Events", "category": "Clients",
        "description": "Recent associate, roam, deauth and auth-failure events",
        "view_path": "/api/widgets/client_events",
        "default_w": 700, "default_h": 360, "min_w": 340, "min_h": 200,
    },

    # ── Trends (charts) ───────────────────────────────────────────────────────
    {
        "id": "radio_trend", "title": "Radio Trend", "category": "Trends",
        "description": "Utilization, clients and noise over time for one radio",
        "view_path": "/api/widgets/radio_trend",
        "default_w": 680, "default_h": 320, "min_w": 320, "min_h": 180,
        "params": [
            _AP_PARAM,
            # {ap_id} is substituted from the widget's own config by pktHub, so the
            # radio list reflects whatever bands that AP currently reports.
            {"key": "radio_id", "label": "Radio", "type": "select",
             "options_path": "/api/widgets/options/radios?ap_id={ap_id}"},
            {"key": "metric", "label": "Metric", "type": "select",
             "options": [{"value": "utilization_pct", "label": "Utilization %"},
                         {"value": "client_count",    "label": "Clients"},
                         {"value": "noise_floor_dbm", "label": "Noise floor"},
                         {"value": "retry_pct",       "label": "Retry %"},
                         {"value": "crc_error_pct",   "label": "CRC error %"},
                         {"value": "tx_power_dbm",    "label": "TX power"}]},
            _WINDOW_PARAM,
        ],
    },
    {
        "id": "client_trend", "title": "Client Trend", "category": "Trends",
        "description": "Total connected clients over time",
        "view_path": "/api/widgets/client_trend",
        "default_w": 620, "default_h": 300, "min_w": 300, "min_h": 170,
        "params": [_WINDOW_PARAM],
    },

    # ── Alerts ────────────────────────────────────────────────────────────────
    {
        "id": "active_alerts", "title": "Active Alerts", "category": "Alerts",
        "description": "Unresolved WiFi alert events",
        "view_path": "/api/widgets/active_alerts",
        "default_w": 640, "default_h": 360, "min_w": 320, "min_h": 200,
    },

    # ── Collectors ────────────────────────────────────────────────────────────
    {
        "id": "collector_status", "title": "Collector Status", "category": "Collectors",
        "description": "Controller/collector health and last successful poll",
        "view_path": "/api/widgets/collector_status",
        "default_w": 620, "default_h": 300, "min_w": 320, "min_h": 180,
    },
]


@router.get("/manifest")
async def widget_manifest():
    return MANIFEST



# ── Widget states ──────────────────────────────────────────────────────────────
# A blank tile on a wallboard reads as "all quiet", so the three reasons a widget
# can show nothing must look different from each other:
#   empty — the query ran and there genuinely is nothing
#   cfg   — the widget needs a param chosen in the NOC editor before it can run
#   err   — the query failed; this must never be mistaken for "nothing to report"
# Query helpers record failures here rather than swallowing them; _page() renders
# the error state instead of whatever half-built body the caller produced. The
# ContextVar is per-request: each request runs in its own task context.
_WIDGET_ERR: ContextVar = ContextVar("widget_err", default=None)


def _note_err(exc: BaseException) -> None:
    _WIDGET_ERR.set(f"{type(exc).__name__}: {exc}"[:200])


def _state(kind: str, msg: str, sub: str = "") -> str:
    icon = {"empty": "○", "cfg": "⚙", "err": "⚠"}.get(kind, "○")
    sub_html = f'<div class="state-sub">{html.escape(str(sub))}</div>' if sub else ""
    return (f'<div class="state state-{kind}"><div class="state-icon">{icon}</div>'
            f'<div class="state-msg">{html.escape(str(msg))}</div>{sub_html}</div>')


def _empty(msg: str) -> str:
    return _state("empty", msg)


def _needs(msg: str) -> str:
    """The widget is fine — it is waiting on a filter the NOC editor must set."""
    return _state("cfg", msg, "Select it in the widget's Filters panel")


# ── Shared page shell ───────────────────────────────────────────────────────────
def _page(title: str, body: str) -> str:
    # Widget titles carry device/metric/subnet names chosen in the NOC editor
    # and read back from device data, and these pages render on an
    # unauthenticated display URL — escape before interpolating.
    title = html.escape(str(title))
    # A failed query leaves a body saying "nothing here" — which is a lie.
    _err = _WIDGET_ERR.get()
    if _err:
        body = _state("err", "Widget unavailable", _err)
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#04060a;color:#e2e8f0;font-family:'Inter',system-ui,sans-serif;font-size:13px;height:100vh;overflow:hidden;display:flex;flex-direction:column}}
.hdr{{padding:8px 14px;border-bottom:1px solid #1e293b;display:flex;align-items:center;gap:8px;flex-shrink:0;height:36px}}
.hdr-dot{{width:6px;height:6px;border-radius:50%;background:#fb923c;flex-shrink:0}}
.hdr-title{{font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.03em}}
.content{{flex:1;overflow:auto;padding:12px}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;padding:4px 8px;border-bottom:1px solid #1e293b}}
td{{padding:6px 8px;border-bottom:1px solid #0f172a;font-size:12px;color:#cbd5e1}}
tr:hover td{{background:#111827}}
.badge{{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600}}
.bg{{background:#052e16;color:#4ade80}}.br{{background:#3f1515;color:#f87171}}
.by{{background:#422006;color:#fbbf24}}.bn{{background:#1e293b;color:#64748b}}
.empty{{text-align:center;padding:40px;color:#334155;font-size:12px}}
.tile-row{{display:flex;gap:14px;margin-bottom:14px;flex-wrap:wrap}}
.tile{{flex:1;min-width:84px;background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px 12px}}
.tile-label{{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px}}
.tile-value{{font-size:22px;font-weight:700;color:#e2e8f0}}
.bar-row{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.bar-lbl{{font-size:11px;color:#94a3b8;width:120px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar-trk{{flex:1;background:#1e293b;border-radius:3px;height:8px;overflow:hidden}}
.bar-fill{{height:8px;border-radius:3px;background:#fb923c}}
.bar-val{{font-size:10px;color:#475569;width:62px;text-align:right;flex-shrink:0}}
.chart-wrap{{width:100%;height:100%;min-height:90px;display:flex;flex-direction:column}}
.chart-meta{{display:flex;gap:12px;font-size:10px;color:#475569;margin-bottom:6px;flex-wrap:wrap}}
.chart-meta b{{color:#94a3b8;font-weight:600}}
.chart-svg{{flex:1;width:100%;min-height:0}}
.legend{{display:flex;gap:12px;font-size:10px;color:#94a3b8;margin-top:6px;flex-wrap:wrap}}
.legend i{{width:8px;height:2px;display:inline-block;margin-right:4px;vertical-align:middle}}
.state{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;min-height:80px;text-align:center;padding:18px;gap:5px}}
.state-icon{{font-size:17px;line-height:1;opacity:0.85}}
.state-msg{{font-size:12px;font-weight:500}}
.state-sub{{font-size:10px;color:#64748b;max-width:92%;word-break:break-word}}
.state-empty{{color:#64748b}}
.state-cfg{{color:#fbbf24}}
.state-err{{color:#f87171}}
</style>
<script>setTimeout(()=>location.reload(),{_REFRESH.get() * 1000})</script>
</head><body>
<div class="hdr"><div class="hdr-dot"></div><div class="hdr-title">{title}</div></div>
<div class="content">{body}</div>
</body></html>"""


def _status_badge(status: str) -> str:
    s = (status or "").lower()
    if s in ("online", "ok"):
        return '<span class="badge bg">{}</span>'.format(html.escape(s.upper()))
    if s in ("offline", "error"):
        return '<span class="badge br">{}</span>'.format(html.escape(s.upper()))
    return f'<span class="badge bn">{html.escape((status or "UNKNOWN").upper())}</span>'


# ── Time window ─────────────────────────────────────────────────────────────────
def _since(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


# ── AP lookup ───────────────────────────────────────────────────────────────────
async def _ap_name(ap_id: int) -> str | None:
    """None when the AP is gone. A NOC screen outlives the estate it was built
    against, so a widget pinned to a decommissioned AP has to say so rather than
    render an empty frame the wall-watcher reads as 'all quiet'."""
    try:
        async with aiosqlite.connect(_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT name FROM access_points WHERE id=?", (ap_id,)) as cur:
                row = await cur.fetchone()
        return row["name"] if row else None
    except Exception:
        return None


def _gone(what: str) -> str:
    return f_empty('{html.escape(what)} no longer exists')


# ── Formatting ──────────────────────────────────────────────────────────────────
def _fmt_n(n) -> str:
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "—"
    for div, suf in ((1_000_000_000, "G"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}{suf}"
    return f"{n:.0f}" if n == int(n) else f"{n:.1f}"


def _fmt_ts(ts) -> str:
    return str(ts)[:19].replace("T", " ") if ts else "—"


def _fmt_uptime(seconds) -> str:
    try:
        secs = int(seconds or 0)
    except (TypeError, ValueError):
        return "—"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    return f"{d}d {h}h" if d else f"{h}h {rem // 60}m"


# ── Tiles / bars ────────────────────────────────────────────────────────────────
def _tiles(pairs) -> str:
    return '<div class="tile-row">' + "".join(
        f'<div class="tile"><div class="tile-label">{html.escape(str(label))}</div>'
        f'<div class="tile-value">{html.escape(str(value))}</div></div>'
        for label, value in pairs
    ) + "</div>"


def _bars(rows, color: str = "#fb923c") -> str:
    """rows = [(label, numeric_value, display_value)] — scaled to the largest."""
    peak = max((r[1] or 0) for r in rows) if rows else 0
    return "".join(
        f'<div class="bar-row"><div class="bar-lbl" title="{html.escape(str(lbl))}">{html.escape(str(lbl))}</div>'
        f'<div class="bar-trk"><div class="bar-fill" style="width:{(val / peak * 100) if peak else 0:.1f}%;background:{color}"></div></div>'
        f'<div class="bar-val">{html.escape(str(disp))}</div></div>'
        for lbl, val, disp in rows
    )


# ── Inline SVG line chart ───────────────────────────────────────────────────────
# Server-rendered so the iframe stays dependency-free — pktWiFi ships no charting
# library to these views, and the NOC display must render without network access
# to anything but this app.
_SERIES_COLORS = ("#fb923c", "#60a5fa", "#4ade80", "#f87171", "#a78bfa")


def _line_chart(series, fmt=_fmt_n, height: int = 120) -> str:
    """series = [(label, [float, ...])] — equal-length samples, oldest first."""
    series = [(lbl, [v for v in vals if v is not None]) for lbl, vals in series]
    series = [(lbl, vals) for lbl, vals in series if len(vals) >= 2]
    if not series:
        return _empty('No samples in window')

    W, H, PAD = 600, height, 4
    lo = min(min(v) for _, v in series)
    hi = max(max(v) for _, v in series)
    span = (hi - lo) or 1.0

    def _y(v: float) -> float:
        return PAD + (H - 2 * PAD) * (1 - (v - lo) / span)

    paths, legend = [], []
    for i, (lbl, vals) in enumerate(series):
        color = _SERIES_COLORS[i % len(_SERIES_COLORS)]
        step  = W / (len(vals) - 1)
        pts   = [(j * step, _y(v)) for j, v in enumerate(vals)]
        line  = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area  = f"{line} L{W:.1f},{H} L0,{H} Z"
        paths.append(
            f'<path d="{area}" fill="{color}" opacity="0.10"/>'
            f'<path d="{line}" fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        )
        legend.append(
            f'<span><i style="background:{color}"></i>{html.escape(str(lbl))} '
            f'<b>{html.escape(fmt(vals[-1]))}</b></span>'
        )

    meta = (f'<div class="chart-meta"><span>min <b>{html.escape(fmt(lo))}</b></span>'
            f'<span>max <b>{html.escape(fmt(hi))}</b></span>'
            f'<span>samples <b>{max(len(v) for _, v in series)}</b></span></div>')
    return (
        f'<div class="chart-wrap">{meta}'
        f'<svg class="chart-svg" viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(paths)}</svg>'
        f'<div class="legend">{"".join(legend)}</div></div>'
    )


# ── AP Status widget ──────────────────────────────────────────────────────────
@router.get("/ap_status", response_class=HTMLResponse, include_in_schema=False)
async def widget_ap_status():
    rows = []
    try:
        async with aiosqlite.connect(_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT ap.id, ap.name, ap.site, ap.status,
                          COALESCE((SELECT SUM(r.client_count) FROM radios r WHERE r.access_point_id = ap.id), 0) AS clients
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
                "SELECT band, client_count FROM radios WHERE access_point_id=? ORDER BY band", (ap_id,)
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


# ── Query helper ──────────────────────────────────────────────────────────────
async def _rows(sql: str, params: tuple = ()) -> list[dict]:
    try:
        async with aiosqlite.connect(_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        _note_err(exc)
        return []


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
    cli = await _rows("SELECT COUNT(*) AS clients FROM wifi_clients")
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


# ── Radio Overview widget ─────────────────────────────────────────────────────
@router.get("/radio_overview", response_class=HTMLResponse, include_in_schema=False)
async def widget_radio_overview():
    rows = await _rows(
        """SELECT ap.name AS ap_name, r.band, r.channel, r.channel_width_mhz,
                  r.tx_power_dbm, r.utilization_pct, r.noise_floor_dbm, r.client_count
           FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
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
        """SELECT ap.name AS ap_name, r.band, r.channel, r.utilization_pct
           FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
           WHERE r.utilization_pct IS NOT NULL
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
        """SELECT ap.name AS ap_name, r.band, r.noise_floor_dbm
           FROM radios r JOIN access_points ap ON ap.id = r.access_point_id
           WHERE r.noise_floor_dbm IS NOT NULL
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


# ── Clients by Band widget ────────────────────────────────────────────────────
@router.get("/clients_by_band", response_class=HTMLResponse, include_in_schema=False)
async def widget_clients_by_band():
    rows = await _rows(
        "SELECT COALESCE(NULLIF(band,''),'unknown') AS band, COUNT(*) AS n "
        "FROM wifi_clients GROUP BY band ORDER BY n DESC"
    )
    body = _bars([(r["band"], r["n"], str(r["n"])) for r in rows]) \
        if rows else _empty('No clients are currently associated')
    return HTMLResponse(_page("Clients by Band", body))


# ── Clients by SSID widget ────────────────────────────────────────────────────
@router.get("/clients_by_ssid", response_class=HTMLResponse, include_in_schema=False)
async def widget_clients_by_ssid():
    rows = await _rows(
        "SELECT COALESCE(NULLIF(ssid,''),'unknown') AS ssid, COUNT(*) AS n "
        "FROM wifi_clients GROUP BY ssid ORDER BY n DESC LIMIT 20"
    )
    body = _bars([(r["ssid"], r["n"], str(r["n"])) for r in rows]) \
        if rows else _empty('No clients are currently associated')
    return HTMLResponse(_page("Clients by SSID", body))


# ── Client Signal Health widget ───────────────────────────────────────────────
@router.get("/client_health", response_class=HTMLResponse, include_in_schema=False)
async def widget_client_health():
    rows = await _rows(
        """SELECT c.hostname, c.mac_address, c.ssid, c.band, c.rssi_dbm, c.snr_db,
                  c.tx_rate_mbps, ap.name AS ap_name
           FROM wifi_clients c LEFT JOIN access_points ap ON ap.id = c.access_point_id
           WHERE c.rssi_dbm IS NOT NULL ORDER BY c.rssi_dbm ASC LIMIT 40"""
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


# ── Param option pickers ──────────────────────────────────────────────────────
# Every picker reads live state rather than a static list, so an AP or radio
# added or removed after a NOC screen was built shows up (or drops out) the next
# time the editor opens the param — no manifest edit and no pktHub change needed.
@router.get("/options/access_points")
async def widget_options_access_points():
    rows = await _rows("SELECT id, name, site FROM access_points ORDER BY name")
    return JSONResponse([
        {"value": str(r["id"]), "label": f"{r['name']} ({r['site'] or 'unknown'})"} for r in rows
    ])


@router.get("/options/radios")
async def widget_options_radios(ap_id: int | None = None):
    if not ap_id:
        return JSONResponse([])
    rows = await _rows(
        "SELECT id, band, channel FROM radios WHERE access_point_id = ? ORDER BY band", (ap_id,)
    )
    return JSONResponse([
        {"value": str(r["id"]),
         "label": f"{r['band']}" + (f" · ch {r['channel']}" if r.get("channel") else "")}
        for r in rows
    ])
