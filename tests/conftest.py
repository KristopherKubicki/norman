# tests/conftest.py
import os
import sys
from pydantic import typing as _pydantic_typing

if sys.version_info >= (3, 12):
    def _evaluate_forwardref(type_, globalns, localns):
        return type_._evaluate(globalns, localns, None, recursive_guard=set())

    _pydantic_typing.evaluate_forwardref = _evaluate_forwardref

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from pathlib import Path

os.environ["SKIP_MIGRATIONS"] = "1"
from app.main import app
from app.connectors import init_connectors
from app.core.test_settings import test_settings
from app.core.config import settings
from app.api.deps import get_db
from app.db.base import Base


# Ensure the test database directory exists
db_dir = Path("./db")
db_dir.mkdir(parents=True, exist_ok=True)

settings.database_url = f"sqlite:///{db_dir}/test.db"
engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# Override the application's SessionLocal to ensure the API uses the test database
from app.db import session as db_session
db_session.SessionLocal = TestingSessionLocal
db_session.engine = engine
import app.api.deps as api_deps
api_deps.SessionLocal = TestingSessionLocal


@pytest.fixture(scope="module")
def test_app():
    init_connectors(app, test_settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

