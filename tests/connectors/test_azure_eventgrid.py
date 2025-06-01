import asyncio
import types
import pytest
import app.connectors.azure_eventgrid_connector as mod

class DummyClient:
    def __init__(self, endpoint, credential):
        self.sent = []
    def send(self, events):
        self.sent.append(events)

class DummyEvent:
    def __init__(self, subject=None, event_type=None, data=None, data_version=None):
        self.data = data


def test_send_message_success(monkeypatch):
    stub = types.SimpleNamespace(
        EventGridPublisherClient=DummyClient,
        EventGridEvent=DummyEvent,
        AzureKeyCredential=lambda key: object(),
    )
    monkeypatch.setattr(mod, "EventGridPublisherClient", stub.EventGridPublisherClient)
    monkeypatch.setattr(mod, "EventGridEvent", stub.EventGridEvent)
    monkeypatch.setattr(mod, "AzureKeyCredential", stub.AzureKeyCredential)
    connector = mod.AzureEventGridConnector("https://e", "KEY")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message({"a":1}))
    assert result == "ok"
    assert connector.client.sent[0][0].data == {"a":1}


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mod, "EventGridPublisherClient", None)
    monkeypatch.setattr(mod, "EventGridEvent", None)
    monkeypatch.setattr(mod, "AzureKeyCredential", None)
    connector = mod.AzureEventGridConnector("https://e", "KEY")
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.send_message({}))
