import types
import asyncio
import pytest
import app.connectors.kafka_connector as mod


class DummyProducer:
    def __init__(self):
        self.messages = []

    def produce(self, topic, value=None):
        self.messages.append((topic, value))

    def flush(self):
        pass


class DummyMessage:
    def __init__(self, value):
        self._value = value.encode()

    def error(self):
        return False

    def value(self):
        return self._value


class DummyConsumer:
    def __init__(self, messages):
        self.messages = messages
        self.subscribed = []
        self.closed = False

    def subscribe(self, topics):
        self.subscribed = topics

    def poll(self, timeout=0.1):
        if self.messages:
            return self.messages.pop(0)
        return None

    def close(self):
        self.closed = True


def test_send_message_success(monkeypatch):
    monkeypatch.setattr(mod, "Producer", lambda conf: DummyProducer())
    connector = mod.KafkaConnector(bootstrap_servers="s", topic="t")
    assert connector.send_message("hi") == "ok"


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mod, "Producer", None)
    connector = mod.KafkaConnector()
    with pytest.raises(RuntimeError):
        connector.send_message("hi")


def test_listen_and_process(monkeypatch):
    msgs = [DummyMessage("hello")]
    monkeypatch.setattr(mod, "Consumer", lambda conf: DummyConsumer(msgs))

    processed = []

    class TestConnector(mod.KafkaConnector):
        async def process_incoming(self, message):
            processed.append(message)

    connector = TestConnector(bootstrap_servers="s", topic="t")

    async def fake_sleep(t):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.get_event_loop().run_until_complete(connector.listen_and_process())

    assert processed == ["hello"]
