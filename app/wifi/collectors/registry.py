"""
app/wifi/collectors/registry.py
---------------------------------
Single place that lists every collector plugin pktWiFi knows about, whether
it's actually implemented yet, and what config fields its Settings/Collectors
UI form should render. Add a new vendor by writing a Collector subclass next
to the others in this package and adding one entry here.
"""
from __future__ import annotations

from app.wifi.collectors.field_schema import text, password, number, toggle, select, string_list, host_list, site_select
from app.wifi.collectors.base import Collector
from app.wifi.collectors.snmp_generic import SnmpGenericCollector
from app.wifi.collectors.cisco_meraki import CiscoMerakiCollector
from app.wifi.collectors.unifi import UnifiCollector
from app.wifi.collectors.aruba_central import ArubaCentralCollector
from app.wifi.collectors.cisco_catalyst import CiscoCatalystCollector
from app.wifi.collectors.ruckus import RuckusCollector

COLLECTOR_TYPES: dict[str, dict] = {
    "snmp_generic": {
        "label": "Generic SNMP (vendor-neutral)",
        "implemented": True,
        "cls": SnmpGenericCollector,
        "fields": [
            select("version", "SNMP version", [("v2c", "v2c"), ("v3", "v3")], default="v2c"),
            password("community", "Community string", placeholder="public", help="v2c only"),
            text("username", "Username", help="v3 only"),
            select("auth_protocol", "Auth protocol", [("SHA", "SHA"), ("MD5", "MD5")], default="SHA", help="v3 only"),
            password("auth_password", "Auth password", help="v3 only"),
            select("priv_protocol", "Privacy protocol", [("AES", "AES"), ("DES", "DES")], default="AES", help="v3 only"),
            password("priv_password", "Privacy password", help="v3 only"),
            number("port", "SNMP port", default=161),
            host_list("hosts", "Access points / controllers to poll", [
                text("ip", "IP address", required=True, placeholder="10.0.0.5"),
                text("name", "Name", placeholder="ap-lobby-1"),
                site_select("site", "Site"),
                text("floor", "Floor", placeholder="1"),
            ], help="Reachability + best-effort channel data comes from these hosts"),
        ],
    },
    "cisco_meraki": {
        "label": "Cisco Meraki (Dashboard API)",
        "implemented": True,
        "cls": CiscoMerakiCollector,
        "fields": [
            password("api_key", "API key", required=True, help="Dashboard -> My Profile -> API access"),
            text("organization_id", "Organization ID", required=True, help="GET /organizations to find this"),
            string_list("network_ids", "Network IDs", item_placeholder="N_1234567890",
                        help="Leave empty to include every wireless network in the org"),
        ],
    },
    "unifi": {
        "label": "Ubiquiti UniFi (Controller API)",
        "implemented": True,
        "cls": UnifiCollector,
        "fields": [
            text("controller_url", "Controller URL", required=True, placeholder="https://10.0.0.1",
                 help="No trailing slash"),
            select("auth_method", "Authentication method",
                   [("userpass", "Username & password"), ("api_key", "API key")], default="userpass", required=True,
                   help="API key requires a UniFi OS console (UDM/UDM-Pro/Cloud Gateway) with the official "
                        "Network Integration API enabled — Settings -> Control Plane -> Integrations"),
            text("username", "Username", required=True, show_if=("auth_method", "userpass")),
            password("password", "Password", required=True, show_if=("auth_method", "userpass")),
            password("api_key", "API key", required=True, show_if=("auth_method", "api_key"),
                      help="Generated in the UniFi OS console under Settings -> Control Plane -> Integrations"),
            site_select("site", "Site", help="Must match the site name/description as configured on the controller"),
            toggle("udm", "UDM / UDM-Pro / Cloud Key Gen2+", default=False,
                   show_if=("auth_method", "userpass"),
                   help="Enable if this is a UniFi OS console, not a standalone controller app"),
            toggle("verify_tls", "Verify TLS certificate", default=False,
                   help="Most on-prem controllers use a self-signed cert"),
        ],
    },
    "aruba_central": {
        "label": "Aruba Central / Aruba Networking (not yet implemented)",
        "implemented": False,
        "cls": ArubaCentralCollector,
        "fields": [],
    },
    "cisco_catalyst": {
        "label": "Cisco Catalyst 9800 / AireOS (not yet implemented)",
        "implemented": False,
        "cls": CiscoCatalystCollector,
        "fields": [],
    },
    "ruckus": {
        "label": "Ruckus / SmartZone (not yet implemented)",
        "implemented": False,
        "cls": RuckusCollector,
        "fields": [],
    },
}


def get_collector_instance(collector_type: str, config: dict) -> Collector | None:
    meta = COLLECTOR_TYPES.get(collector_type)
    if not meta:
        return None
    return meta["cls"](config)
