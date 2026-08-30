# pktWiFi

<p align="center">
  <img src="lockup-256h.png" alt="pktWiFi" height="64">
</p>

Enterprise WiFi analyzer — part of the pkt suite. Aggregates access point,
RF/channel, and client data from your own SNMP polling or vendor controller
APIs, plus device/traffic/log context pulled from sibling pkt* apps
(pktsnmp, pktflow, pktlog, pktpcap, pktipam) over suite-token API calls, and
surfaces it through a React UI with alerting.

**Default port:** `8769` (HTTP)

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Frontend Build & Deploy](#frontend-build--deploy)
- [Feature Inventory](#feature-inventory)
- [Vendor Collectors](#vendor-collectors)
- [Metrics](#metrics)
- [Configuration Reference](#configuration-reference)
- [Running & Managing the Service](#running--managing-the-service)
- [Settings](#settings)
- [Roles & Auth](#roles--auth)
- [IP Intelligence Lookup](#ip-intelligence-lookup)
- [Alerting & Notifications](#alerting--notifications)
- [Suite Integration](#suite-integration)
- [Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps)
- [Backup, Retention & Restore](#backup-retention--restore)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Known Gaps / Fast-Follow Work](#known-gaps--fast-follow-work)
- [Log Forwarding](#log-forwarding)

---

## Quick Start

```bash
# 1. Clone the repository
git clone git@github.com:bsnwgit/pktwifi.git
cd pktwifi

# 2. Run the installer — prompts for an install directory (default /opt/pktwifi)
#    and a port (default 8769), then handles system packages, Python venv,
#    config.yaml + secret/credential keys, DB migrations, admin user,
#    frontend build (if npm is present), and the systemd service
#    (installed + started)
bash install.sh

# Prints the admin password at the end — save it, it is not shown again.

# 3. Open the firewall for the app port
sudo ufw allow 8769/tcp

# 4. Open http://<server-ip>:8769 and log in with the admin credentials from step 2
```

Never run `sudo ./install.sh` — the script is meant to run as your normal
user and calls `sudo` internally only for the steps that need it (package
install, directory ownership, the systemd unit). Running the whole script
as root changes file ownership in ways that can break the service later.

### Environment variables

`install.sh` honors the following overrides (skips the matching interactive
prompt when set):

| Variable | Default | Description |
|---|---|---|
| `PKTWIFI_INSTALL_DIR` | `/opt/pktwifi` | App root — every other path defaults to somewhere under this |
| `PKTWIFI_PORT` | `8769` | HTTP port the service listens on |
| `PKTWIFI_LOG_DIR` | `$PKTWIFI_INSTALL_DIR/logs` | Log file directory |
| `PKTWIFI_SERVICE_USER` | current user | systemd service user |
| `PKTWIFI_SERVICE_GROUP` | same as service user | systemd service group |

### What the installer actually does (8 steps)

1. Installs system packages (`python3`, venv/pip, `libssl-dev`/`libffi-dev`,
   `libxmlsec1*`/`libxml2-dev` + `pkg-config`/`gcc` for SAML, `curl`).
2. Creates the install, log, and `ssl` directories.
3. Creates a Python virtualenv under `<install_dir>/venv` and installs
   `requirements.txt`.
4. Copies `app/`, `migrations/`, and the icon/lockup SVGs into the install
   dir — skipped entirely when you install in place inside the repo
   checkout (`install_dir == repo dir`).
5. Generates `config.yaml` from `config.example.yaml` (only if one doesn't
   already exist — re-running `install.sh` never clobbers your config): a
   random JWT `secret_key`, a random Fernet `credential_key`, the detected
   LAN IP baked into `cors_origins`/`base_url`, the chosen port, and an
   explicit `install_dir` line.
6. Runs DB migrations and seeds the initial `admin` user with a random
   16-character password.
7. Builds the frontend with `npm` if it's present on the box (`npm install
   && npm run build`, output copied to `<install_dir>/frontend/dist`); if
   `npm` isn't found, it skips this and prints the manual build command —
   the web UI will return `{"detail":"Not Found"}` until that's done.
8. Renders `pktwifi.service` from the template (substituting install dir,
   log dir, service user/group), re-owns the install/log directories to
   the service user, and enables + starts the systemd service.

The final banner prints the login URL, the `admin` username, and the
generated password — save it, it's not shown again. `install_dir` is
resolved at runtime everywhere in the codebase (env var -> config.yaml
location -> cwd) and every other path (db, logs, ssl, backups) is derived
from it — no source file hardcodes an absolute install path; see
`app/config.py`.

---

## Architecture

```
                        +-------------------------------+
                        |            pktWiFi             |
                        |  FastAPI + SQLite + React UI    |
                        +---------------+-----------------+
                                        |
              +-------------------------+-------------------------+
              |                         |                         |
    app/wifi/poll_engine.py   app/alerts/engine.py       app/integrations/*
    (native collectors)       (WiFi alert rules)         (suite-token clients)
              |                                                    |
    +---------+---------+                              +-----------+-----------+
    |  generic SNMP      |                              |  pktsnmp  pktflow    |
    |  Cisco Meraki API   |                              |  pktlog   pktpcap    |
    |  UniFi API          |                              +-----------------------+
    |  (Aruba/Catalyst/   |
    |   Ruckus: stubs)    |
    +---------------------+
```

Two independent data paths feed pktWiFi, matching how it was scoped:

1. **Native collectors** (`app/wifi/collectors/`) — pktWiFi polls WiFi
   hardware/controllers directly for WiFi-specific RF data (channel,
   utilization, noise floor, per-client RSSI/SNR) that no other pkt app
   collects. A pluggable `Collector` base class (`app/wifi/collectors/base.py`)
   makes adding a new vendor a matter of writing one file — see
   [Vendor Collectors](#vendor-collectors).
2. **Suite integrations** (`app/integrations/`) — pktWiFi acts as a
   suite-token *client* of pktsnmp/pktflow/pktlog/pktpcap/pktipam, reusing
   data those apps already collect (generic device/interface polling,
   traffic flows, syslogs, packet captures, subnet/DHCP/DNS inventory)
   instead of re-implementing any of it. This is the same token mechanism
   pktHub uses to proxy into every pkt app, just used in the other
   direction — see
   [Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps).
   Note: `app/integrations/` currently ships client modules for pktsnmp,
   pktflow, pktlog, and pktpcap; pktipam is registered as a connectable
   sibling app (Settings -> Security -> Suite Integration) but does not yet
   have its own dedicated client module.

Everything else — Dashboard, Access Points, Clients, Metrics, Alerts, Logs,
Settings — is standard FastAPI routers under `app/api/` serving a React SPA
(`frontend/`) built with Vite. Controller (formerly "Collector") management,
the credential library, and Sites all live inside Settings rather than as
their own top-level nav items — see [Settings](#settings). See
[Feature Inventory](#feature-inventory) for the full current page/tab list.

---

## Requirements

- Ubuntu Server 22.04/24.04 LTS (install.sh targets this; other Linux
  distros likely work with manual package-manager substitution)
- Python 3.10+
- Node.js + npm (only needed to build the frontend — see
  [Frontend Build & Deploy](#frontend-build--deploy))

---

## Installation

See [Quick Start](#quick-start) for the full walkthrough and the 8-step
breakdown of what `install.sh` does. In short: `install.sh` is
idempotent-ish — re-running it will not overwrite an existing
`config.yaml`, and skips the copy step entirely when run in-place inside
the repo checkout (`REPO_DIR == INSTALL_DIR`).

---

## Frontend Build & Deploy

```bash
cd frontend
npm install
npm run build         # outputs frontend/dist
```

`app/main.py` serves `frontend/dist` directly when it exists. After a
rebuild, always clear the old `dist/` before copying a new one in — Vite
doesn't clean up stale hashed chunk filenames, and a browser holding an old
`index.html` will happily keep loading old-but-still-present JS chunks with
no 404 to reveal the problem.

---

## Feature Inventory

Sidebar navigation (`frontend/src/components/Layout.tsx`):

| Page | Access | What it does |
|---|---|---|
| **Dashboard** | all roles | AP counts (total/online/offline/rogue), connected client count, active alerts list, recent AP status at a glance. |
| **Access Points** | all roles | Searchable, server-side-paginated AP inventory across every controller — status, vendor, model, firmware. Click a row for a detail panel: per-radio channel/utilization/retry data where the controller supplies it, and connected clients grouped by the actual radio/channel they're attached to (see [Vendor Collectors](#vendor-collectors) for the UniFi API-key-mode caveat on that). A client row jumps to Clients pre-filtered to that AP; **View Metrics →** opens [Metrics](#metrics) pre-selected to that AP. |
| **Clients** | all roles | Searchable, server-side-paginated client list — SSID, band, channel, RSSI/SNR, tx/rx rate, real connect time (**Connected** column — see the UniFi collector notes on what's actually reported per auth mode), which AP it's attached to. Supports an `?access_point_id=` filter (with a clearable chip) used by the Access Points detail panel's click-through. |
| **Metrics** | all roles | Dedicated time-series view — pick an AP from the searchable left-hand list, see per-band channel-utilization/retry-rate/client-count charts for a 1h/6h/24h/7d window; see [Metrics](#metrics). |
| **Alerts** | all roles (analyst+ can ack/resolve) | Alert rules + fired events; see [Alerting & Notifications](#alerting--notifications). |
| **Logs** | all roles | AP/controller syslog and event context, including anything pulled in via the pktLog suite integration. |

Controller management (formerly a separate top-level **Collectors** nav
item) and the **Sites** catalog now live inside Settings, alongside a new
**Credentials** tab — see [Settings](#settings) and
[Vendor Collectors](#vendor-collectors).


Most pages and Settings sub-tabs (Dashboard, Access Points, Clients,
Metrics, Alerts, Logs, and the Users/User Keys/Controllers/Sites/
Credentials/Suite Integration/SSL-TLS Settings tabs) also have a small
**?** help button next to their heading (`frontend/src/components/
HelpButton.tsx`) that pops a short "How It Works" explainer for that page
— quick in-app context without leaving for this README.

The standalone "Integrations" page from earlier builds no longer exists;
`/integrations` now redirects straight to `/settings`. Both directions of
suite integration (the inbound token pktHub uses to proxy in, and the
outbound connections pktWiFi uses to call into sibling apps) live under
**Settings -> Security -> Suite Integration** — see
[Suite Integration](#suite-integration) and
[Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps).

---

## Vendor Collectors

Controllers are configured under **Settings -> Controllers** (admin only —
this was a separate top-level **Collectors** nav item before this
functionality moved into Settings alongside the new Credentials tab; the
term "controller" is now used in the UI, though the backend API/DB still
say "collector" throughout). Each controller is one row: a name, a type, a
poll interval, an enabled toggle, and a config form. That form is
**schema-driven** (`app/wifi/collectors/field_schema.py` + `frontend/src/
components/CollectorConfigForm.tsx`) — fields render as real text/password/
number/toggle/select/multiselect/host-list/site-picker/credential-picker
inputs with per-field help text and conditional (`show_if`) fields, instead
of a raw JSON textarea. An **"Edit as JSON"** link is still available in the
Controller modal as an escape hatch/power-user path — it round-trips
through the same config dict.

**Credentials** (`Settings -> Credentials`, admin only) is a separate named
credential library — four types (username/password, API key/token, SNMP
v2c, SNMP v3), Fernet-encrypted at rest and write-only through the API
(a saved secret is never returned, and editing with a blank secret field
keeps the stored value). A controller's config form references a saved
credential via a typed dropdown (filtered to the credential types that
controller type actually uses) instead of asking you to re-type a
username/password/API key/community string inline every time you add a
controller. Deleting a credential still referenced by a controller is
blocked — the error names which controller(s) are using it. The Controller
modal also has a **Test Credentials** button (once a credential is
selected) that runs a real, save-nothing auth attempt against the target
currently in the form — a UniFi login or Integration API call, a Meraki
`/organizations` call, or an SNMP `sysDescr` GET — and shows pass/fail with
the full error inline, so you can verify a credential works before ever
creating (or polling) the controller itself.

**Sites** (`Settings -> Sites`, admin only) is a small managed catalog —
just a name and an optional description per row (`app/api/sites.py`,
`sites` table). Its only purpose is to populate the **Site** dropdown that
appears in controller config forms (the SNMP generic collector's per-host
`site` field, and the UniFi collector's top-level `site` field) instead of
free-typing a location name and risking typo'd duplicates ("HQ" / "Hq" /
"headquarters" all meaning the same place). Deleting a site here does not
touch controllers already referencing that name — it just stops showing up
as a dropdown choice going forward. **Do not confuse this with a UniFi
controller's own "Site" concept** — see the site-slug note below.

Each controller row has a **Poll Now** action that polls immediately
(instead of waiting for its interval) and reports the AP/client counts
inline on success. On failure it shows a short "Failed — see error" link;
clicking it (or the link is also shown automatically) opens a modal with
the full error text and a copy-to-clipboard button — useful for grabbing
the exact underlying HTTP/auth error to search or paste into a ticket,
without the message getting truncated in a table cell.

| Type | Status | Notes |
|---|---|---|
| Generic SNMP | Implemented | Vendor-neutral: sysUpTime reachability + best-effort standard `dot11` MIB channel walk. See `app/wifi/collectors/snmp_generic.py`. |
| Cisco Meraki | Implemented | Dashboard API v1. Written against the documented API shape but not exercised against a live org in this build — spot-check field mappings in `app/wifi/collectors/cisco_meraki.py` against a real response. |
| Ubiquiti UniFi | Implemented | Two selectable auth methods — see below. See `app/wifi/collectors/unifi.py`. |
| Aruba Central / Aruba Networking | Not implemented | Stub with implementation notes in `app/wifi/collectors/aruba_central.py`. |
| Cisco Catalyst 9800 / AireOS | Not implemented | Stub with implementation notes in `app/wifi/collectors/cisco_catalyst.py`. |
| Ruckus / SmartZone | Not implemented | Stub with implementation notes in `app/wifi/collectors/ruckus.py`. |

### Ubiquiti UniFi — two auth methods

The **Authentication method** field switches which set of fields the form
shows:

- **Username & password** (default) — the classic controller REST API
  (`/api/s/<site>/stat/device`, `/stat/sta`). Works against both a
  standalone UniFi Network Application and a UDM/UDM-Pro/Cloud Key Gen2+
  console (toggle **UDM / UDM-Pro / Cloud Key Gen2+** for the latter —
  paths get proxied under `/proxy/network`). Gives rich per-radio
  (channel/utilization/noise-floor) and per-client detail. Auth comes from
  a **username/password credential** picked via dropdown from the
  Credentials library (`Settings -> Credentials`), not typed inline — use a
  dedicated local (non-cloud) read-only admin account, not your own login.
- **API key** — Ubiquiti's official local Network Integration API v1
  (`/proxy/network/integration/v1`), authenticated with an `X-API-KEY`
  header sourced from an **API key credential** in the Credentials
  library. Only available on a UniFi OS console (UDM/UDM-Pro/Cloud Gateway)
  with Integrations enabled under Settings -> Control Plane ->
  Integrations in the UniFi UI — no standalone-controller equivalent
  exists. **Verified against a live UDM-Pro.** AP-level detail is real:
  online/offline, per-radio channel/width/standard (device detail
  endpoint) and tx-retry-% (`statistics/latest`). **Per-client detail is
  a hard API limitation, not a parsing gap** — the Integration API's
  client payload carries only `id`/`name`/`macAddress`/`ipAddress`/
  `connectedAt`/`uplinkDeviceId`/`type`, confirmed by inspecting the raw
  response directly. There is no SSID, RSSI, protocol, tx/rx rate, or
  per-radio attribution anywhere in that payload, at the list endpoint or
  the per-client detail endpoint (they're identical). Every client from an
  API-key-mode controller lands in a single "Unassigned / no per-radio
  breakdown" bucket in the UI (Access Points detail panel, Clients page
  Channel column) — that's the API telling the truth about what it knows,
  not a bug. Switch the controller to username/password mode for full
  per-client SSID/signal/rate/channel detail. One field it does report
  usefully: a real `connectedAt` per client, which pktwifi stores as the
  Clients page's **Connected** column instead of inventing a "first seen
  by pktwifi" timestamp the way it used to.

**Site slug gotcha (username/password mode):** a UniFi controller's Site
concept has two names — the one shown in the UniFi UI (the `desc` field)
and a separate URL slug (the `name` field) that the REST API actually
needs, which the UI never displays. Typing the display name into a `site`
field used to 401 outright. The collector now resolves whatever you enter
— display name or slug — against the controller's real sites via
`GET /self/sites` before making any device/client calls, so either works.
If resolution fails, the error names the sites it actually found so you
can match the spelling. If your controller has exactly one site, any
value resolves to it automatically.

Three other things the userpass path handles that are easy to miss when
implementing something similar by hand: it uses `follow_redirects=True`
(an `http://` `controller_url` that self-redirects to `https://` would
otherwise raise before ever authenticating), and it echoes the
`x-csrf-token` response header from login back as `X-Csrf-Token` on every
subsequent request (required by UniFi OS consoles — proxied
`/proxy/network/api/*` calls 401 without it even with a valid session
cookie; classic standalone controllers don't set the header at all, so
it's a no-op there).

Add a new vendor by writing a `Collector` subclass (see `base.py` for the
`AccessPointReading`/`RadioReading`/`ClientReading` shapes), a field-schema
entry, and registering both in `app/wifi/collectors/registry.py`. See also
[docs/collector-setup.md](docs/collector-setup.md) for per-vendor config
field reference.

---

## Metrics

A dedicated **Metrics** page (`frontend/src/pages/Metrics.tsx`, left nav
between Clients and Alerts) — pick an AP from the searchable list on the
left, then see its RF history on the right: **Channel Utilization** and
**Retry Rate** per real radio band, plus **Client Count** (which also
works for the UniFi API-key-mode "no per-radio breakdown" bucket, since
that's tracked as its own radio row even without a channel). Backed by
`GET /api/metrics/access-points/{id}?since_minutes=N`
(`app/api/metrics.py`), reading from the `radio_metrics` table the poll
engine writes to every poll cycle.

The time-window selector (1h/6h/24h/7d) is synced to the URL
(`?ap=<id>&since=<minutes>`, so a link to a specific AP's metrics is
shareable/bookmarkable) and applies immediately — no separate reload step.
Two behaviors worth knowing if you're extending this page:

- **The chart X-axis domain is anchored to the full selected window**
  (`[fetchedAt - windowMinutes, fetchedAt]`), captured once per successful
  fetch — not derived from the data's own min/max timestamps. A small
  amount of real history (e.g. right after adding a new AP) renders as a
  correctly-proportioned *slice* of a wide window with empty space around
  it, instead of always stretching to fill the chart regardless of how
  much of the window it actually covers.
- **Requests are sequence-guarded** (`app/`-side: a ref-based counter in
  `Metrics.tsx`, incremented per fetch) so a slow response from a
  previously-selected AP or window can't land after a newer one and
  silently overwrite it with stale data — the failure mode that made an
  earlier version of this page look like changing the time range "did
  nothing."

The Access Points detail panel links out here via **View Metrics →**
instead of embedding its own copy of these charts — keeps that panel's
bundle small (recharts, the charting library, only loads on this page).

---

## Configuration Reference

See `config.example.yaml` for the full annotated list. Key fields:

| Key | Description |
|---|---|
| `port` | HTTP port (default 8769) |
| `install_dir` | App root — appended by install.sh, don't hand-edit unless moving the install |
| `secret_key` | JWT signing key |
| `credential_key` | Fernet key encrypting collector credentials at rest |
| `cors_origins` | Restrict to your actual origin in production |
| `suite_token` | pktHub inbound token — managed via Settings -> Security -> Suite Integration, not hand-edited |

Note: `port` also has a UI path (Settings -> General -> Port), which
writes back to this same file — see [Settings](#settings).

---

## Running & Managing the Service

```bash
sudo systemctl status pktwifi
sudo systemctl restart pktwifi
journalctl -u pktwifi -f
```

You don't need shell access for a routine restart — an admin can trigger
one from the UI: **Settings -> General -> Restart Service**. It calls
`POST /api/system/restart`, which waits ~1.5s and then exits the process
so systemd (`Restart=on-failure`) brings it back up; reload the page a few
seconds later. Useful after changing the port or applying a Settings
change that needs a restart to take effect, or to recover a wedged
process without SSH.

---

## Settings

Admin-only, reached via the **Settings** nav item. Tabs are split into two
**sections**, selected from a section bar above the tab bar: **Common** —
the suite-common set every pkt app shares (General through System) — and
**pktWiFi** — this app's own management tabs (Controllers, Credentials,
Sites). The latter three used to be their own top-level nav items before
they were folded into Settings, matching the convention every other pkt
app already used for app-specific management. Choosing a section swaps the
tab bar underneath, so only one group is visible at a time; previously all
of them shared a single row separated by a thin divider. Deep links to a
tab still work and select the section automatically. Two tabs have their
own left-hand sub-tab strip:

### Common

| Tab | Sub-tabs | Covers |
|---|---|---|
| **General** | — | App name, timezone, **Port** (writes `config.yaml`, needs a restart to take effect), Base URL (feeds SAML ACS/metadata URLs), and the **Restart Service** button. |
| **Data** | Storage, Backups | See below. |
| **Notifications** | — | Alert-channel config: Slack, Email (SMTP), PagerDuty, generic Webhook, TraceCat SOAR — see [Alerting & Notifications](#alerting--notifications). |
| **User Keys** | — | Personal (per-user, not shared) external API keys — currently a Lucidchart Personal Access Token, used for exporting diagrams. Each user manages their own; nobody else, including admins, can see another user's key value. |
| **System** | — | Read-only version + install directory display. |

### pktWiFi

| Tab | Sub-tabs | Covers |
|---|---|---|
| **Controllers** | — | Add/edit/delete/poll vendor controllers; see [Vendor Collectors](#vendor-collectors). |
| **Credentials** | — | Named, reusable controller auth library; see [Vendor Collectors](#vendor-collectors). |
| **Sites** | — | Small managed location catalog; see [Vendor Collectors](#vendor-collectors). |

### Security sub-tabs

- **Users** (admin only) — create/edit/deactivate/delete local accounts,
  reset a user's password, filter/sort the list, and mark one active admin
  as the **default admin** (the star icon): when every auth method is
  disabled, the app skips the login page and signs everyone in as that
  account, so there's always a way in.
- **Auth** — toggle local username/password auth, set the session timeout,
  and configure SAML 2.0 SSO (paste IdP metadata XML to auto-fill Entity
  ID/SSO URL/certificate, or fill them in by hand; the ACS URL and SP
  metadata link are derived from **Base URL** on the General tab, so set
  that first).
- **Suite Integration** — both directions of suite-token integration in
  one place: the inbound **Suite Token** (what pktHub uses to proxy into
  pktWiFi) and the outbound **Sibling pkt Apps** connections (what pktWiFi
  uses to call into pktsnmp/pktflow/pktlog/pktpcap/pktipam). See
  [Suite Integration](#suite-integration) and
  [Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps).
- **SSL / TLS** — upload a certificate as either a combined PFX/P12 bundle
  (with passphrase) or a separate PEM cert+key pair; view expiry/subject/
  issuer for whatever's installed; remove it to fall back to plain HTTP.
  Takes effect after a service restart — the running process auto-detects
  cert files under `<install_dir>/ssl` at startup.

### Data sub-tabs

- **Storage** — pktWiFi is SQLite-only; there's no analytical-backend
  picker here (unlike some sibling apps). What you do configure is
  **retention**: days to keep resolved alert events, and days to keep raw
  RF metric history, plus a **Run Cleanup Now** button
  (`POST /api/system/cleanup`) to apply the current thresholds immediately
  instead of waiting for the once-daily scheduled pass.
- **Backups** — enable/disable the scheduled backup, set its interval and
  rotation count, set the backup path, and trigger a manual run. See
  [Backup, Retention & Restore](#backup-retention--restore).

---

## Roles & Auth

Three roles: `admin` (full access, including Settings and its Controllers/
Credentials/Sites/Users tabs), `analyst` (can edit access points, ack/
resolve alerts), `viewer` (read-only).

Local username/password auth is always available; SAML 2.0 SSO can be
layered on top via Settings -> Security -> Auth (same IdP-agnostic
implementation as pktsnmp/pktflow — `app/auth/saml.py`). SAML users are
auto-provisioned on first successful login — no separate "create user"
step. When pktHub proxies a request with a valid `X-Suite-Token`, the
`X-Suite-Role` header maps directly onto these three roles (see
`app/dependencies.py`).

If every auth method (local + SAML) ends up disabled, the app doesn't lock
everyone out — it skips the login page and auto-signs everyone in as the
**default admin** account (see Users tab, above).

---

## IP Intelligence Lookup

Any public IP address rendered in the app is a clickable link (`GET /api/ip-info/{ip}`) that opens a lookup combining:

- **ipinfo.io** — geolocation/ASN/org info, plus company, privacy (VPN/proxy/Tor/relay/hosting), and abuse contact on paid plans
- **ipapi.is** — geolocation, ASN/org, company, abuse contact, VPN/proxy/Tor/datacenter/abuser detection, all in one call, no plan gating
- **AbuseIPDB** — abuse confidence score and report history
- **MXToolbox** — reverse DNS (PTR), ASN, and a blacklist/RBL check

All four are called concurrently. Private/loopback/link-local/reserved/multicast addresses are rejected — external providers have nothing useful to say about them.

Keys are **per-user**, not app-wide: each logged-in user stores their own under Settings -> User Keys (`app/api/user_api_keys.py`), and lookups run under that user's own key/quota — no shared/admin key, no cross-user visibility. Keys are Fernet-encrypted at rest (`app/wifi/collectors/crypto.py`, same `credential_key` used for controller credentials) — decrypted only in memory when a lookup runs or the owning user views their own key. A fifth provider slot, IPQualityScore, can be saved and tested there but isn't consumed by the lookup yet.

MXToolbox's other commands — email/DNS record checks (SPF, DMARC, DKIM, MX, DNS, TXT, SOA, BIMI, MTA-STS, TLSRPT, A, AAAA) and active probes (ping, traceroute, TCP/HTTP/HTTPS/SMTP connect, run from MXToolbox's own infrastructure against the target) — are reachable via `POST /api/mxtoolbox/lookup` (`{command, argument, port?}`, `app/api/mxtoolbox.py`) but aren't surfaced in the UI yet.

---

## Alerting & Notifications

Six built-in condition types (`app/alerts/engine.py`): `ap_down`,
`high_channel_util`, `low_snr`, `high_retry_rate`, `high_client_count`,
`rogue_ap`. Create rules under Alerts -> Rules; the engine evaluates every
30 seconds and auto-resolves an alert once its target is no longer in
violation.

Firing alerts can also dispatch out to five notification channels,
configured under **Settings -> Notifications**: **Slack** (webhook URL +
optional channel override), **Email/SMTP** (host/port/TLS/credentials/
from/default-recipients), **PagerDuty** (Events API v2 integration key),
a generic **Webhook** (URL, POST/PUT, Jinja2 payload template with
`alert_name`/`message`/`severity`/`fired_at` variables), and **TraceCat
SOAR** (workflow webhook URL + optional bearer token). Enabling a channel
here only makes it available — each rule then selects the channels it uses
under **Alerts -> Rules -> Notify on**, and a rule with none selected
records its firings without notifying anyone. Each channel has a **Send
Test** button that performs a real dispatch (actual Slack post, actual SMTP
send, etc.), not a dry run, through the same `app/alerts/notify.py` path a
firing rule takes.

Dispatch happens when an alert *opens* — not repeatedly while it stays open,
and not when it auto-resolves. One rule sends at most ten notifications per
evaluation pass, so a controller taking every access point behind it offline
reads as one incident rather than a hundred pages; the overflow is logged
with the rule name and count, and the Alerts page still lists every event.

---

## Suite Integration

Same token flow as every other pkt app — a suite token identifies pktWiFi
to the whole pkt suite, not just to pktHub specifically (see also
[Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps),
where pktWiFi is the one initiating suite-token calls):

1. Open **Settings -> Security -> Suite Integration** in pktWiFi — a suite
   token is generated automatically (reveal/copy/regenerate available
   inline; regenerating immediately invalidates the old token).
2. Copy it into pktHub's App Manager when registering pktWiFi.
3. pktHub sends `X-Suite-Token` / `X-Suite-User` / `X-Suite-Role` on every
   proxied request; pktWiFi trusts them once the token matches
   (`app/api/suite.py`, `app/dependencies.py`).

### Nav manifest (pktHub's APPS sidebar)

`GET /api/nav/manifest` (`app/api/nav.py`) publishes pktWiFi's own left-nav so
pktHub can mirror it under **APPS** in its sidebar. Entries are
`{path, label, icon, admin_only, divider_before}`. pktHub's health poller
reads the endpoint on every cycle and caches the result, so a page added here
shows up in the hub within one poll interval with no change on the hub side.

Selecting one of those rows opens pktWiFi's **real page** inside pktHub —
proxied, and chromeless so it renders without this app's own sidebar or
header. It is not a re-implementation and cannot drift from what the page
actually does.

`NAV_MANIFEST` in `app/api/nav.py` and `NAV` in
`frontend/src/components/Layout.tsx` are two declarations of one menu, and each
carries a comment pointing at the other — a page added to one belongs in both.
The endpoint is gated by `require_suite_token` for the same reason the widget
endpoints are: it discloses this app's page structure.

`admin_only` controls only what the hub *draws*. The real authorisation is
this app's own role check against the `X-Suite-Role` pktHub asserts.

### Chromeless layout needs a definite height

`Layout.tsx`'s chromeless branch uses `h-screen overflow-auto`, not
`min-h-screen`. A page that fills its container sizes itself with `h-full`,
which resolves against the parent's height — and collapses to zero against an
auto-height parent, rendering blank. Maps and canvases hit this first.

### Widget endpoints now require the suite token

`app/api/widgets.py` previously mounted its router with a bare `APIRouter()`,
so the server-rendered widget views — which read internal data — answered
anyone who could reach the port. The router now carries
`dependencies=[Depends(require_suite_token)]`, matching the NOC Builder's
actual access path. Anything calling those URLs without `X-Suite-Token` now
gets a 401.


---

## Integrating with Sibling pkt Apps

Also under **Settings -> Security -> Suite Integration** — this is the
*other* direction: pktWiFi calling *into* pktsnmp, pktflow, pktlog,
pktpcap, or pktipam as a suite-token client. Unlike the single inbound
token above, this section supports multiple **named connections** — add
as many as you need (e.g. two separate pktsnmp instances for different
sites), each with its own name/app/base URL/token
(`app/api/integrations.py`, allowed `app_name` values: `pktsnmp`,
`pktflow`, `pktlog`, `pktpcap`, `pktipam`, `pkthub`).

1. On the sibling app, open its own Settings -> Security -> Suite
   Integration page and copy its suite token (the same token you'd
   otherwise hand to pktHub).
2. In pktWiFi, click **Add Connection**, pick the app, and paste that app's
   base URL and token.
3. Click **Test Connection** to confirm reachability (this also refreshes
   the connection's health status shown in the list).

**Verify TLS certificate** is on for any connection added from here. Every
call carries that sibling's suite token in a header, so an unverified HTTPS
connection lets anything on the path present a certificate and collect it.
Turn it off only for an on-prem sibling behind a self-signed certificate.
Connections that predate this option keep verification off — they were
configured and tested against a client that never verified, and switching
them over silently would break them with a certificate error; tick the box
on each once its certificate is trusted.

Each call also presents the *asking user's* own role and username to the
sibling (`X-Suite-Role` / `X-Suite-User`), so the sibling applies its own
permissions to the real person and records them in its audit trail rather
than seeing every request as an anonymous administrator.

Deleting a connection here isn't destructive to the sibling app — anything
in pktWiFi that depended on it (e.g. AP inventory context from pktsnmp,
syslog context from pktLog) just stops working until it's reconfigured.
This is intentionally the same mechanism used for pktHub -> app proxying,
just initiated by pktWiFi instead of pktHub. See `app/integrations/` and
`app/api/integrations.py`.

---

## Backup, Retention & Restore

**Settings -> Data -> Backups -> "Run Backup Now"**, or let the built-in
scheduler run on the configured interval (`backup_enabled` /
`backup_interval_hours` / `backup_rotation_count` / `backup_path`
settings, same tab). Each snapshot is a timestamped directory under
`<install_dir>/backups/` (or your configured `backup_path`) containing
`pktwifi.db` (settings, access points, collectors, alert rules, users) and
`config.yaml`. Rotation count caps how many snapshots stay on disk — the
oldest is deleted automatically once you exceed it.

Each listed snapshot has a **Restore…** link that restores directly from
that on-server snapshot — no download/upload round trip required.
Expanding it shows a checkbox per file present in the snapshot
(`pktwifi.db`, `config.yaml`), so you can restore just one piece instead
of always restoring both together. A full bundle can also be downloaded
(**Export bundle**) or uploaded (**Restore from bundle**), with the same
per-file selection available on upload. Every restore requires
confirmation and, for `config.yaml` changes, a service restart to take
effect.

Separately, **Settings -> Data -> Storage** controls *retention*, not
backup: how many days resolved alert events and raw RF metric history
stick around before a background job (or a manual **Run Cleanup Now**)
deletes them — this trims the live database, it isn't related to the
backup snapshots above.

---

### Backup integrity

Database snapshots are taken through SQLite's own online-backup API and then
verified with `PRAGMA integrity_check`; a snapshot that does not pass is logged
loudly and not counted as usable.

This matters more than it sounds. The database runs in WAL mode, so at any
instant the committed state is split between the `.db` file and its `-wal`
sidecar. The previous implementation copied the `.db` alone with `shutil.copy2`,
which captures neither a consistent snapshot nor the most recent commits — the
worst possible failure mode for the one artifact you reach for in an emergency,
because it looks like a backup either way.


## Troubleshooting

**Web UI shows `{"detail":"Not Found"}`** — the frontend wasn't built.
Run `cd frontend && npm install && npm run build`, then
`sudo systemctl restart pktwifi` (or use Settings -> General -> Restart
Service once the UI itself is reachable).

**Controller shows `status: error`** — check `last_error` on the
`Settings -> Controllers` page, or click **Poll Now** to get the full error
in a copyable modal (the **Test Credentials** button in the controller form
is often faster for isolating an auth problem before it ever gets to a real
poll). For SNMP controllers this is almost always a reachability/
community-string/v3-credential mismatch; for vendor API controllers, an
auth or base-URL problem. For UniFi specifically, an error naming "no site
found" usually means the **Site** field doesn't match either the display
name or slug the controller actually has — see the site-slug note under
[Vendor Collectors](#vendor-collectors).

**No RF data despite an "online" AP** — the generic SNMP collector only
guarantees reachability (`sysUpTime`) and a best-effort standard-MIB
channel read; real channel utilization/tx-power/noise-floor numbers need a
vendor-native collector (Meraki, UniFi) or a future Aruba/Catalyst/Ruckus
integration — see [Vendor Collectors](#vendor-collectors).

**Clients all show "Unassigned" with no channel** — expected for a UniFi
controller in API-key auth mode; that mode's Integration API doesn't
attribute clients to a radio at all, so there's no channel to group by.
Switch the controller to username/password auth for real per-client
channel/SSID/signal/rate detail — see
[Ubiquiti UniFi — two auth methods](#ubiquiti-unifi--two-auth-methods).



---

## Development

```bash
# Backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
PKTWIFI_ADMIN_PASSWORD=devpassword uvicorn app.main:app --reload --port 8769

# Frontend (separate terminal)
cd frontend && npm install && npm run dev   # http://localhost:5175, proxies /api to :8769
```

---

## Known Gaps / Fast-Follow Work

- **Aruba Central, Cisco Catalyst/AireOS, and Ruckus/SmartZone collectors**
  are documented stubs, not working integrations — see
  [Vendor Collectors](#vendor-collectors).
- **Cisco Meraki collector is unverified against a live organization** —
  built against the documented API v1 shape; field mappings should be
  spot-checked against a real Dashboard response.
- **UniFi API-key auth mode reports no per-client SSID/RSSI/rate/radio
  attribution** — verified against a live UDM-Pro that this is a real
  limitation of Ubiquiti's Integration API itself (confirmed by inspecting
  the raw client payload), not a parsing gap. AP-level detail (online/
  offline, per-radio channel/width, tx-retry-%) works correctly in this
  mode; only per-client detail is coarse. Use username/password auth mode
  for full per-client detail — see
  [Ubiquiti UniFi — two auth methods](#ubiquiti-unifi--two-auth-methods).
- **No floor-plan heatmaps or spectrum-analysis integration yet.**
- **Single SQLite storage backend for RF metric history** — pktsnmp's
  ClickHouse/DuckDB backend abstraction (`app/storage/`) was deliberately
  not ported in v1; Settings -> Data -> Storage only exposes retention
  windows, not a backend picker. If RF metric volume grows large enough to
  matter, follow that same abstraction pattern.
- **pktIPAM has no dedicated suite-integration client module yet** — it's
  a selectable, connectable app under Suite Integration, but
  `app/integrations/` doesn't yet ship a `pktipam_client.py` the way it
  does for pktsnmp/pktflow/pktlog/pktpcap.

## Resonance (embedded assistant)

Resonance is the suite's shared assistant. It mounts as a launcher in the bottom corner of every
authenticated page, but the assistant itself runs on the resonance server, not inside pktWiFi.
Configure it under **Settings → Resonance** (admin only); every field ships blank, so a fresh
install shows nothing until it is pointed at a resonance server of its own.

`app/integrations/resonance/` and `frontend/src/resonance/` are **vendored** — copied between
pkt\* apps byte-for-byte except for `APP_SLUG`. They are deliberately not a published package,
because `install.sh` builds a venv on customer hosts and a private index would put a credentialed
network dependency in the middle of every install. pktLog is the reference implementation.

```
browser                 pktWiFi                       resonance
embed.js  ──GET──▶  /api/resonance/code  ──POST──▶  /embed/session
          ◀─code──                        ◀─code───
frame ──────────────────────────────────────────────▶  /embed?c=<code>
```

pktWiFi vouches for whoever is signed in and receives a short-lived, single-use code. The key is
encrypted at rest, never reaches the browser, and resonance never sees a pktWiFi credential.
`GET /api/resonance/code` is the one cookie-authenticated route in the app — `embed.js` fetches it
itself, outside the SPA, and the access token lives in memory — so `Sec-Fetch-Site` and `Origin`
are both checked before the cookie is honoured.

**The data surface.** Two documents let resonance discover what it may call, both public because
they carry names rather than data:

| path | what it is |
|---|---|
| `/.well-known/resonance.json` | the grant — the operations this install permits |
| `/api/resonance/openapi.json` | those operations' OpenAPI, narrowed from the app's own |
| `/api/resonance/docs` | the shipped guides, for resonance to ingest (suite token or admin) |

Point resonance's **READ SPEC** at `/api/resonance/openapi.json`. The published operations are:

- `getWifiSummary`
- `listAccessPoints`
- `getAccessPoint`
- `listWifiClients`
- `listRadios`
- `listCollectors`
- `listAlertEvents`
- `listAlertRules`
- `searchApplicationLog`
- `ackAlertEvent`  *(writes)*
- `ackAllAlertEvents`  *(writes)*

Every call is made by pktWiFi's own page, same-origin, on the session of the person already signed
in, so nothing here reaches data that person could not already open. Which operations exist is
fixed in `app/api/resonance_data.py`, not configurable per install. Write operations are withheld
from the grant entirely until an administrator sets a role to **Read and write**.

**Never exposed:** a collector's stored controller credentials. Nothing here changes a channel or transmit power, deauthenticates a client, or creates, edits or deletes an access point, SSID, radio or collector. The app has no rule-toggle endpoint, so the assistant's writes are acknowledge-only.

## Log Forwarding

pktWiFi writes its own application log to the in-app **Logs** page. It can also
ship that log to a syslog collector — normally **pktLog**, which listens on
port `5514` — so this app's events sit alongside the rest of the estate.

Settings keys (Settings → Data → Log Forwarding in apps that expose the UI;
otherwise via `PUT /api/settings`):

| Key | Default | Meaning |
|---|---|---|
| `log_forward_enabled` | `false` | Turn forwarding on |
| `log_forward_host` | `""` | Collector hostname or IP |
| `log_forward_port` | `5514` | pktLog's syslog port |
| `log_forward_protocol` | `udp` | `udp` or `tcp` |
| `log_forward_level` | `INFO` | Minimum level forwarded |
| `log_forward_app_name` | `pktwifi` | APP-NAME in the syslog message |

Admin endpoints:

- `GET  /api/system/log-forward/status` — delivery counters (sent, dropped, errors)
- `POST /api/system/log-forward/test` — send one test line without saving settings
- `POST /api/system/log-forward/reload` — apply settings changes without a restart

**Format is RFC 5424, deliberately.** pktLog parses both 3164 and 5424, but
3164 timestamps carry no timezone and the collector has to guess the offset —
which has produced wrong timestamps in this suite before. 5424 carries a full
offset, so there is nothing to guess.

**Delivery is fire-and-forget** on a background thread, with counters. Log
forwarding must never block or crash the thing it observes: a dropped line is a
nuisance, a stalled collector loop is an outage. If the collector is
unreachable, lines are dropped and counted rather than raised.

### If forwarded logs never arrive

**pktLog drops syslog from sources that are not registered.** Its
`collector_registry` gates what is allowed to persist, so the sending host's IP
must be present *and enabled* under pktLog's Settings → Collectors. Until then
the messages are accepted on the wire and silently discarded — the sender sees
a successful send either way, because UDP cannot tell it otherwise. pktLog also
caches that registry for five minutes, so a newly enabled source is not live
immediately.

Use the **Send test message** button (or the `test` endpoint) to confirm the
path end to end rather than assuming it works.

