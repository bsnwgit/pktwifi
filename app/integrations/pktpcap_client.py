"""
List/download packet-capture feeds from pktPCAP for on-demand RF/association
troubleshooting (e.g. a deauth storm or rogue-AP investigation) without
pktWiFi needing its own capture pipeline.

pktPCAP's data model is "feeds" — named live pcapng streams pushed from a
remote tshark/Wireshark host — rather than a request/trigger-capture API,
so this client is a thin read-only wrapper, not a capture initiator.
"""
from __future__ import annotations

from app.integrations.suite_client import SuiteClient


class PktPcapClient(SuiteClient):
    async def list_feeds(self) -> list:
        return await self.get("/api/feeds")
