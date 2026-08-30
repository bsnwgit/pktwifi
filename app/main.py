"""
pktWiFi — FastAPI application entry point.
"""
from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db, seed_admin
from app.version import get_version

# -- Routers -------------------------------------------------------------------
from app.api import (
    auth,
    users,
    settings as settings_router,
    system as system_router,
    devices as devices_router,
    clients as clients_router,
    metrics as metrics_router,
    alerts as alerts_router,
    logs as logs_router,
    collectors as collectors_router,
    credentials as credentials_router,
    integrations as integrations_router,
    suite as suite_router,
    user_api_keys as user_api_keys_router,
    ip_info as ip_info_router,
    mxtoolbox as mxtoolbox_router,
    sites as sites_router,
    widgets as widgets_router,
    nav as nav_router,
    docs as docs_router,
)
from app.api import resonance as resonance_router
from app.api import resonance_data as resonance_data_router

settings = get_settings()
log = logging.getLogger("pktwifi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # -- Startup ---------------------------------------------------------------
    from app.logging_handler import SQLiteLogHandler
    _log_handler = SQLiteLogHandler(db_path=settings.db_path)
    _log_handler.attach_to_root_logger("pktwifi")

    log.info("pktWiFi starting up")
    # Ship our own logs to pktLog if configured.
    try:
        import json as _json, logging as _logging
        import aiosqlite as _aio
        _fwd: dict = {}
        async with _aio.connect(settings.db_path) as _db:
            async with _db.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'log_forward_%'"
            ) as _cur:
                for _k, _v in await _cur.fetchall():
                    try:
                        _fwd[_k] = _json.loads(_v)
                    except Exception:
                        _fwd[_k] = _v
        if _fwd.get("log_forward_enabled"):
            from app.log_forward import configure_forwarding
            configure_forwarding(
                enabled=True,
                host=str(_fwd.get("log_forward_host") or ""),
                port=int(_fwd.get("log_forward_port") or 5514),
                protocol=str(_fwd.get("log_forward_protocol") or "udp"),
                level=getattr(_logging, str(_fwd.get("log_forward_level") or "INFO"), _logging.INFO),
                app_name=str(_fwd.get("log_forward_app_name") or "pktwifi"),
            )
    except Exception as _e:
        log.warning(f"Log forwarding setup skipped: {_e}")

    await init_db()
    log.info("Database migrations applied")

    await seed_admin()
    log.info("Admin seed check complete")

    from app.alerts.engine import AlertEngine
    engine = AlertEngine()
    await engine.start(settings.db_path)
    app.state.alert_engine = engine
    log.info("Alert engine started")

    from app.alerts.cleanup import AlertCleanup
    cleanup = AlertCleanup()
    await cleanup.start()
    log.info("Alert cleanup started")

    from app.backup import BackupScheduler
    backup_scheduler = BackupScheduler()
    await backup_scheduler.start()
    log.info("Backup scheduler started")

    from app.wifi.oid_catalog import seed_catalog
    import aiosqlite as _aiosqlite
    async with _aiosqlite.connect(settings.db_path) as _oid_db:
        await seed_catalog(_oid_db)
    log.info("WiFi OID catalog seeded")

    from app.wifi.poll_engine import PollEngine
    poll_engine = PollEngine(alert_engine=engine)
    await poll_engine.start(settings.db_path)
    app.state.poll_engine = poll_engine
    log.info("WiFi collector poll engine started")

    yield

    # -- Shutdown ----------------------------------------------------------------
    log.info("pktWiFi shutting down")
    await poll_engine.stop()
    await engine.stop()
    await cleanup.stop()
    await backup_scheduler.stop()
    _log_handler.stop()
    log.info("Shutdown complete")


# -- App -------------------------------------------------------------------------

