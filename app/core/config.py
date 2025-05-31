
from typing import Any, Dict, Optional
from pydantic import BaseSettings, validator

# should this move to schemas?
class Settings(BaseSettings):
    secret_key: str
    app_name: str
    debug: bool
    api_version: str
    api_prefix: str

    # initial admin
    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "password123"

    # Connectors
    telegram_token: str
    telegram_chat_id: str
    slack_token: str
    slack_channel_id: str
    google_chat_service_account_key_path: str
    google_chat_space: str
    discord_token: str
    discord_channel_id: str
    teams_app_id: str
    teams_app_password: str
    teams_tenant_id: str
    teams_bot_endpoint: str
    webhook_secret: str
    whatsapp_account_sid: str
    whatsapp_auth_token: str
    whatsapp_from_number: str
    whatsapp_to_number: str
    matrix_homeserver: str
    matrix_user_id: str
    matrix_access_token: str
    matrix_room_id: str
    twitch_token: str
    twitch_nickname: str
    twitch_channel: str
    openai_api_key: Optional[str]

    access_token_expire_minutes: int
    algorithm: str = "HS256"
    encryption_key: str
    encryption_salt: str

    # Database
    database_url: str

    # Server
    host: str
    port: int

    @validator("secret_key", pre=True)
    def validate_secret_key(cls, v):
        """Ensure a real secret key is provided outside of tests."""
        import sys
        if "pytest" in sys.modules:
            return v
        assert v != "super_secret_key_change_me", (
            "You must set a proper secret key. Please refer to the "
            "#installation section in the README.md for instructions."
        )
        return v

    @validator("initial_admin_password", pre=True)
    def validate_secret_admin(cls, v):
        """Validate admin password unless running under pytest."""
        import sys
        if "pytest" in sys.modules:
            return v
        assert v != "change_me_too", (
            "You must set an admin password in the config.yaml!"
        )
        return v

    @validator("initial_admin_email", pre=True)
    def validate_secret_email(cls, v):
        """Validate admin email unless running under pytest."""
        import sys
        if "pytest" in sys.modules:
            return v
        assert v != "admin@example.com", (
            "You must set an admin email in the config.yaml!"
        )
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

import os
import yaml

def load_config():
    # Read the config from the dist file
    with open("config.yaml.dist", "r") as dist_file:
        config = yaml.safe_load(dist_file)

    # If the config.yaml file exists, merge its contents with the dist config
    if os.path.exists("config.yaml"):
        with open("config.yaml", "r") as custom_file:
            custom_config = yaml.safe_load(custom_file)
            config.update(custom_config)

    return config

config_data = load_config()
settings = Settings(**config_data)

def get_settings() -> Settings:
    return settings
