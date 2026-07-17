"""
app/wifi/collectors/unifi.py
-----------------------------
Ubiquiti UniFi Network Controller collector — uses the classic controller
REST API (/api/s/<site>/stat/device and /api/s/<site>/stat/sta), which works
against both a standalone UniFi Network Application and a UDM/UDM-Pro
("unifi OS" console, where every path is proxied under /proxy/network).

Config shape:
{
  "controller_url": "https://10.0.0.1",   # no trailing slash
  "username": "...", "password": "...",
  "site": "default",
  "udm": false,          # true if this is a UDM/UDM-Pro/Cloud Key Gen2+ console
  "verify_tls": false    # most on-prem controllers use a self-signed cert
}
"""
from __future__ import annotations

import logging

import httpx

from app.wifi.collectors.base import Collector, PollResult, AccessPointReading, RadioReading, ClientReading

log = logging.getLogger("pktwifi.collectors.unifi")


class UnifiCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.base = (config.get("controller_url") or "").rstrip("/")
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.site = config.get("site", "default")
        self.udm = bool(config.get("udm", False))
        self.verify_tls = bool(config.get("verify_tls", False))

    def _api_prefix(self) -> str:
        return f"{self.base}/proxy/network/api" if self.udm else f"{self.base}/api"

    def _login_path(self) -> str:
        return f"{self.base}/api/auth/login" if self.udm else f"{self.base}/api/login"

    async def poll(self) -> PollResult:
        if not self.base or not self.username:
            raise ValueError("controller_url and username are required")

        async with httpx.AsyncClient(timeout=20, verify=self.verify_tls) as client:
            login_resp = await client.post(
                self._login_path(), json={"username": self.username, "password": self.password}
            )
            login_resp.raise_for_status()

            prefix = self._api_prefix()

            devices_resp = await client.get(f"{prefix}/s/{self.site}/stat/device")
            devices_resp.raise_for_status()
            devices = devices_resp.json().get("data", [])

            clients_resp = await client.get(f"{prefix}/s/{self.site}/stat/sta")
            clients_resp.raise_for_status()
            clients = clients_resp.json().get("data", [])

        result = PollResult()
        radios_by_mac: dict[str, dict[str, RadioReading]] = {}

        for dev in devices:
            if dev.get("type") != "uap":
                continue
            mac = dev.get("mac", "")
            ap = AccessPointReading(
                external_id=dev.get("_id") or mac,
                name=dev.get("name") or mac,
                mac_address=mac,
                ip_address=dev.get("ip"),
                vendor="ubiquiti-unifi",
                model=dev.get("model"),
                firmware_version=dev.get("version"),
                status="online" if dev.get("state") == 1 else "offline",
                uptime_seconds=dev.get("uptime"),
            )
            band_radios: dict[str, RadioReading] = {}
            for radio in dev.get("radio_table_stats", dev.get("radio_table", [])):
                radio_name = radio.get("radio", "")
                band = "2.4GHz" if radio_name == "ng" else ("6GHz" if radio_name == "6e" else "5GHz")
                r = RadioReading(
                    band=band,
                    channel=radio.get("channel"),
                    channel_width_mhz=radio.get("ht"),
                    tx_power_dbm=radio.get("tx_power"),
                    utilization_pct=radio.get("cu_total"),
                    noise_floor_dbm=radio.get("noise"),
                )
                ap.radios.append(r)
                band_radios[radio_name] = r
            radios_by_mac[mac] = band_radios
            result.access_points.append(ap)

        for c in clients:
            if not c.get("is_wired", True) is False and "ap_mac" not in c:
                continue
            ap_mac = c.get("ap_mac", "")
            radio_name = c.get("radio", "na")
            target = radios_by_mac.get(ap_mac, {}).get(radio_name)
            if target is None:
                continue
            target.clients.append(ClientReading(
                mac_address=c.get("mac", ""),
                hostname=c.get("hostname") or c.get("name"),
                ip_address=c.get("ip"),
                ssid=c.get("essid"),
                protocol=c.get("radio_proto"),
                rssi_dbm=c.get("signal"),
                snr_db=(c.get("signal") - c.get("noise")) if c.get("signal") is not None and c.get("noise") is not None else None,
                tx_rate_mbps=(c.get("tx_rate") / 1000) if c.get("tx_rate") else None,
                rx_rate_mbps=(c.get("rx_rate") / 1000) if c.get("rx_rate") else None,
            ))

        return result
