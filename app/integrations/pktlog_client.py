"""
Pull AP/controller syslog entries from pktLog — auth failures, deauths, and
roaming events that show up in vendor syslog output but aren't exposed by
every controller's API/SNMP surface.
"""
from __future__ import annotations

from typing import Optional

from app.integrations.suite_client import SuiteClient


class PktLogClient(SuiteClient):
    async def get_wifi_logs(self, mac_address: Optional[str] = None, limit: int = 200) -> list:
        params: dict = {"limit": limit}
        if mac_address:
            params["q"] = mac_address
        result = await self.get("/api/syslog/search", params=params)
        return result.get("results", result) if isinstance(result, dict) else result
