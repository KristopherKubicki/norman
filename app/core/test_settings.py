# app/core/test_settings.py
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings, load_config

__all__ = ["TestSettings", "test_settings"]
__test__ = False


class TestSettings(Settings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
    )


test_defaults = load_config()
test_defaults["connectors"] = []
test_settings = Settings(**{**test_defaults, "database_url": "sqlite:///./db/test.db"})
