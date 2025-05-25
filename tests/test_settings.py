# test/test_settings.py
from app.core.config import Settings


class TestSettings(Settings):
    DATABASE_URL: str = "sqlite:///./db/test.db"

