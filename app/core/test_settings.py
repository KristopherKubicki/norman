# app/core/test_settings.py
from .config import Settings


class TestSettings(Settings):
    database_url: str = "sqlite:///./db/test.db"

