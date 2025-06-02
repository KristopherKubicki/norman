
from typing import Any, Dict, Optional, List
from pydantic import BaseSettings, validator
import logging

# should this move to schemas?
class Settings(BaseSettings):
    secret_key: Optional[str] = "super_secret_key_change_me"
    app_name: Optional[str] = None
    debug: bool = False
    log_level: str = "INFO"
    api_version: Optional[str] = None
    api_prefix: Optional[str] = None

    # initial admin
    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "password123"
    initial_admin_username: str = "admin"

    # Connectors
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    slack_token: Optional[str] = None
    slack_channel_id: Optional[str] = None
    google_chat_service_account_key_path: Optional[str] = None
    google_chat_space: Optional[str] = None
    discord_token: Optional[str] = None
    discord_channel_id: Optional[str] = None
    teams_app_id: Optional[str] = None
    teams_app_password: Optional[str] = None
    teams_tenant_id: Optional[str] = None
    teams_bot_endpoint: Optional[str] = None
    webhook_secret: Optional[str] = None
    whatsapp_account_sid: Optional[str] = None
    whatsapp_auth_token: Optional[str] = None
    whatsapp_from_number: Optional[str] = None
    whatsapp_to_number: Optional[str] = None
    sms_account_sid: Optional[str] = None
    sms_auth_token: Optional[str] = None
    sms_from_number: Optional[str] = None
    sms_to_number: Optional[str] = None
    signal_service_url: Optional[str] = None
    signal_phone_number: Optional[str] = None
    matrix_homeserver: Optional[str] = None
    matrix_user_id: Optional[str] = None
    matrix_access_token: Optional[str] = None
    matrix_room_id: Optional[str] = None
    twitch_token: Optional[str] = None
    twitch_nickname: Optional[str] = None
    twitch_channel: Optional[str] = None
    twitch_server: Optional[str] = None
    twitch_port: Optional[int] = None
    rest_callback_url: Optional[str] = None
    mcp_api_url: Optional[str] = "your_mcp_api_url"
    mcp_api_key: Optional[str] = "your_mcp_api_key"
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_address: Optional[str] = None
    smtp_to_address: Optional[str] = None
    mqtt_host: Optional[str] = None
    mqtt_port: int = 1883
    mqtt_topic: Optional[str] = None
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mastodon_base_url: Optional[str] = "https://mastodon.example.com"
    mastodon_access_token: Optional[str] = "your_mastodon_token"
    steam_chat_token: Optional[str] = None
    steam_chat_id: Optional[str] = None
    xmpp_jid: Optional[str] = None
    xmpp_password: Optional[str] = None
    xmpp_server: Optional[str] = None
    bluesky_handle: Optional[str] = None
    bluesky_app_password: Optional[str] = None
    facebook_page_token: Optional[str] = None
    facebook_verify_token: Optional[str] = None
    linkedin_access_token: Optional[str] = None
    skype_app_id: Optional[str] = None
    skype_app_password: Optional[str] = None
    rocketchat_url: Optional[str] = "your_rocketchat_url"
    rocketchat_token: Optional[str] = "your_rocketchat_token"
    rocketchat_user_id: Optional[str] = "your_rocketchat_user_id"
    mattermost_url: Optional[str] = "your_mattermost_url"
    mattermost_token: Optional[str] = "your_mattermost_token"
    mattermost_channel_id: Optional[str] = "your_mattermost_channel_id"
    wechat_app_id: Optional[str] = None
    wechat_app_secret: Optional[str] = None
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    reddit_username: Optional[str] = None
    reddit_password: Optional[str] = None
    reddit_user_agent: Optional[str] = None
    instagram_access_token: Optional[str] = None
    instagram_user_id: Optional[str] = None
    twitter_api_key: Optional[str] = None
    twitter_api_secret: Optional[str] = None
    twitter_access_token: Optional[str] = None
    twitter_access_token_secret: Optional[str] = None
    xcom_api_key: Optional[str] = None
    xcom_api_secret: Optional[str] = None
    xcom_access_token: Optional[str] = None
    xcom_access_token_secret: Optional[str] = None
    imessage_service_url: Optional[str] = None
    imessage_phone_number: Optional[str] = None
    aprs_host: Optional[str] = None
    aprs_port: Optional[int] = None
    aprs_callsign: Optional[str] = None
    aprs_passcode: Optional[str] = None
    ax25_port: Optional[str] = None
    ax25_callsign: Optional[str] = None
    zapier_webhook_url: Optional[str] = None
    ifttt_webhook_url: Optional[str] = None
    salesforce_instance_url: Optional[str] = "your_salesforce_instance_url"
    salesforce_access_token: Optional[str] = "your_salesforce_access_token"
    salesforce_endpoint: Optional[str] = "your_salesforce_endpoint"
    github_token: Optional[str] = None
    github_repo: Optional[str] = None
    gitter_token: Optional[str] = None
    gitter_room_id: Optional[str] = None
    jira_service_desk_url: Optional[str] = "https://your-domain.atlassian.net"
    jira_service_desk_email: Optional[str] = "your_email@example.com"
    jira_service_desk_api_token: Optional[str] = "your_jira_api_token"
    jira_service_desk_project_key: Optional[str] = "PROJ"
    tap_snpp_host: Optional[str] = None
    tap_snpp_port: Optional[int] = None
    tap_snpp_password: Optional[str] = None
    acars_host: Optional[str] = None
    acars_port: Optional[int] = None
    rfc5425_host: Optional[str] = None
    rfc5425_port: Optional[int] = None
    aws_eventbridge_region: Optional[str] = None
    aws_eventbridge_event_bus_name: Optional[str] = None
    aws_iot_core_region: Optional[str] = None
    aws_iot_core_topic: Optional[str] = None
    aws_iot_core_endpoint: Optional[str] = None
    aws_iot_core_client_id: Optional[str] = None
    aws_iot_core_cert_path: Optional[str] = None
    aws_iot_core_key_path: Optional[str] = None
    aws_iot_core_ca_path: Optional[str] = None
    azure_eventgrid_endpoint: Optional[str] = None
    azure_eventgrid_key: Optional[str] = None
    google_pubsub_project_id: Optional[str] = None
    google_pubsub_topic_id: Optional[str] = None
    google_pubsub_credentials_path: Optional[str] = None
    amqp_url: Optional[str] = None
    amqp_queue: Optional[str] = None
    redis_host: Optional[str] = None
    redis_port: Optional[int] = None
    redis_channel: Optional[str] = None
    kafka_bootstrap_servers: Optional[str] = None
    kafka_topic: Optional[str] = None
    nats_servers: Optional[str] = None
    nats_subject: Optional[str] = None
    pagerduty_routing_key: Optional[str] = None
    line_channel_access_token: Optional[str] = None
    line_user_id: Optional[str] = None
    viber_auth_token: Optional[str] = None
    viber_receiver: Optional[str] = None
    coap_oscore_host: Optional[str] = None
    coap_oscore_port: Optional[int] = None
    opcua_pubsub_endpoint: Optional[str] = None
    ais_host: Optional[str] = None
    ais_port: Optional[int] = None
    cap_endpoint: Optional[str] = None
    google_business_access_token: Optional[str] = None
    google_business_phone_number: Optional[str] = None
    apple_business_access_token: Optional[str] = None
    apple_business_sender_id: Optional[str] = None
    intercom_access_token: Optional[str] = None
    intercom_app_id: Optional[str] = None
    snmp_host: Optional[str] = None
    snmp_port: Optional[int] = None
    snmp_community: Optional[str] = None
    tox_bootstrap_host: Optional[str] = None
    tox_bootstrap_port: Optional[int] = None
    tox_friend_id: Optional[str] = None
    zulip_email: Optional[str] = "your_zulip_email"
    zulip_api_key: Optional[str] = "your_zulip_api_key"
    zulip_site_url: Optional[str] = "https://zulip.example.com"
    zulip_stream: Optional[str] = "your_zulip_stream"
    zulip_topic: Optional[str] = "your_zulip_topic"
    connectors: List[Dict[str, Any]] = []
    broadcast_connectors: str = ""
    openai_api_key: Optional[str]
    openai_default_model: str = "gpt-4.1-mini"
    openai_max_tokens: int = 150
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""

    access_token_expire_minutes: Optional[int] = 1440
    algorithm: str = "HS256"
    encryption_key: Optional[str] = "your_encryption_key"
    encryption_salt: Optional[str] = "your_encryption_salt"

    # Database
    database_url: Optional[str] = "sqlite:///./db/norman.db"
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # Server
    host: Optional[str] = "0.0.0.0"
    port: Optional[int] = 8000

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
            "You must set an admin password via environment variables!"
        )
        return v

    @validator("initial_admin_email", pre=True)
    def validate_secret_email(cls, v):
        """Validate admin email unless running under pytest."""
        import sys
        if "pytest" in sys.modules:
            return v
        assert v != "admin@example.com", (
            "You must set an admin email via environment variables!"
        )
        return v

    @validator("initial_admin_username", pre=True)
    def validate_admin_username(cls, v):
        """Validate admin username unless running under pytest."""
        import sys
        if "pytest" in sys.modules:
            return v
        assert v != "admin", (
            "You must set an admin username via environment variables!"
        )
        return v

    @validator("log_level", pre=True)
    def validate_log_level(cls, v):
        if isinstance(v, str):
            level = v.upper()
            if level not in logging._nameToLevel:
                raise ValueError(f"Invalid log level: {v}")
            return level
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

def get_settings() -> Settings:
    return settings
