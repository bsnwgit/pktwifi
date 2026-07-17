"""
app/wifi/collectors/registry.py
---------------------------------
Single place that lists every collector plugin pktWiFi knows about, whether
it's actually implemented yet, and what config fields its Settings/Collectors
UI form should render. Add a new vendor by writing a Collector subclass next
to the others in this package and adding one entry here.
"""
from __future__ import annotations

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
        "fields": ["version", "community", "username", "auth_protocol", "auth_password",
                   "priv_protocol", "priv_password", "port", "hosts"],
    },
    "cisco_meraki": {
        "label": "Cisco Meraki (Dashboard API)",
        "implemented": True,
        "cls": CiscoMerakiCollector,
        "fields": ["api_key", "organization_id", "network_ids"],
    },
    "unifi": {
        "label": "Ubiquiti UniFi (Controller API)",
        "implemented": True,
        "cls": UnifiCollector,
        "fields": ["controller_url", "username", "password", "site", "udm", "verify_tls"],
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
