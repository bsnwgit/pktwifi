# pktWiFi Collector Setup

Each collector is created under **Collectors** in the UI: a name, a type,
a poll interval, and a JSON config blob. Secret fields inside that config
(passwords, API keys, SNMP v3 credentials) are Fernet-encrypted at rest —
see `app/wifi/collectors/crypto.py` and `credential_key` in `config.yaml`.

---

## Generic SNMP (`snmp_generic`)

Vendor-neutral. Confirms reachability via `sysUpTime` and does a
best-effort read of the standard `dot11` MIB channel table — this will
work against almost anything with SNMP enabled, but won't give you
per-radio utilization/tx-power/noise-floor unless the device happens to
expose that over the standard MIB (most vendor gear doesn't; use a
vendor-native collector below for real RF detail).

```json
{
  "version": "v2c",
  "community": "public",
  "port": 161,
  "hosts": [
    { "ip": "10.0.1.11", "name": "ap-lobby-1", "site": "HQ", "floor": "1" },
    { "ip": "10.0.1.12", "name": "ap-lobby-2", "site": "HQ", "floor": "1" }
  ]
}
```

For SNMPv3, replace `community` with:

```json
{
  "version": "v3",
  "username": "monitor",
  "auth_protocol": "SHA",
  "auth_password": "...",
  "priv_protocol": "AES",
  "priv_password": "...",
  "hosts": [ ... ]
}
```

---

## Cisco Meraki (`cisco_meraki`)

Dashboard API v1 (https://developer.cisco.com/meraki/api-v1/). Get an API
key from Dashboard -> My Profile -> API access, and find your
`organization_id` via `GET /organizations`.

```json
{
  "api_key": "your-dashboard-api-key",
  "organization_id": "123456",
  "network_ids": []
}
```

Leave `network_ids` empty to poll every wireless network in the
organization, or list specific network IDs to restrict scope.

> This integration has not been exercised against a live Meraki
> organization in this build — verify field mappings in
> `app/wifi/collectors/cisco_meraki.py` against a real API response before
> relying on it for production alerting.

---

## Ubiquiti UniFi (`unifi`)

Classic UniFi Network controller REST API. Works against both a
standalone controller and a UDM/UDM-Pro/Cloud Key Gen2+ console (set
`"udm": true` for the latter — paths get proxied under `/proxy/network`).

```json
{
  "controller_url": "https://10.0.0.1",
  "username": "monitor",
  "password": "...",
  "site": "default",
  "udm": false,
  "verify_tls": false
}
```

Create a dedicated local (non-cloud) admin/read-only account on the
controller for this rather than reusing your own login.

---

## Not Yet Implemented

These are registered in `app/wifi/collectors/registry.py` as documented
stubs — creating a collector of these types will fail with a clear "not
implemented yet" error until someone builds them out:

- **Aruba Central / Aruba Networking** — OAuth2 against the Central API
  gateway. See `app/wifi/collectors/aruba_central.py` for the specific
  endpoints and auth flow needed.
- **Cisco Catalyst 9800 / AireOS** — either RESTCONF/YANG (Catalyst 9800)
  or SNMP against `CISCO-LWAPP-*`/`AIRESPACE-WIRELESS-MIB` (AireOS). See
  `app/wifi/collectors/cisco_catalyst.py`.
- **Ruckus / SmartZone** — SmartZone REST API or RuckusONE cloud OAuth2.
  See `app/wifi/collectors/ruckus.py`.

Each stub file's docstring has enough detail to implement it the same way
`cisco_meraki.py` / `unifi.py` were: return a `PollResult` built from
`AccessPointReading` / `RadioReading` / `ClientReading` (`base.py`), and
flip `"implemented": True` in `registry.py` once tested against real
hardware.
