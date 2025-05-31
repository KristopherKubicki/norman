import asyncio

from app.connectors.tox_connector import ToxConnector


class DummyClient:
    def __init__(self):
        self.sent = None

    def send_message(self, friend_id, message):
        self.sent = (friend_id, message)


class ErrorClient(DummyClient):
    def send_message(self, friend_id, message):
        raise Exception("boom")


def test_send_message_success():
    connector = ToxConnector("ID", "FRIEND")
    connector.client = DummyClient()
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result == "sent"
    assert connector.client.sent == ("FRIEND", "hi")


def test_send_message_error():
    connector = ToxConnector("ID", "FRIEND")
    connector.client = ErrorClient()
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result is None


def test_process_incoming():
    connector = ToxConnector("ID", "FRIEND")
    payload = {"foo": "bar"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