app = FastAPI(
    title="pktWiFi",
    description="Enterprise WiFi Analyzer — access point, RF, and client visibility for the pkt suite",
    version=get_version(),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# -- Middleware --------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _decode_setting(raw):
    """
    Read one settings-table value. They are JSON-encoded, but rows written
    before that convention settled are bare strings — decode tolerantly, the
    same way app/config.py reads suite_token.
    """
    import json
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


# Paths that answer even while pktHub has this app locked. /api/suite/ is the
# one that must never be removed: it is the channel pktHub unlocks through, and
# without it a lock could only be lifted by editing the database by hand.
# /api/auth/ carries the hub's SSO bootstrap, and /api/resonance/ and
# /api/widgets/ are mounted by pages the hub itself renders — a blocked one of
# those reads as a broken feature rather than as Managed mode doing its job.
_LOCK_ALLOW_PREFIXES = (
    "/api/health", "/api/suite/", "/api/auth/", "/api/resonance/",
    "/api/widgets/", "/.well-known/", "/assets/",
)

# How long a lock outlives pktHub's last contact. pktHub polls health well
# inside this, so the only way to reach the expiry is for the hub to actually
# stop — at which point the lock releases rather than stranding this app behind
# a redirect to an address that no longer answers.
_LOCK_HEARTBEAT_MAX_AGE = 300  # seconds

# How often the heartbeat is actually written. It only has to stay inside
# _LOCK_HEARTBEAT_MAX_AGE, and pktHub proxies every user request through here —
# so writing on each one meant a write plus a commit per request, all of them
# contending for the same SQLite writer to record a fact that had not changed.
_LOCK_HEARTBEAT_WRITE_EVERY = 60  # seconds

# How long the lock state is trusted between reads. Unlocked is the normal
# state, and it used to cost an open/query/close of the database on the event
# loop for every single request just to re-learn it. A lock arriving from
# pktHub therefore takes effect within this window rather than instantly —
# except that POST /api/suite/direct-access calls invalidate_lock_cache()
# directly, so the path that actually sets one is immediate anyway.
_LOCK_STATE_TTL = 5.0  # seconds

_lock_state_cache: tuple | None = None   # (locked, redirect_to)
_lock_state_at: float = 0.0
_last_heartbeat_at: float = 0.0


def invalidate_lock_cache() -> None:
    """Drop the cached lock state, so the next request re-reads it."""
    global _lock_state_cache
    _lock_state_cache = None


async def _touch_heartbeat(db_path: str) -> None:
    """Record that pktHub has been in touch. Also called from /api/health."""
    import aiosqlite, json
    from datetime import datetime, timezone
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('lock_heartbeat_at', ?)",
            (json.dumps(datetime.now(timezone.utc).isoformat()),)
        )
        await db.commit()


async def _read_lock_state_applying_failsafe(db_path: str) -> tuple[bool, str]:
    """(locked, redirect_to) as stored, applying the heartbeat failsafe.

    Returns locked=False when the lock has outlived pktHub's last contact, and
    clears the stored flag so /api/health reports the release back to the hub.
    """
    import aiosqlite, json, logging
    from datetime import datetime, timezone

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT value FROM settings WHERE key='direct_ui_locked'") as cur:
            row = await cur.fetchone()
        # "is True", not bool(): a value that failed to decode comes back as the
        # raw text, and bool("false") is True.
        if not (row and _decode_setting(row[0]) is True):
            return False, ""

        async with db.execute("SELECT value FROM settings WHERE key='lock_heartbeat_at'") as cur:
            hrow = await cur.fetchone()
        beat = _decode_setting(hrow[0]) if hrow else None
        # No heartbeat at all counts as expired — a lock we cannot date is a
        # lock we cannot trust to still be wanted.
        expired = True
        if beat:
            try:
                last = datetime.fromisoformat(str(beat))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                expired = (datetime.now(timezone.utc) - last).total_seconds() > _LOCK_HEARTBEAT_MAX_AGE
            except ValueError:
                pass

        if expired:
            logging.getLogger("pktwifi.main").warning(
                "pktHub has not called in %ss — releasing the direct-access lock",
                _LOCK_HEARTBEAT_MAX_AGE,
            )
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('direct_ui_locked', ?)",
                (json.dumps(False),)
            )
            await db.commit()
            return False, ""

        async with db.execute("SELECT value FROM settings WHERE key='hub_redirect_url'") as cur:
            rrow = await cur.fetchone()
        # No target means nowhere to send anyone — the caller serves the app
        # rather than bouncing users to a blank address.
        return True, (str(_decode_setting(rrow[0]) or "") if rrow else "")


