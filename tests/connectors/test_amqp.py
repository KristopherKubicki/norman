import types
import asyncio
import pytest
import app.connectors.amqp_connector as mod


class DummyChannel:
    def __init__(self):
        self.published = []
        self.callback = None
        self.consumed = False

    def queue_declare(self, queue, durable=True):
        self.queue = queue

    def basic_publish(self, exchange="", routing_key=None, body=None):
        self.published.append((routing_key, body))

    def basic_consume(self, queue=None, on_message_callback=None, auto_ack=False):
        self.callback = on_message_callback

    def start_consuming(self):
        if self.callback:
            self.callback(None, None, None, b"hello")
        self.consumed = True

    def stop_consuming(self):
        pass


class DummyConnection:
    def __init__(self):
        self.channel_obj = DummyChannel()

    def channel(self):
        return self.channel_obj

    def close(self):
        self.closed = True


def test_send_message_success(monkeypatch):
    dummy = DummyConnection()
    stub = types.SimpleNamespace(
        BlockingConnection=lambda params: dummy,
        URLParameters=lambda url: url,
    )
    monkeypatch.setattr(mod, "pika", stub)
    connector = mod.AMQPConnector("amqp://", "q")
    connector.send_message("hi")
    assert dummy.channel_obj.published == [("q", b"hi")]


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mod, "pika", None)
    connector = mod.AMQPConnector("amqp://", "q")
    with pytest.raises(RuntimeError):
        connector.send_message("hi")


def test_listen_and_process(monkeypatch):
    dummy = DummyConnection()
    stub = types.SimpleNamespace(
        BlockingConnection=lambda params: dummy,
        URLParameters=lambda url: url,
    )
    monkeypatch.setattr(mod, "pika", stub)

    processed = []

    class TestConnector(mod.AMQPConnector):
        async def process_incoming(self, message):
            processed.append(message)

    connector = TestConnector("amqp://", "q")
    asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert processed == ["hello"]


def test_listen_and_process_no_library(monkeypatch):
    monkeypatch.setattr(mod, "pika", None)
    connector = mod.AMQPConnector("amqp://", "q")
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
