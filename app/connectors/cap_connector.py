"""Connector for sending alerts using the Common Alerting Protocol (CAP v1.2)."""

from typing import Any, List, Optional
import asyncio
import xml.etree.ElementTree as ET

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class CAPConnector(BaseConnector):
    """Send CAP 1.2 messages to a remote HTTP endpoint."""

    id = "cap"
    name = "Common Alerting Protocol v1.2"

    def __init__(self, endpoint: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.endpoint = endpoint
        self.sent_messages: List[Any] = []

    async def send_message(self, message: Any) -> Optional[str]:
        """POST ``message`` to the configured endpoint and record it."""

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.endpoint, data=message)
                resp.raise_for_status()
                self.sent_messages.append(message)
                return resp.text
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error sending CAP message: %s", exc)
                return None

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
                "description": info.findtext(
                    "cap:description", default="", namespaces=ns
                ),
                "severity": info.findtext("cap:severity", default="", namespaces=ns),
            }
            processed = self.process_incoming(message)
            if asyncio.iscoroutine(processed):
                processed = await processed
            if processed:
                results.append(processed)
        return results

    async def process_incoming(self, message: Any) -> Any:
        if not isinstance(message, dict):
            text = str(message)
            summary = f"cap • {text}" if text else "cap"
            return {"text": text, "text_summary": summary}
        text = message.get("headline") or message.get("description") or ""
        summary_parts = ["cap"]
        if message.get("severity"):
            summary_parts.append(str(message.get("severity")))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "headline": message.get("headline"),
            "description": message.get("description"),
            "severity": message.get("severity"),
            "text_summary": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the endpoint responds successfully."""

        try:
            resp = httpx.get(self.endpoint, timeout=5)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
