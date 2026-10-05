"""
Shared by every widget: the router, the page shell and states, formatting, tiles, bars and the line chart, and the read helper.
"""
from __future__ import annotations

import html
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

import aiosqlite
from fastapi import APIRouter, Depends, Request

from app.config import get_settings
from app.dependencies import require_suite_token


log = logging.getLogger("pktwifi.api.widgets")


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


# These views are embedded as unauthenticated iframes by pktHub's NOC Builder,
# so they can't require a login session — but they do render internal access
# point, client and alert data, so every route on this router requires a valid
# X-Suite-Token (the trusted-proxy secret pktHub already sends on every
# proxied request).
router = APIRouter(dependencies=[Depends(_capture_refresh), Depends(require_suite_token)])
_s     = get_settings()
_DB    = _s.db_path


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
    # The page is shown on an unauthenticated display URL, and a database error
    # names tables and file paths: the full text goes to the log, the page gets
    # only the kind of failure.
    log.warning("widget query failed: %s: %s", type(exc).__name__, exc)
    _WIDGET_ERR.set(type(exc).__name__)


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
    return _empty(f'{html.escape(what)} no longer exists')


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
