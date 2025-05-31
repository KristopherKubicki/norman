# app/connectors/__init__.py

from fastapi import FastAPI
from app.core.config import Settings

#from .base_connector import BaseConnector
from .irc_connector import IRCConnector
from . import irc_connector as irc
from .slack_connector import SlackConnector
from .google_chat_connector import GoogleChatConnector
from .discord_connector import DiscordConnector
from .teams_connector import TeamsConnector
from .telegram_connector import TelegramConnector
from .webhook_connector import WebhookConnector
from .rest_callback_connector import RESTCallbackConnector
from .whatsapp_connector import WhatsAppConnector
from .matrix_connector import MatrixConnector
from .signal_connector import SignalConnector
from .twitch_connector import TwitchConnector
from .mcp_connector import MCPConnector
from .smtp_connector import SMTPConnector
from .mqtt_connector import MQTTConnector
from .mastodon_connector import MastodonConnector
from .sms_connector import SMSConnector
from .steam_chat_connector import SteamChatConnector
from .xmpp_connector import XMPPConnector
from .bluesky_connector import BlueskyConnector
from .facebook_messenger_connector import FacebookMessengerConnector
from .linkedin_connector import LinkedInConnector
from .skype_connector import SkypeConnector
from .rocketchat_connector import RocketChatConnector
from .mattermost_connector import MattermostConnector
from .wechat_connector import WeChatConnector
from .reddit_chat_connector import RedditChatConnector
from .instagram_dm_connector import InstagramDMConnector
from .twitter_connector import TwitterConnector
from .imessage_connector import IMessageConnector
from .aprs_connector import APRSConnector
from .ax25_connector import AX25Connector
from .zapier_connector import ZapierConnector
from .ifttt_connector import IFTTTConnector
from .salesforce_connector import SalesforceConnector
from .github_connector import GitHubConnector
from .jira_service_desk_connector import JiraServiceDeskConnector
from .tap_snpp_connector import TAPSNPPConnector
from .acars_connector import ACARSConnector
from .rfc5425_connector import RFC5425Connector

from .connector_utils import get_connector

