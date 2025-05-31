import asyncio
from app.connectors.cap_connector import CAPConnector


def test_send_message():
    connector = CAPConnector("http://example.com")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message({"msg": "hi"})
    )
    assert result == "sent"
    assert connector.sent_messages == [{"msg": "hi"}]


def test_process_incoming():
    connector = CAPConnector("http://example.com")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
