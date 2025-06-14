import sys
import types

# Provide a minimal slack_sdk stub if the real package isn't installed
if "slack_sdk" not in sys.modules:
    slack_sdk = types.ModuleType("slack_sdk")

    class DummyClient:
        def __init__(self, token=None):
            self.token = token

        def auth_test(self):
            return {"ok": True}

    slack_sdk.WebClient = DummyClient
    errors_mod = types.ModuleType("slack_sdk.errors")
    slack_sdk.errors = errors_mod
    sys.modules["slack_sdk"] = slack_sdk
    sys.modules["slack_sdk.errors"] = errors_mod

from app.connectors.connector_utils import get_connector, get_connectors_data
from app.connectors.slack_connector import SlackConnector
from app.connectors.signal_connector import SignalConnector
from app.connectors.rest_callback_connector import RESTCallbackConnector
from app.connectors.mcp_connector import MCPConnector
from app.connectors.smtp_connector import SMTPConnector
from app.connectors.mqtt_connector import MQTTConnector
from app.connectors.mastodon_connector import MastodonConnector
from app.connectors.sms_connector import SMSConnector
from app.connectors.steam_chat_connector import SteamChatConnector
from app.connectors.xmpp_connector import XMPPConnector
from app.connectors.bluesky_connector import BlueskyConnector
from app.connectors.facebook_messenger_connector import FacebookMessengerConnector
from app.connectors.linkedin_connector import LinkedInConnector
from app.connectors.skype_connector import SkypeConnector
from app.connectors.rocketchat_connector import RocketChatConnector
from app.connectors.mattermost_connector import MattermostConnector
from app.connectors.wechat_connector import WeChatConnector
from app.connectors.reddit_chat_connector import RedditChatConnector
from app.connectors.instagram_dm_connector import InstagramDMConnector
from app.connectors.twitter_connector import TwitterConnector
from app.connectors.aws_iot_core_connector import AWSIoTCoreConnector
from app.connectors.aws_eventbridge_connector import AWSEventBridgeConnector
from app.connectors.google_pubsub_connector import GooglePubSubConnector
from app.connectors.azure_eventgrid_connector import AzureEventGridConnector
from app.connectors.imessage_connector import IMessageConnector
from app.connectors.rfc5425_connector import RFC5425Connector
from app.connectors.kafka_connector import KafkaConnector
from app.connectors.nats_connector import NATSConnector
from app.connectors.pagerduty_connector import PagerDutyConnector
from app.connectors.line_connector import LineConnector
from app.connectors.viber_connector import ViberConnector
from app.connectors.coap_oscore_connector import CoAPOSCOREConnector
from app.connectors.opcua_pubsub_connector import OPCUAPubSubConnector
from app.connectors.ais_safety_text_connector import AISSafetyTextConnector
from app.connectors.cap_connector import CAPConnector
from app.core.test_settings import test_settings


