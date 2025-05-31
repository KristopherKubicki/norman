# app/core/test_settings.py
from app.core.config import Settings, load_config

__all__ = ["TestSettings", "test_settings"]
__test__ = False


class TestSettings(Settings):
    class Config(Settings.Config):
        env_prefix = ""

test_defaults = load_config()
test_settings = Settings(
    **{**test_defaults, "database_url": "sqlite:///./db/test.db"}
)