def init_connectors(app: FastAPI, settings: Settings):
    app.state.telegram_connector = TelegramConnector(token=settings.telegram_token, chat_id=settings.telegram_chat_id)
    app.state.slack_connector = SlackConnector(token=settings.slack_token, channel_id=settings.slack_channel_id)
    app.state.google_chat_connector = GoogleChatConnector(service_account_key_path=settings.google_chat_service_account_key_path, space=settings.google_chat_space)
    app.state.discord_connector = DiscordConnector(token=settings.discord_token, channel_id=settings.discord_channel_id)
    app.state.teams_connector = TeamsConnector(app_id=settings.teams_app_id, app_password=settings.teams_app_password, tenant_id=settings.teams_tenant_id, bot_endpoint=settings.teams_bot_endpoint)
    app.state.whatsapp_connector = WhatsAppConnector(
        account_sid=settings.whatsapp_account_sid,
        auth_token=settings.whatsapp_auth_token,
        from_number=settings.whatsapp_from_number,
        to_number=settings.whatsapp_to_number,
    )
    app.state.sms_connector = SMSConnector(
        account_sid=settings.sms_account_sid,
        auth_token=settings.sms_auth_token,
        from_number=settings.sms_from_number,
        to_number=settings.sms_to_number,
    )
    app.state.signal_connector = SignalConnector(
        service_url=settings.signal_service_url,
        phone_number=settings.signal_phone_number,
    )
    app.state.matrix_connector = MatrixConnector(
        homeserver=settings.matrix_homeserver,
        user_id=settings.matrix_user_id,
        access_token=settings.matrix_access_token,
        room_id=settings.matrix_room_id,
    )
    app.state.twitch_connector = TwitchConnector(
        token=settings.twitch_token,
        nickname=settings.twitch_nickname,
        channel=settings.twitch_channel,
        server=settings.twitch_server,
        port=settings.twitch_port,
    )
    app.state.rest_callback_connector = RESTCallbackConnector(
        callback_url=settings.rest_callback_url
    )

    app.state.mqtt_connector = MQTTConnector(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        topic=settings.mqtt_topic,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
    )

    app.state.mastodon_connector = MastodonConnector(
        base_url=settings.mastodon_base_url,
        access_token=settings.mastodon_access_token,
    )

    app.state.mcp_connector = MCPConnector(
        api_url=settings.mcp_api_url,
        api_key=settings.mcp_api_key,
    )
    app.state.smtp_connector = SMTPConnector(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_address=settings.smtp_from_address,
        to_address=settings.smtp_to_address,
    )

    app.state.steam_chat_connector = SteamChatConnector(
        token=settings.steam_chat_token,
        chat_id=settings.steam_chat_id,
    )
    app.state.xmpp_connector = XMPPConnector(
        jid=settings.xmpp_jid,
        password=settings.xmpp_password,
        server=settings.xmpp_server,
    )
    app.state.bluesky_connector = BlueskyConnector(
        handle=settings.bluesky_handle,
        app_password=settings.bluesky_app_password,
    )
    app.state.facebook_messenger_connector = FacebookMessengerConnector(
        page_token=settings.facebook_page_token,
        verify_token=settings.facebook_verify_token,
    )
    app.state.linkedin_connector = LinkedInConnector(
        access_token=settings.linkedin_access_token,
    )
    app.state.skype_connector = SkypeConnector(
        app_id=settings.skype_app_id,
        app_password=settings.skype_app_password,
    )
    app.state.rocketchat_connector = RocketChatConnector(
        url=settings.rocketchat_url,
        token=settings.rocketchat_token,
        user_id=settings.rocketchat_user_id,
    )
    app.state.mattermost_connector = MattermostConnector(
        url=settings.mattermost_url,
        token=settings.mattermost_token,
        channel_id=settings.mattermost_channel_id,
    )
    app.state.wechat_connector = WeChatConnector(
        app_id=settings.wechat_app_id,
        app_secret=settings.wechat_app_secret,
    )
    app.state.reddit_chat_connector = RedditChatConnector(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        username=settings.reddit_username,
        password=settings.reddit_password,
        user_agent=settings.reddit_user_agent,
    )
    app.state.instagram_dm_connector = InstagramDMConnector(
        access_token=settings.instagram_access_token,
        user_id=settings.instagram_user_id,
    )
    app.state.twitter_connector = TwitterConnector(
        api_key=settings.twitter_api_key,
        api_secret=settings.twitter_api_secret,
        access_token=settings.twitter_access_token,
        access_token_secret=settings.twitter_access_token_secret,
    )
    app.state.imessage_connector = IMessageConnector(
        service_url=settings.imessage_service_url,
        phone_number=settings.imessage_phone_number,
    )
    app.state.aprs_connector = APRSConnector(
        host=settings.aprs_host,
        port=settings.aprs_port,
        callsign=settings.aprs_callsign,
        passcode=settings.aprs_passcode,
    )
    app.state.ax25_connector = AX25Connector(
        port=settings.ax25_port,
        callsign=settings.ax25_callsign,
    )
    app.state.zapier_connector = ZapierConnector(
        webhook_url=settings.zapier_webhook_url,
    )
    app.state.ifttt_connector = IFTTTConnector(
        webhook_url=settings.ifttt_webhook_url,
    )
    app.state.salesforce_connector = SalesforceConnector(
        instance_url=settings.salesforce_instance_url,
        access_token=settings.salesforce_access_token,
        endpoint=settings.salesforce_endpoint,
    )
    app.state.github_connector = GitHubConnector(
        token=settings.github_token,
        repo=settings.github_repo,
    )
    app.state.jira_service_desk_connector = JiraServiceDeskConnector(
        url=settings.jira_service_desk_url,
        email=settings.jira_service_desk_email,
        api_token=settings.jira_service_desk_api_token,
        project_key=settings.jira_service_desk_project_key,
    )
    app.state.tap_snpp_connector = TAPSNPPConnector(
        host=settings.tap_snpp_host,
        port=settings.tap_snpp_port,
        password=settings.tap_snpp_password,
    )
    app.state.acars_connector = ACARSConnector(
        host=settings.acars_host,
        port=settings.acars_port,
    )
    app.state.rfc5425_connector = RFC5425Connector(
        host=settings.rfc5425_host,
        port=settings.rfc5425_port,
    )
