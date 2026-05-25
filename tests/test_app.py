from fastapi.testclient import TestClient
import pytest


def test_home_page_requires_login(
    test_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root endpoint should redirect unauthenticated users to login."""
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    response = test_app.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in {"/login.html", "/setup.html"}


def test_root_redirects_to_main_norman_chat_when_auth_disabled(
    test_app: TestClient,
) -> None:
    response = test_app.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert (
        response.headers["location"]
        == "/editor.html?pane=conversation&thread=console+-+Norman&shell=prime"
    )


def test_dashboard_embed_hides_global_chrome(test_app: TestClient) -> None:
    response = test_app.get("/dashboard.html?embed=1", follow_redirects=False)
    assert response.status_code == 200
    assert "Norman Prime" in response.text
    assert "site-banner" not in response.text
    assert 'id="global-status-bar"' not in response.text


def test_switchboard_host_redirects_to_bbs_surface(test_app: TestClient) -> None:
    response = test_app.get(
        "/",
        headers={"host": "switchboard.home.arpa"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/messages_log.html?view=switchboard"


def test_switchboard_endpoint_redirects_to_bbs_surface(test_app: TestClient) -> None:
    response = test_app.get("/switchboard", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/messages_log.html?view=switchboard"


def test_bots_page_requires_login(
    test_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    response = test_app.get("/bots.html", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in {"/login.html", "/setup.html"}


def test_consoles_page_requires_login(
    test_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    response = test_app.get("/consoles.html", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in {"/login.html", "/setup.html"}


def test_systems_page_requires_login(
    test_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    response = test_app.get("/systems.html", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in {"/login.html", "/setup.html"}
