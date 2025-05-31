from fastapi.testclient import TestClient


def test_home_page(test_app: TestClient) -> None:
    """The root endpoint should return a HTML page."""
    response = test_app.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
