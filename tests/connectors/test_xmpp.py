import asyncio
from app.connectors.xmpp_connector import XMPPConnector


def test_send_message():
    connector = XMPPConnector("user@example.com", "pass", "server")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = XMPPConnector("user@example.com", "pass", "server")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
