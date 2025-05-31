import asyncio
from app.connectors.bluesky_connector import BlueskyConnector


def test_send_message():
    connector = BlueskyConnector("h", "pw")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = BlueskyConnector("h", "pw")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"x": 1})
    )
    assert result == {"x": 1}
