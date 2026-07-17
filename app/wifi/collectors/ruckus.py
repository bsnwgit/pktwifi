"""
app/wifi/collectors/ruckus.py
-------------------------------
STUB — Ruckus/CommScope (SmartZone controller or RuckusONE cloud) is not
implemented yet.

SmartZone exposes a documented REST API (session-token auth via
/wsg/api/public/v9_1/session, then /rkszones, /aps, /clients endpoints).
RuckusONE (cloud) uses OAuth2 client credentials against
https://api.ruckus.cloud. Either would slot into this file the same way
unifi.py wraps the UniFi controller API — see that file and base.py for the
shape a working collector needs to return.
"""
from __future__ import annotations

from app.wifi.collectors.base import Collector, PollResult


class RuckusCollector(Collector):
    async def poll(self) -> PollResult:
        raise NotImplementedError(
            "The Ruckus/SmartZone collector is not implemented yet — see the "
            "module docstring in app/wifi/collectors/ruckus.py for what's needed."
        )