@app.middleware("http")
async def _direct_access_lock(request: Request, call_next):
    """Send users to pktHub while it has this app in Managed mode.

    Failure here is deliberately silent: any error reading the lock falls
    through to serving the request. A bug in this middleware must not be able
    to take the app off the network, and the lock is a convenience for hub
    operators rather than a security boundary — every route keeps its own auth.
    """
    import logging
    import secrets as _sec
    from time import monotonic

    global _lock_state_cache, _lock_state_at, _last_heartbeat_at

    path = request.url.path
    if any(path == p or path.startswith(p) for p in _LOCK_ALLOW_PREFIXES):
        return await call_next(request)

    redirect_to = ""
    try:
        cfg = get_settings()
        now = monotonic()

        presented = request.headers.get("x-suite-token", "")
        stored    = (cfg.suite_token or "").strip()

        if presented and stored and _sec.compare_digest(presented, stored):
            # pktHub itself, or a user it is proxying — never redirected, and
            # its arrival is what keeps the lock alive. Nothing to read.
            if now - _last_heartbeat_at >= _LOCK_HEARTBEAT_WRITE_EVERY:
                await _touch_heartbeat(cfg.db_path)
                _last_heartbeat_at = now
            return await call_next(request)

        if _lock_state_cache is None or (now - _lock_state_at) >= _LOCK_STATE_TTL:
            _lock_state_cache = await _read_lock_state_applying_failsafe(cfg.db_path)
            _lock_state_at = now

        locked, target = _lock_state_cache
        if locked:
            redirect_to = target
    except Exception:
        logging.getLogger("pktwifi.main").exception("direct-access lock check failed")

    if redirect_to:
        return RedirectResponse(url=redirect_to, status_code=302)
    return await call_next(request)

# -- API Routers -----------------------------------------------------------------

app.include_router(auth.router,             prefix="/api/auth",         tags=["auth"])
app.include_router(users.router,            prefix="/api/users",        tags=["users"])
app.include_router(devices_router.router,   prefix="/api/devices",      tags=["devices"])
app.include_router(clients_router.router,   prefix="/api/clients",      tags=["clients"])
app.include_router(metrics_router.router,   prefix="/api/metrics",      tags=["metrics"])
app.include_router(alerts_router.router,    prefix="/api/alerts",       tags=["alerts"])
app.include_router(logs_router.router,      prefix="/api/logs",         tags=["logs"])
app.include_router(collectors_router.router, prefix="/api/collectors", tags=["collectors"])
app.include_router(credentials_router.router, prefix="/api/credentials", tags=["credentials"])
app.include_router(sites_router.router,      prefix="/api/sites",        tags=["sites"])
app.include_router(integrations_router.router, prefix="/api/integrations", tags=["integrations"])
app.include_router(settings_router.router,  prefix="/api/settings",     tags=["settings"])
app.include_router(system_router.router,    prefix="/api/system",       tags=["system"])
app.include_router(suite_router.router,     prefix="/api/suite",        tags=["suite"])
app.include_router(user_api_keys_router.router, prefix="/api/user-api-keys", tags=["user-api-keys"])
app.include_router(ip_info_router.router,   prefix="/api/ip-info",      tags=["ip-info"])
app.include_router(mxtoolbox_router.router, prefix="/api/mxtoolbox",    tags=["mxtoolbox"])
app.include_router(widgets_router.router,    prefix="/api/widgets",      tags=["widgets"])
app.include_router(nav_router.router,        prefix="/api/nav",          tags=["nav"])
app.include_router(docs_router.router,       prefix="/api/docs-content", tags=["docs"])
app.include_router(resonance_router.router,  prefix="/api/resonance",    tags=["resonance"])
# The assistant's data surface. Carries its own absolute paths — /api/resonance/data/*
# plus the two documents at /api/resonance/openapi.json and /.well-known/resonance.json —
# so it is mounted without a prefix, and before the SPA catch-all so the grant file wins
# over it.
app.include_router(resonance_data_router.router)
resonance_data_router.register_error_handler(app)
resonance_data_router.validate_grants(app)

