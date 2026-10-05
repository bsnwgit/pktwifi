#!/usr/bin/env python3
"""
The shared WHERE builder, the exception redactor, and the endpoints that use
them.

Standalone script — run from the repo root:
    python3 tests/test_query_helpers.py

The properties worth proving:

  * `Where` joins fragments, keeps their values in order, and refuses a
    fragment whose placeholders do not match its values,
  * every list endpoint that was moved onto it still filters exactly as before
    — each filter narrows the result, and several combine,
  * error text that is stored or returned never carries a URL's credentials or
    query string, but keeps the host and path an admin needs,
  * a server error on the suite endpoints and the widgets does not hand the
    caller the database's own message.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]

TMP = Path(tempfile.mkdtemp(prefix="pktwifi-query-"))
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

from fastapi.testclient import TestClient           # noqa: E402

from app.errors import describe_exception, redact   # noqa: E402
from app.main import app                            # noqa: E402
from app.sqlutil import Where                       # noqa: E402

DB = TMP / "pktwifi.db"
FAILURES: list[str] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not passed else ""))
    if not passed:
        FAILURES.append(label)


def sql(query: str, *params):
    conn = sqlite3.connect(str(DB))
    try:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def main() -> int:
    print("── Where ──")
    w = Where()
    check("empty builds no clause", w.sql == "" and w.params == [])
    w.add("a = ?", 1)
    w.add("b IS NULL")
    w.add("(c LIKE ? OR d LIKE ?)", "x", "y")
    check("fragments are joined with AND", w.sql == "WHERE a = ? AND b IS NULL AND (c LIKE ? OR d LIKE ?)", w.sql)
    check("values stay in order", w.params == [1, "x", "y"], str(w.params))
    check("paging values are appended without changing it", w.with_params(10, 0) == [1, "x", "y", 10, 0]
          and w.params == [1, "x", "y"])
    for label, args in (("too few values", ("a = ? AND b = ?", 1)), ("too many values", ("a = ?", 1, 2))):
        try:
            Where().add(*args)
            check(f"a fragment with {label} is refused", False)
        except ValueError:
            check(f"a fragment with {label} is refused", True)

    print("\n── redaction ──")
    check("credentials in a URL are removed",
          redact("GET https://user:s3cret@host.example.com/api failed") == "GET https://***@host.example.com/api failed")
    q = redact("Client error for url 'https://host.example.com/v1/x?apikey=abc123&b=2'")
    check("a query string is removed, the host and path kept",
          "abc123" not in q and "https://host.example.com/v1/x" in q, q)
    check("text without a URL is untouched", redact("Connection refused") == "Connection refused")
    check("an empty message falls back to the type name", describe_exception(TimeoutError()) == "TimeoutError")
    check("the type can be included", describe_exception(ValueError("bad"), with_type=True) == "ValueError: bad")

    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin-test-password"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # three access points: two online (one rogue), one offline at another site
        sql("INSERT INTO collectors (id, name, collector_type) VALUES (1, 'c', 'unifi')")
        ap = {}
        for key, name, mac, ip, status, site, rogue in (
            ("a", "Lobby", "aa:00:00:00:00:01", "10.0.0.1", "online", "HQ", 0),
            ("b", "Warehouse", "aa:00:00:00:00:02", "10.0.0.2", "online", "Depot", 1),
            ("c", "Annex", "aa:00:00:00:00:03", "10.0.0.3", "offline", "HQ", 0),
        ):
            ap[key] = sql(
                "INSERT INTO access_points (collector_id, external_id, name, mac_address, ip_address, model, site,"
                " status, is_rogue, last_seen) VALUES (1, ?, ?, ?, ?, 'U6', ?, ?, ?, datetime('now'))",
                key, name, mac, ip, site, status, rogue)
        radio = {}
        for key, apk, band in (("a5", "a", "5GHz"), ("a24", "a", "2.4GHz"), ("b5", "b", "5GHz")):
            radio[key] = sql("INSERT INTO radios (access_point_id, band, channel, utilization_pct, client_count, updated_at)"
                             " VALUES (?, ?, 1, 10, 0, datetime('now'))", ap[apk], band)
        for mac, apk, rk, ssid, band, rssi in (
            ("02:00:00:00:00:01", "a", "a5", "corp", "5GHz", -50),
            ("02:00:00:00:00:02", "a", "a24", "guest", "2.4GHz", -80),
            ("02:00:00:00:00:03", "b", "b5", "corp", "5GHz", -72),
        ):
            sql("INSERT INTO wifi_clients (mac_address, access_point_id, radio_id, hostname, ip_address, ssid, band,"
                " rssi_dbm, last_seen) VALUES (?, ?, ?, ?, '10.0.0.50', ?, ?, ?, datetime('now'))",
                mac, ap[apk], radio[rk], f"host-{mac[-2:]}", ssid, band, rssi)
        for sev, apk, active, acked in (("critical", "a", 1, 0), ("warning", "b", 1, 1), ("warning", "a", 0, 0)):
            sql("INSERT INTO alert_events (access_point_id, severity, message, active, acked) VALUES (?, ?, 'm', ?, ?)",
                ap[apk], sev, active, acked)
        for lvl, no, lg, msg in (("INFO", 20, "pktwifi.alpha", "hello world"), ("ERROR", 40, "pktwifi.beta", "boom happened"),
                                 ("WARNING", 30, "pktwifi.alpha", "careful now")):
            sql("INSERT INTO app_logs (level, level_no, logger, message) VALUES (?, ?, ?, ?)", lvl, no, lg, msg)

        # These endpoints answer 404 on an install that never enabled the panel.
        sql("INSERT INTO settings (key, value) VALUES ('resonance_enabled', 'true')")
        P = "/api/resonance/data"

        def rows(doc: dict) -> list:
            """The list a response carries, whatever it calls it."""
            return next(v for v in doc.values() if isinstance(v, list))

        def get(path: str, **params):
            resp = client.get(f"{P}{path}", params=params, headers=h)
            assert resp.status_code == 200, (path, params, resp.status_code, resp.text[:200])
            return resp.json()

        print("\n── access points ──")
        check("no filter returns all three", get("/access-points")["total"] == 3)
        check("status narrows", get("/access-points", status="offline")["total"] == 1)
        check("site narrows", get("/access-points", site="HQ")["total"] == 2)
        check("rogue only narrows", get("/access-points", rogue_only="true")["total"] == 1)
        check("search narrows", get("/access-points", search="Warehouse")["total"] == 1)
        check("search reaches the address", get("/access-points", search="10.0.0.3")["total"] == 1)
        check("filters combine", get("/access-points", status="online", site="HQ")["total"] == 1)
        check("the listed rows match the count", len(rows(get("/access-points", site="HQ"))) == 2)

        print("\n── clients ──")
        check("no filter returns all current clients", get("/clients")["total"] == 3)
        check("ssid narrows", get("/clients", ssid="corp")["total"] == 2)
        check("band narrows", get("/clients", band="2.4")["total"] == 1)
        check("and finds the 5 GHz clients", get("/clients", band="5")["total"] == 2)
        check("a band nothing is on is empty", get("/clients", band="6")["total"] == 0)
        check("weak signal narrows", get("/clients", weak_signal_only="true")["total"] == 2)
        check("search narrows", get("/clients", search="host-03")["total"] == 1)
        check("access point narrows", get("/clients", access_point_id=ap["a"])["total"] == 2)
        check("filters combine", get("/clients", ssid="corp", weak_signal_only="true")["total"] == 1)

        print("\n── radios ──")
        check("no filter returns all radios", len(rows(get("/radios"))) == 3)
        check("band narrows", len(rows(get("/radios", band="5"))) == 2)
        check("2.4 GHz finds its radio", len(rows(get("/radios", band="2.4"))) == 1)
        check("access point narrows", len(rows(get("/radios", access_point_id=ap["a"]))) == 2)
        check("filters combine", len(rows(get("/radios", access_point_id=ap["a"], band="5"))) == 1)

        print("\n── alert events ──")
        check("no filter returns all", get("/alerts/events")["total"] == 3)
        check("severity narrows", get("/alerts/events", severity="critical")["total"] == 1)
        check("unacknowledged narrows", get("/alerts/events", unacked_only="true")["total"] == 2)
        check("active narrows", get("/alerts/events", active_only="true")["total"] == 2)
        check("access point narrows", get("/alerts/events", access_point_id=ap["b"])["total"] == 1)
        check("filters combine", get("/alerts/events", severity="warning", active_only="true")["total"] == 1)
        check("a time bound narrows", get("/alerts/events", since="2999-01-01T00:00:00")["total"] == 0)

        print("\n── application log ──")
        check("no filter returns all", get("/app-log")["total"] >= 3)
        check("level narrows", get("/app-log", level="ERROR")["total"] == 1)
        check("logger prefix narrows", get("/app-log", logger="pktwifi.alpha")["total"] == 2)
        check("search narrows", get("/app-log", search="boom")["total"] == 1)

        def logs(**params):
            resp = client.get("/api/logs", params=params, headers=h)
            assert resp.status_code == 200, (params, resp.status_code, resp.text[:200])
            return resp.json()

        print("\n── /api/logs ──")
        base = logs()["total"]
        check("no filter returns everything", base >= 3)
        check("minimum level includes it and above", logs(level="WARNING")["total"] >= 2)
        check("logger prefix narrows", logs(logger="pktwifi.beta")["total"] == 1)
        check("search narrows", logs(search="careful")["total"] == 1)
        check("filters combine", logs(logger="pktwifi.alpha", search="hello")["total"] == 1)

        print("\n── server errors do not leak ──")
        # Break the settings table so the suite endpoints' own queries fail with
        # an error that names it.
        sql("ALTER TABLE settings RENAME TO settings_off")
        try:
            resp = client.post("/api/suite/regenerate", headers=h)
            check("regenerate fails", resp.status_code == 500, str(resp.status_code))
            check("without naming the table or the database", "settings" not in resp.text and "no such" not in resp.text,
                  resp.text)
            resp = client.post("/api/suite/register", json={"suite_token": "x" * 20}, headers=h)
            check("register fails", resp.status_code == 500, str(resp.status_code))
            check("and says nothing of the cause", "settings" not in resp.text and "no such" not in resp.text, resp.text)
        finally:
            sql("ALTER TABLE settings_off RENAME TO settings")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
