"""
app/wifi/collectors/unifi.py
-----------------------------
Ubiquiti UniFi Network Controller collector. Supports two auth modes,
picked via config["auth_method"]:

- "userpass" (default) — the classic controller REST API
  (/api/s/<site>/stat/device and /api/s/<site>/stat/sta), which works
  against both a standalone UniFi Network Application and a UDM/UDM-Pro
  ("UniFi OS" console, where every path is proxied under /proxy/network).
  Rich per-radio (channel/utilization/noise floor) and per-client detail.
  Three things confirmed necessary against real UniFi OS gear:
  `follow_redirects=True` (an http:// controller_url that self-redirects
  to https:// otherwise raises on the login request before ever
  authenticating), echoing the `x-csrf-token` response header from login
  back as `X-Csrf-Token` on every subsequent request (UniFi OS consoles
  401 every proxied /proxy/network/api/* call without it, even with a
  valid session cookie — classic standalone controller software doesn't
  set this header, so it's a no-op there), and resolving the configured
  site against `GET /self/sites` (the UniFi UI's Site name is the `desc`
  field — the URL path segment the API needs is the separate, never-
  shown `name` slug; using the display name directly 401s).

- "api_key" — Ubiquiti's official local Network Integration API v1
  (/proxy/network/integration/v1), authenticated with an `X-API-KEY`
  header instead of a username/password login. Only available on a UniFi
  OS console (UDM/UDM-Pro/Cloud Gateway) with Integrations enabled under
  Settings -> Control Plane -> Integrations — there is no standalone-
  controller equivalent. Endpoint paths and the {meta, data} envelope are
  per Ubiquiti's published documentation; this mode has not been verified
  against live UniFi OS hardware. The Integration API is intentionally a
  "limited subset focused on common operations" (Ubiquiti's own
  description) — it does not expose the per-radio channel/utilization
  breakdown the classic API does, so api_key-mode devices report coarse
  online/offline status only, with an empty radios list.

Config shape:
{
  "controller_url": "https://10.0.0.1",   # no trailing slash
  "auth_method": "userpass",              # "userpass" | "api_key"
  "username": "...", "password": "...",   # userpass mode
  "api_key": "...",                       # api_key mode
  "site": "default",
  "udm": false,          # userpass mode only — true if this is a UDM/UDM-Pro/Cloud Key Gen2+ console
  "verify_tls": false    # most on-prem controllers use a self-signed cert
}
"""
from __future__ import annotations

import logging

import httpx

from app.wifi.collectors.base import Collector, PollResult, AccessPointReading, RadioReading, ClientReading

log = logging.getLogger("pktwifi.collectors.unifi")


