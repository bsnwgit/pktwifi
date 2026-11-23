"""
/api/floors/* — floor plans. A site holds one or more floors; each floor has a
plan image, a scale (pixels per metre, set by calibration) and the access
points placed on it. The Map page and client location read from here.

Plan images are stored under <install_dir>/floorplans/<floor id>.<png|jpg>.
The file name is built from the floor's integer id, never from anything the
client sent, and the type is decided from the file's own bytes.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import get_db
from app.dependencies import AnalystUser, CurrentUser
from app.wifi.imagesize import image_info

log = logging.getLogger("pktwifi.floors")
router = APIRouter()

MAX_PLAN_BYTES = 8 * 1024 * 1024
# The browser decodes the image, so an absurd pixel size is refused even when
# the file itself is small.
MAX_PLAN_SIDE_PX = 8000
_MIN_CALIBRATION_PX = 5.0
_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg"}


def plan_dir() -> Path:
    return Path(get_settings().install_dir) / "floorplans"


def _plan_file(name: Optional[str]) -> Optional[Path]:
    """The stored plan for a row, or None. Resolved and checked to sit inside the
    plans directory, so a bad value in the table can never point elsewhere."""
    if not name:
        return None
    root = plan_dir().resolve()
    path = (root / name).resolve()
    if path.parent != root:
        return None
    return path


class FloorRequest(BaseModel):
    site_id: int
    name: str = Field(min_length=1, max_length=80)
    level: int = Field(default=0, ge=-50, le=200)


class FloorUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    level: Optional[int] = Field(default=None, ge=-50, le=200)


class ScaleRequest(BaseModel):
    """Two points on the plan (image pixels) and the real distance between them."""
    x1: float
    y1: float
    x2: float
    y2: float
    distance_m: float = Field(gt=0, le=10_000)


def _floor_out(row) -> dict:
    return {
        "id": row["id"],
        "site_id": row["site_id"],
        "site_name": row["site_name"],
        "name": row["name"],
        "level": row["level"],
        "has_plan": bool(row["image_path"]),
        "image_w": row["image_w"],
        "image_h": row["image_h"],
        "scale_px_per_m": row["scale_px_per_m"],
        "placed_aps": row["placed_aps"],
        "created_at": row["created_at"],
    }


_FLOOR_SELECT = """
    SELECT f.*, s.name AS site_name,
           (SELECT COUNT(*) FROM access_points a
             WHERE a.floor_id = f.id AND a.x_px IS NOT NULL AND a.y_px IS NOT NULL) AS placed_aps
      FROM floors f JOIN sites s ON s.id = f.site_id
