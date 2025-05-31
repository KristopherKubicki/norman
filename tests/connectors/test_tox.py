import asyncio

from app.connectors.tox_connector import ToxConnector


def test_send_message():
    connector = ToxConnector("host")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = ToxConnector("host")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
