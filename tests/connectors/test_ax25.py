import asyncio
from app.connectors.ax25_connector import AX25Connector


def test_send_message():
    connector = AX25Connector("port", "CALL")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = AX25Connector("port", "CALL")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
