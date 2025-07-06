from fastapi.testclient import TestClient


def test_health_endpoint(test_app: TestClient) -> None:
    resp = test_app.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_request_id_header(test_app: TestClient) -> None:
    resp = test_app.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")
