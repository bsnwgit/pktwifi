"""
app/wifi/freshness.py
---------------------
Which rows of the radios and wifi_clients snapshots are current.

The poll engine upserts both tables and never expires either: a band a
controller stops reporting keeps its last client_count, and a client that
leaves keeps its row with an ageing last_seen. Summed or listed as they stand,
both count what is no longer on air. A row is current when the poll that last
reported its access point also wrote it.

Each helper returns that rule as an SQL condition for a query that already
joins the row to its access point, so everything that sums, lists or alerts on
these tables applies the one rule rather than its own copy of it.
"""
from __future__ import annotations

# Only covers the seconds a large poll takes to persist its access points,
# radios and clients.
_SLACK = "-60 seconds"


def _alias(name: str) -> str:
    # Interpolated into SQL, so never anything but a plain identifier.
    if not name.isidentifier():
        raise ValueError(f"not an SQL alias: {name!r}")
    return name


def radio_is_current(radio: str = "r", ap: str = "ap") -> str:
    """`radio` was written by the latest poll of `ap`, the access point it is joined to."""
    return f"{_alias(radio)}.updated_at >= datetime({_alias(ap)}.last_seen, '{_SLACK}')"


def client_is_current(client: str = "c", ap: str = "ap") -> str:
    """`client` was written by the latest poll of `ap`, the access point it is joined to."""
    return f"{_alias(client)}.last_seen >= datetime({_alias(ap)}.last_seen, '{_SLACK}')"
