# pktWiFi — Administrator Guide

Covers installing, configuring, and operating pktWiFi. For day-to-day usage (Dashboard, Access Points, Clients, Metrics), see [USER_GUIDE.md](USER_GUIDE.md). See the [README](../README.md) for the full technical reference.

## Installation

```bash
git clone git@github.com:bsnwgit/pktwifi.git
cd pktwifi
bash install.sh
```

Prompts for install directory and port, then handles the venv, `config.yaml` + secret key, DB setup, admin user, frontend build (if `npm` is present), and the systemd service. Open the app port in your firewall and log in with the printed admin credentials.

## First-time setup checklist

1. **Change the admin password.**
2. **Set Base URL** (Settings → General) before configuring SAML — it feeds the ACS/metadata URLs.
3. **Add credentials** (Settings → Credentials) for each vendor/site before adding controllers, so you can reference them from a dropdown instead of retyping secrets.
4. **Add sites** (Settings → Sites) if you want a consistent Site dropdown across controllers instead of free-typed, typo-prone location names — this is a display catalog, unrelated to a UniFi controller's own internal "Site" concept (see Vendor Collectors below).
5. **Add controllers** (Settings → Controllers) — use **Test Credentials** in the controller form before saving to confirm the auth actually works, then **Poll Now** to pull the first batch of data immediately.
6. **Configure alert channels** (Notifications) and retention (Data → Storage).
7. **Set up backups** (Data → Backups) and confirm a manual run succeeds.
8. **Create accounts** for your team.

## Users & roles

All roles can view every page; analysts and admins can acknowledge/resolve alerts; only admins reach Settings. Manage accounts at Settings → Security → Users — create/edit/deactivate/delete, reset password, and mark one active admin as the **default admin** (star icon): if every auth method is ever disabled, the app auto-signs everyone in as that account instead of dead-ending.

### Okta SAML SSO

Settings → Security → Auth: paste Okta's IdP metadata XML (auto-fills SSO URL/Entity ID/certificate) or enter by hand. ACS URL and SP metadata link are derived from **Base URL** — set that first.

## Settings reference

Two sections, chosen from a section bar above the tab bar: **Common** — the suite-common tabs every pkt app shares (General through System) — and **pktWiFi** — this app's own management tabs (Controllers, Credentials, Sites). Only the selected section's tabs appear in the row below, so switch sections if a tab isn't where you expect. Deep links to a tab select the right section automatically.

| Section | Tab | Sub-tabs | Covers |
|---|---|---|---|
| **Common** | General | — | App name, timezone, Port (needs restart), Base URL, Restart Service |
| | Security | Users, Auth, Suite Integration, AI Assistant, SSL/TLS | Accounts; SAML; suite token (both directions); local/self-hosted (Ollama, OpenAI-compatible) + cloud (Anthropic, OpenAI) AI providers, each independently enabled, scoped strictly to pktWiFi's own domain with off-topic/prompt-injection questions refused server-side, and each given up to 180s to answer before the request fails (headroom for slow local models); cert upload |
| | Data | Storage, Backups | Retention windows + manual cleanup (SQLite-only, no backend picker); backup schedule/restore |
| | Notifications | — | Slack, Email (SMTP), PagerDuty, Webhook, TraceCat SOAR |
| | User Keys | — | Per-user Lucidchart token, private to each account |
| | System | — | Read-only version + install directory |
| **pktWiFi** | Controllers | — | Add/edit/delete/poll vendor controllers |
| | Credentials | — | Named, reusable, Fernet-encrypted controller auth library |
| | Sites | — | Small name+description catalog feeding the Site dropdown in controller forms |

The old standalone Collectors and Integrations nav items are gone — everything above lives under Settings now (`/integrations` and `/sites` both redirect there).

## Vendor Collectors (Controllers)

Each controller row is a name, type, poll interval, enabled toggle, and a **schema-driven config form** (real inputs with per-field help and conditional fields, not a raw JSON textarea — though "Edit as JSON" is still available as an escape hatch). Reference a saved credential via a typed dropdown filtered to that controller type's relevant credential kinds, instead of retyping secrets. Deleting a credential still in use is blocked, and the error names which controller(s) reference it.

**Test Credentials** in the controller form runs a real, save-nothing auth attempt (UniFi login/Integration API call, Meraki `/organizations` call, or an SNMP `sysDescr` GET) and shows pass/fail with the full error — verify before you ever poll the controller for real. **Poll Now** on a saved controller polls immediately instead of waiting for its interval.

