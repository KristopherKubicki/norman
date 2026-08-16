from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app import crud
from app.core.auth_cache import clear_auth_caches
from app.views import templates
from main import static_directory


def _create_admin_user(db) -> None:
    crud.user.create_admin_user(
        db,
        email="admin@example.com",
        password="pass123",
        username="admin",
    )
    clear_auth_caches()


def test_web_assets_resolve_from_the_installed_package() -> None:
    static_path = Path(static_directory)
    template_path = Path(templates.env.loader.searchpath[0])

    assert (static_path / "css" / "styles.css").is_file()
    assert (template_path / "index.html").is_file()


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
    assert response.headers["location"] == "/bot/norman/"


def test_root_redirects_switchboard_host_to_switchboard_dashboard(
    test_app: TestClient,
) -> None:
    response = test_app.get(
        "/",
        follow_redirects=False,
        headers={"Host": "switchboard.home.arpa"},
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard.html?view=switchboard"


def test_dashboard_embed_hides_global_chrome(test_app: TestClient) -> None:
    response = test_app.get("/dashboard.html?embed=1", follow_redirects=False)
    assert response.status_code == 200
    assert "Norman Prime" in response.text
    assert "site-banner" not in response.text
    assert 'id="global-status-bar"' not in response.text


def test_switchboard_route_redirects_to_switchboard_dashboard(
    test_app: TestClient,
) -> None:
    response = test_app.get("/switchboard.html", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard.html?view=switchboard"


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


def test_invalid_auth_cookie_redirects_to_login_and_clears_cookie(
    test_app: TestClient, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    _create_admin_user(db)

    test_app.cookies.set("access_token", "definitely-invalid")
    response = test_app.get("/dashboard.html", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login.html"
    assert 'access_token=""' in response.headers.get("set-cookie", "")
