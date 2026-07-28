# pktWiFi Collector Setup

Each controller is created under **Settings -> Controllers** in the UI
(admin only). This was a separate top-level **Collectors** nav item before
it moved into Settings alongside the new Credentials and Sites tabs — the
term "controller" is used in the UI, but the backend API/DB and this doc
still say "collector" throughout. A controller is one row: a name, a type,
a poll interval, an enabled toggle, and a config form.

The config form is schema-driven (`app/wifi/collectors/field_schema.py` +
`frontend/src/components/CollectorConfigForm.tsx`) — each collector type
declares its fields (text/password/number/toggle/select/multiselect/
host-list/site-picker/credential-picker) with labels, placeholders, and
help text, and the UI renders real inputs instead of a raw JSON blob.
Fields can be conditional (`show_if`) — for example, the UniFi collector
only shows the username/password credential picker when "Username &
password" is selected, and only shows the API-key credential picker when
"API key" is selected. An **"Edit as JSON"** link in the Controller modal
is still available for pasting a config directly or for anything the form
doesn't cover; it round-trips through the same config dict, so switching
back to the form re-parses whatever you typed.

## Credentials live in a separate library, not inline in the config

Every field that used to be a raw secret typed into the collector's own
config (SNMP community/v3 auth, a controller username/password, an API
key) is now a **credential picker** instead: a dropdown sourced from
**Settings -> Credentials**, a separate named credential library (four
types — username/password, API key/token, SNMP v2c, SNMP v3),
Fernet-encrypted at rest and write-only through the API. A controller's
config stores only a `credential_id` referencing the saved credential;
`app/wifi/poll_engine.resolve_credential` decrypts it and merges the real
auth fields in at poll time. This means:

- Creating a controller requires first creating (or reusing) a matching
  credential under Settings -> Credentials.
- The JSON examples below show `credential_id` rather than inline
  `username`/`password`/`api_key`/`community` — that's the form the field
  schema actually produces now.
- If you paste a config via **Edit as JSON** with inline secret fields
  instead of a `credential_id`, they still work — `resolve_credential` is a
  no-op when `credential_id` is absent — but the resulting collector won't
  benefit from the credential library (rotation, reuse across controllers,
  delete-protection), so this isn't the recommended path.
- Deleting a credential still referenced by a controller is blocked — the
  error names which controller(s) use it.
- The Controller modal has a **Test Credentials** button (once a credential
  is selected) that runs a real, save-nothing auth attempt against the
  target currently in the form and shows pass/fail with the full error
  inline — use it before ever creating (or polling) the controller itself.

Any **Site** field in a collector's form is a dropdown populated from
**Settings -> Sites** (`site_select` field type) rather than a free-typed
string — see the README's [Vendor Collectors](../README.md#vendor-collectors)
section (Sites paragraph) for how that catalog works, and the UniFi section
below for a site-naming gotcha specific to that collector.

Once a controller is saved, use its **Poll Now** action (Controllers page)
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

Fields: an **SNMP credential** picked from Settings -> Credentials
(type `snmp_v2c` or `snmp_v3` — the credential itself carries the version,
community string, or v3 username/auth/priv secrets), port (default 161),
and a repeatable **hosts** list where each host has an IP, a name, a
**Site** (picked from Settings -> Sites), and a floor.

As raw config JSON (the "Edit as JSON" shape, matching what the form
produces), this is equivalent to:

```json
{
  "credential_id": 3,
  "port": 161,
  "hosts": [
    { "ip": "10.0.1.11", "name": "ap-lobby-1", "site": "HQ", "floor": "1" },
    { "ip": "10.0.1.12", "name": "ap-lobby-2", "site": "HQ", "floor": "1" }
  ]
}
```

`credential_id` must point to an existing SNMP v2c or v3 credential under
Settings -> Credentials. Create it there first (community string for v2c;
username/auth-protocol/auth-password/priv-protocol/priv-password for v3) —
there's no way to set those secrets from this collector's own form anymore.

---

## Cisco Meraki (`cisco_meraki`)

Dashboard API v1 (https://developer.cisco.com/meraki/api-v1/). Get an API
key from Dashboard -> My Profile -> API access, save it as an **API key
credential** under Settings -> Credentials, and find your
`organization_id` via `GET /organizations`.

Fields: an API-key credential (required, picked from Settings ->
Credentials), Organization ID (required), and a repeatable Network IDs
list.

```json
{
  "credential_id": 5,
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

Fields shown: Controller URL (no trailing slash), a **username/password
credential** (picked from Settings -> Credentials), Site, the UDM toggle,
and Verify TLS certificate.

```json
{
  "controller_url": "https://10.0.0.1",
  "auth_method": "userpass",
  "credential_id": 2,
  "site": "default",
  "udm": false,
  "verify_tls": false
}
```

Create a dedicated local (non-cloud) admin/read-only account on the
controller and save it as a credential rather than reusing your own login.

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
is no standalone-controller equivalent. **Verified against a live
UDM-Pro.**

Fields shown: Controller URL, an **API-key credential** (picked from
Settings -> Credentials), Site, Verify TLS certificate (no UDM toggle —
this mode is UniFi-OS-only by definition).

```json
{
  "controller_url": "https://10.0.0.1",
  "auth_method": "api_key",
  "credential_id": 7,
  "site": "default",
  "verify_tls": false
}
```

Site resolution in this mode matches against the Integration API's own
`/self/sites` list by name/description, falling back to the single site if
there's only one.

> AP-level detail is real in this mode — online/offline, per-radio
> channel/width/standard, and tx-retry-% all come back correctly. **Per-
> client detail is a confirmed API limitation, not a parsing gap:**
> inspecting the raw response directly shows the Integration API's client
> payload carries only `id`/`name`/`macAddress`/`ipAddress`/`connectedAt`/
> `uplinkDeviceId`/`type` — no SSID, RSSI, protocol, tx/rx rate, or
> per-radio attribution, at either the list or per-client detail endpoint.
> Every client from an API-key-mode controller lands in a single
> "Unassigned / no per-radio breakdown" bucket in the UI. Switch to
> username/password mode for full per-client detail. `connectedAt` is
> real and used as the Clients page's **Connected** column.

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
field-schema entry in `registry.py` (using `credential_select` for any
auth fields, matching the existing collectors), and flip
`"implemented": True` once tested against real hardware.
