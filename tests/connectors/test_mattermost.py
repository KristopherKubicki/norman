import asyncio
from app.connectors.mattermost_connector import MattermostConnector


def test_send_message():
    connector = MattermostConnector("http://mm", "tok", "chan")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = MattermostConnector("http://mm", "tok", "chan")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"foo": "bar"})
    )
    assert result == {"foo": "bar"}
