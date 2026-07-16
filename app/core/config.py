from pathlib import Path
from typing import Any, Dict, Optional, List
from pydantic import BaseSettings, validator
import logging
import json
import os
import secrets
import shlex
import shutil
import subprocess
from urllib import error as urllib_error
from urllib import request as urllib_request

import yaml


# should this move to schemas?
class Settings(BaseSettings):
    secret_key: str
    app_name: str
    ui_theme: str = "default"
    ui_available_themes: List[str] = [
        "default",
        "fluxbox",
        "classic",
        "graphite",
        "terminal",
        "colorblind",
        "oceanic",
        "sunset",
        "mono",
        "forest",
        "neon",
    ]
    # Optional UI customization. These are stored as web paths under /static/...
    ui_background_image_url: str = ""
    ui_titlebar_image_url: str = ""
    ui_ambient_backgrounds: bool = False
    debug: bool
    log_level: str = "INFO"
    api_version: str
    api_prefix: str

    # initial setup
    admin_setup_key: str = "change_me_setup_key"

    # initial admin
    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "password123"
    initial_admin_username: str = "admin"

    # Connectors
    telegram_token: str
    telegram_chat_id: str
    telegram_webhook_secret: str = ""
    slack_token: str
    slack_channel_id: str
    slack_signing_secret: str = ""
    google_chat_service_account_key_path: str
    google_chat_space: str
    discord_token: str
    discord_channel_id: str
    discord_webhook_url: str = ""
    teams_app_id: str
    teams_app_password: str
    teams_tenant_id: str
    teams_bot_endpoint: str
    teams_webhook_url: str = ""
    teams_scope: str = "https://graph.microsoft.com/.default"
    webhook_secret: str
    webhook_url: str = ""
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
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_use_ssl: bool = True
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
    twitter_recipient_id: str
    xcom_api_key: str
    xcom_api_secret: str
    xcom_access_token: str
    xcom_access_token_secret: str
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
    aws_iot_core_client_id: str
    aws_iot_core_cert_path: str
    aws_iot_core_key_path: str
    aws_iot_core_ca_path: str
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
    connectors: List[Dict[str, Any]] = []
    broadcast_connectors: str = ""
    openai_api_key: Optional[str]
    openai_default_model: str = "gpt-5.5"
    openai_available_models: List[str] = ["gpt-5.5", "gpt-5-mini", "o3"]
    openai_max_tokens: int = 150
    llm_primary_provider: str = "openai"
    llm_primary_api_key: str = ""
    llm_primary_base_url: str = ""
    llm_primary_model: str = ""
    llm_backup_provider: str = "disabled"
    llm_backup_api_key: str = ""
    llm_backup_base_url: str = ""
    llm_backup_model: str = ""
    llm_offline_provider: str = "openai_compatible"
    llm_offline_api_key: str = "ollama"
    llm_offline_base_url: str = "https://llm.home.arpa/v1"
    llm_offline_model: str = "qwen3.6:27b"
    llm_provider_timeout_seconds: int = 45
    console_runtime_norllama_timeout_seconds: int = 180
    console_runtime_bedrock_timeout_seconds: int = 300
    llm_mesh_cache_ttl_seconds: int = 15
    llm_mesh_cache_stale_seconds: int = 300
    llm_mesh_workers: List[Dict[str, Any]] = [
        {
            "id": "mac-mini-133",
            "name": "Mac mini fallback",
            "role": "fallback",
            "base_url": "http://192.168.2.133:18151",
            "memory_gb": 16,
            "priority": 1,
        },
        {
            "id": "spark-150",
            "name": "Production spark 150",
            "role": "production",
            "base_url": "http://192.168.2.150:18151",
            "memory_gb": 128,
            "priority": 2,
        },
        {
            "id": "spark-151",
            "name": "Production spark 151",
            "role": "production",
            "base_url": "http://192.168.2.151:18151",
            "memory_gb": 128,
            "priority": 3,
        },
    ]
    llm_benchmark_packet_path: str = "/var/lib/norman/norllama/benchmark_packet.json"
    llm_benchmark_packet_url: str = ""
    llm_warm_policy_enabled: bool = True
    llm_warm_policy_prefetch_limit: int = 3
    llm_warm_policy_prefetch_timeout_seconds: int = 30
    llm_warm_policy_min_benchmark_score: float = 0.6
    llm_warm_policy_min_coverage_ratio: float = 0.5
    llm_warm_policy_fallback_prefetch: bool = False
    tui_acceptance_report_glob: str = "tmp/tuiacc-*.json"
    tui_acceptance_report_max_age_seconds: int = 86400
    tui_acceptance_required_targets: List[str] = [
        "norman",
        "housebot",
        "uplink",
        "networking",
        "scout",
        "cloudagent",
    ]
    llm_ping_targets: List[Dict[str, Any]] = []
    planner_cloud_gate_mode: str = "enforce"
    mcp_api_url: str = ""
    mcp_api_key: str = ""
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
    database_pool_size: int = 20
    database_max_overflow: int = 40
    database_pool_timeout: int = 30
    database_pool_recycle: int = 3600

    # Server
    host: str
    port: int
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    # Notifications
    notify_email_enabled: bool = False
    notify_email_to: str = ""
    notify_webhook_enabled: bool = False
    notify_webhook_url: str = ""
    notify_digest_frequency: str = "daily"

    # Connector defaults
    connector_default_language: str = "en"
    connector_default_channel: str = ""
    connector_retry_attempts: int = 3
    connector_timeout_seconds: int = 10

    # Safety / execution controls
    safety_execution_enabled: bool = True
    safety_read_only: bool = False
    safety_default_tmux_mode: str = "chat"
    safety_tmux_send_timeout_seconds: int = 8
    safety_kill_switch_level: int = 0
    safety_provenance_enforce: bool = True
    safety_shadow_rules_default: bool = True
    safety_tmux_watchdog_autolock: bool = False
    safety_budget_default_per_minute: int = 0
    safety_budget_default_per_hour: int = 0
    safety_budget_autolock: bool = True

    # Routing controls
    routing_ingest_only: bool = False

    # Console runtime service integration
    console_runtime_service_token: str = ""
    console_runtime_service_user_email: str = ""
    console_runtime_worker_enabled: bool = False
    console_runtime_worker_dry_run: bool = True
    console_runtime_worker_live_execution_enabled: bool = False
    console_runtime_worker_continuous_enabled: bool = False
    console_runtime_worker_max_steps: int = 4
    console_runtime_worker_max_runtime_seconds: int = 1800
    console_runtime_worker_goal_phase_sequence: list[str] = ["plan", "work", "verify"]
    console_runtime_worker_tick_seconds: float = 5.0
    console_runtime_worker_batch_size: int = 1
    console_runtime_worker_id: str = "runtime-background-worker"

    # Norman Keys service integration
    norman_keys_service_token: str = ""
    norman_keys_service_user_email: str = ""

    # Performance
    cache_ttl_seconds: int = 60

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

    @validator("admin_setup_key", pre=True)
    def validate_admin_setup_key(cls, v):
        """Require a real setup key outside of tests."""
        import sys

        if "pytest" in sys.modules:
            return v
        assert (
            v != "change_me_setup_key"
        ), "You must set admin_setup_key in config.yaml for first-time setup."
        return v

    @validator("initial_admin_password", pre=True)
    def validate_secret_admin(cls, v, values):
        """Validate admin password unless running under pytest."""
        import sys

        if "pytest" in sys.modules:
            return v
        setup_key = values.get("admin_setup_key")
        if setup_key and setup_key != "change_me_setup_key":
            return v
        assert (
            v != "change_me_too"
        ), "You must set an admin password in the config.yaml!"
        return v

    @validator("initial_admin_email", pre=True)
    def validate_secret_email(cls, v, values):
        """Validate admin email unless running under pytest."""
        import sys

        if "pytest" in sys.modules:
            return v
        setup_key = values.get("admin_setup_key")
        if setup_key and setup_key != "change_me_setup_key":
            return v
        assert (
            v != "admin@example.com"
        ), "You must set an admin email in the config.yaml!"
        return v

    @validator("initial_admin_username", pre=True)
    def validate_admin_username(cls, v, values):
        """Validate admin username unless running under pytest."""
        import sys

        if "pytest" in sys.modules:
            return v
        setup_key = values.get("admin_setup_key")
        if setup_key and setup_key != "change_me_setup_key":
            return v
        assert v != "admin", "You must set an admin username in the config.yaml!"
        return v

    @validator("log_level", pre=True)
    def validate_log_level(cls, v):
        if isinstance(v, str):
            level = v.upper()
            if level not in logging._nameToLevel:
                raise ValueError(f"Invalid log level: {v}")
            return level
        return v

    @validator("llm_ping_targets", pre=True)
    def validate_llm_ping_targets(cls, v):
        if v is None:
            return []
        return v

    @validator("llm_mesh_workers", pre=True)
    def validate_llm_mesh_workers(cls, v):
        if v is None:
            return []
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path("config.yaml")
_CONFIG_PATH_ENV = "NORMAN_CONFIG_PATH"
_CONFIG_SECRET_ENV = "NORMAN_CONFIG_SECRET"


