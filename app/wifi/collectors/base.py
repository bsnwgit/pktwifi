"""
app/wifi/collectors/base.py
----------------------------
Shared data shapes + abstract base class for every WiFi collector plugin
(generic SNMP, Cisco Meraki, UniFi, and future Aruba Central / Cisco
Catalyst-AireOS / Ruckus integrations).

A collector's only job is: given its config dict, return a PollResult
describing the access points (with nested radios and clients) it currently
sees. app/wifi/poll_engine.py owns turning that into database rows — a new
collector never needs to know about SQL.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ClientReading:
    mac_address: str
    hostname: str | None = None
    ip_address: str | None = None
    ssid: str | None = None
    protocol: str | None = None
    rssi_dbm: float | None = None
    snr_db: float | None = None
    tx_rate_mbps: float | None = None
    rx_rate_mbps: float | None = None
    connected_at: str | None = None  # ISO 8601, when the collector's own API reports a real one


@dataclass
class RadioReading:
    band: str  # "2.4GHz" | "5GHz" | "6GHz"
    channel: int | None = None
    channel_width_mhz: int | None = None
    tx_power_dbm: float | None = None
    utilization_pct: float | None = None
    noise_floor_dbm: float | None = None
    tx_bytes: int | None = None
    rx_bytes: int | None = None
    retry_pct: float | None = None
    crc_error_pct: float | None = None
    clients: list[ClientReading] = field(default_factory=list)

    @property
    def client_count(self) -> int:
        return len(self.clients)


@dataclass
class AccessPointReading:
    external_id: str
    name: str
    mac_address: str | None = None
    ip_address: str | None = None
    vendor: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    site: str | None = None
    floor: str | None = None
    status: str = "online"
    uptime_seconds: int | None = None
    is_rogue: bool = False
    radios: list[RadioReading] = field(default_factory=list)


@dataclass
class PollResult:
    access_points: list[AccessPointReading] = field(default_factory=list)

    @property
    def clients(self) -> list[ClientReading]:
        return [c for ap in self.access_points for r in ap.radios for c in r.clients]


class Collector(ABC):
    """Base class every collector plugin implements."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def poll(self) -> PollResult:
        """Fetch current state from the data source. Raise on failure —
        the caller (poll_engine / the poll-now API) records the error."""
        raise NotImplementedError

    async def test_connection(self) -> tuple[bool, str]:
        """Default implementation: a poll that succeeds counts as reachable."""
        try:
            result = await self.poll()
            return True, f"OK — {len(result.access_points)} access point(s) found"
        except Exception as exc:
            return False, str(exc)
