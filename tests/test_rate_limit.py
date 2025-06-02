from fastapi.testclient import TestClient


def test_login_rate_limit(test_app: TestClient):
    for _ in range(10):
        test_app.post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
    resp = test_app.post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
    assert resp.status_code == 429
