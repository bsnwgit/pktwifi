"""
app/wifi/oid_catalog.py
-----------------------
Reference catalog of SNMP OIDs the generic collector (app/wifi/collectors/
snmp_generic.py) knows how to poll: the standard IEEE 802.11 MIB
(IEEE8021-DOT11-MIB / IEEE802dot11-MIB, widely supported) plus a handful of
common enterprise vendor OIDs for channel/utilization/client-count where the
standard MIB doesn't cover it. This is informational/browsable in the UI
(Collectors -> OID Catalog) — the poller itself hardcodes the OIDs it walks;
this table documents what they mean.

Extending vendor coverage: add rows here for Aruba (WLSX-WLAN-MIB), Cisco
AireOS (AIRESPACE-WIRELESS-MIB / CISCO-LWAPP-* MIBs), or Ruckus (RUCKUS-*
MIB) as those integrations are built out — see
app/wifi/collectors/{aruba_central,cisco_catalyst,ruckus}.py for the current
stub state of each.
"""
from __future__ import annotations

import aiosqlite

# (oid, name, description, vendor, category, unit)
_CATALOG: list[tuple[str, str, str, str, str, str]] = [
    ("1.2.840.10036.1.1.1.6", "dot11StationID", "Station MAC address", "standard", "system", ""),
    ("1.2.840.10036.2.2.1.3", "dot11CurrentChannel", "Currently operating channel", "standard", "radio", "channel"),
    ("1.2.840.10036.2.3.1.2", "dot11CurrentTxAntenna", "Current transmit antenna", "standard", "radio", ""),
    ("1.2.840.10036.2.4.1.3", "dot11CurrentRTSThreshold", "RTS threshold", "standard", "radio", "bytes"),
    ("1.2.840.10036.4.1.1.2", "dot11PhyType", "Physical layer type (a/b/g/n/ac/ax)", "standard", "system", ""),
    ("1.2.840.10036.6.1.1.2", "dot11TransmittedFragmentCount", "Transmitted fragment count", "standard", "radio", "count"),
    ("1.2.840.10036.6.1.1.5", "dot11FailedCount", "Failed transmission count", "standard", "radio", "count"),
    ("1.2.840.10036.6.1.1.9", "dot11RetryCount", "Retried frame count", "standard", "radio", "count"),
    ("1.2.840.10036.6.1.1.14", "dot11FCSErrorCount", "FCS/CRC error count", "standard", "radio", "count"),
    # Common enterprise WLC/AP MIB extensions (naming varies by vendor —
    # values below are illustrative placeholders for the generic collector's
    # "best effort" mode; a real deployment should confirm the vendor's
    # actual enterprise OID tree via its MIB reference before relying on them).
    ("1.3.6.1.4.1.14179.2.2.2.1.15", "bsnAPIfLoad", "Cisco AireOS: radio channel utilization", "cisco", "radio", "percent"),
    ("1.3.6.1.4.1.14179.2.2.1.1.6", "bsnAPIfPhyChannelNumber", "Cisco AireOS: operating channel", "cisco", "radio", "channel"),
    ("1.3.6.1.4.1.14179.2.1.4.1.1", "bsnMobileStationRSSI", "Cisco AireOS: client RSSI", "cisco", "client", "dBm"),
    ("1.3.6.1.4.1.14179.2.1.4.1.2", "bsnMobileStationSnr", "Cisco AireOS: client SNR", "cisco", "client", "dB"),
]


async def seed_catalog(db: aiosqlite.Connection) -> None:
    """Idempotently insert the built-in OID catalog. Safe to call on every startup."""
    for oid, name, description, vendor, category, unit in _CATALOG:
        await db.execute(
            """INSERT OR IGNORE INTO wifi_oid_catalog (oid, name, description, vendor, category, unit)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (oid, name, description, vendor, category, unit),
        )
    await db.commit()
