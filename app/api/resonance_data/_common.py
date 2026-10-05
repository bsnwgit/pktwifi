"""
The shared router, the paths of the contract, the operations a grant may name, and the fixed vocabularies.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter


log = logging.getLogger("pktwifi.api.resonance_data")


router = APIRouter(tags=["resonance-data"])


DATA_PREFIX = "/api/resonance/data"


SPEC_PATH = "/api/resonance/openapi.json"


GRANT_PATH = "/.well-known/resonance.json"


# ── What the assistant is allowed to call ────────────────────────────────────
#
# The one list. The grant file is generated from it, the published spec is
# filtered to it, and startup checks it against the routes that actually exist.
# An operationId that is not here is invisible to the assistant even though it
# is a perfectly ordinary route of this app.


@dataclass(frozen=True)
class Grant:
    op: str
    # Set on ANY operation that changes state, whatever its HTTP verb.
    # Resonance reads the values back to the person before running one.
    writes: bool = False


GRANTED: tuple[Grant, ...] = (
    Grant("getWifiSummary"),
    Grant("listAccessPoints"),
    Grant("getAccessPoint"),
    Grant("listWifiClients"),
    Grant("listRadios"),
    Grant("listCollectors"),
    Grant("listAlertEvents"),
    Grant("listAlertRules"),
    Grant("searchApplicationLog"),
    # The only state change on offer. There is deliberately no channel or power
    # change, no client deauthentication, and no create, edit or delete of
    # anything: an assistant may acknowledge what an administrator is already
    # being told about, and nothing else.
    Grant("ackAlertEvent", writes=True),
    Grant("ackAllAlertEvents", writes=True),
)


# ── Vocabulary ────────────────────────────────────────────────────────────────
#
# These are the enums the requirement is really about: without them a model asks
# for a band of "5G" or a status of "offline", gets a 422, and reports the app
# as broken. All of these are fixed in pktWiFi's own code — the
# install-specific vocabulary (AP names, SSIDs, site names) cannot be, and is
# published through listAccessPoints and listWifiClients instead.

ApStatus = Literal["online", "offline", "unknown"]


Band = Literal["2.4", "5", "6"]


AlertSeverity = Literal["info", "warning", "critical"]


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
