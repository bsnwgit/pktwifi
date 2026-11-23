"""
app/wifi/locate.py
------------------
Where a client is on a floor plan, from the signal strength APs hear it at.
Pure maths: no database, no I/O, so it is testable on its own.

Two results, best available first:

  * trilateration  three or more placed APs heard the client; their distance
                   circles are intersected (weighted least squares),
  * associated     only the AP the client is joined to is known; the client is
                   somewhere on a ring around that AP, so the AP is the point
                   and the ring radius is the accuracy.

Distance comes from a log-distance path-loss model. The reference level and
exponent below are typical indoor figures, not measurements of any building:
walls, bodies and antenna orientation move real signal several dB either way,
so every figure here is an estimate. `accuracy_m` says how rough, and is
itself a rule of thumb rather than a statistical bound.

Coordinates are image pixels; `scale_px_per_m` (set per floor by calibration)
converts between pixels and metres. Distances are metres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

# RSSI expected one metre from an AP, and how fast it falls with distance
# (2 in free space, roughly 2.7 to 4 indoors).
REF_RSSI_DBM = -40.0
PATH_LOSS_EXPONENT = 3.0

# Outside this range the model says nothing useful: very strong signals are
# near-field, very weak ones are dominated by walls and noise.
MIN_DISTANCE_M = 0.5
MAX_DISTANCE_M = 80.0

# Fewer than this many APs cannot fix a position.
MIN_ANCHORS = 3

# Anchors lying (nearly) on one line leave the position mirrored across it.
# The smaller eigenvalue of their coordinate spread (m^2) must exceed this.
_MIN_SPREAD_M2 = 0.25

# Solver limits. A centimetre is converged: the distance model itself is good
# to metres, so chasing more precision only burns iterations.
_LM_ITERATIONS = 100
_LM_DAMPING_TRIES = 20
_LM_TOLERANCE_M = 0.01
_LM_FLAT_REL = 1e-6   # relative error improvement below which the search has settled


@dataclass(frozen=True)
class Anchor:
    """One AP that heard the client, placed on the plan."""
    x_px: float
    y_px: float
    rssi_dbm: float


@dataclass(frozen=True)
class Fix:
    x_px: float
    y_px: float
    accuracy_m: float
    method: str       # "trilateration" | "associated"
    anchors: int      # how many APs the fix used


def rssi_to_distance_m(
    rssi_dbm: float,
    ref_rssi_dbm: float = REF_RSSI_DBM,
    exponent: float = PATH_LOSS_EXPONENT,
) -> float:
    """Estimated distance in metres, clamped to the range the model is good for."""
    d = 10 ** ((ref_rssi_dbm - rssi_dbm) / (10.0 * exponent))
    return min(max(d, MIN_DISTANCE_M), MAX_DISTANCE_M)


def _spread_ok(points: Sequence[tuple[float, float]]) -> bool:
    """True when the points are not (nearly) collinear."""
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points) / n
    syy = sum((p[1] - my) ** 2 for p in points) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points) / n
    half_trace = (sxx + syy) / 2
    disc = math.sqrt(max(half_trace ** 2 - (sxx * syy - sxy ** 2), 0.0))
    return half_trace - disc > _MIN_SPREAD_M2


def trilaterate(
    anchors: Sequence[Anchor],
    scale_px_per_m: float,
    bounds_px: Optional[tuple[float, float]] = None,
) -> Optional[Fix]:
    """Position from three or more anchors, or None when it cannot be fixed
    (too few, no scale, anchors in a line, or no convergence). Nearer APs
    weigh more: their distance estimate is the least wrong."""
    if len(anchors) < MIN_ANCHORS or not scale_px_per_m or scale_px_per_m <= 0:
        return None

    pts = [(a.x_px / scale_px_per_m, a.y_px / scale_px_per_m) for a in anchors]
    dist = [rssi_to_distance_m(a.rssi_dbm) for a in anchors]
    if not _spread_ok(pts):
        return None

    weights = [1.0 / max(d, 1.0) ** 2 for d in dist]
    wsum = sum(weights)
    px = sum(w * p[0] for w, p in zip(weights, pts)) / wsum
    py = sum(w * p[1] for w, p in zip(weights, pts)) / wsum

    def cost(x: float, y: float) -> float:
        return sum(w * (math.hypot(x - ax, y - ay) - d) ** 2 for (ax, ay), d, w in zip(pts, dist, weights))

    # Levenberg-Marquardt: a Gauss-Newton step, damped, kept only if it lowers
    # the weighted error. Plain Gauss-Newton crawls when two circles are too
    # small to meet (noisy readings), because the gradients of the nearest APs
    # line up; the damping is what lets it settle on the best compromise.
    lam = 1e-3
    current = cost(px, py)
    for _ in range(_LM_ITERATIONS):
        before = current
        a11 = a12 = a22 = b1 = b2 = 0.0
        for (ax, ay), d, w in zip(pts, dist, weights):
            dx, dy = px - ax, py - ay
            r = math.hypot(dx, dy) or 1e-9
            jx, jy = dx / r, dy / r
            res = r - d
            a11 += w * jx * jx
            a12 += w * jx * jy
            a22 += w * jy * jy
            b1 += w * jx * res
            b2 += w * jy * res
        moved = False
        for _try in range(_LM_DAMPING_TRIES):
            h11, h22 = a11 * (1 + lam) + 1e-12, a22 * (1 + lam) + 1e-12
            det = h11 * h22 - a12 * a12
            if det <= 0:
                lam *= 4
                continue
            sx = (h22 * b1 - a12 * b2) / det
            sy = (h11 * b2 - a12 * b1) / det
            trial = cost(px - sx, py - sy)
            if trial < current:
                px, py, current = px - sx, py - sy, trial
                lam = max(lam * 0.3, 1e-9)
                moved = True
                break
            lam *= 4
        # Settled: no damping lowers the error, or the step is negligible, or
        # the error has stopped improving (a flat valley, where moving a few
        # centimetres changes nothing that matters).
        if not moved or math.hypot(sx, sy) < _LM_TOLERANCE_M or before - current <= _LM_FLAT_REL * before:
            break
    else:
        return None

    if not (math.isfinite(px) and math.isfinite(py)):
        return None

    rms = math.sqrt(
        sum(w * (math.hypot(px - ax, py - ay) - d) ** 2 for (ax, ay), d, w in zip(pts, dist, weights)) / wsum
    )
    mean_d = sum(dist) / len(dist)
    # The residual shows how far the circles disagree; the second term is the
    # model's own uncertainty, which does not vanish when the circles happen
    # to agree.
    accuracy = math.sqrt(rms ** 2 + (0.25 * mean_d) ** 2)

    x_px, y_px = px * scale_px_per_m, py * scale_px_per_m
    if bounds_px:
        x_px = min(max(x_px, 0.0), float(bounds_px[0]))
        y_px = min(max(y_px, 0.0), float(bounds_px[1]))
    return Fix(x_px=x_px, y_px=y_px, accuracy_m=accuracy, method="trilateration", anchors=len(anchors))


def associated_fix(anchor: Anchor) -> Fix:
    """The client is on a ring around its AP: the AP is the point, the
    estimated distance is how far off that may be."""
    return Fix(
        x_px=anchor.x_px,
        y_px=anchor.y_px,
        accuracy_m=rssi_to_distance_m(anchor.rssi_dbm),
        method="associated",
        anchors=1,
    )


def locate(
    heard_by: Sequence[Anchor],
    associated: Optional[Anchor],
    scale_px_per_m: Optional[float],
    bounds_px: Optional[tuple[float, float]] = None,
) -> Optional[Fix]:
    """Best fix available: trilateration when `heard_by` (placed APs on the
    floor that heard the client) allows it, else the associated AP, else
    None (nothing placed to anchor on)."""
    if scale_px_per_m:
        fix = trilaterate(heard_by, scale_px_per_m, bounds_px)
        if fix:
            return fix
    return associated_fix(associated) if associated else None
