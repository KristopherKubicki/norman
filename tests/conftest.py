# tests/conftest.py
import os
import sys
from pydantic import typing as _pydantic_typing

if sys.version_info >= (3, 12):

    def _evaluate_forwardref(type_, globalns, localns):
        return type_._evaluate(globalns, localns, None, recursive_guard=set())

    _pydantic_typing.evaluate_forwardref = _evaluate_forwardref

import asyncio
import threading
from typing import Optional

import anyio
import starlette.concurrency as starlette_concurrency
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

os.environ["SKIP_MIGRATIONS"] = "1"
os.environ["SKIP_ROUTING_WORKER"] = "1"
from app.main import app
from app.connectors import init_connectors
from app.core.test_settings import test_settings
from app.core.config import settings
from app.api.deps import get_db
from app.api.deps import get_current_user
from app.db.base import Base
from app.crud.user import get_user_by_email, create_user
from app.schemas.user import UserCreate


# anyio.to_thread.run_sync hangs in this environment; run sync work in a
# dedicated thread per call to keep tests moving.
async def _run_sync(func, *args, **kwargs):
    kwargs.pop("limiter", None)
    kwargs.pop("cancellable", None)
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def worker():
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - surfaced via future
            loop.call_soon_threadsafe(future.set_exception, exc)
        else:
            loop.call_soon_threadsafe(future.set_result, result)

    threading.Thread(target=worker, daemon=True).start()
    return await future


anyio.to_thread.run_sync = _run_sync
starlette_concurrency.run_in_threadpool = _run_sync


@pytest.fixture(scope="function", autouse=True)
def _ensure_event_loop():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        yield loop
    finally:
        loop.close()
        asyncio.set_event_loop(None)


# Use a temporary SQLite file to avoid in-memory + multi-thread contention that can
# deadlock in this environment.
settings.database_url = f"sqlite:////tmp/norman_test_{os.getpid()}.db"
if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        poolclass=QueuePool,
        connect_args={"check_same_thread": False, "timeout": 1},
    )
else:
    engine = create_engine(
        settings.database_url,
        poolclass=QueuePool,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# Override the application's SessionLocal to ensure the API uses the test database
from app.db import session as db_session

db_session.SessionLocal = TestingSessionLocal
db_session.engine = engine
import app.api.deps as api_deps

api_deps.SessionLocal = TestingSessionLocal
import app.auth_middleware as auth_middleware

auth_middleware.SessionLocal = TestingSessionLocal


class SyncASGIClient:
    """Sync wrapper around AsyncClient using asyncio.run per request.

    Starlette's TestClient hangs in this environment, so we issue requests
    via AsyncClient + ASGITransport and keep a simple cookie jar.
    """

    def __init__(self, asgi_app):
        self.app = asgi_app
        self._cookies = httpx.Cookies()

    async def _request_async(self, method: str, url: str, **kwargs):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", cookies=self._cookies
        ) as client:
            resp = await client.request(method, url, **kwargs)
            self._cookies.update(resp.cookies)
            return resp

    @property
    def cookies(self) -> httpx.Cookies:
        return self._cookies

    def request(self, method: str, url: str, **kwargs):
        return asyncio.run(self._request_async(method, url, **kwargs))

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        return None


@pytest.fixture(scope="module")
def test_app():
    print("test_app fixture: init_connectors", flush=True)
    init_connectors(app, test_settings)
    print("test_app fixture: creating SyncASGIClient", flush=True)

    async def _override_get_current_user():
        db = TestingSessionLocal()
        try:
            user = get_user_by_email(db, email="test@example.com")
            if not user:
                user = create_user(
                    db,
                    UserCreate(
                        email="test@example.com",
                        username="test_user",
                        password="pass123",
                    ),
                )
            return user
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = _override_get_current_user
    client = SyncASGIClient(app)
    print("test_app fixture: SyncASGIClient ready", flush=True)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        client.close()


@pytest.fixture(scope="function")
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
