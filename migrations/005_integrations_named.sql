-- Upgrade from one singleton row per app_name to multiple named instances
-- per app_name, matching pktIPAM/pktflow/pktsnmp/pktlog's own integrations
-- table shape. SQLite can't ALTER a UNIQUE constraint away, so this rebuilds
-- the table, same approach as pktIPAM's migration 006.
CREATE TABLE integrations_new (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,   -- user-given label, e.g. "Main pktsnmp"
    app_name          TEXT NOT NULL,
    base_url          TEXT NOT NULL DEFAULT '',
    suite_token       TEXT NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 1,
    health_status     TEXT NOT NULL DEFAULT 'unknown',
    last_health_check TEXT,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Carry over any existing configured singleton row as a named instance
-- (named after its app_name) so a configured connection isn't silently
-- dropped by this migration.
INSERT INTO integrations_new (name, app_name, base_url, suite_token, enabled, health_status, last_health_check, updated_at)
SELECT app_name, app_name, base_url, suite_token, enabled, health_status, last_health_check, updated_at
FROM integrations
WHERE base_url != '' OR suite_token != '';

DROP TABLE integrations;
ALTER TABLE integrations_new RENAME TO integrations;

CREATE INDEX IF NOT EXISTS idx_integrations_app_name ON integrations(app_name);
