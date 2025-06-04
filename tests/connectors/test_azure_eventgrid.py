import asyncio
import types
import pytest
import app.connectors.azure_eventgrid_connector as mod


class DummyResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("bad")

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


def test_is_connected(monkeypatch):
    stub = types.SimpleNamespace(
        EventGridPublisherClient=DummyClient,
        EventGridEvent=DummyEvent,
        AzureKeyCredential=lambda key: object(),
    )
    monkeypatch.setattr(mod, "EventGridPublisherClient", stub.EventGridPublisherClient)
    monkeypatch.setattr(mod, "EventGridEvent", stub.EventGridEvent)
    monkeypatch.setattr(mod, "AzureKeyCredential", stub.AzureKeyCredential)
    monkeypatch.setattr(mod.importlib, "import_module", lambda n: types.SimpleNamespace(get=lambda *a, **kw: DummyResponse()))
    connector = mod.AzureEventGridConnector("https://e", "KEY")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    stub = types.SimpleNamespace(
        EventGridPublisherClient=DummyClient,
        EventGridEvent=DummyEvent,
        AzureKeyCredential=lambda key: object(),
    )
    monkeypatch.setattr(mod, "EventGridPublisherClient", stub.EventGridPublisherClient)
    monkeypatch.setattr(mod, "EventGridEvent", stub.EventGridEvent)
    monkeypatch.setattr(mod, "AzureKeyCredential", stub.AzureKeyCredential)
    def bad_import(name):
        def raise_err(*args, **kwargs):
            raise Exception("boom")
        return types.SimpleNamespace(get=raise_err, HTTPError=Exception)
    monkeypatch.setattr(mod.importlib, "import_module", bad_import)
    connector = mod.AzureEventGridConnector("https://e", "KEY")
    assert not connector.is_connected()


def test_is_connected_no_library(monkeypatch):
    monkeypatch.setattr(mod, "EventGridPublisherClient", None)
    connector = mod.AzureEventGridConnector("https://e", "KEY")
    assert not connector.is_connected()