# -- Health check ------------------------------------------------------------------

@app.get("/api/health", tags=["system"])
async def health(request: Request):
    """
    Also reports Managed-mode state. pktHub reads direct_ui_locked on every poll
    and flips its own record back to Direct when this app says it is unlocked,
    so the hub cannot go on showing a lock that the failsafe has released.

    The poll doubles as the lock's heartbeat — this request is the evidence that
    pktHub is still alive, which is why it answers even while locked.

    hub_redirect_url is deliberately not reported here. pktHub reads it from the
    token-authenticated /api/suite/direct-access, and this endpoint is public —
    an unlocked app has no reason to publish the hub's address to every caller.
    """
    import aiosqlite, logging
    import secrets as _sec
    from time import monotonic

    global _last_heartbeat_at

    locked = False
    try:
        cfg = get_settings()
        presented = request.headers.get("x-suite-token", "")
        stored    = (cfg.suite_token or "").strip()
        if presented and stored and _sec.compare_digest(presented, stored):
            # Same interval the middleware uses — the heartbeat only has to stay
            # inside _LOCK_HEARTBEAT_MAX_AGE, and pktHub polls this frequently.
            now = monotonic()
            if now - _last_heartbeat_at >= _LOCK_HEARTBEAT_WRITE_EVERY:
                await _touch_heartbeat(cfg.db_path)
                _last_heartbeat_at = now

        # The flag as stored, not the middleware's cached view: this is what
        # pktHub reads to reconcile its own record, so it must be current — and
        # it must not apply the failsafe's release, which is the middleware's to
        # decide on a real request.
        async with aiosqlite.connect(cfg.db_path) as db:
            async with db.execute("SELECT value FROM settings WHERE key='direct_ui_locked'") as cur:
                row = await cur.fetchone()
        locked = (_decode_setting(row[0]) is True) if row else False
    except Exception:
        logging.getLogger("pktwifi.main").exception("health lock state read failed")

    return {"status": "ok", "version": get_version(), "direct_ui_locked": locked}

