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
from app.core.test_settings import test_settings
from app.core.config import settings
from app.api.deps import get_db
from app.db.base import Base


# Ensure the test database directory exists
db_dir = Path("./db")
db_dir.mkdir(parents=True, exist_ok=True)

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

