# pktWiFi

<p align="center">
  <img src="lockup-256h.png" alt="pktWiFi" height="64">
</p>

Enterprise WiFi analyzer — part of the pkt suite. Aggregates access point,
RF/channel, and client data from your own SNMP polling or vendor controller
APIs, plus device/traffic/log context pulled from sibling pkt* apps
(pktsnmp, pktflow, pktlog, pktpcap, pktipam) over suite-token API calls, and
surfaces it through a React UI with alerting and an optional in-app AI
assistant.

**Default port:** `8769` (HTTP)

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Frontend Build & Deploy](#frontend-build--deploy)
- [Feature Inventory](#feature-inventory)
- [Sites](#sites)
- [Vendor Collectors](#vendor-collectors)
- [Configuration Reference](#configuration-reference)
- [Running & Managing the Service](#running--managing-the-service)
- [Settings](#settings)
- [Roles & Auth](#roles--auth)
- [IP Intelligence Lookup](#ip-intelligence-lookup)
- [Alerting & Notifications](#alerting--notifications)
- [AI Assistant](#ai-assistant)
- [Suite Integration](#suite-integration)
- [Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps)
- [Backup, Retention & Restore](#backup-retention--restore)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Known Gaps / Fast-Follow Work](#known-gaps--fast-follow-work)

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

Everything else — Dashboard, Access Points, Clients, Alerts, Logs,
Collectors, Sites, Settings — is standard FastAPI routers under `app/api/`
serving a React SPA (`frontend/`) built with Vite. See
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
| **Access Points** | all roles | Full AP inventory across every collector — status, vendor, model, firmware, per-radio channel/utilization/noise-floor where the collector supplies it. |
| **Clients** | all roles | Connected client list with RSSI/SNR, SSID, protocol, tx/rx rate, which AP/radio they're attached to. |
| **Alerts** | all roles (analyst+ can ack/resolve) | Alert rules + fired events; see [Alerting & Notifications](#alerting--notifications). |
| **Logs** | all roles | AP/controller syslog and event context, including anything pulled in via the pktLog suite integration. |
| **Collectors** | admin only | Add/edit/delete/poll vendor collectors through a schema-driven form; see [Vendor Collectors](#vendor-collectors). |
| **Sites** | admin only | Small managed catalog of location names/descriptions; see [Sites](#sites). |
| **Settings** | admin only | General, Security (Users/Auth/Suite Integration/AI Assistant/SSL-TLS), Data (Storage/Backups), Notifications, User Keys, System; see [Settings](#settings). |

There's also a floating **AI Assistant** chat button available from any
authenticated page (not a nav item) — see [AI Assistant](#ai-assistant).

The standalone "Integrations" page from earlier builds no longer exists;
`/integrations` now redirects straight to `/settings`. Both directions of
suite integration (the inbound token pktHub uses to proxy in, and the
outbound connections pktWiFi uses to call into sibling apps) live under
**Settings -> Security -> Suite Integration** — see
[Suite Integration](#suite-integration) and
[Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps).

---

## Sites

**Sites** (its own admin-only sidebar item, separate from Settings) is a
small managed catalog — just a name and an optional description per row
(`app/api/sites.py`, `sites` table). Its only purpose is to populate the **Site** dropdown that appears
in collector config forms (the SNMP generic collector's per-host `site`
field, and the UniFi collector's top-level `site` field) instead of
free-typing a location name and risking typo'd duplicates ("HQ" / "Hq" /
"headquarters" all meaning the same place).

Deleting a site here does not touch collectors already referencing that
name — it just stops showing up as a dropdown choice going forward.

**Do not confuse this with a UniFi controller's own "Site" concept.** A
UniFi controller/UDM can itself be multi-site, and each of its sites has
both a display name (shown in the UniFi UI) and a separate URL slug (never
shown in the UI). When configuring a UniFi collector, the value you put in
the **Site** field here should match how you refer to that location — the
collector resolves it against the controller's actual sites at poll time
regardless of whether you typed the display name or the slug (see
[Vendor Collectors](#vendor-collectors) and
[docs/collector-setup.md](docs/collector-setup.md) for the exact
resolution behavior and its gotchas).

---

## Vendor Collectors

Configured under **Collectors** in the UI (admin only). Each collector is
one row: a name, a type, a poll interval, an enabled toggle, and a config
form. As of the structured-config rebuild, that form is **schema-driven**
(`app/wifi/collectors/field_schema.py` + `frontend/src/components/
CollectorConfigForm.tsx`) — fields render as real text/password/number/
toggle/select/multiselect/host-list/site-picker inputs with per-field help
text and conditional (`show_if`) fields, instead of a raw JSON textarea.
An **"Edit as JSON"** link is still available in the Collector modal as an
escape hatch/power-user path — it round-trips through the same config dict.
Secret fields (API keys, passwords, SNMP v3 auth) are Fernet-encrypted at
rest using `credential_key` (see
[Configuration Reference](#configuration-reference)).

Each collector row has a **Poll Now** action that polls immediately
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
  (channel/utilization/noise-floor) and per-client detail. Use a dedicated
  local (non-cloud) read-only admin account, not your own login.
- **API key** — Ubiquiti's official local Network Integration API v1
  (`/proxy/network/integration/v1`), authenticated with an `X-API-KEY`
  header. Only available on a UniFi OS console (UDM/UDM-Pro/Cloud Gateway)
  with Integrations enabled under Settings -> Control Plane ->
  Integrations in the UniFi UI — no standalone-controller equivalent
  exists. This mode is coarser: it's an intentionally limited API subset,
  so it reports online/offline status only, with no per-radio breakdown
  (empty radios list). Not yet verified against live UniFi OS hardware.

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

Admin-only, reached via the **Settings** nav item. Organized as six
top-level tabs, two of which have their own left-hand sub-tab strip:

| Tab | Sub-tabs | Covers |
|---|---|---|
| **General** | — | App name, timezone, **Port** (writes `config.yaml`, needs a restart to take effect), Base URL (feeds SAML ACS/metadata URLs), and the **Restart Service** button. |
| **Security** | Users, Auth, Suite Integration, AI Assistant, SSL / TLS | See below. |
| **Data** | Storage, Backups | See below. |
| **Notifications** | — | Alert-channel config: Slack, Email (SMTP), PagerDuty, generic Webhook, TraceCat SOAR — see [Alerting & Notifications](#alerting--notifications). |
| **User Keys** | — | Personal (per-user, not shared) external API keys — currently a Lucidchart Personal Access Token, used for exporting diagrams. Each user manages their own; nobody else, including admins, can see another user's key value. |
| **System** | — | Read-only version + install directory display. |

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
- **AI Assistant** — Anthropic API key + model picker for the in-app AI
  assistant. See [AI Assistant](#ai-assistant).
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

Three roles: `admin` (full access, including Collectors/Sites/Settings/
Users), `analyst` (can edit access points, ack/resolve alerts), `viewer`
(read-only).

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

Keys are **per-user**, not app-wide: each logged-in user stores their own under Settings -> User Keys (`app/api/user_api_keys.py`), and lookups run under that user's own key/quota — no shared/admin key, no cross-user visibility. A fifth provider slot, IPQualityScore, can be saved and tested there but isn't consumed by the lookup yet.

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
here only makes it available — an alert rule still has to be configured to
use it. Each channel has a **Send Test** button that performs a real
dispatch (actual Slack post, actual SMTP send, etc.), not a dry run.

---

## AI Assistant

A floating chat button (bottom-right, available from any authenticated
page — `frontend/src/components/AiAssistant.tsx`) opens a slide-in drawer
that sends your question, plus optional structured context from the
current view (AP status, client counts, SNR/RSSI, alerts), to Claude via
`POST /api/ai/chat` (`app/api/ai.py`). It's meant for network engineers to
get a quick read on WiFi health data or a nudge on next diagnostic steps
without leaving the page.

Requires its own Anthropic API key — set at **Settings -> Security -> AI
Assistant**, separate from any Claude Enterprise seat (get one at
console.anthropic.com). Also pick a model there; Claude Haiku is the
default (fastest/cheapest for this kind of question), with Sonnet and
Opus available for harder cases. Until a key is set, the chat drawer
explains it needs configuring rather than silently failing.

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

Separately, **Settings -> Data -> Storage** controls *retention*, not
backup: how many days resolved alert events and raw RF metric history
stick around before a background job (or a manual **Run Cleanup Now**)
deletes them — this trims the live database, it isn't related to the
backup snapshots above.

---

## Troubleshooting

**Web UI shows `{"detail":"Not Found"}`** — the frontend wasn't built.
Run `cd frontend && npm install && npm run build`, then
`sudo systemctl restart pktwifi` (or use Settings -> General -> Restart
Service once the UI itself is reachable).

**Collector shows `status: error`** — check `last_error` on the Collectors
page, or click **Poll Now** to get the full error in a copyable modal. For
SNMP collectors this is almost always a reachability/community-string/
v3-credential mismatch; for vendor API collectors, an auth or base-URL
problem. For UniFi specifically, an error naming "no site found" usually
means the **Site** field doesn't match either the display name or slug the
controller actually has — see the site-slug note under
[Vendor Collectors](#vendor-collectors).

**No RF data despite an "online" AP** — the generic SNMP collector only
guarantees reachability (`sysUpTime`) and a best-effort standard-MIB
channel read; real channel utilization/tx-power/noise-floor numbers need a
vendor-native collector (Meraki, UniFi) or a future Aruba/Catalyst/Ruckus
integration — see [Vendor Collectors](#vendor-collectors).

**AI Assistant says it's not configured** — set an Anthropic API key at
Settings -> Security -> AI Assistant; see [AI Assistant](#ai-assistant).

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
- **UniFi API-key auth mode is unverified against live UniFi OS hardware**
  — built against Ubiquiti's published Integration API v1 docs; the
  username/password auth mode has been confirmed against real gear
  (site-slug resolution, CSRF token, redirect-following).
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
