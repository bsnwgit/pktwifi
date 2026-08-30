"""
/api/settings/* — generic runtime settings key/value store.

Anything not covering startup/infra config (see app/config.py) lives here:
SAML config, alert/metrics retention windows, backup schedule, base_url
used to build the SAML ACS URL, etc. Frontend renders these on the
Settings page grouped by section.
"""
from __future__ import annotations

import json
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.alerts import notify
from app.database import get_db
from app.dependencies import CurrentUser, AdminUser

router = APIRouter()

# Sentinel written over an encrypted secret in GET responses. Sent back
# unchanged on save, it means "leave the stored value alone".
_MASK = "••••••••"

# Keys that must never be echoed back verbatim to non-admin callers.
#
# A webhook URL is not merely a destination — for Slack, TraceCat and most
# generic receivers, possession of the URL is the whole authorisation to post,
# so it belongs here alongside the tokens. The Settings UI already renders the
# Slack one as a secret field; GET /api/settings was handing the same value to
# any signed-in viewer in plaintext. notify_webhook_headers is here for the
# same reason: it is where an Authorization header for the receiver is kept.
_SECRET_KEYS = {
    "okta_saml_sp_key",
    "lucid_api_token",
    "notify_email_password",
    "notify_email_username",
    "notify_pagerduty_integration_key",
    "notify_slack_webhook_url",
    "notify_tracecat_api_token",
    "notify_tracecat_webhook_url",
    "notify_webhook_url",
    "notify_webhook_headers",
    "suite_token",
    "resonance_key",
}


# Credentials to another system, held the way the suite token and user API keys
# already are: Fernet at rest, not just masked on the way out. Masking alone
# protects the API response; it leaves the value readable to anything that can
# open the SQLite file.
_ENCRYPTED_KEYS = frozenset({
    "resonance_key",
})


def _store_value(key: str, value: Any) -> Any:
    """Encrypt on the way into the settings table, for keys that warrant it."""
    if key in _ENCRYPTED_KEYS and isinstance(value, str) and value:
        from app.wifi.collectors.crypto import encrypt_str
        return encrypt_str(value)
    return value


async def read_secret(db: aiosqlite.Connection, key: str) -> str:
    """Read and decrypt one _ENCRYPTED_KEYS setting for internal use.

    Returns "" when unset or undecryptable — a rotated credential key should
    read as "not configured" rather than raise on every request.
    """
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    if not row or not row[0]:
        return ""
    try:
        stored = json.loads(row[0])
    except (json.JSONDecodeError, TypeError, ValueError):
        stored = row[0]
    if not isinstance(stored, str) or not stored:
        return ""
    from app.wifi.collectors.crypto import decrypt_str
    return decrypt_str(stored)


class SettingsUpdate(BaseModel):
    values: dict


class TestNotificationRequest(BaseModel):
    channel: str


@router.get("")
async def get_settings(user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT key, value FROM settings") as cur:
        rows = await cur.fetchall()
    out = {}
    for r in rows:
        if r["key"] in _SECRET_KEYS and user["role"] != "admin":
            continue
        try:
            value = json.loads(r["value"])
        except (ValueError, TypeError):
            value = r["value"]
        # An encrypted value would come back as ciphertext and be saved
        # straight back re-encrypted. Mask it for everyone instead.
        if r["key"] in _ENCRYPTED_KEYS and value:
            value = _MASK
        out[r["key"]] = value
    return out


@router.put("")
async def update_settings(body: SettingsUpdate, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    for key, value in body.values.items():
        # The UI sends the mask back when a secret was not retyped.
        if key in _ENCRYPTED_KEYS and value == _MASK:
            continue
        value = _store_value(key, value)
        await db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value)),
        )
    await db.commit()
    return {"status": "ok"}


@router.post("/test-notification")
async def test_notification(
    body: TestNotificationRequest,
    _: AdminUser,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Send a test notification on the specified channel using saved settings.

    Goes through the same app/alerts/notify.py path a firing rule takes, so a
    passing test now means the channel will actually carry an alert. This
    endpoint used to hold its own copy of all five channels — the only copy
    that existed, since the engine never dispatched at all, which is exactly
    how a channel could test green and stay silent forever.
    """
    if body.channel not in notify.CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown channel: {body.channel}. Valid: {sorted(notify.CHANNELS)}",
        )

    alert = notify.AlertPayload(
        alert_name="pktWiFi Test",
        message="pktWiFi test notification — your configuration is working correctly.",
        severity="info",
    )
    result = await notify.send(db, body.channel, alert)
    return {"status": result.status, "detail": result.detail}
