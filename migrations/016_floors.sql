-- Floor plans and client location.
--
-- A floor is a plan image belonging to a site, so one site can hold several.
-- Access points are placed on a floor by pixel position in the image; the
-- scale (pixels per metre) turns an RSSI-derived distance into pixels.
-- `access_points.floor` (free text) is written by the collectors on every poll
-- and stays as it was; `floor_id` is the one an admin sets, so a poll never
-- overwrites a placement.
CREATE TABLE IF NOT EXISTS floors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id       INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    level         INTEGER NOT NULL DEFAULT 0,   -- ordering, lowest first
    image_path    TEXT,                         -- file name under the floorplans directory
    image_w       INTEGER,
    image_h       INTEGER,
    scale_px_per_m REAL,                        -- NULL until calibrated
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (site_id, name)
);
CREATE INDEX IF NOT EXISTS idx_floors_site ON floors(site_id);

-- The signal a client was last heard at by each AP. Today collectors report
-- only the AP a client is joined to, so there is one row per client; a
-- collector that can report more fills the same table and location improves.
CREATE TABLE IF NOT EXISTS client_ap_signals (
    client_mac      TEXT NOT NULL,
    access_point_id INTEGER NOT NULL REFERENCES access_points(id) ON DELETE CASCADE,
    rssi_dbm        REAL NOT NULL,
    seen_at         TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (client_mac, access_point_id)
);
CREATE INDEX IF NOT EXISTS idx_client_ap_signals_seen ON client_ap_signals(seen_at);

ALTER TABLE access_points ADD COLUMN floor_id INTEGER REFERENCES floors(id) ON DELETE SET NULL;
ALTER TABLE access_points ADD COLUMN x_px     REAL;
ALTER TABLE access_points ADD COLUMN y_px     REAL;
