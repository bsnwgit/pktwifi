"""
app/wifi/collectors/cisco_catalyst.py
----------------------------------------
STUB — Cisco Catalyst 9800 / legacy AireOS wireless LAN controllers are not
implemented as a dedicated collector yet.

Two viable paths, either is a reasonable v2 implementation:
  1. RESTCONF/YANG on the Catalyst 9800 (Cisco-IOS-XE-wireless-*-oper YANG
     models) for AP/radio/client state — no SNMP required, most complete data.
  2. SNMP against CISCO-LWAPP-AP-MIB / CISCO-LWAPP-DOT11-MIB /
     AIRESPACE-WIRELESS-MIB (legacy AireOS controllers) — the generic SNMP
     collector (snmp_generic.py) already has the plumbing for SNMP v2c/v3;
     this would mostly be adding vendor-specific OID walks and mapping them
     onto AccessPointReading/RadioReading, gated on collector_type so it
     doesn't affect the vendor-neutral collector's behavior.

See aruba_central.py's docstring for the general pattern to follow.
"""
from __future__ import annotations

from app.wifi.collectors.base import Collector, PollResult


class CiscoCatalystCollector(Collector):
    async def poll(self) -> PollResult:
        raise NotImplementedError(
            "The Cisco Catalyst/AireOS collector is not implemented yet — see the "
            "module docstring in app/wifi/collectors/cisco_catalyst.py for what's needed."
        )
