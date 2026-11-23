#!/usr/bin/env python3
"""
Floor plans, AP placement, client location and the poll engine's part in it.

Standalone script — run from the repo root:
    python3 tests/test_floors.py

The properties worth proving:

  * only an analyst or admin changes floors, scales or placements, and nobody
    reads a plan without signing in,
  * an upload is accepted only if its own bytes say PNG or JPEG, within the size
    and pixel limits; an SVG, HTML or junk body is refused,
  * a plan is served only from the plans directory, whatever the table says,
  * a scale needs a plan, two real points on it and a real distance,
  * an AP can be placed only on a floor that has a plan, and only inside it,
  * a client heard by three placed APs is placed near its true position, one
    heard by a single AP sits at that AP, a client of an unplaced AP is counted
    and not drawn, and one the latest poll no longer reports is not shown,
  * a poll never undoes a placement, even when the AP comes back under another
    collector, and it records the signal each client has to its AP,
  * deleting a floor clears its placements and removes its image.
"""
from __future__ import annotations

import asyncio
import math
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]

TMP = Path(tempfile.mkdtemp(prefix="pktwifi-floors-"))
(TMP / "config.yaml").write_text(
    f"install_dir: {TMP}\n"
    f"secret_key: {'a' * 64}\n"
    f"credential_key: {Fernet.generate_key().decode()}\n"
    f"suite_token: ''\n"
)
os.environ["PKTWIFI_CONFIG"] = str(TMP / "config.yaml")
os.environ["PKTWIFI_INSTALL_DIR"] = str(TMP)
os.environ["PKTWIFI_ADMIN_PASSWORD"] = "admin-test-password"
sys.path.insert(0, str(REPO_ROOT))

import aiosqlite                                            # noqa: E402
from fastapi.testclient import TestClient                   # noqa: E402

from app.database import init_db                            # noqa: E402
from app.dependencies import get_current_user               # noqa: E402
from app.main import app                                    # noqa: E402
from app.wifi import poll_engine                            # noqa: E402
from app.wifi.collectors.base import (                      # noqa: E402
    AccessPointReading, ClientObservation, ClientReading, PollResult, RadioReading,
)
from app.wifi.locate import PATH_LOSS_EXPONENT, REF_RSSI_DBM   # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_locate import make_jpeg, make_png                 # noqa: E402

DB = TMP / "pktwifi.db"
FAILURES: list[str] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not passed else ""))
    if not passed:
        FAILURES.append(label)


def sql(query: str, *params):
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


ROLE = {"v": "analyst"}


async def fake_user():
    return {"id": 1, "username": "tester", "email": None, "role": ROLE["v"], "is_active": 1}


def as_role(role: str) -> None:
    ROLE["v"] = role
    app.dependency_overrides[get_current_user] = fake_user


def rssi_at(ap: tuple[float, float], at: tuple[float, float], scale: float) -> float:
    d = math.hypot(at[0] - ap[0], at[1] - ap[1]) / scale
    return REF_RSSI_DBM - 10 * PATH_LOSS_EXPONENT * math.log10(d)


