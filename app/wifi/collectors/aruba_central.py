"""
app/wifi/collectors/aruba_central.py
--------------------------------------
STUB — HPE Aruba Networking (Aruba Central cloud, or on-prem MobilityMaster/
MobilityController) is not implemented yet.

To implement: Aruba Central uses OAuth2 (client credentials or refresh-token
flow) against https://app1-apigw.central.arubanetworks.com (region-specific
gateway), then REST endpoints under /monitoring/v1/aps and
/monitoring/v1/clients return AP and client state including per-radio
channel/utilization/noise and per-client RSSI/SNR. On-prem controllers
instead expose a session-cookie REST API (AOS-8) or a gRPC-based API
(AOS-10 / Aruba Central-managed hardware).

Follow the pattern in cisco_meraki.py / unifi.py: implement Collector.poll()
to return a PollResult built from AccessPointReading/RadioReading/
ClientReading (see base.py), register it in registry.py, and mark
"implemented": True there once it's been tested against a real Aruba
deployment.
"""
from __future__ import annotations

from app.wifi.collectors.base import Collector, PollResult


class ArubaCentralCollector(Collector):
    async def poll(self) -> PollResult:
        raise NotImplementedError(
            "The Aruba Central collector is not implemented yet — see the "
            "module docstring in app/wifi/collectors/aruba_central.py for what's needed."
        )
