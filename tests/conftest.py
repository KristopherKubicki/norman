# tests/conftest.py
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["SKIP_MIGRATIONS"] = "1"
from app.main import app
from app.connectors import init_connectors
from app.core.test_settings import TestSettings
from app.core.config import settings
from app.api.deps import get_db
from app.models.base import Base

test_settings = TestSettings

# Configure in-memory SQLite for tests
settings.database_url = "sqlite:///./db/test.db"
engine = create_engine(settings.database_url)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


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

