import asyncio

from app.connectors.dingtalk_connector import DingTalkConnector


def test_send_message():
    connector = DingTalkConnector("token")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = DingTalkConnector("token")
    payload = {"foo": "bar"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
