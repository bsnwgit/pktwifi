"""
Pull traffic-flow context from pktFlow for WiFi clients/subnets — e.g. "what
is this roaming client actually talking to" without pktWiFi needing its own
flow-collection pipeline.
"""
from __future__ import annotations

from app.integrations.suite_client import SuiteClient


class PktFlowClient(SuiteClient):
    async def get_top_talkers(self, limit: int = 20) -> list:
        return await self.get("/api/flows/top-talkers", params={"limit": limit})

    async def search_flows_for_ip(self, ip_address: str, limit: int = 100) -> list:
        return await self.get("/api/flows/search", params={"q": ip_address, "limit": limit})

    async def get_flow_rate(self) -> dict:
        return await self.get("/api/flows/rate")
