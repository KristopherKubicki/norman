"""Passive ARP listener connector for local network observations."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class ARPConnector(BaseConnector):
    """Passive connector that normalizes ARP observations for routing."""

    id = "arp"
    name = "ARP Monitor"

    def __init__(
        self,
        listen_interface: str = "",
        sample_window_seconds: int = 10,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.listen_interface = listen_interface
        self.sample_window_seconds = sample_window_seconds

    def send_message(self, message: Any) -> Optional[str]:
        """ARP connector is passive-only; outbound send is unsupported."""
        return None

    async def listen_and_process(self) -> None:
        """Passive loop placeholder for capture integrations (pcap/ebpf)."""
        while True:  # pragma: no cover - long-running loop
            await asyncio.sleep(max(1, int(self.sample_window_seconds or 10)))

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        """Normalize ARP events from webhook/collector payloads."""
        if isinstance(message, dict):
            src_ip = (
                message.get("src_ip") or message.get("ip") or message.get("sender_ip")
            )
            src_mac = (
                message.get("src_mac")
                or message.get("mac")
                or message.get("sender_mac")
            )
            dst_ip = message.get("dst_ip") or message.get("target_ip")
            op = message.get("op") or message.get("operation") or "observation"
            iface = message.get("interface") or self.listen_interface
        else:
            text = str(message)
            return {
                "text": text,
                "text_summary": f"arp • {text}",
                "signal_class": "passive",
                "passive_source": "arp",
                "sensor_type": "arp",
            }

        details = [part for part in [src_ip, src_mac, dst_ip] if part]
        detail_text = " -> ".join(details) if details else "event"
        text = f"ARP {op}: {detail_text}"

        return {
            "text": text,
            "src_ip": src_ip,
            "src_mac": src_mac,
            "dst_ip": dst_ip,
            "operation": op,
            "interface": iface,
            "text_summary": f"arp • {op} • {detail_text}",
            "signal_class": "passive",
            "passive_source": "arp",
            "sensor_type": "arp",
        }
