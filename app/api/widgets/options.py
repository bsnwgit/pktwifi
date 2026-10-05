"""
GET /api/widgets/options/*: JSON choices for the dynamic parameter pickers.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse

from app.api.widgets._common import _rows, router


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
