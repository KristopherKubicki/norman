from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exception_handlers import add_exception_handlers
from app.core.exceptions import APIError, DatabaseError, AuthenticationError


def _create_app():
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/api")
    async def _api():
        raise APIError("boom")

    @app.get("/db")
    async def _db():
        raise DatabaseError("broken")

    @app.get("/auth")
    async def _auth():
        raise AuthenticationError("bad token")

    return app


def test_api_error_handler():
    client = TestClient(_create_app())
    resp = client.get("/api")
    assert resp.status_code == 502
    assert resp.json() == {"detail": "boom"}


def test_database_error_handler():
    client = TestClient(_create_app())
    resp = client.get("/db")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Database error"}


def test_authentication_error_handler():
    client = TestClient(_create_app())
    resp = client.get("/auth")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "bad token"}
