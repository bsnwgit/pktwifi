-- pktWiFi initial schema

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    email           TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'viewer',   -- admin | analyst | viewer
    is_active       INTEGER NOT NULL DEFAULT 1,
    auth_provider   TEXT NOT NULL DEFAULT 'local',     -- local | saml
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_login      TEXT
);

-- Generic key/value store for runtime settings (JSON-encoded values),
-- mirrors the pattern used across the pkt* suite.
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT NOT NULL,
    level_no    INTEGER NOT NULL,
    logger      TEXT NOT NULL,
    message     TEXT NOT NULL,
    exc_info    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_app_logs_created ON app_logs(created_at);

-- ── Collectors ──────────────────────────────────────────────────────────────
-- One row per configured data source: the built-in generic-SNMP poller, or a
-- vendor controller integration (Meraki, UniFi, Aruba Central, Catalyst/AireOS,
-- Ruckus, ...). `config_json` holds collector-specific settings; any secret
-- fields inside it (API keys, passwords) are Fernet-encrypted at rest — see
-- app/wifi/collectors/base.py.
CREATE TABLE IF NOT EXISTS collectors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    collector_type   TEXT NOT NULL,   -- snmp_generic | cisco_meraki | unifi | aruba_central | cisco_catalyst | ruckus
    config_json      TEXT NOT NULL DEFAULT '{}',
    poll_interval_sec INTEGER NOT NULL DEFAULT 60,
    enabled          INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'unknown',   -- ok | error | unknown
    last_poll_at     TEXT,
    last_error       TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Access points ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS access_points (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    collector_id     INTEGER REFERENCES collectors(id) ON DELETE SET NULL,
    external_id      TEXT,                 -- vendor's own AP id/serial, unique per collector
    name             TEXT NOT NULL,
    mac_address      TEXT,
    ip_address       TEXT,
    vendor           TEXT,
    model            TEXT,
    firmware_version TEXT,
    site             TEXT,
    floor            TEXT,
    status           TEXT NOT NULL DEFAULT 'unknown',   -- online | offline | unknown
    is_rogue         INTEGER NOT NULL DEFAULT 0,
    uptime_seconds   INTEGER,
    last_seen        TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (collector_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_aps_collector ON access_points(collector_id);
CREATE INDEX IF NOT EXISTS idx_aps_status ON access_points(status);

-- ── Radios (one row per AP per band, current snapshot) ─────────────────────
CREATE TABLE IF NOT EXISTS radios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    access_point_id     INTEGER NOT NULL REFERENCES access_points(id) ON DELETE CASCADE,
    band                TEXT NOT NULL,   -- 2.4GHz | 5GHz | 6GHz
    channel             INTEGER,
    channel_width_mhz   INTEGER,
    tx_power_dbm        REAL,
    utilization_pct     REAL,
    noise_floor_dbm     REAL,
    client_count        INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (access_point_id, band)
);

-- ── RF metrics time series (one row per radio per poll) ─────────────────────
CREATE TABLE IF NOT EXISTS radio_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    radio_id            INTEGER NOT NULL REFERENCES radios(id) ON DELETE CASCADE,
    ts                  TEXT NOT NULL DEFAULT (datetime('now')),
    channel             INTEGER,
    channel_width_mhz   INTEGER,
    tx_power_dbm        REAL,
    utilization_pct     REAL,
    noise_floor_dbm     REAL,
    client_count        INTEGER,
    tx_bytes            INTEGER,
    rx_bytes            INTEGER,
    retry_pct           REAL,
    crc_error_pct       REAL
);
CREATE INDEX IF NOT EXISTS idx_radio_metrics_radio_ts ON radio_metrics(radio_id, ts);

-- ── WiFi clients (stations) — current snapshot ──────────────────────────────
CREATE TABLE IF NOT EXISTS wifi_clients (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    mac_address      TEXT NOT NULL UNIQUE,
    access_point_id  INTEGER REFERENCES access_points(id) ON DELETE SET NULL,
    radio_id         INTEGER REFERENCES radios(id) ON DELETE SET NULL,
    hostname         TEXT,
    ip_address       TEXT,
    ssid             TEXT,
    band             TEXT,
    protocol         TEXT,        -- 802.11a/b/g/n/ac/ax/be
    rssi_dbm         REAL,
    snr_db           REAL,
    tx_rate_mbps     REAL,
    rx_rate_mbps     REAL,
    connected_at     TEXT,
    last_seen        TEXT NOT NULL DEFAULT (datetime('now')),
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_clients_ap ON wifi_clients(access_point_id);

-- ── Client roam/association events ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS client_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    mac_address      TEXT NOT NULL,
    event_type       TEXT NOT NULL,   -- associate | disassociate | roam | deauth | auth_fail
    from_ap_id       INTEGER REFERENCES access_points(id) ON DELETE SET NULL,
    to_ap_id         INTEGER REFERENCES access_points(id) ON DELETE SET NULL,
    details_json     TEXT NOT NULL DEFAULT '{}',
    ts               TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_client_events_mac_ts ON client_events(mac_address, ts);

-- ── Known SSIDs (catalog pulled from controllers, informational) ───────────
CREATE TABLE IF NOT EXISTS ssids (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    collector_id INTEGER REFERENCES collectors(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    band         TEXT,
    security     TEXT,
    vlan_id      INTEGER,
    enabled      INTEGER NOT NULL DEFAULT 1,
    UNIQUE (collector_id, name, band)
);

-- ── Alerting ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_rules (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    condition_type TEXT NOT NULL,   -- ap_down | high_channel_util | low_snr | rogue_ap | high_retry_rate | high_client_count
    threshold      REAL,
    severity       TEXT NOT NULL DEFAULT 'warning',   -- info | warning | critical
    enabled        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alert_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id          INTEGER REFERENCES alert_rules(id) ON DELETE SET NULL,
    access_point_id  INTEGER REFERENCES access_points(id) ON DELETE SET NULL,
    client_mac       TEXT,
    severity         TEXT NOT NULL DEFAULT 'warning',
    message          TEXT NOT NULL,
    value            REAL,
    threshold        REAL,
    active           INTEGER NOT NULL DEFAULT 1,
    acked            INTEGER NOT NULL DEFAULT 0,
    acked_by         TEXT,
    acked_at         TEXT,
    resolved         INTEGER NOT NULL DEFAULT 0,
    auto_resolved    INTEGER NOT NULL DEFAULT 0,
    resolved_at      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_alert_events_active ON alert_events(active, acked);

-- ── WiFi OID catalog (reference table for the generic SNMP collector) ──────
CREATE TABLE IF NOT EXISTS wifi_oid_catalog (
    oid          TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    vendor       TEXT NOT NULL DEFAULT 'standard',   -- standard | cisco | aruba | ruckus | ubiquiti
    category     TEXT NOT NULL DEFAULT 'radio',       -- radio | client | system
    unit         TEXT NOT NULL DEFAULT ''
);

-- ── Outbound suite integrations (pktWiFi acting as a client of sibling apps) ─
-- base_url + suite_token for calling pktsnmp/pktflow/pktlog/pktpcap directly
-- (in addition to pktWiFi's own inbound /api/suite/* for pktHub to call in).
CREATE TABLE IF NOT EXISTS integrations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name          TEXT NOT NULL UNIQUE,   -- pktsnmp | pktflow | pktlog | pktpcap
    base_url          TEXT NOT NULL DEFAULT '',
    suite_token       TEXT NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 0,
    health_status     TEXT NOT NULL DEFAULT 'unknown',
    last_health_check TEXT,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
