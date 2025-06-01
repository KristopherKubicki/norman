
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
    initial_admin_username: str = "admin"

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
    sms_account_sid: str
    sms_auth_token: str
    sms_from_number: str
    sms_to_number: str
    signal_service_url: str
    signal_phone_number: str
    matrix_homeserver: str
    matrix_user_id: str
    matrix_access_token: str
    matrix_room_id: str
    twitch_token: str
    twitch_nickname: str
    twitch_channel: str
    twitch_server: str
    twitch_port: int
    rest_callback_url: str
    mcp_api_url: str
    mcp_api_key: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from_address: str
    smtp_to_address: str
    mqtt_host: str
    mqtt_port: int = 1883
    mqtt_topic: str
    mqtt_username: str
    mqtt_password: str
    mastodon_base_url: str
    mastodon_access_token: str
    steam_chat_token: str
    steam_chat_id: str
    xmpp_jid: str
    xmpp_password: str
    xmpp_server: str
    bluesky_handle: str
    bluesky_app_password: str
    facebook_page_token: str
    facebook_verify_token: str
    linkedin_access_token: str
    skype_app_id: str
    skype_app_password: str
    rocketchat_url: str
    rocketchat_token: str
    rocketchat_user_id: str
    mattermost_url: str
    mattermost_token: str
    mattermost_channel_id: str
    wechat_app_id: str
    wechat_app_secret: str
    reddit_client_id: str
    reddit_client_secret: str
    reddit_username: str
    reddit_password: str
    reddit_user_agent: str
    instagram_access_token: str
    instagram_user_id: str
    twitter_api_key: str
    twitter_api_secret: str
    twitter_access_token: str
    twitter_access_token_secret: str
    imessage_service_url: str
    imessage_phone_number: str
    aprs_host: str
    aprs_port: int
    aprs_callsign: str
    aprs_passcode: str
    ax25_port: str
    ax25_callsign: str
    zapier_webhook_url: str
    ifttt_webhook_url: str
    salesforce_instance_url: str
    salesforce_access_token: str
    salesforce_endpoint: str
    github_token: str
    github_repo: str
    gitter_token: str
    gitter_room_id: str
    jira_service_desk_url: str
    jira_service_desk_email: str
    jira_service_desk_api_token: str
    jira_service_desk_project_key: str
    tap_snpp_host: str
    tap_snpp_port: int
    tap_snpp_password: str
    acars_host: str
    acars_port: int
    rfc5425_host: str
    rfc5425_port: int
    aws_eventbridge_region: str
    aws_eventbridge_event_bus_name: str
    aws_iot_core_region: str
    aws_iot_core_topic: str
    aws_iot_core_endpoint: str
    azure_eventgrid_endpoint: str
    azure_eventgrid_key: str
    google_pubsub_project_id: str
    google_pubsub_topic_id: str
    google_pubsub_credentials_path: str
    amqp_url: str
    amqp_queue: str
    redis_host: str
    redis_port: int
    redis_channel: str
    kafka_bootstrap_servers: str
    kafka_topic: str
    nats_servers: str
    nats_subject: str
    pagerduty_routing_key: str
    line_channel_access_token: str
    line_user_id: str
    viber_auth_token: str
    viber_receiver: str
    coap_oscore_host: str
    coap_oscore_port: int
    opcua_pubsub_endpoint: str
    ais_host: str
    ais_port: int
    cap_endpoint: str
    google_business_access_token: str
    google_business_phone_number: str
    apple_business_access_token: str
    apple_business_sender_id: str
    intercom_access_token: str
    intercom_app_id: str
    snmp_host: str
    snmp_port: int
    snmp_community: str
    tox_bootstrap_host: str
    tox_bootstrap_port: int
    tox_friend_id: str
    zulip_email: str
    zulip_api_key: str
    zulip_site_url: str
    zulip_stream: str
    zulip_topic: str
    broadcast_connectors: str = ""
    openai_api_key: Optional[str]
    openai_default_model: str = "gpt-3.5-turbo"
    openai_max_tokens: int = 150
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""

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

    @validator("initial_admin_username", pre=True)
    def validate_admin_username(cls, v):
        """Validate admin username unless running under pytest."""
        import sys
        if "pytest" in sys.modules:
            return v
        assert v != "admin", (
            "You must set an admin username in the config.yaml!"
        )
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

import os
import shutil
import secrets
import yaml


def ensure_user_config():
    """Create config.yaml with random credentials on first run."""
    if not os.path.exists("config.yaml"):
        shutil.copyfile("config.yaml.dist", "config.yaml")
        with open("config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
        cfg["secret_key"] = secrets.token_urlsafe(32)
        cfg["initial_admin_password"] = secrets.token_urlsafe(12)
        cfg["initial_admin_email"] = f"admin+{secrets.token_hex(4)}@example.com"
        cfg["initial_admin_username"] = f"admin_{secrets.token_hex(4)}"
        cfg["encryption_key"] = secrets.token_urlsafe(32)
        cfg["encryption_salt"] = secrets.token_urlsafe(16)
        with open("config.yaml", "w") as f:
            yaml.safe_dump(cfg, f)
        print("Generated config.yaml with admin credentials:")
        print(f"  username: {cfg['initial_admin_username']}")
        print(f"  email: {cfg['initial_admin_email']}")
        print(f"  password: {cfg['initial_admin_password']}")
        print("Edit config.yaml to customize settings, including your OpenAI API key.")

def load_config():
    ensure_user_config()
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
