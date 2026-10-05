"""
GET /api/widgets/manifest: the list of widget definitions pktHub's NOC Builder offers.
"""
from __future__ import annotations

from app.api.widgets._common import router


# ── Manifest ──────────────────────────────────────────────────────────────────
# `category` groups these in pktHub's NOC library picker. Every data surface the
# app renders in its own UI should have an entry here — the NOC builder can only
# offer what this list declares.
_AP_PARAM = {
    "key": "ap_id", "label": "Access Point", "type": "select",
    "options_path": "/api/widgets/options/access_points",
}


_WINDOW_PARAM = {
    "key": "hours", "label": "Window", "type": "select",
    "options": [{"value": "1", "label": "1 hour"}, {"value": "6", "label": "6 hours"},
                {"value": "24", "label": "24 hours"}, {"value": "168", "label": "7 days"}],
}


MANIFEST = [
    # ── Overview ──────────────────────────────────────────────────────────────
    {
        "id": "wifi_summary", "title": "WiFi Summary", "category": "Overview",
        "description": "Access point, client and rogue counts across the estate",
        "view_path": "/api/widgets/wifi_summary",
        "default_w": 560, "default_h": 200, "min_w": 300, "min_h": 150,
    },
    {
        "id": "alert_summary", "title": "Alert Summary", "category": "Overview",
        "description": "Active alert counts by severity",
        "view_path": "/api/widgets/alert_summary",
        "default_w": 420, "default_h": 200, "min_w": 260, "min_h": 150,
    },
    {
        "id": "aps_by_site", "title": "APs by Site", "category": "Overview",
        "description": "Access point count and offline count per site",
        "view_path": "/api/widgets/aps_by_site",
        "default_w": 480, "default_h": 320, "min_w": 280, "min_h": 200,
    },

    # ── Access Points ─────────────────────────────────────────────────────────
    {
        "id": "ap_status", "title": "AP Status", "category": "Access Points",
        "description": "All access points with site, status, and connected client count",
        "view_path": "/api/widgets/ap_status",
        "default_w": 640, "default_h": 380, "min_w": 340, "min_h": 220,
    },
    {
        "id": "ap_uptime", "title": "AP Uptime", "category": "Access Points",
        "description": "Reported uptime per access point, least stable first",
        "view_path": "/api/widgets/ap_uptime",
        "default_w": 540, "default_h": 340, "min_w": 300, "min_h": 200,
    },
    {
        "id": "rogue_aps", "title": "Rogue APs", "category": "Access Points",
        "description": "Access points flagged as rogue",
        "view_path": "/api/widgets/rogue_aps",
        "default_w": 620, "default_h": 320, "min_w": 320, "min_h": 180,
    },

    # ── Radios ────────────────────────────────────────────────────────────────
    {
        "id": "radio_overview", "title": "Radio Overview", "category": "Radios",
        "description": "Per-radio band, channel, width, power, utilization and noise",
        "view_path": "/api/widgets/radio_overview",
        "default_w": 780, "default_h": 400, "min_w": 380, "min_h": 220,
    },
    {
        "id": "channel_utilization", "title": "Channel Utilization", "category": "Radios",
        "description": "Busiest radios by channel utilization",
        "view_path": "/api/widgets/channel_utilization",
        "default_w": 540, "default_h": 340, "min_w": 300, "min_h": 200,
    },
    {
        "id": "noise_floor", "title": "Noise Floor", "category": "Radios",
        "description": "Radios with the highest noise floor",
        "view_path": "/api/widgets/noise_floor",
        "default_w": 540, "default_h": 340, "min_w": 300, "min_h": 200,
    },

    # ── Clients ───────────────────────────────────────────────────────────────
    {
        "id": "client_count", "title": "Client Count", "category": "Clients",
        "description": "Connected client count by radio band for one access point",
        "view_path": "/api/widgets/client_count",
        "default_w": 460, "default_h": 300, "min_w": 280, "min_h": 180,
        "params": [_AP_PARAM],
    },
    {
        "id": "clients_by_band", "title": "Clients by Band", "category": "Clients",
        "description": "Connected client distribution across radio bands",
        "view_path": "/api/widgets/clients_by_band",
        "default_w": 440, "default_h": 280, "min_w": 260, "min_h": 170,
    },
    {
        "id": "clients_by_ssid", "title": "Clients by SSID", "category": "Clients",
        "description": "Connected client distribution across SSIDs",
        "view_path": "/api/widgets/clients_by_ssid",
        "default_w": 480, "default_h": 300, "min_w": 280, "min_h": 180,
    },
    {
        "id": "client_health", "title": "Client Signal Health", "category": "Clients",
        "description": "Clients bucketed by signal strength, weakest listed first",
        "view_path": "/api/widgets/client_health",
        "default_w": 620, "default_h": 360, "min_w": 320, "min_h": 200,
    },
    {
        "id": "client_events", "title": "Client Events", "category": "Clients",
        "description": "Recent associate, roam, deauth and auth-failure events",
        "view_path": "/api/widgets/client_events",
        "default_w": 700, "default_h": 360, "min_w": 340, "min_h": 200,
    },

    # ── Trends (charts) ───────────────────────────────────────────────────────
    {
        "id": "radio_trend", "title": "Radio Trend", "category": "Trends",
        "description": "Utilization, clients and noise over time for one radio",
        "view_path": "/api/widgets/radio_trend",
        "default_w": 680, "default_h": 320, "min_w": 320, "min_h": 180,
        "params": [
            _AP_PARAM,
            # {ap_id} is substituted from the widget's own config by pktHub, so the
            # radio list reflects whatever bands that AP currently reports.
            {"key": "radio_id", "label": "Radio", "type": "select",
             "options_path": "/api/widgets/options/radios?ap_id={ap_id}"},
            {"key": "metric", "label": "Metric", "type": "select",
             "options": [{"value": "utilization_pct", "label": "Utilization %"},
                         {"value": "client_count",    "label": "Clients"},
                         {"value": "noise_floor_dbm", "label": "Noise floor"},
                         {"value": "retry_pct",       "label": "Retry %"},
                         {"value": "crc_error_pct",   "label": "CRC error %"},
                         {"value": "tx_power_dbm",    "label": "TX power"}]},
            _WINDOW_PARAM,
        ],
    },
    {
        "id": "client_trend", "title": "Client Trend", "category": "Trends",
        "description": "Total connected clients over time",
        "view_path": "/api/widgets/client_trend",
        "default_w": 620, "default_h": 300, "min_w": 300, "min_h": 170,
        "params": [_WINDOW_PARAM],
    },

    {
        "id": "airtime_trend", "title": "Airtime by Band", "category": "Trends",
        "description": "Average channel utilization per band over time, across all radios",
        "view_path": "/api/widgets/airtime_trend",
        "default_w": 680, "default_h": 320, "min_w": 320, "min_h": 180,
        "params": [_WINDOW_PARAM],
    },
    {
        "id": "rf_spectrum", "title": "RF Spectrum", "category": "Radios",
        "description": "Where each radio sits in the 2.4, 5 and 6 GHz bands; height is channel utilization",
        "view_path": "/api/widgets/rf_spectrum",
        "default_w": 760, "default_h": 420, "min_w": 400, "min_h": 260,
    },
    {
        "id": "signal_scope", "title": "Signal Scope", "category": "Clients",
        "description": "Every connected client by the access point it is on; range is signal strength",
        "view_path": "/api/widgets/signal_scope",
        "default_w": 520, "default_h": 460, "min_w": 300, "min_h": 300,
    },

    # ── Alerts ────────────────────────────────────────────────────────────────
    {
        "id": "active_alerts", "title": "Active Alerts", "category": "Alerts",
        "description": "Unresolved WiFi alert events",
        "view_path": "/api/widgets/active_alerts",
        "default_w": 640, "default_h": 360, "min_w": 320, "min_h": 200,
    },

    # ── Collectors ────────────────────────────────────────────────────────────
    {
        "id": "collector_status", "title": "Collector Status", "category": "Collectors",
        "description": "Controller/collector health and last successful poll",
        "view_path": "/api/widgets/collector_status",
        "default_w": 620, "default_h": 300, "min_w": 320, "min_h": 180,
    },
]


@router.get("/manifest")
async def widget_manifest():
    return MANIFEST
