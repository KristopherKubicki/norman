# test/test_settings.py
from app.core.config import Settings

__test__ = False


class TestSettings(Settings):
    database_url: str = "sqlite:///./db/test.db"
