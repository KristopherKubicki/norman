from fastapi.testclient import TestClient
from app.api.api_v1.routers.connectors import webhook as webhook_router
from app.core.test_settings import test_settings


def test_get_webhook_connector_uses_settings():
    connector = webhook_router.get_webhook_connector(test_settings)
    assert connector.webhook_url == test_settings.webhook_secret


def test_process_webhook_update(monkeypatch, test_app: TestClient):
    received = {}

    class DummyConnector:
        def __init__(self, webhook_url: str):
            self.webhook_url = webhook_url
        def process_incoming(self, payload):
            received["payload"] = payload
            return "ok"

    monkeypatch.setattr(webhook_router, "WebhookConnector", DummyConnector)
    resp = test_app.post(
        "/api/v1/connectors/webhook/webhooks/webhook",
        json={"text": "hi"},
        headers={"X-Webhook-Token": test_settings.webhook_auth_token},
    )
    assert resp.status_code == 200
    assert received["payload"] == {"text": "hi"}


def test_process_webhook_update_invalid_token(monkeypatch, test_app: TestClient):
    class DummyConnector:
        def __init__(self, webhook_url: str):
            self.webhook_url = webhook_url
        def process_incoming(self, payload):
            return "ok"

    monkeypatch.setattr(webhook_router, "WebhookConnector", DummyConnector)
    resp = test_app.post(
        "/api/v1/connectors/webhook/webhooks/webhook",
        json={"text": "hi"},
        headers={"X-Webhook-Token": "bad"},
    )
    assert resp.status_code == 401
