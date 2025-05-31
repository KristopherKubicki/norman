import asyncio
from app.connectors.instagram_dm_connector import InstagramDMConnector


def test_send_message():
    connector = InstagramDMConnector("tok", "uid")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = InstagramDMConnector("tok", "uid")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"d": 3})
    )
    assert result == {"d": 3}
