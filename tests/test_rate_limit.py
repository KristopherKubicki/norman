from fastapi.testclient import TestClient
from main import rate_limiter


def test_rate_limiting(test_app: TestClient) -> None:
    rate_limiter.requests.clear()
    rate_limiter.max_requests = 2
    for _ in range(2):
        resp = test_app.get("/api/v1/filters/")
        assert resp.status_code == 200
    resp = test_app.get("/api/v1/filters/")
    assert resp.status_code == 429
    rate_limiter.max_requests = 10000
    rate_limiter.requests.clear()
