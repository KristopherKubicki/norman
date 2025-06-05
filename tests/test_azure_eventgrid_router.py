from fastapi.testclient import TestClient
from app.api.api_v1.routers.connectors import azure_eventgrid as eventgrid_router
from app.core.test_settings import test_settings


def test_get_eventgrid_connector_uses_settings():
    connector = eventgrid_router.get_eventgrid_connector(test_settings)
    assert connector.endpoint == test_settings.azure_eventgrid_endpoint
    assert connector.key == test_settings.azure_eventgrid_key


def test_process_eventgrid_update(monkeypatch, test_app: TestClient):
    received = {}

    class DummyConnector:
        def __init__(self, endpoint: str, key: str, config=None):
            self.endpoint = endpoint
            self.key = key

        def process_incoming(self, payload):
            received["payload"] = payload

    monkeypatch.setattr(eventgrid_router, "AzureEventGridConnector", DummyConnector)
    resp = test_app.post(
        "/api/v1/connectors/azure_eventgrid/webhooks/eventgrid",
        json={"msg": "hi"},
    )
    assert resp.status_code == 200
    assert received["payload"] == {"msg": "hi"}
