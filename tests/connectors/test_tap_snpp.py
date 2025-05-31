import asyncio
from app.connectors.tap_snpp_connector import TAPSNPPConnector


def test_send_message():
    connector = TAPSNPPConnector("host")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = TAPSNPPConnector("host")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
