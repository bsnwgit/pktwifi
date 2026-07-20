-- Site catalog — collector config "site" fields (UniFi controller site,
-- SNMP generic host entries) stay plain TEXT (no FK migration of existing
-- values), but the UI now picks from this managed list via a dropdown
-- instead of free-typing a site name. Same pattern as pktIPAM's sites table.
CREATE TABLE IF NOT EXISTS sites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
