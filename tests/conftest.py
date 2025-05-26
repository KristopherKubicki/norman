# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.connectors import init_connectors
from app.core.test_settings import TestSettings
from app.api.deps import get_db

test_settings = TestSettings()

@pytest.fixture(scope="module")
def test_app():
    init_connectors(app, test_settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
def db():
    with get_db() as session:
        yield session

