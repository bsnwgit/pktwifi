"""
pktWiFi configuration.

Priority order (highest -> lowest):
  1. Environment variables  (PKTWIFI_*)
  2. config.yaml — found via $PKTWIFI_CONFIG, $PKTWIFI_INSTALL_DIR/config.yaml,
     ./config.yaml, or ~/.pktwifi/config.yaml
  3. Defaults defined here

No path in this file is hardcoded to a specific install location. Every
on-disk path (db_path, log_file, ssl_dir, ...) defaults to somewhere under
`install_dir` — the directory install.sh (or $PKTWIFI_INSTALL_DIR) was
pointed at — so the app works the same whether it's installed at
/opt/pktwifi, in-place in a repo checkout, or anywhere else. Override any
individual path in config.yaml if you need it to live somewhere else.

Runtime settings (collector credentials, alert thresholds, integration
base URLs/tokens, etc.) are stored in SQLite and loaded via the settings
table; those are NOT in this file. This file only covers startup/
infrastructure settings that must be known before the database is connected.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from time import monotonic
from typing import Literal, Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_config_path() -> Optional[Path]:
    """Try known config file locations, in priority order."""
    candidates = [Path("config.yaml")]
    install_dir = os.environ.get("PKTWIFI_INSTALL_DIR")
    if install_dir:
        candidates.insert(0, Path(install_dir) / "config.yaml")
    candidates.append(Path.home() / ".pktwifi" / "config.yaml")

    env_path = os.environ.get("PKTWIFI_CONFIG")
    if env_path:
        candidates.insert(0, Path(env_path))

    for path in candidates:
        if path.exists():
            return path
    return None


def _load_yaml(path: Optional[Path]) -> dict:
    if path is None:
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _default_install_dir(config_path: Optional[Path]) -> Path:
    """The app root: everything else defaults to a path under this."""
    env_dir = os.environ.get("PKTWIFI_INSTALL_DIR")
    if env_dir:
        return Path(env_dir)
    if config_path is not None:
        return config_path.resolve().parent
    return Path.cwd()


_CONFIG_PATH = _find_config_path()
_yaml_cfg = _load_yaml(_CONFIG_PATH)
_INSTALL_DIR = _default_install_dir(_CONFIG_PATH)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PKTWIFI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Server --------------------------------------------------------------
    host: str = Field(default=_yaml_cfg.get("host", "0.0.0.0"))
    port: int = Field(default=_yaml_cfg.get("port", 8769))
    https_port: int = Field(default=_yaml_cfg.get("https_port", 443))
    workers: int = Field(default=_yaml_cfg.get("workers", 2))
    debug: bool = Field(default=_yaml_cfg.get("debug", False))

    # -- App root — every other path below defaults to somewhere under this --
    install_dir: str = Field(default=_yaml_cfg.get("install_dir", str(_INSTALL_DIR)))

    # -- First-boot admin seed -------------------------------------------------
    # Set by install.sh from PKTWIFI_ADMIN_PASSWORD; ignored if DB already has users.
    admin_password: str = Field(default="")

    # -- App database (SQLite) ------------------------------------------------
    db_path: str = Field(
        default=_yaml_cfg.get("db_path", str(_INSTALL_DIR / "pktwifi.db"))
    )

    # -- ClickHouse (reserved for a future high-scale RF-metrics backend;
    #    v1 stores everything in SQLite — see app/storage/sqlite_ts.py) -------
    clickhouse_host: str = Field(default=_yaml_cfg.get("clickhouse_host", "localhost"))
    clickhouse_port: int = Field(default=_yaml_cfg.get("clickhouse_port", 9000))
    clickhouse_database: str = Field(default=_yaml_cfg.get("clickhouse_database", "pktwifi"))
    clickhouse_user: str = Field(default=_yaml_cfg.get("clickhouse_user", "default"))
    clickhouse_password: str = Field(default=_yaml_cfg.get("clickhouse_password", ""))

    # -- JWT -------------------------------------------------------------------
    secret_key: str = Field(
        default=_yaml_cfg.get("secret_key", "CHANGE_ME_IN_PRODUCTION_secret_key_32chars")
    )
    algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # -- CORS --------------------------------------------------------------------
    cors_origins: list[str] = Field(
        default=_yaml_cfg.get("cors_origins", ["*"])
    )

    # -- pktSuite integration (inbound — pktHub calling into this app) -----------
    suite_token: str = Field(default=_yaml_cfg.get("suite_token", ""))

    # -- Fernet key for encrypting stored vendor-collector credentials -----------
    credential_key: str = Field(default=_yaml_cfg.get("credential_key", ""))

    # -- Logging -------------------------------------------------------------------
    log_level: str = Field(default=_yaml_cfg.get("log_level", "info"))
    log_file: str = Field(
        default=_yaml_cfg.get("log_file", str(_INSTALL_DIR / "logs" / "pktwifi.log"))
    )

    # -- SSL certificate storage -------------------------------------------------
    ssl_dir: str = Field(default=_yaml_cfg.get("ssl_dir", str(_INSTALL_DIR / "ssl")))


# Insecure placeholders that must never actually sign a JWT or encrypt a
# stored secret. Two distinct spellings exist for secret_key: this module's
# own in-code fallback (used when the key is entirely absent from
# config.yaml) and config.example.yaml's placeholder text (what's actually
# in config.yaml if an operator copied that file without editing it) — a
# different string, so checking only one leaves the other route to a
# publicly-known secret unguarded.
_INSECURE_SECRET_KEY_VALUES = {
    "", "CHANGE_ME_IN_PRODUCTION_secret_key_32chars",
    "CHANGE_ME_generate_with_openssl_rand_hex_32",
}
_INSECURE_CREDENTIAL_KEY_VALUES = {
    "", "CHANGE_ME_generate_with_fernet_generate_key",
}


def _validate_secrets(s: "Settings") -> None:
    """Fail loudly at startup rather than silently signing JWTs / encrypting
    secrets with a publicly-known key."""
    if (s.secret_key or "").strip() in _INSECURE_SECRET_KEY_VALUES:
        raise RuntimeError(
            "pktwifi refuses to start: secret_key is missing or still set to a "
            "placeholder value from config.example.yaml. Set a real, unique "
            "secret_key in config.yaml — `openssl rand -hex 32` generates one."
        )
    if (s.credential_key or "").strip() in _INSECURE_CREDENTIAL_KEY_VALUES:
        raise RuntimeError(
            "pktwifi refuses to start: credential_key is missing or still set to "
            "a placeholder value from config.example.yaml. Set a real, unique "
            "credential_key in config.yaml — "
            "`python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "generates one."
        )


@lru_cache
def _base_settings() -> Settings:
    """Startup config, read once. Everything this reads — environment,
    config.yaml, .env — is fixed for the life of the process, so constructing
    Settings() again per call only re-reads the same files off disk."""
    s = Settings()
    _validate_secrets(s)
    return s


# suite_token is the one field that must not be read once and kept: it is
# rewritten by /api/suite/register and /api/suite/regenerate, and the new value
# has to take effect without a service restart. Re-reading SQLite on every call
# did achieve that — but get_settings() runs at least twice per request (the
# auth dependency, then the Managed-mode middleware), sqlite3 is synchronous,
# and FastAPI calls both from the event loop. Every request was therefore
# opening and closing a database on the loop thread and blocking every other
# request in flight while it did.
#
# Cache the resolved Settings instead and let the token's writers invalidate
# it. The TTL is the backstop for a writer this module doesn't know about (a
# restored backup, a hand-edited row) — without it, such a write would not be
# seen until the process restarted, which is the behaviour this indirection
# exists to avoid.
_TOKEN_TTL_SECONDS = 5.0

_cached: Optional[Settings] = None
_cached_at: float = 0.0


def invalidate_settings_cache() -> None:
    """Drop the cached suite token, so the next read picks up a new one."""
    global _cached
    _cached = None


def get_settings() -> Settings:
    global _cached, _cached_at

    now = monotonic()
    if _cached is not None and (now - _cached_at) < _TOKEN_TTL_SECONDS:
        return _cached

    s = _base_settings()
    try:
        import sqlite3 as _sq, json as _j
        _conn = _sq.connect(s.db_path)
        _row = _conn.execute("SELECT value FROM settings WHERE key='suite_token'").fetchone()
        _conn.close()
        if _row and _row[0]:
            _val = _row[0]
            _tok = _j.loads(_val) if _val.startswith('"') else _val
            if _tok:
                # model_copy, not mutation — _base_settings() hands back the one
                # shared instance and it must stay as config.yaml wrote it.
                s = s.model_copy(update={'suite_token': _tok})
    except Exception:
        pass

    _cached, _cached_at = s, now
    return s
