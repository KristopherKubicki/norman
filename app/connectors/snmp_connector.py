from typing import Optional

try:
    from pysnmp.hlapi import (
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,
        ContextData,
        ObjectType,
        ObjectIdentity,
        sendNotification,
    )
except ImportError:  # pragma: no cover - optional dependency
    SnmpEngine = CommunityData = UdpTransportTarget = ContextData = ObjectType = ObjectIdentity = sendNotification = None

from .base_connector import BaseConnector


class SNMPConnector(BaseConnector):
    """Connector for sending SNMP traps using ``pysnmp``."""

    id = "snmp"
    name = "SNMP"

    def __init__(self, host: str, port: int = 162, community: str = "public", oid: str = "1.3.6.1.4.1.32473.1.0", config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.host = host
        self.port = port
        self.community = community
        self.oid = oid

    def send_message(self, message: str) -> Optional[str]:
        if sendNotification is None:
            raise RuntimeError("pysnmp not installed")
        error_indication, error_status, error_index, _var_binds = next(
            sendNotification(
                SnmpEngine(),
                CommunityData(self.community),
                UdpTransportTarget((self.host, self.port)),
                ContextData(),
                "trap",
                ObjectType(ObjectIdentity(self.oid), message),
            )
        )
        if error_indication or error_status:
            return None
        return "ok"

    async def listen_and_process(self) -> None:
        """Listening for SNMP traps not implemented."""
        return None

    async def process_incoming(self, message: str) -> str:
        return message