"""


async def _get_floor(db: aiosqlite.Connection, floor_id: int):
    async with db.execute(_FLOOR_SELECT + " WHERE f.id = ?", (floor_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Floor not found")
    return row


@router.get("")
async def list_floors(
    user: CurrentUser,
    site_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    sql = _FLOOR_SELECT
    params: tuple = ()
    if site_id is not None:
        sql += " WHERE f.site_id = ?"
        params = (site_id,)
    sql += " ORDER BY s.name, f.level, f.name"
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [_floor_out(r) for r in rows]


@router.post("", status_code=201)
async def create_floor(body: FloorRequest, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT id FROM sites WHERE id = ?", (body.site_id,)) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Site not found")
    try:
        cur = await db.execute(
            "INSERT INTO floors (site_id, name, level) VALUES (?, ?, ?)",
            (body.site_id, body.name.strip(), body.level),
        )
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail=f"This site already has a floor named '{body.name.strip()}'")
    return _floor_out(await _get_floor(db, cur.lastrowid))


@router.patch("/{floor_id}")
async def update_floor(floor_id: int, body: FloorUpdate, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_floor(db, floor_id)
    name = body.name.strip() if body.name is not None else row["name"]
    level = body.level if body.level is not None else row["level"]
    try:
        await db.execute("UPDATE floors SET name = ?, level = ? WHERE id = ?", (name, level, floor_id))
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail=f"This site already has a floor named '{name}'")
    return _floor_out(await _get_floor(db, floor_id))


@router.delete("/{floor_id}", status_code=204)
async def delete_floor(floor_id: int, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_floor(db, floor_id)
    # Placed APs keep their row; only the placement goes (floor_id is SET NULL by
    # the key, the coordinates are cleared here so they cannot be mistaken for
    # a position on some other floor).
    await db.execute("UPDATE access_points SET x_px = NULL, y_px = NULL WHERE floor_id = ?", (floor_id,))
    await db.execute("DELETE FROM floors WHERE id = ?", (floor_id,))
    await db.commit()
    path = _plan_file(row["image_path"])
    if path and path.exists():
        try:
            path.unlink()
        except OSError as exc:
            log.warning(f"Could not remove plan file for floor {floor_id}: {exc}")


@router.put("/{floor_id}/plan")
async def upload_plan(floor_id: int, request: Request, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    """Body is the raw image (PNG or JPEG), not a form. Replaces any earlier plan."""
    row = await _get_floor(db, floor_id)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_PLAN_BYTES:
        raise HTTPException(status_code=413, detail=f"Plan image is over {MAX_PLAN_BYTES // (1024 * 1024)} MB")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_PLAN_BYTES:
            raise HTTPException(status_code=413, detail=f"Plan image is over {MAX_PLAN_BYTES // (1024 * 1024)} MB")
        chunks.append(chunk)
    data = b"".join(chunks)

    info = image_info(data)
    if info is None:
        raise HTTPException(status_code=415, detail="The plan must be a PNG or JPEG image")
    ext, width, height = info
    if width > MAX_PLAN_SIDE_PX or height > MAX_PLAN_SIDE_PX:
        raise HTTPException(status_code=422, detail=f"The plan is over {MAX_PLAN_SIDE_PX} pixels on a side")

    root = plan_dir()
    root.mkdir(parents=True, exist_ok=True)
    name = f"{floor_id}.{ext}"
    target = root / name
    tmp = root / f".{name}.part"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()

    # A plan saved under the other extension is now stale.
    old = _plan_file(row["image_path"])
    if old and old != target.resolve() and old.exists():
        try:
            old.unlink()
        except OSError:
            pass

    # The scale describes pixels of the old image; a different size makes it wrong.
    scale_reset = bool(row["scale_px_per_m"]) and (row["image_w"], row["image_h"]) != (width, height)
    await db.execute(
        "UPDATE floors SET image_path = ?, image_w = ?, image_h = ?, scale_px_per_m = ? WHERE id = ?",
        (name, width, height, None if scale_reset else row["scale_px_per_m"], floor_id),
    )
    await db.commit()
    out = _floor_out(await _get_floor(db, floor_id))
    out["scale_reset"] = scale_reset
    return out


@router.get("/{floor_id}/plan")
async def get_plan(floor_id: int, user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_floor(db, floor_id)
    path = _plan_file(row["image_path"])
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="This floor has no plan image")
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(path.suffix.lstrip(".").lower(), "application/octet-stream"),
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"},
    )


@router.put("/{floor_id}/scale")
async def set_scale(floor_id: int, body: ScaleRequest, user: AnalystUser, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_floor(db, floor_id)
    if not row["image_path"]:
        raise HTTPException(status_code=409, detail="Upload a plan before setting its scale")
    for x, y in ((body.x1, body.y1), (body.x2, body.y2)):
        if not (math.isfinite(x) and math.isfinite(y)) or not (0 <= x <= row["image_w"]) or not (0 <= y <= row["image_h"]):
            raise HTTPException(status_code=422, detail="Both points must be on the plan")
    px = math.hypot(body.x2 - body.x1, body.y2 - body.y1)
    if px < _MIN_CALIBRATION_PX:
        raise HTTPException(status_code=422, detail="The two points are too close together to measure a scale")
    await db.execute("UPDATE floors SET scale_px_per_m = ? WHERE id = ?", (px / body.distance_m, floor_id))
    await db.commit()
    return _floor_out(await _get_floor(db, floor_id))
