# pktWiFi Collector Setup

Each collector is created under **Collectors** in the UI (admin only): a
name, a type, a poll interval, an enabled toggle, and a config form.

The config form is schema-driven (`app/wifi/collectors/field_schema.py` +
`frontend/src/components/CollectorConfigForm.tsx`) — each collector type
declares its fields (text/password/number/toggle/select/multiselect/
host-list/site-picker) with labels, placeholders, and help text, and the
UI renders real inputs instead of a raw JSON blob. Fields can be
conditional (`show_if`) — for example, the UniFi collector only shows
username/password fields when "Username & password" is selected, and only
shows the API-key field when "API key" is selected. An **"Edit as JSON"**
link in the Collector modal is still available for pasting a config
directly or for anything the form doesn't cover; it round-trips through
the same config dict, so switching back to the form re-parses whatever
you typed.

Secret fields inside that config (passwords, API keys, SNMP v3
credentials) are Fernet-encrypted at rest — see
`app/wifi/collectors/crypto.py` and `credential_key` in `config.yaml`.

Any **Site** field in a collector's form is a dropdown populated from
**Settings -> Sites** (`site_select` field type) rather than a free-typed
string — see the README's [Sites](../README.md#sites) section for how
that catalog works, and the UniFi section below for a site-naming gotcha
specific to that collector.

Once a collector is saved, use its **Poll Now** button (Collectors page)
to poll immediately instead of waiting for the interval. On failure, a
modal shows the full error text with a copy-to-clipboard button — useful
for getting the exact underlying error out of a truncated table cell.

---

## Generic SNMP (`snmp_generic`)

Vendor-neutral. Confirms reachability via `sysUpTime` and does a
best-effort read of the standard `dot11` MIB channel table — this will
work against almost anything with SNMP enabled, but won't give you
per-radio utilization/tx-power/noise-floor unless the device happens to
expose that over the standard MIB (most vendor gear doesn't; use a
vendor-native collector below for real RF detail).

Fields: SNMP version (v2c/v3), community string (v2c) or
username/auth-protocol/auth-password/priv-protocol/priv-password (v3),
port (default 161), and a repeatable **hosts** list where each host has an
IP, a name, a **Site** (picked from Settings -> Sites), and a floor.

As raw config JSON, this is equivalent to:

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

Fields: API key (required), Organization ID (required), and a repeatable
Network IDs list.

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

The form's **Authentication method** select switches between two distinct
config shapes:

### Username & password (default)

Classic UniFi Network controller REST API. Works against both a
standalone controller and a UDM/UDM-Pro/Cloud Key Gen2+ console — toggle
**UDM / UDM-Pro / Cloud Key Gen2+** for the latter (paths get proxied
under `/proxy/network`).

Fields shown: Controller URL (no trailing slash), Username, Password,
Site, the UDM toggle, and Verify TLS certificate.

```json
{
  "controller_url": "https://10.0.0.1",
  "auth_method": "userpass",
  "username": "monitor",
  "password": "...",
  "site": "default",
  "udm": false,
  "verify_tls": false
}
```

Create a dedicated local (non-cloud) admin/read-only account on the
controller for this rather than reusing your own login.

**Site slug gotcha:** the UniFi UI's Site name is the `desc` field — the
URL path segment the API actually needs is a separate `name` slug that the
UI never shows you. Typing the display name directly used to 401. The
collector now resolves whatever you put in the **Site** field — display
name or slug — against the controller's real sites via `GET /self/sites`
before making any device/client calls (`_resolve_site_slug` in
`app/wifi/collectors/unifi.py`), so either spelling works. If it can't
find a match, the error lists the site names/descriptions it actually saw,
so you can fix the typo. If the controller has exactly one site, any value
resolves to it automatically regardless of spelling.

Three other behaviors confirmed necessary against real UniFi OS gear, in
case you're comparing against your own client code: `follow_redirects=True`
(an `http://` `controller_url` that self-redirects to `https://`
otherwise raises before ever logging in), echoing the `x-csrf-token`
response header from the login call back as `X-Csrf-Token` on every
subsequent request (UniFi OS consoles 401 every proxied
`/proxy/network/api/*` call without it, even with a valid session cookie
— classic standalone controller software doesn't set this header, so it's
a harmless no-op there), and the site-slug resolution above.

### API key

Ubiquiti's official local Network Integration API v1
(`/proxy/network/integration/v1`), authenticated with an `X-API-KEY`
header instead of a username/password login. Only available on a UniFi OS
console (UDM/UDM-Pro/Cloud Gateway) with Integrations enabled under
Settings -> Control Plane -> Integrations in the UniFi UI itself — there
is no standalone-controller equivalent.

Fields shown: Controller URL, API key, Site, Verify TLS certificate (no
UDM toggle — this mode is UniFi-OS-only by definition).

```json
{
  "controller_url": "https://10.0.0.1",
  "auth_method": "api_key",
  "api_key": "...",
  "site": "default",
  "verify_tls": false
}
```

Site resolution in this mode matches against the Integration API's own
`/sites` list by name/description, falling back to the single site if
there's only one.

> The Integration API is intentionally a "limited subset focused on
> common operations" per Ubiquiti's own description — it does not expose
> the per-radio channel/utilization breakdown the classic API does, so
> API-key-mode devices report coarse online/offline status only, with an
> empty radios list. This mode has not been verified against live UniFi OS
> hardware — endpoint paths and the field casing follow the published
> docs; spot-check `app/wifi/collectors/unifi.py`'s `_first()` key-name
> probing against a real response if you rely on it.

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
`AccessPointReading` / `RadioReading` / `ClientReading` (`base.py`), add a
field-schema entry in `registry.py`, and flip `"implemented": True` once
tested against real hardware.
