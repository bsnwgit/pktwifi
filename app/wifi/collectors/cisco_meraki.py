"""
app/wifi/collectors/cisco_meraki.py
------------------------------------
Cisco Meraki cloud-managed WiFi collector — uses the Meraki Dashboard API v1
(https://developer.cisco.com/meraki/api-v1/).

Config shape:
{
  "api_key": "...",             # Dashboard > My Profile > API access
  "organization_id": "...",     # GET /organizations to find this
  "network_ids": ["..."]        # optional — restrict to specific networks; empty = all wireless networks in the org
}

NOTE: this integration has been written against the documented API v1 shape
but has not been exercised against a live Meraki organization in this build
session — field names for radio/channel/utilization data in particular
should be spot-checked against a real dashboard response and adjusted here
if Meraki's API has moved fields since. See README.md's Vendor Collectors
section.
"""
from __future__ import annotations

import logging

import httpx

from app.wifi.collectors.base import Collector, PollResult, AccessPointReading, RadioReading, ClientReading

log = logging.getLogger("pktwifi.collectors.meraki")

_BASE = "https://api.meraki.com/api/v1"


class CiscoMerakiCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.org_id = config.get("organization_id", "")
        self.network_ids = config.get("network_ids") or []

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def poll(self) -> PollResult:
        if not self.api_key or not self.org_id:
            raise ValueError("api_key and organization_id are required")

        result = PollResult()
        async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
            devices_resp = await client.get(f"{_BASE}/organizations/{self.org_id}/devices")
            devices_resp.raise_for_status()
            devices = [d for d in devices_resp.json() if d.get("productType") == "wireless" or (d.get("model") or "").startswith("MR")]

            if self.network_ids:
                devices = [d for d in devices if d.get("networkId") in self.network_ids]

            statuses_resp = await client.get(f"{_BASE}/organizations/{self.org_id}/devices/statuses")
            statuses_resp.raise_for_status()
            status_by_serial = {s["serial"]: s for s in statuses_resp.json()}

            for dev in devices:
                serial = dev["serial"]
                status = status_by_serial.get(serial, {})
                ap = AccessPointReading(
                    external_id=serial,
                    name=dev.get("name") or serial,
                    mac_address=dev.get("mac"),
                    ip_address=dev.get("lanIp"),
                    vendor="cisco-meraki",
                    model=dev.get("model"),
                    firmware_version=dev.get("firmware"),
                    site=dev.get("address"),
                    status="online" if status.get("status") == "online" else "offline",
                )

                try:
                    radio_resp = await client.get(f"{_BASE}/devices/{serial}/wireless/status")
                    radio_resp.raise_for_status()
                    radio_data = radio_resp.json()
                    for bss in radio_data.get("basicServiceSets", []):
                        band = bss.get("band", "unknown")
                        radio = RadioReading(
                            band=f"{band}GHz" if band and "GHz" not in str(band) else str(band),
                            channel=bss.get("channel"),
                            channel_width_mhz=bss.get("channelWidth"),
                            tx_power_dbm=bss.get("power"),
                        )
                        ap.radios.append(radio)
                except httpx.HTTPStatusError as exc:
                    log.debug(f"Meraki wireless/status unavailable for {serial}: {exc}")

                result.access_points.append(ap)

            # Client list per network (RSSI/SSID) — best-effort attach to nearest AP by band.
            network_ids = self.network_ids or list({d.get("networkId") for d in devices if d.get("networkId")})
            for net_id in network_ids:
                try:
                    clients_resp = await client.get(
                        f"{_BASE}/networks/{net_id}/clients", params={"timespan": 3600}
                    )
                    clients_resp.raise_for_status()
                    for c in clients_resp.json():
                        if not c.get("ssid"):
                            continue
                        ap = next((a for a in result.access_points if a.mac_address == c.get("recentDeviceMac")), None)
                        if not ap or not ap.radios:
                            continue
                        ap.radios[0].clients.append(ClientReading(
                            mac_address=c.get("mac", ""),
                            hostname=c.get("description"),
                            ip_address=c.get("ip"),
                            ssid=c.get("ssid"),
                        ))
                except httpx.HTTPStatusError as exc:
                    log.debug(f"Meraki clients unavailable for network {net_id}: {exc}")

        return result
