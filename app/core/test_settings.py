# app/core/test_settings.py
from .config import Settings


class TestSettings(Settings):
    DATABASE_URL: str = "sqlite:///./db/test.db"

