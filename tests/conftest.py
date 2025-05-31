# tests/conftest.py
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pathlib import Path

os.environ["SKIP_MIGRATIONS"] = "1"
from app.main import app
from app.connectors import init_connectors
from app.core.test_settings import TestSettings
from app.core.config import settings
from app.api.deps import get_db
from app.models.base import Base
import importlib
importlib.import_module("app.models")  # ensure models are registered

test_settings = TestSettings

# Ensure the test database directory exists
db_dir = Path("./db")
db_dir.mkdir(parents=True, exist_ok=True)
db_file = db_dir / "test.db"
if db_file.exists():
    db_file.unlink()

settings.database_url = f"sqlite:///{db_dir}/test.db"
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