def test_get_connector_returns_slack(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("slack")
    assert isinstance(connector, SlackConnector)


def test_get_connector_returns_signal(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("signal")
    assert isinstance(connector, SignalConnector)


def test_get_connector_returns_rest_callback(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("rest_callback")
    assert isinstance(connector, RESTCallbackConnector)


def test_get_connector_returns_mcp(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("mcp")
    assert isinstance(connector, MCPConnector)


def test_get_connector_returns_smtp(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("smtp")
    assert isinstance(connector, SMTPConnector)


def test_get_connector_returns_mqtt(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("mqtt")
    assert isinstance(connector, MQTTConnector)


def test_get_connector_returns_mastodon(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("mastodon")
    assert isinstance(connector, MastodonConnector)


def test_get_connector_returns_sms(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("sms")
    assert isinstance(connector, SMSConnector)


def test_get_connector_returns_steam_chat(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("steam_chat")
    assert isinstance(connector, SteamChatConnector)


def test_get_connector_returns_xmpp(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("xmpp")
    assert isinstance(connector, XMPPConnector)


def test_get_connector_returns_bluesky(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("bluesky")
    assert isinstance(connector, BlueskyConnector)


def test_get_connector_returns_facebook_messenger(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("facebook_messenger")
    assert isinstance(connector, FacebookMessengerConnector)


def test_get_connector_returns_linkedin(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("linkedin")
    assert isinstance(connector, LinkedInConnector)


def test_get_connector_returns_skype(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("skype")
    assert isinstance(connector, SkypeConnector)


def test_get_connector_returns_rocketchat(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("rocketchat")
    assert isinstance(connector, RocketChatConnector)


def test_get_connector_returns_mattermost(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("mattermost")
    assert isinstance(connector, MattermostConnector)


def test_get_connector_returns_wechat(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("wechat")
    assert isinstance(connector, WeChatConnector)


def test_get_connector_returns_reddit_chat(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("reddit_chat")
    assert isinstance(connector, RedditChatConnector)


def test_get_connector_returns_instagram_dm(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("instagram_dm")
    assert isinstance(connector, InstagramDMConnector)


def test_get_connector_returns_twitter(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("twitter")
    assert isinstance(connector, TwitterConnector)


def test_get_connector_returns_xcom(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("xcom")
    from app.connectors.xcom_connector import XComConnector

    assert isinstance(connector, XComConnector)


def test_get_connector_returns_imessage(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("imessage")
    assert isinstance(connector, IMessageConnector)


def test_get_connector_returns_aprs(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("aprs")
    from app.connectors.aprs_connector import APRSConnector

    assert isinstance(connector, APRSConnector)


def test_get_connector_returns_ax25(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("ax25")
    from app.connectors.ax25_connector import AX25Connector

    assert isinstance(connector, AX25Connector)


def test_get_connector_returns_zapier(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("zapier")
    from app.connectors.zapier_connector import ZapierConnector

    assert isinstance(connector, ZapierConnector)


def test_get_connector_returns_ifttt(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("ifttt")
    from app.connectors.ifttt_connector import IFTTTConnector

    assert isinstance(connector, IFTTTConnector)


def test_get_connector_returns_salesforce(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("salesforce")
    from app.connectors.salesforce_connector import SalesforceConnector

    assert isinstance(connector, SalesforceConnector)


def test_get_connector_returns_github(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("github")
    from app.connectors.github_connector import GitHubConnector

    assert isinstance(connector, GitHubConnector)


def test_get_connector_returns_jira_service_desk(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("jira_service_desk")
    from app.connectors.jira_service_desk_connector import JiraServiceDeskConnector

    assert isinstance(connector, JiraServiceDeskConnector)


def test_get_connector_returns_tap_snpp(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("tap_snpp")
    from app.connectors.tap_snpp_connector import TAPSNPPConnector

    assert isinstance(connector, TAPSNPPConnector)


def test_get_connector_returns_acars(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("acars")
    from app.connectors.acars_connector import ACARSConnector

    assert isinstance(connector, ACARSConnector)


def test_get_connector_returns_rfc5425(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("rfc5425")
    assert isinstance(connector, RFC5425Connector)


def test_get_connectors_data_missing_config(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    data = get_connectors_data()
    assert all(item["status"] == "missing_config" for item in data)
    slack_data = next(item for item in data if item["id"] == "slack")
    assert slack_data["status"] == "missing_config"


def test_get_connectors_data_status_up(monkeypatch):
    from app.core.config import load_config, Settings

    config = load_config()
    config["connectors"] = [
        {"type": "slack", "token": "x", "channel_id": "C1", "config": {}}
    ]
    settings = Settings(**config)

    monkeypatch.setattr("app.connectors.connector_utils.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.connectors.slack_connector.SlackConnector.is_connected", lambda self: True
    )

    data = get_connectors_data()
    slack_data = next(item for item in data if item["id"] == "slack")
    assert slack_data["status"] == "up"


def test_get_connector_returns_aws_iot_core(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("aws_iot_core")
    assert isinstance(connector, AWSIoTCoreConnector)


def test_get_connector_returns_aws_eventbridge(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("aws_eventbridge")
    assert isinstance(connector, AWSEventBridgeConnector)


def test_get_connector_returns_google_pubsub(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("google_pubsub")
    assert isinstance(connector, GooglePubSubConnector)


def test_get_connector_returns_azure_eventgrid(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("azure_eventgrid")
    assert isinstance(connector, AzureEventGridConnector)


def test_get_connector_returns_amqp(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("amqp")
    from app.connectors.amqp_connector import AMQPConnector

    assert isinstance(connector, AMQPConnector)


def test_get_connector_returns_redis_pubsub(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("redis_pubsub")
    from app.connectors.redis_pubsub_connector import RedisPubSubConnector

    assert isinstance(connector, RedisPubSubConnector)


def test_get_connector_returns_kafka(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("kafka")
    assert isinstance(connector, KafkaConnector)


def test_get_connector_returns_nats(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("nats")
    assert isinstance(connector, NATSConnector)


def test_get_connector_returns_pagerduty(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("pagerduty")
    assert isinstance(connector, PagerDutyConnector)


def test_get_connector_returns_line(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("line")
    assert isinstance(connector, LineConnector)


def test_get_connector_returns_viber(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("viber")
    assert isinstance(connector, ViberConnector)


def test_get_connector_returns_coap_oscore(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("coap_oscore")
    assert isinstance(connector, CoAPOSCOREConnector)


def test_get_connector_returns_opcua_pubsub(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("opcua_pubsub")
    assert isinstance(connector, OPCUAPubSubConnector)


def test_get_connector_returns_ais_safety_text(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("ais_safety_text")
    assert isinstance(connector, AISSafetyTextConnector)


def test_get_connector_returns_cap(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("cap")
    assert isinstance(connector, CAPConnector)


def test_get_connector_returns_zulip(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    connector = get_connector("zulip")
    from app.connectors.zulip_connector import ZulipConnector

    assert isinstance(connector, ZulipConnector)


def test_get_configured_connectors_none(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.connector_utils.get_settings", lambda: test_settings
    )
    from app.connectors.connector_utils import get_configured_connectors

    assert get_configured_connectors() == {}


def test_get_configured_connectors_with_slack(monkeypatch):
    from app.core.config import load_config, Settings
    from app.connectors.connector_utils import get_configured_connectors

    config = load_config()
    config["connectors"] = [{"type": "slack", "token": "x", "channel_id": "C1"}]
    settings = Settings(**config)

    monkeypatch.setattr("app.connectors.connector_utils.get_settings", lambda: settings)
    connectors = get_configured_connectors()
    assert "slack" in connectors
    assert isinstance(connectors["slack"][0], SlackConnector)
