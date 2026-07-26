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

import aiosqlite
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
