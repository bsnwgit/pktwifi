"""
The declared response shapes of the read operations.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AccessPoint(BaseModel):
    """One access point pktWiFi knows about."""

    model_config = ConfigDict(extra="allow")

    id: int
    name: Optional[str] = None
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    site: Optional[str] = None
    floor: Optional[str] = None
    status: Optional[str] = Field(None, description="online, offline, or unknown.")
    is_rogue: bool = Field(False, description="True when this AP is not one of ours.")
    uptime_seconds: Optional[int] = None
    client_count: int = Field(0, description="Clients currently associated across its radios.")
    collector_id: Optional[int] = None
    last_seen: Optional[str] = Field(None, description="When it was last polled (ISO 8601).")


class AccessPointList(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int = Field(description="How many access points matched, before paging.")
    limit: int
    offset: int
    returned: int = 0
    truncated_for_size: bool = Field(
        False, description="True when the page was cut to fit. Ask for fewer, or narrow the filters."
    )
    access_points: list[AccessPoint] = Field(default_factory=list)


class WifiClient(BaseModel):
    """One client currently associated, as last observed."""

    model_config = ConfigDict(extra="allow")

    id: int
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    ssid: Optional[str] = None
    band: Optional[str] = Field(None, description="The band as the controller reports it: 2.4GHz, 5GHz or 6GHz.")
    protocol: Optional[str] = Field(None, description="The 802.11 generation it associated with.")
    rssi_dbm: Optional[int] = Field(
        None, description="Signal strength in dBm. Closer to zero is stronger; below -70 is poor."
    )
    snr_db: Optional[int] = Field(None, description="Signal-to-noise ratio in dB. Under 20 is poor.")
    tx_rate_mbps: Optional[float] = None
    rx_rate_mbps: Optional[float] = None
    access_point_id: Optional[int] = None
    access_point_name: Optional[str] = Field(None, description="Which AP it is on, for reading back.")
    connected_at: Optional[str] = None
    last_seen: Optional[str] = Field(None, description="When it was last observed (ISO 8601).")


class WifiClientList(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    limit: int
    offset: int
    returned: int = 0
    truncated_for_size: bool = False
    clients: list[WifiClient] = Field(default_factory=list)


class Radio(BaseModel):
    """One radio on an access point — the thing a channel and a power belong to."""

    model_config = ConfigDict(extra="allow")

    id: int
    access_point_id: Optional[int] = None
    access_point_name: Optional[str] = None
    band: Optional[str] = Field(None, description="The band as the controller reports it: 2.4GHz, 5GHz or 6GHz.")
    channel: Optional[int] = None
    channel_width_mhz: Optional[int] = None
    tx_power_dbm: Optional[int] = None
    utilization_pct: Optional[float] = Field(
        None, description="How busy the channel is. Sustained above 50 is congestion."
    )
    noise_floor_dbm: Optional[int] = None
    client_count: Optional[int] = None
    updated_at: Optional[str] = None


class RadioList(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    returned: int = 0
    truncated_for_size: bool = False
    radios: list[Radio] = Field(default_factory=list)


class Collector(BaseModel):
    """A collector pktWiFi polls a wireless controller through."""

    model_config = ConfigDict(extra="allow")

    id: int
    name: Optional[str] = None
    collector_type: Optional[str] = Field(None, description="Which controller it speaks to.")
    enabled: bool = False
    status: Optional[str] = None
    poll_interval_sec: Optional[int] = None
    last_poll_at: Optional[str] = Field(None, description="When it last ran (ISO 8601).")
    last_error: Optional[str] = Field(None, description="Why the last poll failed, if it did.")


class CollectorList(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    returned: int = 0
    truncated_for_size: bool = False
    collectors: list[Collector] = Field(default_factory=list)


class WifiSummary(BaseModel):
    """Counts across the whole wireless estate — the "how are we doing" answer."""

    model_config = ConfigDict(extra="allow")

    access_points: int
    access_points_online: int
    rogue_access_points: int = Field(description="APs seen that are not ours.")
    clients: int = Field(description="Clients currently associated.")
    radios: int
    ssids: int
    sites: int
    collectors: int
    collectors_enabled: int
    unacknowledged_alerts: int


class AlertEvent(BaseModel):
    """One firing of a pktWiFi alert rule."""

    model_config = ConfigDict(extra="allow")

    id: int
    rule_id: Optional[int] = None
    rule_name: Optional[str] = Field(None, description="Name of the rule that fired.")
    access_point_id: Optional[int] = Field(None, description="The AP it is about, if any.")
    client_mac: Optional[str] = Field(None, description="The client it is about, if any.")
    severity: Optional[str] = None
    message: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None
    active: bool = Field(False, description="True while the condition behind it still holds.")
    acked: bool = False
    acked_by: Optional[str] = None
    acked_at: Optional[str] = None
    resolved: bool = False
    resolved_at: Optional[str] = None
    created_at: Optional[str] = Field(None, description="When it fired (ISO 8601).")


class AlertEventList(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    limit: int
    offset: int
    returned: int = 0
    truncated_for_size: bool = False
    events: list[AlertEvent] = Field(default_factory=list)


class AlertRule(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    name: Optional[str] = None
    condition_type: Optional[str] = Field(None, description="What the rule watches.")
    threshold: Optional[float] = None
    severity: Optional[str] = None
    enabled: bool = False
    created_at: Optional[str] = None
    channels: list[str] = Field(
        default_factory=list,
        description=(
            "Which notification channels this rule sends on when it fires. Empty means it records "
            "the firing here and notifies nobody — an enabled rule with no channels is being "
            "watched but not reported."
        ),
    )


class AlertRuleList(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    returned: int = 0
    truncated_for_size: bool = False
    rules: list[AlertRule] = Field(default_factory=list)


class AppLogRecord(BaseModel):
    """One line of pktWiFi's own diagnostic log — not wireless data."""

    model_config = ConfigDict(extra="allow")

    id: int
    level: Optional[str] = None
    logger: Optional[str] = Field(None, description="Which part of pktWiFi wrote it.")
    message: Optional[str] = None
    created_at: Optional[str] = Field(None, description="When it was written (ISO 8601).")


class AppLogResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    limit: int
    offset: int
    returned: int = 0
    truncated_for_size: bool = False
    records: list[AppLogRecord] = Field(default_factory=list)
