import asyncio
from app.connectors.pinterest_connector import PinterestConnector


def test_send_message():
    connector = PinterestConnector("tok", "board")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = PinterestConnector("tok", "board")
    result = asyncio.get_event_loop().run_until_complete(connector.process_incoming({"m": 1}))
    assert result == {"m": 1}