class ConfigSourceError(RuntimeError):
    """Raised when Norman cannot safely load its configured settings source."""


def _clean_env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _configured_config_path() -> Optional[Path]:
    raw_path = _clean_env(_CONFIG_PATH_ENV)
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ConfigSourceError(f"{_CONFIG_PATH_ENV} must be an absolute path")
    path = path.resolve()
    try:
        path.relative_to(Path.cwd().resolve())
    except ValueError:
        pass
    else:
        raise ConfigSourceError(
            f"{_CONFIG_PATH_ENV} must point outside the application working tree"
        )
    return path


def _configured_config_secret() -> str:
    return _clean_env(_CONFIG_SECRET_ENV)


def active_config_file_path() -> Optional[Path]:
    """Return a writable file-backed config path, if this source has one."""

    if _configured_config_secret():
        return None
    return _configured_config_path() or _DEFAULT_CONFIG_PATH


def _read_yaml_mapping(source: str, *, label: str) -> Dict[str, Any]:
    try:
        config = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise ConfigSourceError(f"{label} does not contain valid YAML") from exc
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ConfigSourceError(f"{label} must contain a YAML mapping")
    return config


def _read_yaml_file(path: Path, *, label: str) -> Dict[str, Any]:
    try:
        return _read_yaml_mapping(path.read_text(encoding="utf-8"), label=label)
    except FileNotFoundError:
        raise ConfigSourceError(f"{label} was not found") from None


