import os
import yaml
from pydantic import BaseSettings

class Settings(BaseSettings):
    app_name: str = "Norman"
    secret_key: str
    database_url: str

    class Config:
        env_file = ".env"

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
