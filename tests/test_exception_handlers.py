import asyncio
import httpx
from fastapi import FastAPI

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


def _get(app: FastAPI, path: str) -> httpx.Response:
    async def _call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.get(path)

    return asyncio.run(_call())


def test_api_error_handler():
    resp = _get(_create_app(), "/api")
    assert resp.status_code == 502
    assert resp.json() == {"detail": "boom"}


def test_database_error_handler():
    resp = _get(_create_app(), "/db")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Database error"}


def test_authentication_error_handler():
    resp = _get(_create_app(), "/auth")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "bad token"}
