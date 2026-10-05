#!/usr/bin/env python3
"""
Poll engine tests: what a poll may and may not do to stored data, and how many
polls run at once.

Standalone script — run from the repo root:
    python3 tests/test_poll_engine.py

The properties worth proving:

  * a poll that comes back with no access points does not wipe the ones on
    record — it is asked again, and if it is still empty the stored data stays
    and the collector reports an error,
  * a poll that fails half way leaves nothing half written,
  * a poll that returns fewer access points still removes the ones that are
    really gone (the guard must not turn "full replace" into "never delete"),
  * polls run in parallel but never more than the cap, a collector is never
    polled twice at once, and one that hangs is cut off and frees its slot,
  * Poll Now stores what it fetches and is guarded the same way a scheduled
    poll is, and cannot run on top of one,
  * existing UniFi collectors keep working when TLS verification becomes the
    default, and a credential key that no longer fits is reported.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]

TMP = Path(tempfile.mkdtemp(prefix="pktwifi-poll-"))
(TMP / "config.yaml").write_text(
    f"install_dir: {TMP}\n"
    f"secret_key: {'a' * 64}\n"
    f"credential_key: {Fernet.generate_key().decode()}\n"
    f"suite_token: ''\n"
)
os.environ["PKTWIFI_CONFIG"] = str(TMP / "config.yaml")
os.environ["PKTWIFI_INSTALL_DIR"] = str(TMP)
sys.path.insert(0, str(REPO_ROOT))

import aiosqlite                                    # noqa: E402
from fastapi import HTTPException                   # noqa: E402

from app.api.collectors import poll_now             # noqa: E402

from app.database import init_db                    # noqa: E402
from app.wifi import poll_engine                    # noqa: E402
from app.wifi.collectors import crypto              # noqa: E402
from app.wifi.collectors.base import (              # noqa: E402
    AccessPointReading, ClientReading, PollResult, RadioReading,
)
from app.wifi.collectors.unifi import UnifiCollector  # noqa: E402

DB = TMP / "pktwifi.db"
FAILURES: list[str] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not passed else ""))
    if not passed:
        FAILURES.append(label)


def q(sql: str, *params):
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def ap(ext: str, mac: str, clients: int = 1) -> AccessPointReading:
    return AccessPointReading(
        external_id=ext, name=f"AP {ext}", mac_address=mac, vendor="test",
        radios=[RadioReading(
            band="5GHz", channel=36,
            clients=[ClientReading(mac_address=f"02:00:00:{ext}:00:{n:02x}") for n in range(clients)],
        )],
    )


class Fake:
    """Stands in for a vendor collector. `results` is the sequence of poll
    results handed back call by call (the last one repeats)."""
    active = 0
    peak = 0

    def __init__(self, results, delay: float = 0.0):
        self.results = results
        self.delay = delay
        self.calls = 0

    async def poll(self) -> PollResult:
        Fake.active += 1
        Fake.peak = max(Fake.peak, Fake.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            result = self.results[min(self.calls, len(self.results) - 1)]
            self.calls += 1
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            Fake.active -= 1


FAKES: dict[str, Fake] = {}
poll_engine.get_collector_instance = lambda ctype, cfg: FAKES.get(cfg.get("fake"))


def add_collector(name: str, ctype: str = "fake", interval: int = 60, config: dict | None = None) -> int:
    conn = sqlite3.connect(str(DB))
    try:
        cur = conn.execute(
            "INSERT INTO collectors (name, collector_type, config_json, poll_interval_sec) VALUES (?, ?, ?, ?)",
            (name, ctype, crypto.encrypt_config(config if config is not None else {"fake": name}), interval),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def collector(cid: int):
    return q("SELECT * FROM collectors WHERE id = ?", cid)[0]


async def run_engine_once() -> poll_engine.PollEngine:
    engine = poll_engine.PollEngine()
    engine._db_path = str(DB)
    await engine._tick()
    if engine._polls:
        await asyncio.gather(*list(engine._polls))
    return engine


async def main() -> int:
    await init_db()
    poll_engine._EMPTY_POLL_RETRY_DELAY_SECONDS = 0

    print("── a normal poll ──")
    FAKES["basic"] = Fake([PollResult([ap("01", "aa:00:00:00:00:01", 2), ap("02", "aa:00:00:00:00:02", 1)])])
    cid = add_collector("basic")
    await run_engine_once()
    check("access points are stored", len(q("SELECT id FROM access_points WHERE collector_id = ?", cid)) == 2)
    check("clients are stored", len(q("SELECT id FROM wifi_clients")) == 3)
    check("collector is marked ok", collector(cid)["status"] == "ok")

    print("\n── an empty result is not believed ──")
    FAKES["basic"] = Fake([PollResult([])])
    q_before = q("SELECT id FROM access_points WHERE collector_id = ?", cid)
    conn = sqlite3.connect(str(DB))
    conn.execute("UPDATE collectors SET last_poll_at = NULL"); conn.commit(); conn.close()
    await run_engine_once()
    check("the controller is asked again, not just once",
          FAKES["basic"].calls == 1 + poll_engine._EMPTY_POLL_RETRIES, f"calls={FAKES['basic'].calls}")
    check("the access points on record survive",
          len(q("SELECT id FROM access_points WHERE collector_id = ?", cid)) == len(q_before) == 2)
    check("so do their clients", len(q("SELECT id FROM wifi_clients")) == 3)
    row = collector(cid)
    check("the collector reports an error", row["status"] == "error")
    check("and says why", "no access points" in (row["last_error"] or ""), str(row["last_error"]))

    print("\n── an empty first answer that recovers ──")
    FAKES["basic"] = Fake([PollResult([]), PollResult([ap("01", "aa:00:00:00:00:01", 2), ap("02", "aa:00:00:00:00:02", 1)])])
    conn = sqlite3.connect(str(DB))
    conn.execute("UPDATE collectors SET last_poll_at = NULL"); conn.commit(); conn.close()
    await run_engine_once()
    check("the re-query result is used", FAKES["basic"].calls == 2, f"calls={FAKES['basic'].calls}")
    check("and the collector is ok again", collector(cid)["status"] == "ok")

    print("\n── a collector that never had anything ──")
    FAKES["new"] = Fake([PollResult([])])
    nid = add_collector("new")
    await run_engine_once()
    check("an empty poll with nothing on record is simply ok", collector(nid)["status"] == "ok")
    check("and is not re-queried", FAKES["new"].calls == 1, f"calls={FAKES['new'].calls}")

    print("\n── really-removed access points are still removed ──")
    FAKES["basic"] = Fake([PollResult([ap("01", "aa:00:00:00:00:01", 2)])])
    conn = sqlite3.connect(str(DB))
    conn.execute("UPDATE collectors SET last_poll_at = NULL"); conn.commit(); conn.close()
    await run_engine_once()
    left = q("SELECT external_id FROM access_points WHERE collector_id = ?", cid)
    check("the one missing from the controller is deleted", [r["external_id"] for r in left] == ["01"],
          str([r["external_id"] for r in left]))

    print("\n── a failed poll leaves nothing half written ──")
    bad = AccessPointReading(external_id="99", name="Bad", mac_address="aa:00:00:00:00:99",
                             radios=[RadioReading(band=None)])   # radios.band is NOT NULL
    FAKES["partial"] = Fake([PollResult([ap("11", "aa:00:00:00:00:11"), bad])])
    pid = add_collector("partial")
    await run_engine_once()
    check("the access point written before the failure is rolled back",
          len(q("SELECT id FROM access_points WHERE collector_id = ?", pid)) == 0)
    check("the failure is recorded", collector(pid)["status"] == "error")

    print("\n── polls run in parallel, but capped ──")
    poll_engine._MAX_CONCURRENT_POLLS = 2
    names = [f"par{i}" for i in range(6)]
    for n in names:
        FAKES[n] = Fake([PollResult([])], delay=0.15)
        add_collector(n)
    Fake.active = Fake.peak = 0
    engine = poll_engine.PollEngine()           # built after the cap was set
    engine._db_path = str(DB)
    await engine._tick()
    first_tick = len(engine._polls)
    await engine._tick()                        # same collectors still in flight
    check("a collector already running is not started again", len(engine._polls) == first_tick,
          f"{first_tick} -> {len(engine._polls)}")
    await asyncio.gather(*list(engine._polls))
    check("more than one poll ran at a time", Fake.peak > 1, f"peak={Fake.peak}")
    check("but never more than the cap", Fake.peak <= 2, f"peak={Fake.peak}")
    check("every collector was polled exactly once", all(FAKES[n].calls == 1 for n in names),
          str({n: FAKES[n].calls for n in names}))

    print("\n── a poll that hangs is cut off ──")
    poll_engine._POLL_TIMEOUT_SECONDS = 0.2
    FAKES["hang"] = Fake([PollResult([])], delay=30)
    hid = add_collector("hang")
    engine = await run_engine_once()
    check("it is recorded as an error", collector(hid)["status"] == "error")
    check("its slot is released", hid not in engine._inflight)

    print("\n── Poll Now ──")
    async def manual(cid_: int):
        """Call the endpoint the way FastAPI would, on its own connection."""
        async with aiosqlite.connect(str(DB)) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys=ON")
            return await poll_now(cid_, user={}, db=conn)

    async def manual_error(cid_: int):
        try:
            await manual(cid_)
        except HTTPException as exc:
            return exc
        return None

    FAKES["manual"] = Fake([PollResult([ap("21", "aa:00:00:00:00:21", 2)])])
    mid = add_collector("manual")
    out = await manual(mid)
    check("it reports what it found", out == {"status": "ok", "access_points": 1, "clients": 2}, str(out))
    check("and stores it", len(q("SELECT id FROM access_points WHERE collector_id = ?", mid)) == 1
          and len(q("SELECT id FROM wifi_clients WHERE mac_address LIKE '02:00:00:21:%'")) == 2)
    check("and records the collector as ok", collector(mid)["status"] == "ok")

    FAKES["manual"] = Fake([PollResult([])])
    err = await manual_error(mid)
    check("an empty answer is refused, as a scheduled poll would", err is not None and err.status_code == 502,
          str(err))
    check("the stored access point survives it", len(q("SELECT id FROM access_points WHERE collector_id = ?", mid)) == 1)

    FAKES["manual"] = Fake([RuntimeError("boom")])
    err = await manual_error(mid)
    check("a failing controller is a 502 naming the failure",
          err is not None and err.status_code == 502 and "boom" in err.detail, str(err and err.detail))
    check("and is recorded on the collector", collector(mid)["status"] == "error" and "boom" in collector(mid)["last_error"])

    bad_cred = add_collector("badcred", config={"fake": "badcred", "credential_id": 9999})
    err = await manual_error(bad_cred)
    check("a missing credential is a 400", err is not None and err.status_code == 400, str(err))
    check("an unknown collector is a 404", (await manual_error(99999)).status_code == 404)

    engine = poll_engine.PollEngine()
    poll_engine.PollEngine._instance = engine
    engine._inflight.add(mid)
    err = await manual_error(mid)
    check("it will not run on top of a poll already in progress", err is not None and err.status_code == 409, str(err))
    engine._inflight.discard(mid)
    FAKES["manual"] = Fake([PollResult([ap("21", "aa:00:00:00:00:21", 2)])])
    await manual(mid)
    check("it releases its claim when done", mid not in engine._inflight)
    FAKES["manual"] = Fake([RuntimeError("boom")])
    await manual_error(mid)
    check("including when it fails", mid not in engine._inflight)
    poll_engine.PollEngine._instance = None

    print("\n── TLS verification default ──")
    check("a UniFi collector with no setting verifies the certificate",
          UnifiCollector({"controller_url": "https://x"}).verify_tls is True)
    check("one that turns it off keeps it off",
          UnifiCollector({"controller_url": "https://x", "verify_tls": False}).verify_tls is False)

    legacy = add_collector("legacy-unifi", "unifi", config={"controller_url": "https://x", "udm": True})
    explicit = add_collector("explicit-unifi", "unifi", config={"controller_url": "https://x", "verify_tls": True})
    other = add_collector("legacy-snmp", "snmp_generic", config={"host": "10.0.0.1"})
    garbled = add_collector("garbled-unifi", "unifi")
    conn = sqlite3.connect(str(DB))
    conn.execute("UPDATE collectors SET config_json = 'not-a-valid-token' WHERE id = ?", (garbled,))
    conn.execute("DELETE FROM _migrations WHERE filename = '999_pin_legacy_collector_tls.py'")
    conn.commit(); conn.close()
    await init_db()
    cfg = lambda i: crypto.decrypt_config(collector(i)["config_json"])      # noqa: E731
    check("a UniFi collector saved before the change is pinned to unverified", cfg(legacy).get("verify_tls") is False)
    check("its other settings are untouched", cfg(legacy).get("udm") is True)
    check("one that already chose is left alone", cfg(explicit).get("verify_tls") is True)
    check("non-UniFi collectors are not touched", "verify_tls" not in cfg(other))
    check("an unreadable config is never overwritten", collector(garbled)["config_json"] == "not-a-valid-token")
    before = collector(legacy)["config_json"]
    await init_db()
    check("it only runs once", collector(legacy)["config_json"] == before)

    print("\n── a credential key that no longer fits ──")
    records: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r.getMessage())             # type: ignore[method-assign]
    logging.getLogger("pktwifi.crypto").addHandler(handler)
    check("an undecryptable secret still reads as empty", crypto.decrypt_str("garbage") == "")
    check("and is logged", any("credential_key" in m for m in records), str(records))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