def _config_secret_timeout_seconds() -> float:
    try:
        timeout = float(_clean_env("NORMAN_CONFIG_SECRET_TIMEOUT_SECONDS") or "5")
    except ValueError:
        return 5.0
    return min(max(timeout, 0.1), 30.0)


def _secret_command(secret_name: str) -> list[str]:
    command_text = _clean_env("NORMAN_CONFIG_SECRET_CMD") or _clean_env(
        "NORMAN_SECRET_CMD"
    )
    if not command_text:
        return []
    command = shlex.split(command_text)
    if not command:
        return []
    if "{name}" in command_text:
        return [part.replace("{name}", secret_name) for part in command]
    return [*command, "get", secret_name]


def _keys_secret_get_url() -> str:
    base = (_clean_env("NORMAN_KEYS_URL") or _clean_env("NORMAN_KEYS_API_BASE")).rstrip(
        "/"
    )
    if not base:
        return ""
    if base.endswith("/v1/secrets/get"):
        return base
    if base.endswith("/v1"):
        return f"{base}/secrets/get"
    return f"{base}/v1/secrets/get"


def _brokered_config_secret(secret_name: str) -> str:
    timeout = _config_secret_timeout_seconds()
    command = _secret_command(secret_name)
    if command:
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConfigSourceError(
                "Configured configuration-secret command did not complete"
            ) from exc
        value = str(result.stdout or "").strip()
        if value:
            return value
        raise ConfigSourceError("Configured configuration-secret command was empty")

    url = _keys_secret_get_url()
    if not url:
        raise ConfigSourceError(
            "NORMAN_CONFIG_SECRET requires NORMAN_CONFIG_SECRET_CMD, "
            "NORMAN_SECRET_CMD, or NORMAN_KEYS_URL"
        )

    payload = {
        "name": secret_name,
        "reason": "Norman service configuration",
        "requester_id": _clean_env("NORMAN_CONFIG_REQUESTER_ID") or "norman-service",
        "session_id": "startup",
        "lane": "backend",
        "target_host": _clean_env("NORMAN_CONFIG_TARGET_HOST")
        or _clean_env("HOSTNAME"),
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = _clean_env("NORMAN_KEYS_TOKEN") or _clean_env("NORMAN_KEYS_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib_request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
        response_payload = json.loads(raw_response) if raw_response else {}
    except (OSError, urllib_error.URLError, json.JSONDecodeError) as exc:
        raise ConfigSourceError(
            "Norman Keys did not return a usable configuration secret"
        ) from exc
    if not isinstance(response_payload, dict):
        raise ConfigSourceError("Norman Keys returned an invalid configuration secret")
    value = str(
        response_payload.get("value") or response_payload.get("secret") or ""
    ).strip()
    if not value:
        raise ConfigSourceError("Norman Keys returned an empty configuration secret")
    return value


def _custom_config() -> Dict[str, Any]:
    config_path = _configured_config_path()
    secret_name = _configured_config_secret()
    if config_path and secret_name:
        raise ConfigSourceError(
            f"Set only one of {_CONFIG_PATH_ENV} or {_CONFIG_SECRET_ENV}"
        )
    if secret_name:
        return _read_yaml_mapping(
            _brokered_config_secret(secret_name),
            label="brokered Norman configuration",
        )
    if config_path:
        return _read_yaml_file(config_path, label=_CONFIG_PATH_ENV)

    ensure_user_config()
    return _read_yaml_file(_DEFAULT_CONFIG_PATH, label="config.yaml")


def ensure_user_config():
    """Create config.yaml with random credentials on first run."""
    if _configured_config_path() or _configured_config_secret():
        return
    if not _DEFAULT_CONFIG_PATH.exists():
        shutil.copyfile("config.yaml.dist", _DEFAULT_CONFIG_PATH)
        with _DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            cfg = yaml.safe_load(config_file)
        cfg["secret_key"] = secrets.token_urlsafe(32)
        cfg["admin_setup_key"] = secrets.token_urlsafe(16)
        cfg["initial_admin_password"] = secrets.token_urlsafe(12)
        cfg["initial_admin_email"] = f"admin+{secrets.token_hex(4)}@example.com"
        cfg["initial_admin_username"] = f"admin_{secrets.token_hex(4)}"
        cfg["encryption_key"] = secrets.token_urlsafe(32)
        cfg["encryption_salt"] = secrets.token_urlsafe(16)
        with _DEFAULT_CONFIG_PATH.open("w", encoding="utf-8") as config_file:
            yaml.safe_dump(cfg, config_file)
        logger.warning(
            "Generated config.yaml with bootstrap credentials. "
            "Read them from the protected config file; they are not logged."
        )


def load_config():
    config = _read_yaml_file(Path("config.yaml.dist"), label="config.yaml.dist")
    if "connectors" not in config:
        config["connectors"] = []

    config.update(_custom_config())
    if "connectors" not in config:
        config["connectors"] = []

    if (
        not config.get("admin_setup_key")
        or config.get("admin_setup_key") == "change_me_setup_key"
    ):
        if _configured_config_path() or _configured_config_secret():
            raise ConfigSourceError(
                "Managed Norman configuration must provide admin_setup_key"
            )
        config_path = active_config_file_path()
        if config_path is None:
            raise ConfigSourceError("No writable configuration file is configured")
        config["admin_setup_key"] = secrets.token_urlsafe(16)
        custom_config = _read_yaml_file(config_path, label=str(config_path))
        custom_config["admin_setup_key"] = config["admin_setup_key"]
        with config_path.open("w", encoding="utf-8") as config_file:
            yaml.safe_dump(custom_config, config_file)
        logger.warning(
            "Generated an admin setup key in the protected configuration file; "
            "the value is not logged."
        )

    return config


config_data = load_config()
settings = Settings(**config_data)


def get_settings() -> Settings:
    return settings
