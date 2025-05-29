"""Tests for connector routers to ensure connectors instantiate without errors."""

from fastapi.testclient import TestClient


def _post_and_check(client: TestClient, url: str) -> None:
    """Helper to post empty payload to ``url`` and assert a successful response."""

    response = client.post(url, json={})
    assert response.status_code == 200
    assert response.json() == {"detail": "Update processed"}


def test_connector_routes_create(test_app: TestClient) -> None:
    base = "/api/v1/connectors"
    endpoints = [
        f"{base}/telegram/webhooks/telegram",
        f"{base}/discord/webhooks/discord",
        f"{base}/google_chat/webhooks/google_chat",
        f"{base}/microsoft_teams/webhooks/teams",
        f"{base}/webhook/webhooks/webhook",
    ]

    for url in endpoints:
        _post_and_check(test_app, url)

