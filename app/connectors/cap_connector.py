"""Connector for sending alerts using the Common Alerting Protocol (CAP v1.2)."""

from typing import Any, List, Optional
import asyncio
import xml.etree.ElementTree as ET

import httpx

from .base_connector import BaseConnector


class CAPConnector(BaseConnector):
    """Send CAP 1.2 messages to a remote HTTP endpoint."""

    id = "cap"
    name = "Common Alerting Protocol v1.2"

    def __init__(self, endpoint: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.endpoint = endpoint
        self.sent_messages: List[Any] = []

    async def send_message(self, message: Any) -> str:
        """POST ``message`` to the configured endpoint and record it."""

        self.sent_messages.append(message)
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.endpoint, data=message)
                resp.raise_for_status()
            except httpx.HTTPError:  # pragma: no cover - network
                pass
        return "sent"

    async def listen_and_process(self) -> List[Any]:
        """Fetch CAP XML from the endpoint and process any alerts."""

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(self.endpoint)
                resp.raise_for_status()
                xml_data = resp.text
            except httpx.HTTPError:  # pragma: no cover - network
                return []

        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError:
            return []

        ns = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
        results = []
        alerts = list(root.findall(".//cap:alert", ns))
        if root.tag.endswith("alert"):
            alerts.insert(0, root)
        for alert in alerts:
            info = alert.find("cap:info", ns)
            if info is None:
                continue
            message = {
                "headline": info.findtext("cap:headline", default="", namespaces=ns),
                "description": info.findtext("cap:description", default="", namespaces=ns),
                "severity": info.findtext("cap:severity", default="", namespaces=ns),
            }
            processed = self.process_incoming(message)
            if asyncio.iscoroutine(processed):
                processed = await processed
            if processed:
                results.append(processed)
        return results

    async def process_incoming(self, message: Any) -> Any:
        return message
