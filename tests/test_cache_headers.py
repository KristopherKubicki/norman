from fastapi.testclient import TestClient


def test_static_icon_cache_header(test_app: TestClient) -> None:
    response = test_app.get("/static/icons/connectors/slack.svg")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "public, max-age=86400, immutable"


def test_json_cache_header(test_app: TestClient) -> None:
    response = test_app.get("/health")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "max-age=60"
