import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.schemas.user import UserCreate
from app.core.security import decode_access_token
from app.tests.utils.utils import random_email, random_lower_string


def _create_user(db: Session):
    email = random_email()
    password = "pass123"
    user_in = UserCreate(email=email, username=random_lower_string(), password=password)
    user = crud.user.create_user(db, user=user_in)
    return user, password


def test_login_sets_cookie(test_app: TestClient, db: Session) -> None:
    user, password = _create_user(db)
    resp = test_app.post(
        "/login",
        data={"username": user.email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    token = resp.cookies.get("access_token")
    assert token
    token = token.strip('"')
    assert decode_access_token(token) == user.email


def test_login_allows_access_to_home(test_app: TestClient, db: Session) -> None:
    user, password = _create_user(db)
    resp = test_app.post(
        "/login",
        data={"username": user.email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    token = resp.cookies.get("access_token").strip('"')
    resp2 = test_app.get(
        "/", headers={"Authorization": f"Bearer {token}"}, follow_redirects=False
    )
    assert resp2.status_code == 200
    assert 'id="norman-bridge"' in resp2.text


def test_login_rejects_malformed_email(test_app: TestClient) -> None:
    response = test_app.post(
        "/login",
        data={"username": "not-an-email", "password": "pass123"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Incorrect email or password"}


def test_login_uses_bridge_language(test_app: TestClient) -> None:
    response = test_app.get("/login.html")
    assert response.status_code == 200
    assert "Log in to Norman" in response.text
    assert "Enter Norman" not in response.text


def test_login_returns_to_requested_bridge_path(
    test_app: TestClient, db: Session
) -> None:
    user, password = _create_user(db)
    resp = test_app.post(
        "/login",
        data={
            "username": user.email,
            "password": password,
            "next": "/bridge?agent=housebot",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/bridge?agent=housebot"


@pytest.mark.parametrize("remember", [False, True])
def test_login_persistence_is_opt_in(
    test_app: TestClient, db: Session, remember: bool
) -> None:
    import jwt
    import time
    from app.core.config import settings

    user, password = _create_user(db)
    response = test_app.post(
        "https://testserver/login",
        data={
            "username": user.email,
            "password": password,
            "remember_me": str(remember).lower(),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert ("Max-Age=2592000" in cookie) == remember
    if not remember:
        assert "Max-Age" not in cookie
    payload = jwt.decode(
        response.cookies["access_token"],
        settings.secret_key,
        algorithms=[settings.algorithm],
    )
    expected = 30 * 86400 if remember else settings.access_token_expire_minutes * 60
    assert abs(payload["exp"] - time.time() - expected) < 5
    assert response.headers["cache-control"] == "no-store"


def test_logout_clears_cookie_on_returned_response(
    test_app: TestClient, db: Session
) -> None:
    import httpx

    user, password = _create_user(db)
    login_response = test_app.post(
        "/login",
        data={"username": user.email, "password": password, "remember_me": "true"},
        follow_redirects=False,
    )
    browser_cookies = httpx.Cookies()
    browser_cookies.extract_cookies(login_response)
    assert browser_cookies.get("access_token")
    response = test_app.get("/logout")
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    browser_cookies.extract_cookies(response)
    assert not browser_cookies.get("access_token")
    assert response.headers["cache-control"] == "no-store"


def test_login_rejects_cross_origin_submission(test_app: TestClient) -> None:
    response = test_app.post(
        "/login",
        data={"username": "a@example.com", "password": "invalid"},
        headers={"Origin": "https://untrusted.example"},
    )
    assert response.status_code == 403


def test_login_remember_option_is_unchecked(test_app: TestClient) -> None:
    response = test_app.get("/login.html")
    assert 'name="remember_me"' in response.text
    assert "Keep me signed in for 30 days" in response.text
    assert 'id="remember-me" checked' not in response.text


def test_login_has_stable_password_manager_fields(test_app: TestClient) -> None:
    """The native form exposes labeled, stable autofill targets on both URLs."""
    for url in ("/login", "/login.html"):
        response = test_app.get(url)
        assert response.status_code == 200
        assert (
            'id="login-form" name="login" action="/login" method="post" autocomplete="on"'
            in response.text
        )
        assert 'id="username" type="email"' in response.text
        assert 'for="username"' in response.text
        assert 'autocomplete="username"' in response.text
        assert 'id="current-password" type="password"' in response.text
        assert 'for="current-password"' in response.text
        assert 'autocomplete="current-password"' in response.text


def test_browser_login_failure_keeps_usable_form(test_app: TestClient) -> None:
    """A rejected native form preserves context without reflecting the password."""
    response = test_app.post(
        "/login",
        headers={"Accept": "text/html"},
        data={
            "username": "invalid@example.com",
            "password": "never-reflect-this-secret",
            "next": "/bridge?agent=networking",
            "remember_me": "true",
        },
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Email or password was not recognized" in response.text
    assert 'value="invalid@example.com"' in response.text
    assert 'value="/bridge?agent=networking"' in response.text
    assert 'aria-describedby="remember-help" checked' in response.text
    assert "never-reflect-this-secret" not in response.text


def test_signed_out_bridge_opens_real_login_form(
    test_app: TestClient, monkeypatch
) -> None:
    """Landing on the site must expose password fields without a second login click."""
    import app.auth_middleware as middleware

    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    monkeypatch.setattr(middleware, "get_cached_admin_exists", lambda: True)
    test_app.cookies.clear()
    response = test_app.get("/bridge?agent=networking", follow_redirects=False)
    assert response.status_code == 303
    assert (
        response.headers["location"]
        == "/login.html?next=%2Fbridge%3Fagent%3Dnetworking"
    )


def test_expired_api_session_is_json_not_login_html(
    test_app: TestClient, monkeypatch
) -> None:
    """Fetch callers can reliably detect expiry and preserve their drafts."""
    import app.auth_middleware as middleware

    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    monkeypatch.setattr(middleware, "get_cached_admin_exists", lambda: True)
    response = test_app.get(
        "/api/v1/bridge/conversations", headers={"Cookie": "access_token=expired"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Sign in required"}
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    "destination",
    [
        "https://untrusted.example/",
        "//untrusted.example/",
        "/\\untrusted.example/",
        "https://[invalid",
        "/\nuntrusted.example",
    ],
)
def test_login_return_path_rejects_unsafe_destinations(destination):
    from app.core.navigation import safe_local_return_to

    assert safe_local_return_to(destination) == "/"
