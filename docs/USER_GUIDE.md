# pktWiFi — User Guide

This guide is for people who use pktWiFi to monitor access points, clients, and wireless health — not for installing or administering the server. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for setup, users, backups, and integrations.

## Logging in

Log in with your username and password (or Okta SSO if configured). All roles can view every page; only admins can acknowledge/resolve alerts freely and reach Settings — analysts can also ack/resolve alerts.

## Navigation

**Dashboard**, **Access Points**, **Clients**, **Metrics**, **Alerts**, **Logs**. **Settings** is admin-only. A floating **AI Assistant** chat button is available on any page.

## Dashboard

At-a-glance counts of total/online/offline/rogue access points, connected client count, and the current active alerts list.

## Access Points

A searchable, paginated inventory of every AP across every configured controller — status, vendor, model, firmware. Click a row for per-radio channel/utilization/retry detail (where the controller reports it) and the clients currently attached, grouped by radio/channel. From there, **View Metrics →** jumps to the Metrics page pre-selected to that AP, and clicking a client jumps to the Clients page pre-filtered to it.

> If you're on a UniFi controller using API-key auth, per-client SSID/RSSI/rate/radio detail won't be available — that's a real limitation of Ubiquiti's Integration API itself, not a bug. AP-level detail still works fully in that mode. Ask your admin to switch to username/password auth mode if you need full per-client detail.

## Clients

A searchable, paginated list of connected wireless clients — SSID, band, channel, RSSI/SNR, tx/rx rate, real connect time, and which AP they're attached to.

## Metrics

Pick an AP from the searchable list to see per-band channel-utilization, retry-rate, and client-count charts over a 1h/6h/24h/7d window.

## Alerts

Shows fired alert events. If your role is analyst or admin, you can acknowledge or resolve them.

## Logs

AP/controller syslog and event context, including anything surfaced via a pktLog suite integration if your admin has one configured.

## Looking up an IP address

Any IP address shown in the app is clickable and opens a lookup using your own per-user API keys (Settings → User Keys), same pattern as the rest of the pkt suite.

## Getting help in the app

Almost every page and Settings tab has a small **?** button that opens a short "How It Works" explainer.

## AI Assistant

A floating chat button, available on every authenticated page, if your admin has configured an Anthropic API key.
