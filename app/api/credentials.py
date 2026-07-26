"""
/api/credentials/* — the named controller-credential library (Settings ->
Credentials). Controllers reference an entry by id via a credential_select
field instead of carrying inline auth; app/wifi/poll_engine.resolve_credential
decrypts and merges the auth fields at poll time.

Secrets are Fernet-encrypted at rest and never returned: GET responses carry
only has_* flags, and an update that sends an empty/masked secret keeps the
stored value (same write-only convention as pktsnmp's SNMP credentials).
"""
from __future__ import annotations

import asyncio

import aiosqlite
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import CurrentUser, AdminUser
from app.wifi.collectors.crypto import encrypt_str, decrypt_config

router = APIRouter()

_MASK = "••••••••"

CRED_TYPES = ("userpass", "api_key", "snmp_v2c", "snmp_v3")


class CredentialRequest(BaseModel):
    name: str
    description: str = ""
    cred_type: str
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    community: str | None = None
    auth_protocol: str | None = None
    auth_password: str | None = None
    priv_protocol: str | None = None
    priv_password: str | None = None


def _out(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "description": r["description"],
        "cred_type": r["cred_type"], "username": r["username"],
        "auth_protocol": r["auth_protocol"], "priv_protocol": r["priv_protocol"],
        "has_password": bool(r["password_enc"]), "has_api_key": bool(r["api_key_enc"]),
        "has_community": bool(r["community_enc"]),
        "has_auth_password": bool(r["auth_password_enc"]), "has_priv_password": bool(r["priv_password_enc"]),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _secret(value: str | None) -> str | None:
    """Encrypt a submitted secret, treating empty/masked values as 'not provided'."""
    if not value or value == _MASK:
        return None
    return encrypt_str(value)


@router.get("")
async def list_credentials(user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM credentials ORDER BY name") as cur:
        rows = await cur.fetchall()
    return [_out(r) for r in rows]


@router.post("", status_code=201)
async def create_credential(body: CredentialRequest, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    if body.cred_type not in CRED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown cred_type '{body.cred_type}'")
    try:
        cur = await db.execute(
            """INSERT INTO credentials
                 (name, description, cred_type, username, password_enc, api_key_enc,
                  community_enc, auth_protocol, auth_password_enc, priv_protocol, priv_password_enc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING *""",
            (body.name, body.description, body.cred_type, body.username,
             _secret(body.password), _secret(body.api_key), _secret(body.community),
             body.auth_protocol, _secret(body.auth_password),
             body.priv_protocol, _secret(body.priv_password)),
        )
        row = await cur.fetchone()
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Credential name already exists")
    return _out(row)


@router.put("/{cred_id}")
async def update_credential(cred_id: int, body: CredentialRequest, user: AdminUser,
                            db: aiosqlite.Connection = Depends(get_db)):
    if body.cred_type not in CRED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown cred_type '{body.cred_type}'")
    async with db.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Credential not found")
    # Write-only secrets: an empty/masked submission keeps the stored ciphertext.
    updates = {
        "password_enc": _secret(body.password) or row["password_enc"],
        "api_key_enc": _secret(body.api_key) or row["api_key_enc"],
        "community_enc": _secret(body.community) or row["community_enc"],
        "auth_password_enc": _secret(body.auth_password) or row["auth_password_enc"],
        "priv_password_enc": _secret(body.priv_password) or row["priv_password_enc"],
    }
    try:
        await db.execute(
            """UPDATE credentials SET name=?, description=?, cred_type=?, username=?,
                 password_enc=?, api_key_enc=?, community_enc=?,
                 auth_protocol=?, auth_password_enc=?, priv_protocol=?, priv_password_enc=?,
                 updated_at=datetime('now') WHERE id=?""",
            (body.name, body.description, body.cred_type, body.username,
             updates["password_enc"], updates["api_key_enc"], updates["community_enc"],
             body.auth_protocol, updates["auth_password_enc"],
             body.priv_protocol, updates["priv_password_enc"], cred_id),
        )
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Credential name already exists")
    async with db.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)) as cur:
        row = await cur.fetchone()
    return _out(row)


class CredentialTestRequest(BaseModel):
    """Target for a live auth test — a credential alone has nothing to
    authenticate against, so the Test modal collects the minimal target per
    credential type (controller URL, vendor, or SNMP host)."""
    target_url: str | None = None   # userpass / api_key+unifi: controller URL
    vendor: str | None = None       # api_key: 'unifi' | 'meraki'
    udm: bool = False               # userpass: UniFi OS console (UDM/Cloud Gateway)
    verify_tls: bool = False
    host: str | None = None         # snmp_v2c/v3: device IP
    port: int = 161


def _exc_detail(exc: Exception) -> str:
    # Same convention as poll_now: some httpx exceptions have an empty str().
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


@router.post("/{cred_id}/test")
async def test_credential(cred_id: int, body: CredentialTestRequest, user: AdminUser,
                          db: aiosqlite.Connection = Depends(get_db)):
    """Attempt a real authentication with the stored (decrypted) secret against
    the caller-supplied target. Auth-only — nothing is persisted."""
    from app.wifi.poll_engine import resolve_credential
    async with db.execute("SELECT cred_type FROM credentials WHERE id = ?", (cred_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Credential not found")
    cred_type = row["cred_type"]
    resolved = await resolve_credential(db, {"credential_id": cred_id})

    try:
        if cred_type == "userpass":
            if not body.target_url:
                raise HTTPException(status_code=400, detail="Controller URL is required for a username/password test")
            base = body.target_url.rstrip("/")
            login_url = f"{base}/api/auth/login" if body.udm else f"{base}/api/login"
            async with httpx.AsyncClient(timeout=15, verify=body.verify_tls, follow_redirects=True) as client:
                resp = await client.post(login_url, json={
                    "username": resolved.get("username", ""), "password": resolved.get("password", ""),
                })
                if resp.status_code in (400, 401, 403):
                    raise ValueError(f"Authentication rejected (HTTP {resp.status_code}) — check username/password"
                                     + ("" if body.udm else "; if this is a UniFi OS console, enable the UDM toggle"))
                resp.raise_for_status()
            return {"ok": True, "detail": f"Authenticated to {base} as '{resolved.get('username')}'"}

        if cred_type == "api_key":
            if body.vendor == "meraki":
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get("https://api.meraki.com/api/v1/organizations",
                                            headers={"X-Cisco-Meraki-API-Key": resolved.get("api_key", "")})
                    if resp.status_code in (401, 403):
                        raise ValueError(f"API key rejected by Meraki Dashboard (HTTP {resp.status_code})")
                    resp.raise_for_status()
                    orgs = resp.json()
                return {"ok": True, "detail": f"Meraki Dashboard OK — {len(orgs)} organization(s) visible"}
            # default: UniFi Network Integration API
            if not body.target_url:
                raise HTTPException(status_code=400, detail="Console URL is required for a UniFi API-key test")
            base = body.target_url.rstrip("/")
            async with httpx.AsyncClient(timeout=15, verify=body.verify_tls, follow_redirects=True) as client:
                resp = await client.get(f"{base}/proxy/network/integration/v1/sites",
                                        headers={"X-API-KEY": resolved.get("api_key", ""), "Accept": "application/json"})
                if resp.status_code in (401, 403):
                    raise ValueError(f"API key rejected (HTTP {resp.status_code}) — check the key and that the "
                                     "Integration API is enabled under Settings -> Control Plane -> Integrations")
                resp.raise_for_status()
                sites = resp.json().get("data", [])
            return {"ok": True, "detail": f"UniFi Integration API OK — {len(sites)} site(s) visible"}

        # snmp_v2c / snmp_v3 — one sysDescr/sysUpTime GET via the generic collector's
        # own poll helper, so the test exercises exactly the code path a poll uses.
        if not body.host:
            raise HTTPException(status_code=400, detail="Host IP is required for an SNMP test")
        from app.wifi.collectors.snmp_generic import _poll_host_sync
        creds = dict(resolved)
        creds["port"] = body.port
        ap = await asyncio.to_thread(_poll_host_sync, {"ip": body.host}, creds)
        if ap.status != "online":
            raise ValueError("Device did not respond to SNMP — check host/port/credentials")
        return {"ok": True, "detail": f"SNMP {creds.get('version')} OK — {ap.model or 'device responded'}"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Test failed: {_exc_detail(exc)}")


@router.delete("/{cred_id}", status_code=204)
async def delete_credential(cred_id: int, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    # Controller configs are encrypted blobs, so usage can't be checked with
    # SQL — decrypt each config and look for a credential_id reference.
    used_by: list[str] = []
    async with db.execute("SELECT name, config_json FROM collectors") as cur:
        async for name, config_json in cur:
            # credential_id may be stored as int or numeric string depending on
            # how the form serialized it — compare loosely.
            if str(decrypt_config(config_json).get("credential_id") or "") == str(cred_id):
                used_by.append(name)
    if used_by:
        raise HTTPException(
            status_code=409,
            detail=f"Credential is used by controller(s): {', '.join(used_by)} — reassign them first",
        )
    async with db.execute("SELECT id FROM credentials WHERE id = ?", (cred_id,)) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Credential not found")
    await db.execute("DELETE FROM credentials WHERE id = ?", (cred_id,))
    await db.commit()
