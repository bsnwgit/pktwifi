"""
app/integrations/suite_client.py
----------------------------------
Base HTTP client for pktWiFi acting as a suite-token CLIENT of a sibling
pkt* app (pktsnmp, pktflow, pktlog, pktpcap). This is the mirror image of
app/api/suite.py (which is the INBOUND side — pktHub calling into pktWiFi).

Every pkt* app's get_current_user() dependency trusts three headers when
they're present and X-Suite-Token matches that app's own configured
suite_token:
  X-Suite-Token — the token copied from that app's Settings -> Integrations page
  X-Suite-User  — an identity string (shows up as the "user" in that app's audit trail)
  X-Suite-Role  — admin | analyst | viewer — mapped to that app's local roles

No login/JWT dance is needed — the token itself is the credential, same as
how pktHub proxies requests to every app it manages.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("pktwifi.integrations")


class SuiteClient:
    """
    suite_role is what the sibling app enforces its own permissions against, so
    it must be the role of the person whose request this is — not a constant.
    It used to default to "admin", which meant a pktWiFi viewer asking for
    pktLog syslogs or a pktIPAM lookup arrived there as an administrator, and
    the sibling's role check had nothing left to decide. It defaults to the
    least privilege instead; every caller passes the real role explicitly.

    suite_user is the identity the sibling records in its audit trail, so it
    takes the same treatment: "who at pktWiFi asked", not just "pktWiFi".
    """

    def __init__(self, base_url: str, suite_token: str, suite_user: str = "pktwifi",
                 suite_role: str = "viewer", verify_tls: bool = True):
        self.base_url = base_url.rstrip("/")
        self.suite_token = suite_token
        self.suite_user = suite_user
        self.suite_role = suite_role
        self.verify_tls = verify_tls

    def _headers(self) -> dict:
        return {
            "X-Suite-Token": self.suite_token,
            "X-Suite-User": self.suite_user,
            "X-Suite-Role": self.suite_role,
        }

    async def get(self, path: str, params: Optional[dict] = None) -> Any:
        # Every one of these requests carries the sibling's suite token in a
        # header, which is that app's whole credential. This was verify=False
        # unconditionally, so anything on the path could present a certificate
        # and collect it. On-prem siblings do often run a self-signed cert, so
        # the escape hatch stays — but per connection, set deliberately by an
        # admin, rather than as the behaviour of every call.
        async with httpx.AsyncClient(timeout=15, verify=self.verify_tls) as client:
            resp = await client.get(f"{self.base_url}{path}", headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json()

    async def health_check(self) -> tuple[bool, str]:
        """
        Full round trip: reach the host on the configured port AND prove the
        stored suite_token is actually accepted there. Hits /api/suite/whoami
        (authenticated), not the public /api/health — a wrong or revoked
        token must fail this test, not just an unreachable host.
        """
        try:
            data = await self.get("/api/suite/whoami")
            ok = bool(data.get("authenticated"))
            return ok, f"connected and authenticated as {data.get('role', 'unknown')}" if ok else f"unexpected response: {data}"
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                return False, "reachable, but suite token was rejected — check the token"
            return False, f"HTTP {exc.response.status_code}"
        except httpx.ConnectError as exc:
            # httpx wraps certificate failures in ConnectError, where they read
            # as a generic connection problem. Name it — the fix is a checkbox
            # on this form, and nothing else in the message points at it.
            if "certificate" in str(exc).lower() or "ssl" in str(exc).lower():
                return False, (f"TLS certificate was not trusted: {exc} — if this app uses a "
                               "self-signed certificate, untick 'Verify TLS certificate'")
            return False, f"could not connect to host/port: {exc}"
        except httpx.TimeoutException:
            return False, "connection timed out"
        except Exception as exc:
            return False, str(exc)
