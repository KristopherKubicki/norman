import asyncio
from app.connectors.snapchat_connector import SnapchatConnector


def test_send_message():
    connector = SnapchatConnector("user", "pw")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = SnapchatConnector("user", "pw")
    result = asyncio.get_event_loop().run_until_complete(connector.process_incoming({"m": 1}))
    assert result == {"m": 1}
