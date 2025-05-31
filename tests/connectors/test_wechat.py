import asyncio
from app.connectors.wechat_connector import WeChatConnector


def test_send_message():
    connector = WeChatConnector("id", "secret")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = WeChatConnector("id", "secret")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"foo": 1})
    )
    assert result == {"foo": 1}
