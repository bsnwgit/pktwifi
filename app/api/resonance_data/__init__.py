"""
app/api/resonance_data/ — the data half of the resonance contract.

app/api/resonance.py mounts the panel. This module is what the panel is
allowed to *read* once it is mounted, and it exists because the embed contract
has three parts and mounting only satisfies one of them:

  1. an OpenAPI document at a stable same-origin path      -> /api/resonance/openapi.json
  2. a grant file naming what may be called                -> /.well-known/resonance.json
  3. endpoints that behave: bounded, JSON, stable fields   -> /api/resonance/data/*

Why a separate surface rather than granting against /api/access-points/* and friends.
The operations named in a grant have to carry a stable operationId, prose a
stranger can choose between, enums for every fixed vocabulary, a declared
response schema, and a bounded page with a total. pktWiFi's own endpoints were
written for a SPA that already knows all of that: most return a bare array with
no total and no paging. Retrofitting the contract onto them would change
response shapes the frontend already consumes. These wrap the same tables
instead, so there is no second implementation of any query — only a second,
narrower doorway with the labels the model needs.

Authentication is the app's existing session, not a new one. The panel's calls
are ordinary same-origin fetches from our own page, so they carry the refresh
cookie exactly as /api/resonance/code does, and they are admitted by the same
helpers that admit /code — see resonance_session_user below. Nothing here
issues, accepts or understands a credential of resonance's, and the panel can
therefore only ever read what the signed-in person could already read.

WHAT IS DELIBERATELY ABSENT IS PART OF THE DESIGN. A collector's stored
configuration — the controller credentials it polls with — is never selected, so
it cannot reach the assistant through a schema's `extra` either. Nothing here
creates, edits or deletes an access point, an SSID, a radio or a collector,
nothing changes a channel or a transmit power, and nothing deauthenticates a
client. Acknowledging an alert is the only thing that changes state, and
pktWiFi's own interface has no rule on/off switch for an assistant to mirror.
"""
from __future__ import annotations

from app.api.resonance_data._common import router  # noqa: F401
from app.api.resonance_data.errors import register_error_handler  # noqa: F401
from app.api.resonance_data.documents import validate_grants  # noqa: F401

# Importing these registers their routes on the shared router.
from app.api.resonance_data import read, documents, writes  # noqa: E402,F401
