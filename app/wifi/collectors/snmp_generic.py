"""
app/wifi/collectors/snmp_generic.py
------------------------------------
Vendor-neutral SNMP collector. Polls a fixed list of AP/controller IPs using
the standard IEEE 802.11 MIB (see app/wifi/oid_catalog.py) plus sysUpTime
for reachability, on the theory that a "works everywhere" collector can only
rely on what's actually standardized — vendor-specific RF detail (accurate
per-radio channel utilization, tx power, multi-band awareness) needs one of
the vendor-native collectors (cisco_meraki.py, unifi.py, and the
aruba_central.py / cisco_catalyst.py / ruckus.py stubs) instead.

Config shape:
{
  "version": "v2c" | "v3",
  "community": "...",                 # v2c
  "username": "...",                  # v3
  "auth_protocol": "SHA" | "MD5", "auth_password": "...",
  "priv_protocol": "AES" | "DES", "priv_password": "...",
  "port": 161,
  "hosts": [{"ip": "10.0.0.5", "name": "ap-lobby-1", "site": "HQ", "floor": "1"}, ...]
}
"""
from __future__ import annotations

import asyncio
import logging

from app.wifi.collectors.base import Collector, PollResult, AccessPointReading, RadioReading

log = logging.getLogger("pktwifi.collectors.snmp_generic")

_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
# dot11CurrentChannel table (one row per radio ifIndex)
_DOT11_CHANNEL = "1.2.840.10036.2.2.1.3"


def _poll_host_sync(host: dict, creds: dict) -> AccessPointReading:
    """Runs in a worker thread — pysnmp's classic hlapi is synchronous."""
    from pysnmp.hlapi import (
        SnmpEngine, CommunityData, UsmUserData, UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity, getCmd, nextCmd,
        usmHMACSHAAuthProtocol, usmHMACMD5AuthProtocol,
        usmAesCfb128Protocol, usmDESPrivProtocol,
    )

    ip = host["ip"]
    port = int(creds.get("port") or 161)

    if creds.get("version") == "v3":
        auth_proto = usmHMACSHAAuthProtocol if creds.get("auth_protocol", "SHA") == "SHA" else usmHMACMD5AuthProtocol
        priv_proto = usmAesCfb128Protocol if creds.get("priv_protocol", "AES") == "AES" else usmDESPrivProtocol
        auth_data = UsmUserData(
            creds.get("username", ""),
            authKey=creds.get("auth_password") or None,
            privKey=creds.get("priv_password") or None,
            authProtocol=auth_proto,
            privProtocol=priv_proto,
        )
    else:
        auth_data = CommunityData(creds.get("community", "public"), mpModel=1)

    engine = SnmpEngine()
    transport = UdpTransportTarget((ip, port), timeout=3, retries=1)

    ap = AccessPointReading(
        external_id=ip, name=host.get("name") or ip, ip_address=ip,
        vendor="generic-snmp", site=host.get("site"), floor=host.get("floor"),
        status="offline",
    )

    try:
        for err_indication, err_status, _err_index, var_binds in getCmd(
            engine, auth_data, transport, ContextData(),
            ObjectType(ObjectIdentity(_SYS_UPTIME)),
            ObjectType(ObjectIdentity(_SYS_DESCR)),
        ):
            if err_indication or err_status:
                raise RuntimeError(str(err_indication or err_status.prettyPrint()))
            uptime_ticks = int(var_binds[0][1])
            ap.uptime_seconds = uptime_ticks // 100
            descr = str(var_binds[1][1])
            ap.model = descr[:120]
            ap.status = "online"
            break
    finally:
        engine.transportDispatcher.closeDispatcher()

    # Best-effort: walk the dot11 channel table if the device exposes it.
    # Not all AP firmware supports this MIB, so failures here are non-fatal —
    # the AP still reports "online" from the sysUpTime probe above.
    radio = RadioReading(band="unknown")
    try:
        engine2 = SnmpEngine()
        for err_indication, err_status, _err_index, var_binds in nextCmd(
            engine2, auth_data, transport, ContextData(),
            ObjectType(ObjectIdentity(_DOT11_CHANNEL)),
            lexicographicMode=False,
        ):
            if err_indication or err_status:
                break
            for _oid, value in var_binds:
                radio.channel = int(value)
            break
        engine2.transportDispatcher.closeDispatcher()
    except Exception as exc:
        log.debug(f"{ip}: dot11 channel walk unavailable: {exc}")

    if radio.channel is not None:
        ap.radios.append(radio)

    return ap


class SnmpGenericCollector(Collector):
    async def poll(self) -> PollResult:
        hosts = self.config.get("hosts") or []
        if not hosts:
            raise ValueError("No hosts configured for this SNMP collector")

        access_points = await asyncio.gather(
            *[asyncio.to_thread(_poll_host_sync, host, self.config) for host in hosts],
            return_exceptions=True,
        )

        result = PollResult()
        for ap in access_points:
            if isinstance(ap, Exception):
                log.warning(f"SNMP poll failed for a host: {ap}")
                continue
            result.access_points.append(ap)
        return result
