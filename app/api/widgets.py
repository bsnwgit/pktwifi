"""
pktWiFi — Widget endpoints for pktHub NOC Builder integration.

Manifest: GET /api/widgets/manifest  → list of widget definitions
Views:    GET /api/widgets/{id}      → server-rendered HTML page (iframe target)
Options:  GET /api/widgets/options/* → JSON [{value,label}] for dynamic param pickers
"""
from __future__ import annotations

import html

import aiosqlite
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.dependencies import require_suite_token

# These views are embedded as unauthenticated iframes by pktHub's NOC Builder,
# so they can't require a login session — but they do render internal access
# point, client and alert data, so every route on this router requires a valid
# X-Suite-Token (the trusted-proxy secret pktHub already sends on every
# proxied request).
router = APIRouter(dependencies=[Depends(require_suite_token)])
_s     = get_settings()
_DB    = _s.db_path

# ── Manifest ──────────────────────────────────────────────────────────────────
MANIFEST = [
    {
        "id": "ap_status", "title": "AP Status",
        "description": "All access points with site, status, and connected client count",
        "view_path": "/api/widgets/ap_status",
        "default_w": 640, "default_h": 380, "min_w": 340, "min_h": 220,
    },
    {
        "id": "client_count", "title": "Client Count",
        "description": "Connected client count by radio band for one access point",
        "view_path": "/api/widgets/client_count",
        "default_w": 460, "default_h": 300, "min_w": 280, "min_h": 180,
        "params": [
            {
                "key": "ap_id", "label": "Access Point", "type": "select",
                "options_path": "/api/widgets/options/access_points",
            }
        ],
    },
    {
        "id": "active_alerts", "title": "Active Alerts",
        "description": "Unresolved WiFi alert events",
        "view_path": "/api/widgets/active_alerts",
        "default_w": 640, "default_h": 360, "min_w": 320, "min_h": 200,
    },
]


@router.get("/manifest")
async def widget_manifest():
    return MANIFEST


# ── Shared page shell ───────────────────────────────────────────────────────────
def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a1628;color:#e2e8f0;font-family:'Inter',system-ui,sans-serif;font-size:13px;height:100vh;overflow:hidden;display:flex;flex-direction:column}}
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
.tile-row{{display:flex;gap:14px;margin-bottom:14px}}
.tile{{flex:1;background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px 12px}}
.tile-label{{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px}}
.tile-value{{font-size:22px;font-weight:700;color:#e2e8f0}}
</style>
<script>setTimeout(()=>location.reload(),30000)</script>
</head><body>
<div class="hdr"><div class="hdr-dot"></div><div class="hdr-title">{title}</div></div>
<div class="content">{body}</div>
</body></html>"""


def _status_badge(status: str) -> str:
    s = (status or "").lower()
    if s == "online":
        return '<span class="badge bg">ONLINE</span>'
    if s == "offline":
        return '<span class="badge br">OFFLINE</span>'
    return f'<span class="badge bn">{html.escape((status or "UNKNOWN").upper())}</span>'


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
    except Exception:
        pass

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
        body = '<div class="empty">No access points</div>'
    return HTMLResponse(_page("AP Status", body))


# ── Client Count widget (per-AP, dynamic) ────────────────────────────────────
@router.get("/client_count", response_class=HTMLResponse, include_in_schema=False)
async def widget_client_count(ap_id: int | None = None):
    if not ap_id:
        return HTMLResponse(_page("Client Count", '<div class="empty">Select an access point</div>'))

    ap_name = str(ap_id)
    bands = []
    try:
        async with aiosqlite.connect(_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT name FROM access_points WHERE id=?", (ap_id,)) as cur:
                row = await cur.fetchone()
                if row:
                    ap_name = row["name"]
            async with db.execute(
                "SELECT band, client_count FROM radios WHERE access_point_id=? ORDER BY band", (ap_id,)
            ) as cur:
                bands = [dict(r) for r in await cur.fetchall()]
    except Exception:
        pass

    total = sum(b["client_count"] or 0 for b in bands)
    tiles = "".join(
        f'<div class="tile"><div class="tile-label">{html.escape(str(b["band"]))}</div><div class="tile-value">{b["client_count"] or 0}</div></div>'
        for b in bands
    ) or '<div class="empty">No radios</div>'
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
    except Exception:
        pass

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
        body = '<div class="empty">No active alerts</div>'
    return HTMLResponse(_page("Active Alerts", body))


# ── Param option pickers ──────────────────────────────────────────────────────
@router.get("/options/access_points")
async def widget_options_access_points():
    try:
        async with aiosqlite.connect(_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT id, name, site FROM access_points ORDER BY name") as cur:
                rows = [dict(r) for r in await cur.fetchall()]
        return JSONResponse([{"value": str(r["id"]), "label": f"{r['name']} ({r['site'] or 'unknown'})"} for r in rows])
    except Exception:
        return JSONResponse([])
