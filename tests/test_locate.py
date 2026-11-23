#!/usr/bin/env python3
"""
Client location maths and floor plan image headers.

Standalone script — run from the repo root:
    python3 tests/test_locate.py

The properties worth proving:

  * signal maps to a distance that grows as the signal falls, and is clamped
    to the range the model is good for,
  * three or more APs recover a known position, from clean readings and from
    readings with realistic error, and nearer APs outweigh farther ones,
  * the cases that cannot be solved are refused rather than guessed: fewer
    than three APs, no scale, APs in a line,
  * a fix never lands outside the plan,
  * a client heard by one AP is placed at that AP with its estimated distance
    as the accuracy, and with nothing placed there is no position at all,
  * only PNG and JPEG are recognised, by their bytes, with the right size.
"""
from __future__ import annotations

import math
import random
import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.wifi.imagesize import image_info                       # noqa: E402
from app.wifi.locate import (                                    # noqa: E402
    MAX_DISTANCE_M, MIN_DISTANCE_M, PATH_LOSS_EXPONENT, REF_RSSI_DBM,
    Anchor, associated_fix, locate, rssi_to_distance_m, trilaterate,
)

FAILURES: list[str] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not passed else ""))
    if not passed:
        FAILURES.append(label)


SCALE = 10.0   # px per metre


def rssi_at(ap: tuple[float, float], at: tuple[float, float]) -> float:
    d = math.hypot(at[0] - ap[0], at[1] - ap[1]) / SCALE
    return REF_RSSI_DBM - 10 * PATH_LOSS_EXPONENT * math.log10(d)


def make_png(w: int, h: int) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    raw = b"".join(b"\x00" + b"\xff" * (w * 3) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_jpeg(w: int, h: int) -> bytes:
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", h, w) + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def main() -> None:
    print("── distance from signal ──")
    near, mid, far = (rssi_to_distance_m(s) for s in (-45, -65, -85))
    check("a weaker signal is farther away", near < mid < far, f"{near:.1f} {mid:.1f} {far:.1f}")
    check("a one-metre reading comes back as about a metre",
          abs(rssi_to_distance_m(REF_RSSI_DBM) - 1.0) < 1e-9)
    check("an implausibly strong signal is clamped to the minimum", rssi_to_distance_m(0) == MIN_DISTANCE_M)
    check("an implausibly weak signal is clamped to the maximum", rssi_to_distance_m(-200) == MAX_DISTANCE_M)

    print("── three or more APs ──")
    aps = [(100.0, 100.0), (900.0, 120.0), (500.0, 700.0)]
    truth = (450.0, 300.0)
    anchors = [Anchor(a[0], a[1], rssi_at(a, truth)) for a in aps]
    fix = trilaterate(anchors, SCALE, (1000, 800))
    check("clean readings recover the true position",
          fix is not None and math.hypot(fix.x_px - truth[0], fix.y_px - truth[1]) < 1.0, str(fix))
    check("the fix says it is a trilateration from three APs",
          fix is not None and fix.method == "trilateration" and fix.anchors == 3)
    check("accuracy is a positive number of metres", fix is not None and fix.accuracy_m > 0)

    rng = random.Random(7)
    errors: list[float] = []
    trials = 1000
    for _ in range(trials):
        noisy = [Anchor(a[0], a[1], rssi_at(a, truth) + rng.gauss(0, 3)) for a in aps]
        f = trilaterate(noisy, SCALE, (1000, 800))
        if f is not None:
            errors.append(math.hypot(f.x_px - truth[0], f.y_px - truth[1]) / SCALE)
    errors.sort()
    # A rare case where the readings are too inconsistent to settle returns no
    # fix; locate() then falls back to the associated AP.
    check("with 3 dB of signal noise almost every trial still gets a fix",
          len(errors) >= 0.98 * trials, f"{len(errors)}/{trials}")
    check("and the typical error is metres, not tens of metres (median under 15 m)",
          bool(errors) and errors[len(errors) // 2] < 15, f"median {errors[len(errors) // 2]:.1f} m" if errors else "none")

    four = aps + [(850.0, 650.0)]
    f4 = trilaterate([Anchor(a[0], a[1], rssi_at(a, truth)) for a in four], SCALE, (1000, 800))
    check("a fourth AP is used too", f4 is not None and f4.anchors == 4
          and math.hypot(f4.x_px - truth[0], f4.y_px - truth[1]) < 1.0)

    print("── what cannot be solved is refused ──")
    check("two APs give no position", trilaterate(anchors[:2], SCALE) is None)
    check("no scale gives no position", trilaterate(anchors, 0) is None and trilaterate(anchors, None) is None)  # type: ignore[arg-type]
    line = [Anchor(0, 0, -50), Anchor(100, 0, -55), Anchor(200, 0, -60)]
    check("APs in a straight line give no position (mirror ambiguity)", trilaterate(line, SCALE) is None)

    print("── the fix stays on the plan ──")
    # Readings that put the client beyond the right-hand edge.
    off = (1400.0, 300.0)
    far_anchors = [Anchor(a[0], a[1], rssi_at(a, off)) for a in aps]
    clamped = trilaterate(far_anchors, SCALE, (1000, 800))
    check("a fix past the edge is clamped to it",
          clamped is not None and 0 <= clamped.x_px <= 1000 and 0 <= clamped.y_px <= 800, str(clamped))

    print("── associated AP ──")
    one = Anchor(250.0, 400.0, -60.0)
    a = associated_fix(one)
    check("a client heard by one AP is placed at that AP",
          (a.x_px, a.y_px) == (250.0, 400.0) and a.method == "associated" and a.anchors == 1)
    check("its accuracy is the estimated distance", abs(a.accuracy_m - rssi_to_distance_m(-60.0)) < 1e-9)
    check("locate() falls back to the associated AP when too few APs heard the client",
          locate(anchors[:2], one, SCALE, (1000, 800)).method == "associated")
    check("locate() with no scale still places at the associated AP",
          locate(anchors, one, None, (1000, 800)).method == "associated")
    check("locate() prefers trilateration when it can",
          locate(anchors, one, SCALE, (1000, 800)).method == "trilateration")
    check("locate() with nothing to anchor on returns none", locate([], None, SCALE) is None)

    print("── floor plan image headers ──")
    check("a PNG is recognised with its size", image_info(make_png(120, 80)) == ("png", 120, 80))
    check("a JPEG is recognised with its size", image_info(make_jpeg(640, 480)) == ("jpg", 640, 480))
    check("an SVG is refused", image_info(b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>') is None)
    check("HTML is refused", image_info(b"<html><script>alert(1)</script></html>") is None)
    check("an empty body is refused", image_info(b"") is None)
    check("a truncated PNG header is refused", image_info(make_png(10, 10)[:20]) is None)
    check("a PNG with a zero side is refused", image_info(make_png(10, 10)[:16] + struct.pack(">II", 0, 5) + b"\x00" * 20) is None)
    check("a JPEG with no frame header is refused", image_info(b"\xff\xd8\xff\xd9") is None)
    check("GIF is refused", image_info(b"GIF89a" + b"\x00" * 30) is None)

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
