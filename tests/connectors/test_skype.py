import asyncio
from app.connectors.skype_connector import SkypeConnector


def test_send_message():
    connector = SkypeConnector("id", "pass")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = SkypeConnector("id", "pass")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"a": 1})
    )
    assert result == {"a": 1}
