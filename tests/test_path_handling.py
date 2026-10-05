#!/usr/bin/env python3
"""
Paths built from a request: the in-app docs, snapshot restore, and the
single-page-app file server.

Standalone script — run from the repo root:
    python3 tests/test_path_handling.py

The app is copied into a temporary tree together with a stand-in for the built
frontend, so that files placed where an escape would land (one and two levels
above the build folder, and a sibling folder that shares its prefix) can be
told apart from files the server is meant to serve. The properties worth
proving:

  * a request cannot name a file outside the folder it is served from — not
    with `..`, encoded or double-encoded `..`, backslashes, an absolute path,
    a null byte, or a sibling folder whose name starts the same way,
  * the files it should serve, it still serves,
  * only a snapshot that really is a directory under the backup root can be
    restored from, and a symlink standing in for one is refused,
  * the docs endpoint serves a document by name and nothing else.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]

ROOT = Path(tempfile.mkdtemp(prefix="pktwifi-paths-"))
shutil.copytree(REPO_ROOT / "app", ROOT / "app", ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(REPO_ROOT / "migrations", ROOT / "migrations")
DIST = ROOT / "frontend" / "dist"
(DIST / "assets").mkdir(parents=True)
(DIST / "index.html").write_text("<html>THE-INDEX</html>")
(DIST / "assets" / "app.js").write_text("console.log('real asset')")
(ROOT / "frontend" / "canary_one_up.txt").write_text("CANARY-ONE-ABOVE-DIST")
(ROOT / "canary_two_up.txt").write_text("CANARY-TWO-ABOVE-DIST")
(ROOT / "frontend" / "dist-evil.txt").write_text("CANARY-SIBLING-OF-DIST")
(ROOT / "docs").mkdir()
(ROOT / "docs" / "guide.md").write_text("# The guide")
(ROOT / "outside_docs.md").write_text("CANARY-OUTSIDE-DOCS")
(ROOT / "config.yaml").write_text(
    f"install_dir: {ROOT}\nsecret_key: {'a' * 64}\ncredential_key: {Fernet.generate_key().decode()}\nsuite_token: ''\n")
os.environ["PKTWIFI_CONFIG"] = str(ROOT / "config.yaml")
os.environ["PKTWIFI_INSTALL_DIR"] = str(ROOT)
os.environ["PKTWIFI_ADMIN_PASSWORD"] = "admin-test-password"
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient           # noqa: E402

from app.main import app                            # noqa: E402

FAILURES: list[str] = []
CANARIES = ("CANARY-ONE-ABOVE-DIST", "CANARY-TWO-ABOVE-DIST", "CANARY-SIBLING-OF-DIST", "CANARY-OUTSIDE-DOCS")


def check(label: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not passed else ""))
    if not passed:
        FAILURES.append(label)


def main() -> int:
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin-test-password"})
        admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

        print("── the frontend file server ──")
        check("a real asset is served", "real asset" in client.get("/assets/app.js").text)
        check("the index is served at the root", "THE-INDEX" in client.get("/").text)
        check("and for an app route", "THE-INDEX" in client.get("/settings").text)
        escapes = [
            "/../../canary_two_up.txt", "/..%2f..%2fcanary_two_up.txt", "/%2e%2e/%2e%2e/canary_two_up.txt",
            "/assets/../../canary_two_up.txt", "/assets/..%2f..%2f..%2fcanary_two_up.txt",
            "/assets/../../../canary_two_up.txt", "/....//....//canary_two_up.txt",
            "/assets/%2e%2e%2f%2e%2e%2f%2e%2e%2fcanary_two_up.txt", "/\\..\\..\\canary_two_up.txt",
            "/../canary_one_up.txt", "/..%2fcanary_one_up.txt", "/%2e%2e/canary_one_up.txt",
            "/assets/../../canary_one_up.txt", "/../dist-evil.txt", "/..%2fdist-evil.txt",
            "/..;/..;/canary_two_up.txt", "/%252e%252e/%252e%252e/canary_two_up.txt",
            f"/{ROOT}/canary_two_up.txt", f"//{ROOT}/canary_two_up.txt", f"/%2f{str(ROOT)[1:]}/canary_two_up.txt",
            "/%00", "/assets/%00../x", "/.well-known/../../../canary_two_up.txt", "//etc/passwd", "/%2fetc/passwd",
        ]
        leaked = [p for p in escapes if any(c in client.get(p).text for c in CANARIES)]
        check(f"none of {len(escapes)} escape attempts returns a file from outside the build folder",
              not leaked, str(leaked))
        check("config.yaml is not reachable", "secret_key" not in client.get("/../../config.yaml").text
              and "secret_key" not in client.get("/..%2f..%2fconfig.yaml").text)

        print("\n── in-app docs ──")
        check("a document is served by name", "The guide" in client.get("/api/docs-content/guide", headers=admin).json().get("content", ""))
        check("the list names it", any(d["slug"] == "guide" for d in client.get("/api/docs-content", headers=admin).json()))
        for slug in ("..%2foutside_docs", "guide.md", "guide%00", "../outside_docs", "gu ide", "gui%0ade"):
            r = client.get(f"/api/docs-content/{slug}", headers=admin)
            check(f"{slug!r} is refused", r.status_code in (400, 404) and not any(c in r.text for c in CANARIES), f"{r.status_code} {r.text[:80]}")
        check("an unknown document is a 404", client.get("/api/docs-content/nothing", headers=admin).status_code == 404)
        check("sign-in is required", client.get("/api/docs-content/guide").status_code == 401)

        print("\n── restoring from a snapshot ──")
        backups = ROOT / "backups"
        (backups / "backup_2026-10-05_10-00").mkdir(parents=True)
        outside = ROOT / "elsewhere"
        outside.mkdir()
        (backups / "backup_2026-10-05_11-00").symlink_to(outside, target_is_directory=True)
        (backups / "backup_2026-10-05_12-00").write_text("a file, not a directory")

        def restore(name: str):
            # files=noop selects nothing, so a successful call changes nothing on disk.
            return client.post(f"/api/system/backups/restore/{name}", params={"files": "noop"}, headers=admin)

        r = restore("backup_2026-10-05_10-00")
        check("a real snapshot is accepted", r.status_code == 200, f"{r.status_code} {r.text}")
        check("a snapshot that does not exist is a 404", restore("backup_2026-10-05_09-00").status_code == 404)
        check("a symlink standing in for one is refused", restore("backup_2026-10-05_11-00").status_code == 404)
        check("a file standing in for one is refused", restore("backup_2026-10-05_12-00").status_code == 404)
        for name in ("..%2f..%2fetc", "backup_2026-10-05_10-00%2f..%2f..", "backup_2026-10-05_10-00%0a",
                     "backup_٢٠٢٦-١٠-٠٥_١٠-٠٠", "backup_2026-10-05_10-00/", "other"):
            # Refused is any answer but success: the name is rejected outright (400/404),
            # or, when it carries a decoded slash, matches no restore route at all (405).
            r = restore(name)
            check(f"{name!r} is refused", r.status_code in (400, 404, 405), str(r.status_code))
        check("a non-admin cannot restore", client.post("/api/system/backups/restore/backup_2026-10-05_10-00").status_code == 401)

        # With no backup root at all.
        shutil.rmtree(backups)
        check("a missing backup folder is a 404, not a crash", restore("backup_2026-10-05_10-00").status_code == 404)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