def _first(d: dict, *keys: str, default=None):
    """The Integration API's exact per-field casing isn't independently
    verified against live gear (see module docstring) — probe a few
    plausible key spellings rather than assuming one and silently
    returning None for every device/client."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _is_ap(dev: dict) -> bool:
    """The Integration API identifies device roles via the `features` list
    ("accessPoint" / "switching"...), not a type field — verified against a
    live UDM-Pro. Fall back to type/deviceType for firmware that sends those
    instead, and treat anything unidentifiable as not-an-AP rather than
    polluting the AP list with switches and gateways."""
    features = [str(f).lower() for f in (dev.get("features") or [])]
    if features:
        return "accesspoint" in features
    device_type = str(_first(dev, "type", "deviceType", default="")).lower()
    return bool(device_type) and ("ap" in device_type or "uap" in device_type)


def _freq_band(freq) -> str | None:
    """Map the Integration API's frequencyGHz (2.4 / 5 / 6) to the band
    strings the rest of the app uses."""
    try:
        f = float(freq)
    except (TypeError, ValueError):
        return None
    if 2 <= f < 3:
        return "2.4GHz"
    if 5 <= f < 6:
        return "5GHz"
    if 6 <= f < 8:
        return "6GHz"
    return None


class UnifiCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.base = (config.get("controller_url") or "").rstrip("/")
        self.auth_method = config.get("auth_method", "userpass")
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.api_key = config.get("api_key", "")
        self.site = config.get("site", "default")
        self.udm = bool(config.get("udm", False))
        self.verify_tls = bool(config.get("verify_tls", False))

    def _api_prefix(self) -> str:
        return f"{self.base}/proxy/network/api" if self.udm else f"{self.base}/api"

    def _login_path(self) -> str:
        return f"{self.base}/api/auth/login" if self.udm else f"{self.base}/api/login"

    async def poll(self) -> PollResult:
        if not self.base:
            raise ValueError("controller_url is required")
        if self.auth_method == "api_key":
            if not self.api_key:
                raise ValueError("api_key is required in API key mode")
            return await self._poll_api_key()
        if not self.username:
            raise ValueError("username and password are required in username/password mode")
        return await self._poll_userpass()

    async def _poll_api_key(self) -> PollResult:
        headers = {"X-API-KEY": self.api_key, "Accept": "application/json"}
        integration_base = f"{self.base}/proxy/network/integration/v1"

        async with httpx.AsyncClient(timeout=20, verify=self.verify_tls, headers=headers, follow_redirects=True) as client:
            sites_resp = await client.get(f"{integration_base}/sites")
            sites_resp.raise_for_status()
            sites = sites_resp.json().get("data", [])
            site_id = None
            for s in sites:
                name = _first(s, "name", "desc", "description", default="")
                if str(name).lower() == str(self.site).lower():
                    site_id = s.get("id")
                    break
            if site_id is None and len(sites) == 1:
                site_id = sites[0].get("id")
            if site_id is None:
                raise ValueError(f"No site named '{self.site}' found via the Integration API — check the Site field")

            devices_resp = await client.get(f"{integration_base}/sites/{site_id}/devices")
            devices_resp.raise_for_status()
            devices = devices_resp.json().get("data", [])

            clients_resp = await client.get(f"{integration_base}/sites/{site_id}/clients")
            clients_resp.raise_for_status()
            clients = clients_resp.json().get("data", [])

            # The device *list* carries no radio data, but the per-device
            # detail endpoint reports each radio's channel/width/standard and
            # statistics/latest adds uptime + per-radio tx retry % — verified
            # against a live UDM-Pro. Both are best-effort: an AP still
            # reports (with no radio rows) if either extra call fails.
            ap_devices = [d for d in devices if _is_ap(d)]
            radio_detail: dict[str, list[dict]] = {}
            device_stats: dict[str, dict] = {}
            for dev in ap_devices:
                dev_id = str(_first(dev, "id", "_id", default=""))
                try:
                    dr = await client.get(f"{integration_base}/sites/{site_id}/devices/{dev_id}")
                    dr.raise_for_status()
                    radio_detail[dev_id] = (dr.json().get("interfaces") or {}).get("radios") or []
                except Exception:
                    radio_detail[dev_id] = []
                try:
                    sr = await client.get(f"{integration_base}/sites/{site_id}/devices/{dev_id}/statistics/latest")
                    sr.raise_for_status()
                    device_stats[dev_id] = sr.json() or {}
                except Exception:
                    device_stats[dev_id] = {}

        result = PollResult()
        for dev in ap_devices:
            mac = _first(dev, "macAddress", "mac", default="")
            state = str(_first(dev, "state", "status", default="")).lower()
            dev_id = str(_first(dev, "id", "_id", default=mac))
            stats = device_stats.get(dev_id, {})
            ap = AccessPointReading(
                external_id=dev_id,
                name=_first(dev, "name", default=mac),
                mac_address=mac,
                ip_address=_first(dev, "ipAddress", "ip"),
                vendor="ubiquiti-unifi",
                model=_first(dev, "model"),
                firmware_version=_first(dev, "firmwareVersion", "version"),
                status="online" if state in ("online", "connected", "1") else "offline",
                uptime_seconds=stats.get("uptimeSec") or _first(dev, "uptimeSeconds", "uptime"),
            )
            retries_by_band: dict[str, float] = {}
            for r in ((stats.get("interfaces") or {}).get("radios") or []):
                band = _freq_band(r.get("frequencyGHz"))
                if band and r.get("txRetriesPct") is not None:
                    retries_by_band[band] = r["txRetriesPct"]
            for r in radio_detail.get(dev_id, []):
                band = _freq_band(r.get("frequencyGHz"))
                if not band:
                    continue
                ap.radios.append(RadioReading(
                    band=band,
                    channel=r.get("channel"),
                    channel_width_mhz=r.get("channelWidthMHz"),
                    retry_pct=retries_by_band.get(band),
                ))
            result.access_points.append(ap)

        ap_by_id = {ap.external_id: ap for ap in result.access_points}
        for c in clients:
            # The clients list includes wired devices too — only WIRELESS
            # entries uplinked to an AP belong here.
            ctype = str(c.get("type", "")).upper()
            if ctype and ctype != "WIRELESS":
                continue
            ap = ap_by_id.get(str(_first(c, "uplinkDeviceId", "apId", "ap_id", default="")))
            if ap is None:
                continue
            # api_key mode doesn't attribute clients to a radio — keep them in
            # a dedicated "unknown"-band bucket next to the real radios so
            # per-radio channel data and the client list can coexist.
            bucket = next((r for r in ap.radios if r.band == "unknown"), None)
            if bucket is None:
                bucket = RadioReading(band="unknown")
                ap.radios.append(bucket)
            bucket.clients.append(ClientReading(
                mac_address=_first(c, "macAddress", "mac", default=""),
                hostname=_first(c, "name", "hostnameOrIp", "hostname"),
                ip_address=_first(c, "ipAddress", "ip"),
                # The Integration API's client payload has no ssid/rssi/rate
                # fields at all (confirmed empirically — not a parsing gap,
                # a real API-key-mode limitation; use userpass mode for full
                # per-client RF detail). It does report a real connectedAt,
                # so that's not lost the way the others are.
                connected_at=_first(c, "connectedAt"),
            ))

        return result

    async def _resolve_site_slug(self, client: httpx.AsyncClient, api_prefix: str, site: str) -> str:
        """The UniFi UI's Site name is the `desc` field — the URL path
        segment the API needs is the separate `name` slug, which the UI
        never shows. Resolve whatever was configured (display name or
        slug) to the real slug via /self/sites."""
        resp = await client.get(f"{api_prefix}/self/sites")
        resp.raise_for_status()
        sites = resp.json().get("data", [])
        for s in sites:
            if s.get("name") == site:
                return s["name"]
        for s in sites:
            if (s.get("desc") or "").strip().lower() == site.strip().lower():
                return s["name"]
        if len(sites) == 1:
            return sites[0]["name"]
        available = ", ".join(sorted({s.get("desc") or s.get("name", "") for s in sites})) or "none"
        raise ValueError(f"No site named '{site}' found on this controller — check the Site field (available: {available})")

    async def _poll_userpass(self) -> PollResult:
        async with httpx.AsyncClient(timeout=20, verify=self.verify_tls, follow_redirects=True) as client:
            login_resp = await client.post(
                self._login_path(), json={"username": self.username, "password": self.password}
            )
            login_resp.raise_for_status()

            # UniFi OS (UDM/UDM-Pro/Cloud Gateway) consoles require every
            # request after login to echo back the CSRF token issued on
            # login as an X-Csrf-Token header, or proxied API calls 401
            # even with a valid session cookie. Classic standalone
            # controller software doesn't set this header at all, so this
            # is a no-op there.
            csrf_token = login_resp.headers.get("x-csrf-token")
            if csrf_token:
                client.headers["X-Csrf-Token"] = csrf_token

            prefix = self._api_prefix()
            site_slug = await self._resolve_site_slug(client, prefix, self.site)

            devices_resp = await client.get(f"{prefix}/s/{site_slug}/stat/device")
            devices_resp.raise_for_status()
            devices = devices_resp.json().get("data", [])

            clients_resp = await client.get(f"{prefix}/s/{site_slug}/stat/sta")
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
