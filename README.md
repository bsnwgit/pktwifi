# pktWiFi

Enterprise WiFi analyzer — part of the pkt suite. Aggregates access point,
RF/channel, and client data from your own SNMP polling or vendor controller
APIs, plus device/traffic/log context pulled from sibling pkt* apps
(pktsnmp, pktflow, pktlog, pktpcap) over suite-token API calls, and surfaces
it through a React UI with alerting.

**Default port:** `8769` (HTTP)

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Frontend Build & Deploy](#frontend-build--deploy)
- [Vendor Collectors](#vendor-collectors)
- [Configuration Reference](#configuration-reference)
- [Running & Managing the Service](#running--managing-the-service)
- [Roles & Auth](#roles--auth)
- [Alerting](#alerting)
- [Suite Integration](#suite-integration)
- [Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps)
- [Backup & Restore](#backup--restore)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Known Gaps / Fast-Follow Work](#known-gaps--fast-follow-work)

---

## Quick Start

```bash
# 1. Clone the repository
git clone git@github.com:bsnwgit/pktwifi.git
cd pktwifi

# 2. Run the installer — prompts for an install directory (default /opt/pktwifi),
#    then handles system packages, Python venv, config.yaml + secret/credential
#    keys, DB migrations, admin user, frontend build (if npm is present), and
#    the systemd service (installed + started)
bash install.sh

# Prints the admin password at the end — save it, it is not shown again.

# 3. Open the firewall for the app port
sudo ufw allow 8769/tcp

# 4. Open http://<server-ip>:8769 and log in with the admin credentials from step 2
```

### Environment variables

`install.sh` honors the following overrides (skips the interactive prompt when set):

| Variable | Default | Description |
|---|---|---|
| `PKTWIFI_INSTALL_DIR` | `/opt/pktwifi` | App root — every other path defaults to somewhere under this |
| `PKTWIFI_LOG_DIR` | `$PKTWIFI_INSTALL_DIR/logs` | Log file directory |
| `PKTWIFI_SERVICE_USER` | current user | systemd service user |
| `PKTWIFI_SERVICE_GROUP` | same as service user | systemd service group |

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
   suite-token *client* of pktsnmp/pktflow/pktlog/pktpcap, reusing data
   those apps already collect (generic device/interface polling, traffic
   flows, syslogs, packet captures) instead of re-implementing any of it.
   This is the same token mechanism pktHub uses to proxy into every pkt
   app, just used in the other direction — see
   [Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps).

---

## Requirements

- Ubuntu Server 22.04/24.04 LTS (install.sh targets this; other Linux
  distros likely work with manual package-manager substitution)
- Python 3.10+
- Node.js + npm (only needed to build the frontend — see
  [Frontend Build & Deploy](#frontend-build--deploy))

---

## Installation

See [Quick Start](#quick-start). `install.sh` is idempotent-ish: re-running
it will not overwrite an existing `config.yaml`, and skips the copy step
entirely when run in-place inside the repo checkout (`REPO_DIR == INSTALL_DIR`).

No source file hardcodes an absolute install path — `install_dir` is
resolved at runtime (env var -> config.yaml location -> cwd) and every
other path (db, logs, ssl, backups) is derived from it. See
`app/config.py`.

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

## Vendor Collectors

Configured under **Collectors** in the UI. Each collector is one row:
a type, a poll interval, and a JSON config blob whose secret fields
(API keys, passwords, SNMP v3 auth) are Fernet-encrypted at rest using
`credential_key` (see [Configuration Reference](#configuration-reference)).

| Type | Status | Notes |
|---|---|---|
| Generic SNMP | Implemented | Vendor-neutral: sysUpTime reachability + best-effort standard `dot11` MIB channel walk. See `app/wifi/collectors/snmp_generic.py`. |
| Cisco Meraki | Implemented | Dashboard API v1. Written against the documented API shape but not exercised against a live org in this build — spot-check field mappings in `app/wifi/collectors/cisco_meraki.py` against a real response. |
| Ubiquiti UniFi | Implemented | Classic controller REST API (`/api/s/<site>/stat/device`, `/stat/sta`); supports both standalone controllers and UDM/UDM-Pro via the `udm` config flag. |
| Aruba Central / Aruba Networking | Not implemented | Stub with implementation notes in `app/wifi/collectors/aruba_central.py`. |
| Cisco Catalyst 9800 / AireOS | Not implemented | Stub with implementation notes in `app/wifi/collectors/cisco_catalyst.py`. |
| Ruckus / SmartZone | Not implemented | Stub with implementation notes in `app/wifi/collectors/ruckus.py`. |

Add a new vendor by writing a `Collector` subclass (see `base.py` for the
`AccessPointReading`/`RadioReading`/`ClientReading` shapes) and registering
it in `app/wifi/collectors/registry.py`. See also
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
| `suite_token` | pktHub inbound token — managed via the Integrations page, not hand-edited |

---

## Running & Managing the Service

```bash
sudo systemctl status pktwifi
sudo systemctl restart pktwifi
journalctl -u pktwifi -f
```

---

## Roles & Auth

Three roles: `admin` (full access, including Collectors/Integrations/Settings/Users),
`analyst` (can edit access points, ack/resolve alerts), `viewer` (read-only).

Local username/password auth is always available; SAML 2.0 SSO can be
layered on top via Settings (same IdP-agnostic implementation as pktsnmp/
pktflow — `app/auth/saml.py`). When pktHub proxies a request with a valid
`X-Suite-Token`, the `X-Suite-Role` header maps directly onto these three
roles (see `app/dependencies.py`).

---

## Alerting

Six built-in condition types (`app/alerts/engine.py`): `ap_down`,
`high_channel_util`, `low_snr`, `high_retry_rate`, `high_client_count`,
`rogue_ap`. Create rules under Alerts -> Rules; the engine evaluates every
30 seconds and auto-resolves an alert once its target is no longer in
violation.

---

## Suite Integration

Same token flow as every other pkt app — a suite token identifies pktWiFi to the whole pkt suite, not just to pktHub specifically (see also [Integrating with Sibling pkt Apps](#integrating-with-sibling-pkt-apps), where pktWiFi is the one initiating suite-token calls):

1. Open **Integrations** in pktWiFi — a suite token is generated automatically.
2. Copy it into pktHub's App Manager when registering pktWiFi.
3. pktHub sends `X-Suite-Token` / `X-Suite-User` / `X-Suite-Role` on every
   proxied request; pktWiFi trusts them once the token matches
   (`app/api/suite.py`, `app/dependencies.py`).

---

## Integrating with Sibling pkt Apps

Also under **Integrations** — this is the *other* direction: pktWiFi calling
*into* pktsnmp/pktflow/pktlog/pktpcap as a suite-token client.

1. On the sibling app, open its own Settings -> Integrations page and copy
   its suite token (the same token you'd otherwise hand to pktHub).
2. Paste that app's base URL and token into pktWiFi's Integrations page.
3. Click **Test Connection** to confirm reachability.

This is intentionally the same mechanism used for pktHub -> app proxying,
just initiated by pktWiFi instead of pktHub. See `app/integrations/`.

---

## Backup & Restore

Settings -> System -> "Run backup now", or let the built-in scheduler run
on the configured interval (`backup_enabled` / `backup_interval_hours` /
`backup_rotation_count` settings). Each snapshot is a timestamped directory
under `<install_dir>/backups/` containing `pktwifi.db` + `config.yaml`.

---

## Troubleshooting

**Web UI shows `{"detail":"Not Found"}`** — the frontend wasn't built.
Run `cd frontend && npm install && npm run build`, then
`sudo systemctl restart pktwifi`.

**Collector shows `status: error`** — check `last_error` on the Collectors
page; for SNMP collectors this is almost always a reachability/community-
string/v3-credential mismatch, for vendor API collectors an auth or
base-URL problem.

**No RF data despite an "online" AP** — the generic SNMP collector only
guarantees reachability (`sysUpTime`) and a best-effort standard-MIB
channel read; real channel utilization/tx-power/noise-floor numbers need a
vendor-native collector (Meraki, UniFi) or a future Aruba/Catalyst/Ruckus
integration — see [Vendor Collectors](#vendor-collectors).

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

This is a first build, scoped deliberately to ship something real rather
than everything at once:

- **Aruba Central, Cisco Catalyst/AireOS, and Ruckus/SmartZone collectors**
  are documented stubs, not working integrations — see
  [Vendor Collectors](#vendor-collectors).
- **Cisco Meraki collector is unverified against a live organization** —
  built against the documented API v1 shape; field mappings should be
  spot-checked against a real Dashboard response.
- **No floor-plan heatmaps or spectrum-analysis integration yet.**
- **Single SQLite storage backend for RF metric history** — pktsnmp's
  ClickHouse/DuckDB backend abstraction (`app/storage/`) was deliberately
  not ported in v1; if RF metric volume grows large enough to matter,
  follow that same abstraction pattern.
- **No email/webhook alert notifications** — alert events surface in-app
  only for now (Alerts page + sidebar badge).
