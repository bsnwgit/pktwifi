# pktWiFi — User Guide

This guide is for people who use pktWiFi to monitor access points, clients, and wireless health — not for installing or administering the server. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for setup, users, backups, and integrations.

## Logging in

Log in with your username and password (or Okta SSO if configured). All roles can view every page; only admins can acknowledge/resolve alerts freely and reach Settings — analysts can also ack/resolve alerts.

## Navigation

**Dashboard**, **Access Points**, **Clients**, **Metrics**, **Alerts**, **Logs**. **Settings** is admin-only.

Settings itself opens with a section bar: **Common** (General, Security, Data, Notifications, User Keys, System — identical across the pkt* apps) and **pktWiFi** (Controllers, Credentials, Sites). The tab row below shows one section at a time, so switch sections if a tab appears to be missing.

## Dashboard

The estate at a glance, refreshed every 30 seconds. Every figure counts only what each access point's latest poll reported, so a client that has left, or a band a controller has stopped reporting, drops off straight away.

- **Readouts** — access points (online/offline/rogue), availability, connected clients by band, mean and peak channel utilization, median client signal, and active alerts. Click one to open the matching page.
- **Connected Clients** and **Airtime by Band** — trends over the window picked at the top right (1h/6h/24h/7d). A gap in a line is time with no samples, not zero. The red dashed line is the threshold your *High channel utilization* alert rule fires at (80% when there is no such rule).
- **RF Spectrum** — every radio drawn where it sits on air, one lane per band, its height set by channel utilization. Shapes that overlap are radios contending for the same airtime. A dashed outline means the controller did not report the channel width (20 MHz is assumed) or the channel plan leaves the position approximate. Click a radio to open its Metrics.
- **Signal Scope** — each connected client in its access point's sector, closer to the centre the stronger its signal. Where a client sits around its sector means nothing. The 16 busiest access points get a sector each and the rest share one; click a sector to list its clients.
- **Client Flow**, **Client Mix** and **Signal Quality** — clients by SSID and band, by band and Wi-Fi generation, and by signal strength (good ≥ −65 dBm, fair ≥ −75 dBm).
- **Busiest Access Points**, **Collection** and **Active Alerts** — the most loaded access points (click one for its Metrics), controller health with the associations and roams seen in the window, and the alerts currently open.

> The client panels and the scope rely on per-client detail. With a UniFi controller on API-key auth, clients show as *Not reported* and signal panels stay empty — the same Integration API limitation described under Access Points.

## Access Points

A searchable, paginated inventory of every AP across every configured controller — status, vendor, model, firmware. Click a row for per-radio channel/utilization/retry detail (where the controller reports it) and the clients currently attached, grouped by radio/channel. From there, **View Metrics →** jumps to the Metrics page pre-selected to that AP, and clicking a client jumps to the Clients page pre-filtered to it.

> If you're on a UniFi controller using API-key auth, per-client SSID/RSSI/rate/radio detail won't be available — that's a real limitation of Ubiquiti's Integration API itself, not a bug. AP-level detail still works fully in that mode. Ask your admin to switch to username/password auth mode if you need full per-client detail.

## Clients

A searchable, paginated list of connected wireless clients — SSID, band, channel, RSSI/SNR, tx/rx rate, real connect time, and which AP they're attached to.

Signal is colour-coded the same way as the Dashboard's Signal Quality — green good (≥ −65 dBm), amber fair (≥ −75 dBm), red poor — with a bar down the left of each row. The good / fair / poor buttons above the table filter to one level. Clicking a bar or a level in the Dashboard's **Signal Quality** opens this page already filtered to that level.

## Metrics

Pick an AP from the searchable list to see per-band channel-utilization, retry-rate, and client-count charts over a 1h/6h/24h/7d window.

## Alerts

Shows fired alert events. If your role is analyst or admin, you can acknowledge or resolve them.

Rules on radios and clients — channel utilization, client count, retry rate and SNR — look only at what each access point's latest poll reported, so a radio or client that stops being reported no longer keeps an alert open.

## Logs

AP/controller syslog and event context, including anything surfaced via a pktLog suite integration if your admin has one configured.

## Looking up an IP address

Any IP address shown in the app is clickable and opens a lookup using your own per-user API keys (Settings → User Keys), same pattern as the rest of the pkt suite.

## The assistant

If your administrator has set it up, a launcher sits in the bottom corner of every page. Click it to ask questions in a chat panel. The panel comes from the resonance server, so what it can help with depends on how your administrator configured it there.

Depending on what your administrator has allowed for your role, it can look at this install's access points, clients, radios, collectors, alerts and logs — never anything your own account could not already open, and never a controller's stored credentials. It may also be able to **act**, but only in one way: acknowledging alerts. It will always say exactly what it is about to do and wait for you to say yes.

It can never change a channel or a transmit power, disconnect a client, or add, change or delete an access point or a collector.

If the launcher never appears, either your role is set to *No access* or the assistant could not load. Your administrator can see both under Settings → Resonance.

## Getting help in the app

Almost every page and Settings tab has a small **?** button that opens a short "How It Works" explainer.

For longer-form documentation, click **Documentation** in the sidebar (just above your account info) — it opens this guide, the Administrator Guide, and the Collector Setup guide as in-app tabs, so you don't need the repo checked out to read them.
