"""
app/alerts/notify.py
--------------------
Outbound alert notification — Slack, Email/SMTP, PagerDuty, generic Webhook
and TraceCat SOAR.

One implementation, two callers: the alert engine when a rule fires, and
Settings -> Notifications' "Send Test" button. They were never going to stay
in step as two copies — and for most of this app's life there was only the
test one, which is why a configured channel could pass its test and still
never carry a real alert.

Channel config lives in the settings table (`notify_*` keys, written by
/api/settings). Which channels a given rule uses lives on the rule itself
(`alert_rules.channels`), so enabling a channel here only makes it available,
exactly as the admin guide has always described it.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

log = logging.getLogger("pktwifi.alerts.notify")

CHANNELS = ("slack", "email", "pagerduty", "webhook", "tracecat")

# A channel that cannot be reached must not hold up the evaluation pass — the
# engine dispatches inside its 30-second loop, and five channels each waiting
# out a TCP timeout would outlast it.
_TIMEOUT = 10


@dataclass
class AlertPayload:
    """What every channel renders. Field names match the Jinja variables the
    webhook template documents (alert_name/message/severity/fired_at)."""

    alert_name: str
    message: str
    severity: str = "warning"
    fired_at: str = ""
    event_id: int = 0

    def __post_init__(self) -> None:
        if not self.fired_at:
            self.fired_at = datetime.now(tz=timezone.utc).isoformat()


@dataclass
class Delivery:
    """Outcome of one channel attempt. `status` is one of sent | skipped |
    failed — skipped meaning the channel is off or unconfigured, which is not
    an error and must not read as one."""

    channel: str
    status: str
    detail: str = ""


async def _get(db: aiosqlite.Connection, key: str):
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    if not row or row[0] is None:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError, ValueError):
        return row[0]


# ── Channels ──────────────────────────────────────────────────────────────────
# Each returns a Delivery and raises nothing the caller has to handle — send()
# below is the single place that turns an exception into a failed Delivery.


async def _send_slack(db: aiosqlite.Connection, alert: AlertPayload) -> Delivery:
    if not await _get(db, "notify_slack_enabled"):
        return Delivery("slack", "skipped", "Slack is not enabled")
    url = await _get(db, "notify_slack_webhook_url") or ""
    if not url:
        return Delivery("slack", "skipped", "No webhook URL configured")

    import httpx
    icon = {"critical": ":red_circle:", "warning": ":large_orange_circle:"}.get(alert.severity, ":white_circle:")
    payload = {"text": f"{icon} *pktWiFi — {alert.alert_name}*\n{alert.message}"}
    channel_override = await _get(db, "notify_slack_channel") or ""
    if channel_override:
        payload["channel"] = channel_override

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=_TIMEOUT)
    if resp.status_code == 200:
        return Delivery("slack", "sent", "Slack message delivered")
    return Delivery("slack", "failed", f"Slack returned HTTP {resp.status_code}: {resp.text[:200]}")


async def _send_email(db: aiosqlite.Connection, alert: AlertPayload) -> Delivery:
    if not await _get(db, "notify_email_enabled"):
        return Delivery("email", "skipped", "Email is not enabled")

    host      = await _get(db, "notify_email_smtp_host")   or ""
    port      = await _get(db, "notify_email_smtp_port")   or 587
    tls       = await _get(db, "notify_email_smtp_tls")
    use_tls   = tls if tls is not None else True
    username  = await _get(db, "notify_email_username")    or ""
    password  = await _get(db, "notify_email_password")    or ""
    from_addr = await _get(db, "notify_email_from")        or "pktwifi@localhost"
    to_addrs  = await _get(db, "notify_email_default_to")  or []
    if not host or not to_addrs:
        return Delivery("email", "skipped", "SMTP host or recipient list not configured")

    import aiosmtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[pktWiFi {alert.severity}] {alert.alert_name}"
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to_addrs)
    msg.attach(MIMEText(
        f"pktWiFi Alert — {alert.alert_name}\n\n{alert.message}\n\n"
        f"Severity: {alert.severity}\nFired at: {alert.fired_at}\n", "plain"
    ))
    await aiosmtplib.send(
        msg,
        hostname=host, port=int(port), use_tls=bool(use_tls),
        username=username or None, password=password or None,
    )
    return Delivery("email", "sent", f"Email sent to {', '.join(to_addrs)}")


async def _send_pagerduty(db: aiosqlite.Connection, alert: AlertPayload) -> Delivery:
    if not await _get(db, "notify_pagerduty_enabled"):
        return Delivery("pagerduty", "skipped", "PagerDuty is not enabled")
    key = await _get(db, "notify_pagerduty_integration_key") or ""
    if not key:
        return Delivery("pagerduty", "skipped", "No integration key configured")

    import httpx
    # PagerDuty's own vocabulary, which is not ours: it has no "warning".
    pd_severity = {"critical": "critical", "warning": "warning", "info": "info"}.get(alert.severity, "warning")
    payload = {
        "routing_key": key,
        "event_action": "trigger",
        # Same key for the same rule+target means PagerDuty updates the open
        # incident instead of opening a second one every evaluation pass.
        "dedup_key": f"pktwifi-{alert.event_id}" if alert.event_id else None,
        "payload": {
            "summary": f"[pktWiFi] {alert.alert_name}: {alert.message}",
            "severity": pd_severity,
            "source": "pktwifi",
        },
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://events.pagerduty.com/v2/enqueue", json=payload, timeout=_TIMEOUT)
    if resp.status_code in (200, 202):
        return Delivery("pagerduty", "sent", "PagerDuty event triggered")
    return Delivery("pagerduty", "failed", f"PagerDuty returned HTTP {resp.status_code}: {resp.text[:200]}")


async def _send_webhook(db: aiosqlite.Connection, alert: AlertPayload) -> Delivery:
    if not await _get(db, "notify_webhook_enabled"):
        return Delivery("webhook", "skipped", "Webhook is not enabled")
    url      = await _get(db, "notify_webhook_url")              or ""
    method   = await _get(db, "notify_webhook_method")           or "POST"
    template = await _get(db, "notify_webhook_payload_template") or ""
    headers  = await _get(db, "notify_webhook_headers")          or {}
    if not url:
        return Delivery("webhook", "skipped", "No webhook URL configured")

    # SandboxedEnvironment, not bare Template: this string is admin-supplied and
    # renders in-process, so an unsandboxed Jinja environment hands anyone who
    # can edit settings a path to attribute access on live objects.
    from jinja2.sandbox import SandboxedEnvironment
    try:
        rendered = SandboxedEnvironment(autoescape=False).from_string(template).render(
            alert_name=alert.alert_name, message=alert.message,
            severity=alert.severity, fired_at=alert.fired_at,
        )
        body_json = json.loads(rendered)
    except Exception as exc:
        return Delivery("webhook", "failed", f"Template render error: {exc}")

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.request(method.upper(), url, json=body_json, headers=headers, timeout=_TIMEOUT)
    if resp.status_code < 300:
        return Delivery("webhook", "sent", f"Webhook returned HTTP {resp.status_code}")
    return Delivery("webhook", "failed", f"Webhook returned HTTP {resp.status_code}: {resp.text[:200]}")


async def _send_tracecat(db: aiosqlite.Connection, alert: AlertPayload) -> Delivery:
    if not await _get(db, "notify_tracecat_enabled"):
        return Delivery("tracecat", "skipped", "TraceCat is not enabled")
    webhook_url = await _get(db, "notify_tracecat_webhook_url") or ""
    api_token   = await _get(db, "notify_tracecat_api_token")   or ""
    if not webhook_url:
        return Delivery("tracecat", "skipped", "No webhook URL configured")

    import httpx
    payload = {
        "source": "pktwifi",
        "event_id": alert.event_id,
        "alert_name": alert.alert_name,
        "severity": alert.severity,
        "message": alert.message,
        "fired_at": alert.fired_at,
        "details": {},
    }
    headers: dict = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json=payload, headers=headers, timeout=_TIMEOUT)
    if resp.status_code < 300:
        return Delivery("tracecat", "sent", f"TraceCat webhook returned HTTP {resp.status_code}")
    return Delivery("tracecat", "failed", f"TraceCat returned HTTP {resp.status_code}: {resp.text[:200]}")


_SENDERS = {
    "slack":     _send_slack,
    "email":     _send_email,
    "pagerduty": _send_pagerduty,
    "webhook":   _send_webhook,
    "tracecat":  _send_tracecat,
}


# ── Dispatch ──────────────────────────────────────────────────────────────────


async def send(db: aiosqlite.Connection, channel: str, alert: AlertPayload) -> Delivery:
    """Deliver one alert on one channel. Never raises: a channel that is down
    is a delivery failure to be reported and logged, not a reason to abandon
    the evaluation pass that produced the alert."""
    sender = _SENDERS.get(channel)
    if sender is None:
        return Delivery(channel, "failed", f"Unknown channel: {channel}")
    try:
        return await sender(db, alert)
    except Exception as exc:
        # The exception text can carry the SMTP host, the webhook URL and
        # occasionally the credential itself — log it, and hand back something
        # an operator can act on without it.
        log.exception("alert dispatch failed on %s", channel)
        return Delivery(channel, "failed", f"{type(exc).__name__} — see the app log for detail")


async def dispatch(db: aiosqlite.Connection, channels, alert: AlertPayload) -> list[Delivery]:
    """Deliver one alert across every channel a rule selected, concurrently.

    Concurrent because these are independent network calls on the engine's own
    30-second loop: run in sequence, five slow channels serialise into longer
    than the interval that scheduled them.
    """
    wanted = [c for c in (channels or []) if c in _SENDERS]
    if not wanted:
        return []

    results = await asyncio.gather(*(send(db, c, alert) for c in wanted))
    for d in results:
        if d.status == "failed":
            log.warning("alert '%s' not delivered on %s: %s", alert.alert_name, d.channel, d.detail)
        elif d.status == "sent":
            log.info("alert '%s' delivered on %s", alert.alert_name, d.channel)
    return list(results)
