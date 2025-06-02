# app/core/test_settings.py
from app.core.config import Settings

__all__ = ["TestSettings", "test_settings"]
__test__ = False


class TestSettings(Settings):
    class Config(Settings.Config):
        env_prefix = ""

test_settings = TestSettings(database_url="sqlite:///./db/test.db")