def main() -> None:
    asyncio.run(init_db())
    c = TestClient(app)
    sql("INSERT INTO sites (name) VALUES ('HQ')")
    site_id = sql("SELECT id FROM sites WHERE name='HQ'")[0]["id"]
    png = make_png(400, 300)

    print("── who may do what ──")
    app.dependency_overrides.pop(get_current_user, None)
    check("a plan cannot be read without signing in", c.get("/api/floors").status_code == 401)
    as_role("viewer")
    check("a viewer can list floors", c.get("/api/floors").status_code == 200)
    check("a viewer cannot create one",
          c.post("/api/floors", json={"site_id": site_id, "name": "Ground"}).status_code == 403)
    as_role("analyst")
    r = c.post("/api/floors", json={"site_id": site_id, "name": "Ground", "level": 0})
    check("an analyst creates a floor", r.status_code == 201, r.text)
    f1 = r.json()["id"]
    check("a duplicate name on the same site is refused",
          c.post("/api/floors", json={"site_id": site_id, "name": "Ground"}).status_code == 409)
    check("an unknown site is refused",
          c.post("/api/floors", json={"site_id": 9999, "name": "X"}).status_code == 404)
    f2 = c.post("/api/floors", json={"site_id": site_id, "name": "First", "level": 1}).json()["id"]
    names = [f["name"] for f in c.get("/api/floors", params={"site_id": site_id}).json()]
    check("floors come back in level order", names == ["Ground", "First"], str(names))

    print("── uploading a plan ──")
    as_role("viewer")
    check("a viewer cannot upload", c.put(f"/api/floors/{f1}/plan", content=png).status_code == 403)
    as_role("analyst")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    check("an SVG is refused", c.put(f"/api/floors/{f1}/plan", content=svg,
                                     headers={"Content-Type": "image/png"}).status_code == 415)
    check("HTML is refused", c.put(f"/api/floors/{f1}/plan", content=b"<html></html>").status_code == 415)
    check("junk is refused", c.put(f"/api/floors/{f1}/plan", content=os.urandom(500)).status_code == 415)
    check("an image over the size cap is refused",
          c.put(f"/api/floors/{f1}/plan", content=png + b"\x00" * (9 * 1024 * 1024)).status_code == 413)
    check("an image with an absurd pixel size is refused",
          c.put(f"/api/floors/{f1}/plan", content=make_jpeg(20000, 100)).status_code == 422)
    check("a refused upload stores nothing", not (TMP / "floorplans").exists() or not any((TMP / "floorplans").iterdir()))
    r = c.put(f"/api/floors/{f1}/plan", content=png)
    check("a PNG is accepted with its size", r.status_code == 200 and r.json()["image_w"] == 400
          and r.json()["image_h"] == 300 and r.json()["has_plan"], r.text)
    check("it is stored under the floor's own id", (TMP / "floorplans" / f"{f1}.png").is_file())
    got = c.get(f"/api/floors/{f1}/plan")
    check("it is served back unchanged, typed and not sniffable",
          got.status_code == 200 and got.content == png and got.headers["content-type"] == "image/png"
          and got.headers.get("x-content-type-options") == "nosniff")
    check("a floor with no plan says so", c.get(f"/api/floors/{f2}/plan").status_code == 404)

    print("── a plan is only ever read from the plans directory ──")
    (TMP / "escape.png").write_bytes(png)
    sql("UPDATE floors SET image_path = ? WHERE id = ?", "../escape.png", f2)
    check("a path that climbs out of the directory is not served", c.get(f"/api/floors/{f2}/plan").status_code == 404)
    sql("UPDATE floors SET image_path = NULL WHERE id = ?", f2)

    print("── scale ──")
    check("a scale needs a plan first",
          c.put(f"/api/floors/{f2}/scale", json={"x1": 0, "y1": 0, "x2": 100, "y2": 0, "distance_m": 10}).status_code == 409)
    check("a point off the plan is refused",
          c.put(f"/api/floors/{f1}/scale", json={"x1": 0, "y1": 0, "x2": 900, "y2": 0, "distance_m": 10}).status_code == 422)
    check("two points that are too close are refused",
          c.put(f"/api/floors/{f1}/scale", json={"x1": 10, "y1": 10, "x2": 12, "y2": 10, "distance_m": 1}).status_code == 422)
    check("a zero distance is refused",
          c.put(f"/api/floors/{f1}/scale", json={"x1": 0, "y1": 0, "x2": 100, "y2": 0, "distance_m": 0}).status_code == 422)
    r = c.put(f"/api/floors/{f1}/scale", json={"x1": 0, "y1": 0, "x2": 60, "y2": 80, "distance_m": 10})
    check("100 px measured as 10 m is 10 px per metre", r.status_code == 200 and abs(r.json()["scale_px_per_m"] - 10) < 1e-9, r.text)

    print("── placing access points ──")
    for name, mac in (("AP1", "aa:00:00:00:00:01"), ("AP2", "aa:00:00:00:00:02"),
                      ("AP3", "aa:00:00:00:00:03"), ("AP4", "aa:00:00:00:00:04")):
        sql("INSERT INTO access_points (name, mac_address, status, last_seen) VALUES (?, ?, 'online', datetime('now'))", name, mac)
    ap = {r["name"]: r["id"] for r in sql("SELECT id, name FROM access_points")}
    spots = {"AP1": (100, 100), "AP2": (300, 100), "AP3": (200, 250)}
    for n, (x, y) in spots.items():
        r = c.patch(f"/api/devices/{ap[n]}/placement", json={"floor_id": f1, "x_px": x, "y_px": y})
        check(f"{n} is placed", r.status_code == 200 and r.json()["floor_id"] == f1 and r.json()["x_px"] == x, r.text)
    check("a position outside the plan is refused",
          c.patch(f"/api/devices/{ap['AP4']}/placement", json={"floor_id": f1, "x_px": 500, "y_px": 10}).status_code == 422)
    check("a missing coordinate is refused",
          c.patch(f"/api/devices/{ap['AP4']}/placement", json={"floor_id": f1, "x_px": 5}).status_code == 422)
    check("a floor with no plan cannot hold APs",
          c.patch(f"/api/devices/{ap['AP4']}/placement", json={"floor_id": f2, "x_px": 5, "y_px": 5}).status_code == 409)
    check("an unknown floor is refused",
          c.patch(f"/api/devices/{ap['AP4']}/placement", json={"floor_id": 999, "x_px": 5, "y_px": 5}).status_code == 404)
    check("an unknown AP is refused",
          c.patch("/api/devices/9999/placement", json={"floor_id": f1, "x_px": 5, "y_px": 5}).status_code == 404)
    as_role("viewer")
    check("a viewer cannot place an AP",
          c.patch(f"/api/devices/{ap['AP4']}/placement", json={"floor_id": f1, "x_px": 5, "y_px": 5}).status_code == 403)
    as_role("analyst")
    check("the floor reports how many APs are placed",
          [f for f in c.get("/api/floors").json() if f["id"] == f1][0]["placed_aps"] == 3)

    print("── where clients are ──")
    scale = 10.0
    truth = (180.0, 150.0)
    sql("""INSERT INTO wifi_clients (mac_address, access_point_id, hostname, rssi_dbm, last_seen)
           VALUES ('02:00:00:00:00:0a', ?, 'tri', ?, datetime('now'))""", ap["AP1"], rssi_at(spots["AP1"], truth, scale))
    for n, p in spots.items():
        sql("INSERT INTO client_ap_signals (client_mac, access_point_id, rssi_dbm) VALUES ('02:00:00:00:00:0a', ?, ?)",
            ap[n], rssi_at(p, truth, scale))
    sql("""INSERT INTO wifi_clients (mac_address, access_point_id, hostname, rssi_dbm, last_seen)
           VALUES ('02:00:00:00:00:0b', ?, 'single', -60, datetime('now'))""", ap["AP2"])
    sql("INSERT INTO client_ap_signals (client_mac, access_point_id, rssi_dbm) VALUES ('02:00:00:00:00:0b', ?, -60)", ap["AP2"])
    sql("""INSERT INTO wifi_clients (mac_address, access_point_id, hostname, last_seen)
           VALUES ('02:00:00:00:00:0c', ?, 'unplaced', datetime('now'))""", ap["AP4"])
    sql("""INSERT INTO wifi_clients (mac_address, access_point_id, hostname, rssi_dbm, last_seen)
           VALUES ('02:00:00:00:00:0d', ?, 'gone', -55, datetime('now', '-30 minutes'))""", ap["AP3"])
    sql("""INSERT INTO wifi_clients (mac_address, access_point_id, hostname, last_seen)
           VALUES ('02:00:00:00:00:0e', ?, 'no-signal', datetime('now'))""", ap["AP3"])

    r = c.get(f"/api/locate/floors/{f1}")
    check("the floor view loads", r.status_code == 200, r.text[:200])
    body = r.json()
    by = {x["hostname"]: x for x in body["clients"]}
    check("three placed APs place a client near where it really is",
          "tri" in by and by["tri"]["method"] == "trilateration"
          and math.hypot(by["tri"]["x_px"] - truth[0], by["tri"]["y_px"] - truth[1]) < 5, str(by.get("tri")))
    check("that fix says how many APs it used and how rough it is",
          by["tri"]["anchors"] == 3 and by["tri"]["accuracy_m"] > 0 and by["tri"]["accuracy_px"] > 0)
    check("a client heard by one AP sits at that AP",
          by["single"]["method"] == "associated" and (by["single"]["x_px"], by["single"]["y_px"]) == (300, 100))
    check("a client with no signal reading is at its AP with no accuracy claimed",
          by["no-signal"]["method"] == "associated" and by["no-signal"]["accuracy_m"] is None)
    check("a client the latest poll no longer reports is not drawn", "gone" not in by)
    check("a client of an unplaced AP is counted, not drawn", "unplaced" not in by and body["unplaced_clients"] == 1,
          str(body["unplaced_clients"]))
    check("every placed AP is listed", len(body["access_points"]) == 3)
    check("an unknown floor is refused", c.get("/api/locate/floors/999").status_code == 404)

    print("── roam trail ──")
    mac = "02:00:00:00:00:0a"
    sql("INSERT INTO client_events (mac_address, event_type, to_ap_id, ts) VALUES (?, 'associate', ?, datetime('now', '-3 hours'))", mac, ap["AP1"])
    sql("INSERT INTO client_events (mac_address, event_type, from_ap_id, to_ap_id, ts) VALUES (?, 'roam', ?, ?, datetime('now', '-2 hours'))", mac, ap["AP1"], ap["AP2"])
    sql("INSERT INTO client_events (mac_address, event_type, from_ap_id, ts) VALUES (?, 'disassociate', ?, datetime('now', '-1 hours'))", mac, ap["AP2"])
    sql("INSERT INTO client_events (mac_address, event_type, to_ap_id, ts) VALUES (?, 'roam', ?, datetime('now', '-200 hours'))", mac, ap["AP3"])
    pts = c.get(f"/api/locate/clients/{mac}/trail", params={"hours": 24}).json()["points"]
    check("the trail is oldest first and only associate and roam events within the window",
          [p["access_point_name"] for p in pts] == ["AP1", "AP2"], str([p["access_point_name"] for p in pts]))
    check("each point carries the floor and position", pts[0]["floor_id"] == f1 and pts[0]["x_px"] == 100)
    check("something that is not a MAC is refused", c.get("/api/locate/clients/not-a-mac!!/trail").status_code == 422)
    check("a window beyond a week is refused", c.get(f"/api/locate/clients/{mac}/trail", params={"hours": 500}).status_code == 422)

    print("── a poll never undoes a placement ──")

    async def persist(collector_id: int, result: PollResult) -> None:
        async with aiosqlite.connect(str(DB)) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await poll_engine._persist(db, collector_id, result)

    for n in ("ca", "cb"):
        sql("INSERT INTO collectors (name, collector_type, config_json) VALUES (?, 'unifi', '{}')", n)
    ca, cb = (r["id"] for r in sql("SELECT id FROM collectors ORDER BY id"))

    def reading(clients: list[ClientReading]) -> AccessPointReading:
        return AccessPointReading(external_id="ext-1", name="Placed AP", mac_address="bb:00:00:00:00:01",
                                  radios=[RadioReading(band="5GHz", channel=36, clients=clients)])

    asyncio.run(persist(ca, PollResult(access_points=[reading([ClientReading("02:00:00:00:01:01", rssi_dbm=-58.0)])])))
    pid = sql("SELECT id FROM access_points WHERE mac_address='bb:00:00:00:00:01'")[0]["id"]
    c.patch(f"/api/devices/{pid}/placement", json={"floor_id": f1, "x_px": 50, "y_px": 60})
    asyncio.run(persist(ca, PollResult(access_points=[reading([ClientReading("02:00:00:00:01:01", rssi_dbm=-61.0)])])))
    row = sql("SELECT floor_id, x_px, y_px FROM access_points WHERE id=?", pid)[0]
    check("the next poll leaves the placement alone", (row["floor_id"], row["x_px"], row["y_px"]) == (f1, 50, 60), str(dict(row)))
    sig = sql("SELECT rssi_dbm FROM client_ap_signals WHERE client_mac='02:00:00:00:01:01' AND access_point_id=?", pid)
    check("the signal a client has to its AP is recorded and kept current", len(sig) == 1 and sig[0]["rssi_dbm"] == -61.0)
    asyncio.run(persist(cb, PollResult(access_points=[reading([ClientReading("02:00:00:00:01:01", rssi_dbm=-62.0)])])))
    rows = sql("SELECT id, floor_id, x_px, y_px FROM access_points WHERE mac_address='bb:00:00:00:00:01'")
    check("an AP that comes back under another collector keeps its row and its placement",
          len(rows) == 1 and rows[0]["id"] == pid and (rows[0]["floor_id"], rows[0]["x_px"]) == (f1, 50), str([dict(r) for r in rows]))

    other = AccessPointReading(external_id="ext-2", name="Other AP", mac_address="bb:00:00:00:00:02",
                               radios=[RadioReading(band="5GHz", channel=40)])
    asyncio.run(persist(cb, PollResult(
        access_points=[reading([]), other],
        observations=[ClientObservation("02:00:00:00:01:01", "ext-2", -70.0),
                      ClientObservation("02:00:00:00:01:01", "no-such-ap", -50.0)],
    )))
    heard = sql("""SELECT ap.name, s.rssi_dbm FROM client_ap_signals s JOIN access_points ap ON ap.id = s.access_point_id
                    WHERE s.client_mac='02:00:00:00:01:01' ORDER BY ap.name""")
    check("a signal a collector reports from another AP is stored", ("Other AP", -70.0) in [(r["name"], r["rssi_dbm"]) for r in heard], str([dict(r) for r in heard]))
    check("one naming an AP the poll did not report is ignored", all(r["name"] != "no-such-ap" for r in heard) and len(heard) == 2)

    print("── deleting a floor ──")
    as_role("viewer")
    check("a viewer cannot delete one", c.delete(f"/api/floors/{f1}").status_code == 403)
    as_role("analyst")
    check("an analyst can", c.delete(f"/api/floors/{f1}").status_code == 204)
    check("its image is removed", not (TMP / "floorplans" / f"{f1}.png").exists())
    placed = sql("SELECT COUNT(*) AS n FROM access_points WHERE floor_id IS NOT NULL OR x_px IS NOT NULL")[0]["n"]
    check("its APs keep their rows and lose the placement", placed == 0 and len(sql("SELECT id FROM access_points")) >= 5, str(placed))

    app.dependency_overrides.clear()
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
