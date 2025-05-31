import asyncio
from app.connectors.reddit_chat_connector import RedditChatConnector


def test_send_message():
    connector = RedditChatConnector("id", "sec", "u", "p", "ua")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = RedditChatConnector("id", "sec", "u", "p", "ua")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"bar": 2})
    )
    assert result == {"bar": 2}
