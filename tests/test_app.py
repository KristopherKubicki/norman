from fastapi.testclient import TestClient


def test_home_page_requires_login(test_app: TestClient) -> None:
    """The root endpoint should redirect unauthenticated users to login."""
    response = test_app.get("/", allow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login.html"


def test_bots_page_requires_login(test_app: TestClient) -> None:
    response = test_app.get("/bots.html", allow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login.html"