# -- Serve React frontend (production build) ---------------------------------------
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(request: Request, full_path: str):
        # /api/ and /.well-known/ are answered by real routes or not at all.
        # Falling through to index.html gave a 200 of HTML to anything asking
        # for a well-known document — resonance reading
        # /.well-known/resonance.json on an install that publishes none got a
        # page instead of an honest 404.
        if full_path.startswith("api/") or full_path.startswith(".well-known/"):
            raise HTTPException(status_code=404, detail="Not found")
        # Normalize-then-prefix-check (CodeQL's own documented pattern for
        # py/path-injection) rather than pathlib's resolve()/is_relative_to,
        # which its Python taint tracker doesn't recognise as a sanitizer.
        _dist_root = os.path.normpath(str(_frontend_dist))
        _candidate = os.path.normpath(os.path.join(_dist_root, full_path))
        if not (_candidate == _dist_root or _candidate.startswith(_dist_root + os.sep)):
            # Path traversal — this handler is unauthenticated and config.yaml
            # sits two levels above dist, so "../../config.yaml" previously
            # returned the JWT signing key and the credential encryption key.
            raise HTTPException(status_code=404, detail="Not found")
        static_file = Path(_candidate)
        if static_file.exists() and static_file.is_file():
            return FileResponse(str(static_file))
        index = _frontend_dist / "index.html"
        # index.html names the hashed bundles, so a cached copy pins the browser
        # to whatever build was current when it was cached — a deploy lands on
        # the server and the person reloading sees no change, with nothing in
        # the network log to explain it because the request never leaves the
        # browser. Vite fingerprints everything under /assets, so only this one
        # file must never be cached; the bundles it points at still can be.
        response = FileResponse(
            str(index),
            headers={"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"},
        )
        # pktHub suite-token bootstrap — set sso cookies so React logs in automatically
        import secrets as _secrets
        # get_settings(), not the module-level `settings`: a token regenerated
        # since startup must be the one this compares against.
        _cfg = get_settings()
        _suite_tk = request.headers.get("x-suite-token", "")
        _stored   = (_cfg.suite_token or "").strip()
        # compare_digest, matching the middleware and /api/health — this decides
        # whether to mint a signed session, so it is exactly the comparison that
        # should not leak its answer through timing.
        if _suite_tk and _stored and _secrets.compare_digest(_suite_tk, _stored):
            from datetime import datetime, timedelta, timezone
            from jose import jwt as _jose_jwt
            from app.dependencies import _SUITE_ROLE_MAP, cookie_secure
            _hub_user = request.headers.get("x-suite-user", "hub_user")
            _hub_role = request.headers.get("x-suite-role", "viewer")
            _local_role = _SUITE_ROLE_MAP.get(_hub_role, "viewer")
            _expire = datetime.now(tz=timezone.utc) + timedelta(hours=8)
            _payload = {"sub": "0", "role": _local_role, "exp": _expire, "type": "access"}
            _jwt = _jose_jwt.encode(_payload, _cfg.secret_key, algorithm=_cfg.algorithm)
            _secure = cookie_secure(request)
            response.set_cookie("sso_access_token", _jwt,       max_age=60, httponly=False, samesite="lax", secure=_secure)
            response.set_cookie("sso_role",         _local_role, max_age=60, httponly=False, samesite="lax", secure=_secure)
        return response


# -- Entrypoint (used by systemd: python -m app.main) -----------------------------
if __name__ == "__main__":
    import json
    import sqlite3
    import uvicorn

    _db_path = Path(__file__).parent.parent / "pktwifi.db"
    _ssl_enabled  = False
    _ssl_certfile = None
    _ssl_keyfile  = None
    try:
        _conn = sqlite3.connect(str(_db_path))
        for _key in ("ssl_enabled", "ssl_certfile", "ssl_keyfile"):
            _row = _conn.execute("SELECT value FROM settings WHERE key=?", (_key,)).fetchone()
            if _row:
                _val = json.loads(_row[0])
                if _key == "ssl_enabled":
                    _ssl_enabled = bool(_val)
                elif _key == "ssl_certfile":
                    _ssl_certfile = _val if _val else None
                elif _key == "ssl_keyfile":
                    _ssl_keyfile = _val if _val else None
        _conn.close()
    except Exception as _e:
        log.warning(f"Could not read SSL settings from config DB: {_e}")

    _bind_port = settings.https_port if _ssl_enabled else settings.port

    _uvicorn_kwargs = dict(
        host=settings.host,
        port=_bind_port,
        log_level=settings.log_level.lower(),
        workers=1,
    )

    _ssl_dir = Path(settings.ssl_dir)
    if not _ssl_certfile and (_ssl_dir / "server.crt").exists():
        _ssl_certfile = str(_ssl_dir / "server.crt")
    if not _ssl_keyfile and (_ssl_dir / "server.key").exists():
        _ssl_keyfile = str(_ssl_dir / "server.key")

    if _ssl_enabled and _ssl_certfile and _ssl_keyfile:
        _uvicorn_kwargs["ssl_certfile"] = _ssl_certfile
        _uvicorn_kwargs["ssl_keyfile"]  = _ssl_keyfile
        log.info(f"Starting with HTTPS on port {_bind_port}: cert={_ssl_certfile}")
    else:
        log.info(f"Starting with HTTP on port {_bind_port} (no SSL configured)")

    uvicorn.run("app.main:app", **_uvicorn_kwargs)
