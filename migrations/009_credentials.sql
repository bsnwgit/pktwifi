-- Named controller-credential library (Settings -> Credentials), referenced by
-- controller configs via credential_select dropdowns instead of inline auth
-- fields. Same pattern as pktsnmp's snmp_credentials / pktipam's library, but
-- typed for WiFi controller auth: username/password pairs, API keys/tokens,
-- and SNMP v2c/v3 for the generic collector. Secret columns (*_enc) are
-- Fernet-encrypted with the app's credential_key and never returned by the API.
CREATE TABLE IF NOT EXISTS credentials (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,
    description       TEXT NOT NULL DEFAULT '',
    cred_type         TEXT NOT NULL CHECK (cred_type IN ('userpass', 'api_key', 'snmp_v2c', 'snmp_v3')),
    username          TEXT,          -- userpass; snmp_v3 security name
    password_enc      TEXT,          -- userpass
    api_key_enc       TEXT,          -- api_key
    community_enc     TEXT,          -- snmp_v2c
    auth_protocol     TEXT,          -- snmp_v3: SHA | MD5
    auth_password_enc TEXT,          -- snmp_v3
    priv_protocol     TEXT,          -- snmp_v3: AES | DES
    priv_password_enc TEXT,          -- snmp_v3
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
