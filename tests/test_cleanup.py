#!/usr/bin/env python3
"""
The daily cleanup: retention windows, and radios a controller no longer reports.

Standalone script — run from the repo root:
    python3 tests/test_cleanup.py

The properties worth proving:

  * a radio no poll has reported for longer than the setting is removed,
    together with its metric history, and a client that pointed at it keeps its
    row and loses only the pointer; a radio that is still reported is kept,
  * the window is a setting (default 30 days), and a value of nothing, less, or
    junk is not honoured — "-0 days" would otherwise match every row — so the
    default stands and nothing current is deleted,
  * the same guard holds for the other retention settings,
  * the manual cleanup reports what it removed.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]

TMP = Path(tempfile.mkdtemp(prefix="pktwifi-cleanup-"))
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

from app.alerts.cleanup import run_cleanup_now      # noqa: E402
from app.database import init_db                    # noqa: E402

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


def set_setting(key: str, value) -> None:
    sql("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        key, json.dumps(value))


def clear_settings() -> None:
    sql("DELETE FROM settings WHERE key LIKE '%retention%'")


def cleanup() -> dict:
    return asyncio.run(run_cleanup_now(str(DB)))


def radios() -> set[str]:
    return {r["band"] for r in sql("SELECT band FROM radios")}


def seed() -> None:
    """One AP with: a current radio, one unreported for 40 days, and one for 6."""
    sql("DELETE FROM radio_metrics")
    sql("DELETE FROM radios")
    sql("DELETE FROM wifi_clients")
    sql("DELETE FROM access_points")
    sql("INSERT INTO collectors (id, name, collector_type) VALUES (1, 'c', 'unifi') ON CONFLICT(id) DO NOTHING")
    sql("INSERT INTO access_points (id, collector_id, external_id, name, last_seen) VALUES (1, 1, 'a', 'AP', datetime('now'))")
    for rid, band, age in ((1, "5GHz", "0 days"), (2, "unknown", "-40 days"), (3, "2.4GHz", "-6 days")):
        sql("INSERT INTO radios (id, access_point_id, band, updated_at) VALUES (?, 1, ?, datetime('now', ?))",
            rid, band, age if age.startswith("-") else "0 days")
    sql("INSERT INTO radio_metrics (radio_id, ts) VALUES (2, datetime('now', '-10 days'))")    # inside the 30-day metric window
    sql("INSERT INTO radio_metrics (radio_id, ts) VALUES (1, datetime('now', '-10 days'))")
    sql("INSERT INTO wifi_clients (mac_address, access_point_id, radio_id, last_seen) VALUES ('02:00:00:00:00:01', 1, 2, datetime('now'))")


def main() -> int:
    asyncio.run(init_db())

    print("── the default (30 days) ──")
    seed()
    out = cleanup()
    check("a radio unreported for 40 days is removed", "unknown" not in radios(), str(radios()))
    check("one unreported for 6 days is kept", "2.4GHz" in radios(), str(radios()))
    check("and the one still reported", "5GHz" in radios())
    check("the result says how many went and what the window was",
          out["stale_radios_deleted"] == 1 and out["stale_radio_retention_days"] == 30, str(out))
    check("its metric history went with it", sql("SELECT COUNT(*) AS n FROM radio_metrics WHERE radio_id = 2")[0]["n"] == 0)
    check("another radio's history is untouched", sql("SELECT COUNT(*) AS n FROM radio_metrics WHERE radio_id = 1")[0]["n"] == 1)
    client = sql("SELECT radio_id, access_point_id FROM wifi_clients")
    check("a client that pointed at it keeps its row, and loses the pointer",
          len(client) == 1 and client[0]["radio_id"] is None and client[0]["access_point_id"] == 1, str([dict(c) for c in client]))
    check("running it again removes nothing more", cleanup()["stale_radios_deleted"] == 0)

    print("\n── the window is a setting ──")
    seed()
    set_setting("stale_radio_retention_days", 5)
    out = cleanup()
    check("with 5 days, the radio unreported for 6 days goes too", radios() == {"5GHz"}, str(radios()))
    check("and the result reports the setting", out["stale_radio_retention_days"] == 5 and out["stale_radios_deleted"] == 2, str(out))
    seed()
    set_setting("stale_radio_retention_days", 60)
    cleanup()
    check("with 60 days, the radio unreported for 40 days stays", radios() == {"5GHz", "unknown", "2.4GHz"}, str(radios()))
    clear_settings()

    print("\n── nothing, less, or junk is not honoured ──")
    for label, value in (("zero", 0), ("negative", -3), ("junk", "soon")):
        seed()
        set_setting("stale_radio_retention_days", value)
        out = cleanup()
        check(f"{label} falls back to 30 days", out["stale_radio_retention_days"] == 30, str(out))
        check(f"and with {label} the current radios survive", {"5GHz", "2.4GHz"} <= radios(), str(radios()))
        clear_settings()

    print("\n── the same guard on the other retention settings ──")
    sql("DELETE FROM alert_events")
    sql("INSERT INTO alert_events (severity, message, resolved, created_at) VALUES ('info', 'm', 1, datetime('now', '-10 days'))")
    sql("INSERT INTO client_events (mac_address, event_type, ts) VALUES ('aa:aa', 'roam', datetime('now', '-10 days'))")
    set_setting("alert_event_retention_days", 0)
    set_setting("client_event_retention_days", -1)
    set_setting("radio_metrics_retention_days", 0)
    seed()
    out = cleanup()
    check("a retention of zero does not delete everything", sql("SELECT COUNT(*) AS n FROM alert_events")[0]["n"] == 1
          and sql("SELECT COUNT(*) AS n FROM client_events")[0]["n"] == 1, str(out))
    check("including RF metrics", sql("SELECT COUNT(*) AS n FROM radio_metrics WHERE radio_id = 1")[0]["n"] == 1)
    check("each falls back to its default", (out["alert_retention_days"], out["client_event_retention_days"], out["metrics_retention_days"]) == (90, 90, 30), str(out))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
