import asyncio
import types
import pytest
import app.connectors.google_pubsub_connector as mod


class DummyFuture:
    def result(self):
        return "id"


class DummyPublisher:
    def __init__(self):
        self.published = []

    def topic_path(self, project_id, topic_id):
        return f"{project_id}/{topic_id}"

    def publish(self, topic_path, message):
        self.published.append((topic_path, message))
        return DummyFuture()


def test_send_message_success(monkeypatch):
    stub = types.SimpleNamespace(PublisherClient=lambda *a, **k: DummyPublisher())
    monkeypatch.setattr(mod, "pubsub_v1", stub)
    connector = mod.GooglePubSubConnector("p", "t")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "id"


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mod, "pubsub_v1", None)
    connector = mod.GooglePubSubConnector("p", "t")
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
