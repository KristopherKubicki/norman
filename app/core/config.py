
from typing import Any, Dict, Optional
from pydantic import BaseSettings, validator

class Settings(BaseSettings):
    secret_key: str
    app_name: str
    debug: bool
    api_version: str
    api_prefix: str

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

    # Database
    database_url: str

    # Server
    host: str
    port: int

    @validator("secret_key", pre=True)
    def validate_secret_key(cls, v):
        assert v != "super_secret_key_change_me", "You must set a proper secret key"
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
