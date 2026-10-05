"""
pktWiFi — Widget endpoints for pktHub NOC Builder integration.

Manifest: GET /api/widgets/manifest  → list of widget definitions
Views:    GET /api/widgets/{id}      → server-rendered HTML page (iframe target)
Options:  GET /api/widgets/options/* → JSON [{value,label}] for dynamic param pickers
"""
from __future__ import annotations

from app.api.widgets._common import router  # noqa: F401

# Importing these registers their routes on the shared router.
from app.api.widgets import manifest, fleet, clients, rf, options  # noqa: E402,F401
