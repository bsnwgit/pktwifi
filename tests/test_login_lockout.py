#!/usr/bin/env python3
"""
Failed-login lockout, and the client-event retention that shipped with it.

Standalone script — run from the repo root:
    python3 tests/test_login_lockout.py

The properties worth proving:

  * the configured number of failures locks an account for 30 minutes, and
    while it is locked even the right password is refused,
  * once that lock lapses, the same number of failures again locks it for good,
    and a lapsed time no longer matters,
  * a successful login wipes the record of an earlier lockout, so an old lock
    never turns the next one permanent,
  * an admin can unlock a user, and so can the host-side script,
  * the limit is a setting, with 3 as the default when it is missing or junk,
  * failures only count within a window (a setting, 24 hours by default), so
    old ones stop counting toward a lockout,
  * an unknown username is refused without anything being counted,
  * old client events are purged on their own retention window.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]

TMP = Path(tempfile.mkdtemp(prefix="pktwifi-lockout-"))
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

from app.alerts.cleanup import run_cleanup_now      # noqa: E402
from app.auth.local import hash_password            # noqa: E402
from app.main import app                            # noqa: E402

DB = TMP / "pktwifi.db"
GOOD, BAD = "right-password", "wrong-password"
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


def make_user(name: str) -> None:
    sql("INSERT INTO users (username, email, hashed_password, role) VALUES (?, ?, ?, 'viewer')",
        name, f"{name}@example.com", hash_password(GOOD))


def row(name: str):
    return sql("SELECT * FROM users WHERE username = ?", name)[0]


def lapse(name: str) -> None:
    """Let a temporary lock run out without waiting 30 minutes."""
    sql("UPDATE users SET locked_until = datetime('now', '-1 minutes') WHERE username = ?", name)


def main() -> int:
    with TestClient(app) as client:
        def login(user: str, pw: str):
            return client.post("/api/auth/login", json={"username": user, "password": pw})

        def fail(user: str, n: int) -> list[int]:
            return [login(user, BAD).status_code for _ in range(n)]

        print("── first lockout ──")
        make_user("bob")
        codes = fail("bob", 3)
        check("failures below the limit are plain refusals", codes[:2] == [401, 401], str(codes))
        check("the failure that reaches it locks the account", codes[2] == 423, str(codes))
        r = login("bob", GOOD)
        check("the right password is refused while locked", r.status_code == 423, str(r.status_code))
        check("and the message says when to try again", "Try again after" in r.json()["detail"], r.text)
        check("the lock is temporary, not permanent", row("bob")["is_locked"] == 0 and row("bob")["locked_until"])

        print("\n── a lapsed lock, then a second round ──")
        lapse("bob")
        check("once it lapses nothing stops the next attempt", login("bob", BAD).status_code == 401)
        codes = fail("bob", 2)
        check("the same number of failures again locks it permanently",
              codes[-1] == 423 and row("bob")["is_locked"] == 1, str(codes))
        lapse("bob")
        r = login("bob", GOOD)
        check("a permanent lock ignores the clock", r.status_code == 423, str(r.status_code))
        check("and says an admin must unlock it", "administrator" in r.json()["detail"], r.text)

        print("\n── an admin unlocks ──")
        admin = login("admin", "admin-test-password")
        check("the seeded admin can sign in", admin.status_code == 200, admin.text)
        h = {"Authorization": f"Bearer {admin.json()['access_token']}"}
        listed = {u["username"]: u for u in client.get("/api/users", headers=h).json()}
        check("the user list shows the lock", listed["bob"]["is_locked"] and listed["bob"]["lock_permanent"],
              str(listed["bob"]))
        check("and an unlocked user as not locked", not listed["admin"]["is_locked"])
        r = client.post(f"/api/users/{row('bob')['id']}/unlock", headers=h)
        check("unlock succeeds", r.status_code == 204, str(r.status_code))
        check("the user can sign in again", login("bob", GOOD).status_code == 200)
        check("unlocking an unknown user is a 404", client.post("/api/users/99999/unlock", headers=h).status_code == 404)
        make_user("viewer1")
        vh = {"Authorization": f"Bearer {login('viewer1', GOOD).json()['access_token']}"}
        check("a non-admin cannot unlock", client.post(f"/api/users/{row('bob')['id']}/unlock", headers=vh).status_code == 403)

        print("\n── a successful login clears earlier lockouts ──")
        make_user("carol")
        fail("carol", 3)
        lapse("carol")
        check("one lockout on record", row("carol")["lockout_count"] == 1)
        check("signing in succeeds after it lapses", login("carol", GOOD).status_code == 200)
        check("which wipes the record", row("carol")["lockout_count"] == 0 and row("carol")["failed_login_count"] == 0)
        codes = fail("carol", 3)
        check("so the next lockout is temporary again, not permanent",
              codes[-1] == 423 and row("carol")["is_locked"] == 0, str(codes))

        print("\n── failures that fall short ──")
        make_user("dave")
        fail("dave", 2)
        login("dave", GOOD)
        check("a success resets the failure count", row("dave")["failed_login_count"] == 0)
        codes = fail("dave", 2)
        check("so two more failures do not lock", codes == [401, 401], str(codes))

        print("\n── the limit is a setting ──")
        make_user("erin")
        sql("INSERT INTO settings (key, value) VALUES ('login_max_failed_attempts', '5')")
        codes = fail("erin", 5)
        check("with 5, four failures do not lock", codes[:4] == [401] * 4, str(codes))
        check("and the fifth does", codes[4] == 423, str(codes))
        make_user("frank")
        sql("UPDATE settings SET value = '\"junk\"' WHERE key = 'login_max_failed_attempts'")
        check("an unusable value falls back to 3", fail("frank", 3)[-1] == 423)
        make_user("gina")
        sql("DELETE FROM settings WHERE key = 'login_max_failed_attempts'")
        check("so does no value at all", fail("gina", 3)[-1] == 423)

        print("\n── failures expire ──")
        def age(name: str, hours: int) -> None:
            sql("UPDATE users SET last_failed_login = datetime('now', ?) WHERE username = ?", f"-{hours} hours", name)

        make_user("ivy")
        fail("ivy", 2)
        age("ivy", 25)
        codes = fail("ivy", 2)
        check("failures older than the default 24 hours no longer count", codes == [401, 401], str(codes))
        check("so the count started again", row("ivy")["failed_login_count"] == 2)
        make_user("jack")
        fail("jack", 2)
        age("jack", 23)
        check("failures inside the window still do", fail("jack", 1) == [423])
        make_user("kim")
        sql("INSERT INTO settings (key, value) VALUES ('login_failure_window_hours', '2')")
        fail("kim", 2)
        age("kim", 3)
        check("a shorter window setting expires them sooner", fail("kim", 2) == [401, 401])
        make_user("lee")
        sql("UPDATE settings SET value = '\"junk\"' WHERE key = 'login_failure_window_hours'")
        fail("lee", 2)
        age("lee", 23)
        check("an unusable window falls back to 24 hours", fail("lee", 1) == [423])
        sql("DELETE FROM settings WHERE key = 'login_failure_window_hours'")
        make_user("mo")
        fail("mo", 2)
        login("mo", GOOD)
        check("a successful login clears the time of the last failure", row("mo")["last_failed_login"] is None)

        print("\n── accounts that do not exist ──")
        before = sql("SELECT COUNT(*) AS n FROM users")[0]["n"]
        check("an unknown username is refused plainly", fail("nobody", 5) == [401] * 5)
        check("and nothing is created or counted", sql("SELECT COUNT(*) AS n FROM users")[0]["n"] == before)

        print("\n── the host-side unlock ──")
        make_user("hank")
        fail("hank", 3)
        lapse("hank")
        fail("hank", 3)
        check("locked permanently", row("hank")["is_locked"] == 1)
        env = dict(os.environ)
        done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "unlock_user.py"), "hank"],
                              env=env, capture_output=True, text=True, cwd=str(REPO_ROOT))
        check("the script reports success", done.returncode == 0, done.stderr + done.stdout)
        check("and the account signs in", login("hank", GOOD).status_code == 200)
        done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "unlock_user.py"), "nobody"],
                              env=env, capture_output=True, text=True, cwd=str(REPO_ROOT))
        check("an unknown user is reported, not ignored", done.returncode == 1)

    print("\n── client event retention ──")
    sql("INSERT INTO client_events (mac_address, event_type, ts) VALUES ('aa:aa', 'roam', datetime('now', '-100 days'))")
    sql("INSERT INTO client_events (mac_address, event_type, ts) VALUES ('bb:bb', 'roam', datetime('now', '-10 days'))")
    result = asyncio.run(run_cleanup_now(str(DB)))
    left = [r["mac_address"] for r in sql("SELECT mac_address FROM client_events")]
    check("with no setting, events older than 90 days go", left == ["bb:bb"] and result["client_events_deleted"] == 1,
          f"{left} {result}")
    sql("INSERT INTO settings (key, value) VALUES ('client_event_retention_days', '5')")
    result = asyncio.run(run_cleanup_now(str(DB)))
    check("the window follows the setting", sql("SELECT COUNT(*) AS n FROM client_events")[0]["n"] == 0
          and result["client_event_retention_days"] == 5, str(result))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