### UniFi — two auth methods

Username/password auth gets full per-client detail (SSID, RSSI, rate, radio). API-key (Integration API) auth does **not** report per-client SSID/RSSI/rate/radio attribution — this is a real limitation of Ubiquiti's own API, confirmed against a live UDM-Pro, not a pktWiFi parsing gap; AP-level detail still works fully either way. Use username/password mode if you need full per-client detail.

Also watch for the **site slug vs. display name** distinction: the UI shows a UniFi site's `desc` (display name), but the API needs the separate `name` slug — both auth modes resolve this correctly via `/self/sites`, but if you're troubleshooting a persistent 401 against a UniFi controller, this mismatch is a common root cause to check first.

### Other vendors

Cisco Meraki is built against the documented API v1 shape but not yet verified against a live organization — spot-check field mappings if you rely on it. Aruba Central, Cisco Catalyst/AireOS, and Ruckus/SmartZone are documented stubs, not working integrations yet.

## Alerting & Notifications

Configure channels on the Notifications tab (Slack, Email/SMTP, PagerDuty, generic Webhook, TraceCat SOAR) — enabling a channel doesn't send anything on its own, it just makes it available to alert rules. **Send Test** performs a real dispatch with the currently filled-in (even unsaved) config.

## Storage & retention

pktWiFi is SQLite-only — there's no analytical-backend picker like pktsnmp/pktflow's ClickHouse/DuckDB option. Data → Storage instead configures **retention**: days to keep resolved alert events and raw RF metric history, plus a **Run Cleanup Now** button to apply the current thresholds immediately instead of waiting for the daily scheduled pass. If RF metric volume ever grows large enough to need it, a ClickHouse/DuckDB backend abstraction would need to be built following the pattern already established in pktsnmp — not present in this app today.

## Backup & Restore

Configure schedule, rotation, and path at Data → Backups. Each snapshot is a timestamped directory containing `pktwifi.db` and `config.yaml`.

**Restoring:**
- Every listed snapshot has a **Restore…** link — restores directly from that on-server snapshot, no download/upload needed. Expanding it shows a checkbox per file present, so you can restore just the DB or just the config instead of both together.
- A full bundle can also be exported/imported as a `.tar.gz` (this capability was added alongside the snapshot-restore feature — earlier builds only had on-server snapshots with no download/upload path at all), with the same per-file selection on upload.
- Restoring `config.yaml` needs a service restart to actually apply.

## SSL/TLS

Upload a combined PFX/P12 bundle or separate PEM cert+key on Settings → Security → SSL/TLS. The running process auto-detects cert files under `<install_dir>/ssl` at startup, so a restart is needed after upload/removal.

## Suite Integration

Both directions live on Settings → Security → Suite Integration:
- **Inbound**: copy the Suite Token, register pktWiFi in pktHub's App Manager so it can proxy in with users already signed in.
- **Outbound (Sibling pkt Apps)**: connect to pktsnmp/pktflow/pktlog/pktpcap/pktipam for cross-app IP lookups and integrations. Note pktIPAM doesn't yet have its own dedicated client module here (`app/integrations/`) the way the others do, even though it's selectable in the UI.

## Known gaps worth knowing about

- Aruba Central, Cisco Catalyst/AireOS, Ruckus/SmartZone: stubs only.
- Cisco Meraki: unverified against a live org.
- No floor-plan heatmaps or spectrum-analysis integration.
- Single SQLite storage backend — no ClickHouse/DuckDB option yet.

## Troubleshooting

| Symptom | Check |
|---|---|
| Service won't start | `journalctl -u pktwifi -n 50`; check `config.yaml` paths and secret key |
| UniFi controller shows `status: error` | Check `last_error` on the Controllers page, or **Poll Now** for the full error in a copyable modal; **Test Credentials** is often faster for isolating an auth problem |
| Persistent 401 against a UniFi controller | Check the site slug vs. display-name mismatch noted above |
| A restored `config.yaml` didn't take effect | Restart the service — restoring never does this automatically |
| Frontend shows `{"detail":"Not Found"}` | The frontend wasn't built — run `cd frontend && npm install && npm run build`, then restart |

## Upgrading

Pull the latest code, rebuild the frontend if you build manually, then restart the service. Migrations run automatically on startup.
