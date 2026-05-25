from fastapi.testclient import TestClient
from app.core.test_settings import test_settings


def test_available_connectors_endpoint(monkeypatch, test_app: TestClient):
    sample = [
        {
            "id": "slack",
            "name": "Slack",
            "status": "missing_config",
            "fields": ["token", "channel_id"],
            "defaults": {},
            "capabilities": {},
            "last_message_sent": None,
            "enabled": False,
            "oauth": None,
        }
    ]

    monkeypatch.setattr(
        "app.api.api_v1.routers.connectors_crud.get_connectors_data",
        lambda: sample,
    )

    resp = test_app.get("/api/v1/connectors/available")
    assert resp.status_code == 200
    assert (
        resp.headers.get("cache-control")
        == "private, max-age=300, stale-while-revalidate=600"
    )
    assert resp.json() == sample
