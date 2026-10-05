# pktWiFi — Troubleshooting

Symptom, cause, and the command that proves which cause it is.

`<INSTALL_DIR>` is the install directory (`/opt/pktwifi` by default).
Collector setup itself is in [collector-setup.md](collector-setup.md).

---

## Contents

- [The first five minutes](#the-first-five-minutes)
- [The service will not start](#the-service-will-not-start)
- [The service runs but nothing answers](#the-service-runs-but-nothing-answers)
- [The UI is blank, stale, or 404](#the-ui-is-blank-stale-or-404)
- [Login and accounts](#login-and-accounts)
- [Which collectors actually exist](#which-collectors-actually-exist)
- [UniFi](#unifi)
- [Cisco Meraki](#cisco-meraki)
- [Generic SNMP](#generic-snmp)
- [Data is missing or thin](#data-is-missing-or-thin)
- [Cross-app context is empty](#cross-app-context-is-empty)
- [Alerts and notifications](#alerts-and-notifications)
- [A config change did not take effect](#a-config-change-did-not-take-effect)
- [TLS / HTTPS](#tls--https)
- [Backup, upgrades and uninstall](#backup-upgrades-and-uninstall)
- [What to capture before reporting a problem](#what-to-capture-before-reporting-a-problem)

---

## The first five minutes

```bash
sudo systemctl status pktwifi --no-pager
```

```bash
sudo journalctl -u pktwifi -n 100 --no-pager
```

```bash
sudo tail -n 100 <INSTALL_DIR>/logs/pktwifi.log
```

```bash
sudo ss -ltnp | grep 8769
```

```bash
curl -s http://127.0.0.1:8769/api/health
```

| What you see | Go to |
|---|---|
| `inactive (dead)` or `failed` | [The service will not start](#the-service-will-not-start) |
| Running, nothing on 8769 | [The service runs but nothing answers](#the-service-runs-but-nothing-answers) |
| Health 200, UI blank or 404 | [The UI is blank, stale, or 404](#the-ui-is-blank-stale-or-404) |
| Health 200, no APs or clients | [Which collectors actually exist](#which-collectors-actually-exist) |

The Controllers page shows `status` and `last_error` per collector, **Poll Now**
returns the full error in a copyable modal, and **Test Credentials** isolates an
auth problem faster than a full poll. Use those three before anything else.

---

## The service will not start

```bash
sudo journalctl -u pktwifi -n 200 --no-pager
sudo tail -n 200 <INSTALL_DIR>/logs/pktwifi.log
```

Reproduce in the foreground:

```bash
sudo -u <service-user> \
  PKTWIFI_CONFIG=<INSTALL_DIR>/config.yaml \
  PKTWIFI_INSTALL_DIR=<INSTALL_DIR> \
  <INSTALL_DIR>/venv/bin/python -m app.server
```

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` | venv missing packages, or built against a different Python | `<INSTALL_DIR>/venv/bin/pip install -r requirements.txt` |
| `yaml.scanner.ScannerError` | `config.yaml` is not valid YAML | `python3 -c "import yaml; yaml.safe_load(open('<INSTALL_DIR>/config.yaml'))"` |
| Complaint about `secret_key` / `credential_key` | Left at `CHANGE_ME_…` | `openssl rand -hex 32`; and `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `Address already in use` | Something else holds 8769 | `sudo ss -ltnp \| grep 8769` |
| Fernet `InvalidToken` | `credential_key` changed after collector credentials were stored | Every controller credential is encrypted with it — see [A config change did not take effect](#a-config-change-did-not-take-effect) |
| `Permission denied` on DB or logs | Install dir not owned by the service user | `sudo chown -R <service-user>:<service-group> <INSTALL_DIR>` |

`Restart=on-failure`, burst limit 3 in 60s — after that it stays `failed`. Read
the first failure, not just the last.

---

## The service runs but nothing answers

```bash
sudo ss -ltnp | grep 8769
curl -sv http://127.0.0.1:8769/api/health
```

`host:` and `port:` come from `config.yaml` at every process start — a port
change needs a restart, never a unit edit. Bound to `127.0.0.1` is loopback
only. If loopback works and nothing else does, it is the firewall or routing.

---

## The UI is blank, stale, or 404

| Symptom | Cause | Fix |
|---|---|---|
| `{"detail":"Not Found"}` at the root | The frontend was never built | `cd frontend && npm install && npm run build`, then restart. Node.js 20.x LTS is a prerequisite `install.sh` does not install |
| Blank page, console 404s on `/assets/*` | `dist` stale or half-built | Rebuild, then hard-refresh |
| Old UI after an upgrade | Cached `index.html` pinning old bundles | Hard refresh (Ctrl/Cmd-Shift-R) |
| Every API call 401 | Session expired | See [Login and accounts](#login-and-accounts) |

---

## Login and accounts

bcrypt plus JWT. Roles `admin` / `analyst` / `viewer`.

| Symptom | Cause | Fix |
|---|---|---|
| 401 immediately after logging in | Clock skew invalidates the token's `exp` | `timedatectl`; fix NTP |
| Cannot see or edit controllers | Collector management is admin-only | Needs `admin` |
| "This account is locked after repeated failed logins" | Too many failed logins: locked 30 minutes the first time, until an admin unlocks it the second time | An admin clicks the unlock icon on Settings -> Security -> Users, or run `scripts/unlock_user.py <username>` on the server |
| Locked out of every account | No admin session left, or the only admin is locked | Unlock with `scripts/unlock_user.py`; otherwise reset the hash against SQLite using the app's own venv for bcrypt |

```bash
<INSTALL_DIR>/venv/bin/python -c "import bcrypt; print(bcrypt.hashpw(b'NewPassword1!', bcrypt.gensalt()).decode())"
```

---

## Which collectors actually exist

**Three are implemented. Three are stubs and say so in their own label.**

| Type | Status |
|---|---|
| Generic SNMP (vendor-neutral) | Implemented |
| Cisco Meraki (Dashboard API) | Implemented |
| Ubiquiti UniFi (Controller API) | Implemented |
| Aruba Central / Aruba Networking | **Not implemented** |
| Cisco Catalyst 9800 / AireOS | **Not implemented** |
| Ruckus / SmartZone | **Not implemented** |

Selecting one of the bottom three and polling returns *"Collector type is not
implemented yet"*. That is not a fault to diagnose — the label carries "(not yet
implemented)" for exactly this reason. For Aruba, Catalyst or Ruckus hardware,
use Generic SNMP instead and accept the reduced RF detail described below.

---

## UniFi

Persistent 401s against UniFi are almost always one of four things, and three of
them are not the password.

### The site is a slug, not the name you see

**The UniFi UI's "Site name" is the `desc` field. The API wants the `name`
slug.** Using the display name directly returns 401.

The collector resolves this against `GET /self/sites`, but a manually entered
site must be the slug. The default is `default`, which is correct for a
single-site controller.

### The login must go straight to HTTPS

A UDM-Pro 301-redirects `http://<ip>/api/auth/login` to the HTTPS URL. Letting
the client auto-follow that redirect turns the login POST into a **bodyless
GET** — the JSON credentials are dropped on the hop, and you get a 401 the
actual credentials never caused.

The collector posts straight to the HTTPS URL for this reason. If you are
testing by hand with `curl`, do the same: do not use `-L` against the HTTP URL.

### The CSRF token must be echoed

Login returns an `x-csrf-token` response header. Every subsequent proxied
`/proxy/network/api/*` call 401s without it, **even with a valid session
cookie**. A hand-rolled test that omits it will look like an auth failure.

### UDM and non-UDM have different login paths

| Device | Login path |
|---|---|
| UDM / UDM-Pro / UniFi OS | `/api/auth/login` |
| Classic controller | `/api/login` |

Pointing the wrong one at a controller returns 404 or 401 rather than anything
descriptive.

### Other UniFi failure modes

| Symptom | Cause |
|---|---|
| Works, then 401s later | Session expired, or the account is being logged out elsewhere |
| Certificate error | Self-signed controller certificate |
| Some APs missing | They are on a different site than the one configured |
| API-key auth fails | The API-key header is only available on the UniFi Integration API — not on the classic controller API |
| Lists come back short | The Integration API paginates every list endpoint; a hand-rolled test that reads page one only will under-report |

---

## Cisco Meraki

Config is an API key, an organization ID, and optionally a list of network IDs.

| Symptom | Cause |
|---|---|
| 401 from the Dashboard API | Wrong API key. Generate it under Dashboard → My Profile → API access, and confirm API access is enabled for the org |
| Empty results | Wrong `organization_id`. Find it with `GET /organizations` |
| Only some networks appear | `network_ids` is set and restricts the scope. Leave it empty for all wireless networks in the org |
| Rate-limited | The Dashboard API has its own limits — raise the poll interval |
| **Radio, channel or utilisation fields look wrong or empty** | This is a documented caveat, not necessarily a bug |

On that last row, from the collector itself:

> this integration has been written against the documented API v1 shape but has
> not been exercised against a live Meraki organization in this build session —
> field names for radio/channel/utilization data in particular should be
> spot-checked against a real dashboard response and adjusted here if Meraki's
> API has moved fields since.
> — [`app/wifi/collectors/cisco_meraki.py`](../app/wifi/collectors/cisco_meraki.py)

So: if AP inventory arrives but RF detail is blank, compare a raw Dashboard API
response against what the collector expects before treating it as a
configuration problem.

---

## Generic SNMP

Polls a fixed list of AP or controller IPs using the standard IEEE 802.11 MIB
plus `sysUpTime` for reachability.

Config takes `version` (`v2c` or `v3`), the matching credentials, `port`
(161), and a `hosts` list where each entry carries `ip`, `name`, `site` and
`floor`.

| Symptom | Cause |
|---|---|
| A host never responds | Community or v3 credentials wrong, or an ACL on the device restricting which source IPs may poll it |
| v3 fails with an auth error | Protocol mismatch, not just a wrong key — auth (SHA/MD5) and priv (AES/DES) must both agree |
| Reachable by ping, not by SNMP | SNMP not enabled, or a different port |
| **RF detail is thin or missing** | By design — see below |

Generic SNMP can only rely on what is actually standardised. Accurate per-radio
channel utilisation, transmit power and multi-band awareness need a
vendor-native collector. On Aruba, Catalyst or Ruckus hardware — where the
vendor-native collector is a stub — that detail is simply not available today.

Test from the app host to separate "pktWiFi cannot" from "this host cannot":

```bash
snmpwalk -v2c -c <community> <AP_IP> sysUpTime.0
```

---

## Data is missing or thin

| Symptom | Cause |
|---|---|
| No APs at all | The collector is disabled, or has never polled successfully |
| APs but no clients | The controller exposes clients on a separate endpoint the collector could not reach, or there genuinely are none associated |
| Client counts look low | UniFi: wrong site. Meraki: `network_ids` restricting scope |
| Channel or utilisation blank | Generic SNMP, or the Meraki field-name caveat above |
| Data goes stale | Check the poll interval and the last successful poll time |
| Error "returned no access points… were kept" | The controller answered three times with an empty list while access points are on record, so nothing was deleted. Check the controller; if it really has none, remove the collector |
| Error "did not answer within 180 seconds" | The controller accepted the connection and never replied |
| Certificate verify failed | TLS verification is on and the controller has a self-signed or untrusted certificate. Trust the certificate, or turn off **Verify TLS certificate** on that controller |
| A site or floor is wrong | Those come from the collector's own `hosts` config on Generic SNMP — they are labels you set, not discovered |

---

## Cross-app context is empty

pktWiFi pulls device, traffic, log and packet context from sibling apps over
suite-token API calls: pktSNMP, pktFlow, pktLog, pktPCAP and pktIPAM.

| Symptom | Cause |
|---|---|
| No traffic context on a client | No enabled pktFlow connection, or pktFlow has no flows for that address |
| No log context | No enabled pktLog connection |
| No packet context | No enabled pktPCAP connection |
| No address context | No enabled pktIPAM connection |
| A connection health check fails on TLS | Suite calls verify the target's certificate — fix the sibling's cert, or clear verify-TLS for that connection |
| Everything broke after rotating a token | The token is shared; every consumer needs updating |

None of these degrade pktWiFi's own collection — they only remove context.

---

## Alerts and notifications

Channels are in-app, Email (SMTP), Slack, PagerDuty, generic Webhook and
Tracecat. Senders are written never to raise, so **a failing channel looks like
nothing happening**. Use Send Test for the real error.

| Symptom | Cause |
|---|---|
| No alerts at all | No collector is returning data |
| Email never arrives | SMTP host, port (default 587), TLS, credentials, or the relay refusing the sender |
| Slack 4xx | Webhook revoked or malformed |
| Webhook target sees nothing | Method, headers, or the Jinja2 payload template failing to render |

---

## A config change did not take effect

**Wrong file.** Env vars beat `config.yaml` silently:

```bash
systemctl show pktwifi -p Environment
```

**Not restarted.** Nothing in `config.yaml` is re-read live, and restoring a
backed-up `config.yaml` never restarts the service.

**The setting is not in `config.yaml`.** That file holds startup and
infrastructure only. Collectors (SNMP hosts, vendor API credentials), alert
rules and the outbound integrations to pktSNMP, pktFlow, pktLog, pktPCAP and
pktIPAM all live in **SQLite** and are managed in the UI.

### `credential_key` changed or was lost

Controller credentials — UniFi passwords, Meraki API keys, SNMP communities and
v3 keys — are Fernet-encrypted with it. Change it and all of them become
undecryptable. Restore the old key, or re-enter every collector. This is why
`uninstall.sh` keeps `config.yaml` by default.

---

## TLS / HTTPS

`ssl_dir` defaults to `<INSTALL_DIR>/ssl`.

| Symptom | Cause | Fix |
|---|---|---|
| Still HTTP after uploading a cert | Not restarted | Restart |
| Will not start after upload | Key does not match the cert, or is unreadable by the service user | Compare `openssl x509 -noout -modulus -in cert.pem \| openssl md5` with `openssl rsa -noout -modulus -in key.pem \| openssl md5` |
| Certificate warning | Self-signed, or the SAN does not cover the hostname used | Expected for self-signed |

```bash
curl -k https://127.0.0.1:8769/api/health
```

---

## Backup, upgrades and uninstall

Backups write timestamped `backup_*` directories; the settings live in SQLite.
A restored `config.yaml` never restarts the service. **Never copy a live SQLite
database with `cp`** — take `pktwifi.db`, `-wal` and `-shm` with the service
stopped.

Upgrade:

```bash
git pull
cd frontend && npm install && npm run build && cd ..
sudo systemctl restart pktwifi
```

Migrations are numbered `.sql` files, run on startup, tracked in `_migrations`.
`no such column` after an upgrade means they did not run — the app failed
earlier in startup.

Re-running `install.sh` is better when a release drops or renames a file; data
is kept, and `PKTWIFI_REMOVE_EXISTING=1` (or `0`) answers its prompt from a
script.

Uninstall:

```bash
bash <INSTALL_DIR>/uninstall.sh
```

Data is kept by default — `config.yaml`, `pktwifi.db` and its `-wal`/`-shm`,
`logs/`, `backups/` and `ssl/`. `--purge` deletes them and is not recoverable;
`--dry-run` prints what would go; `--yes` skips prompts; `--dir PATH` if the
unit is already gone.

**Never mirror over an install directory with `rsync --delete`** — that destroys
the database and the encrypted collector credentials together.

---

## What to capture before reporting a problem

1. `VERSION`, and how it was installed.
2. `systemctl status pktwifi` plus the last 200 lines of **both** the journal and
   `logs/pktwifi.log`.
3. `config.yaml` **with `secret_key`, `credential_key` and passwords removed**.
4. For a collector problem: the type, its `last_error`, and the output of both
   **Test Credentials** and **Poll Now**.
5. For UniFi: whether the controller is UniFi OS or classic, and the exact site
   value configured — the slug, not the display name.
6. For Meraki: whether AP inventory arrives while only RF fields are empty.
7. For Generic SNMP: `snmpwalk` from this host to the AP, showing whether SNMP
   works outside the app at all.

Never paste real credentials, API keys, community strings, or an unredacted
`config.yaml`.
