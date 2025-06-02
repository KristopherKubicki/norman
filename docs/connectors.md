# Connectors

Connectors are the way Norman interacts with different chat platforms. They handle sending and receiving messages from various services, allowing you to use Norman with a wide range of platforms. This document describes the available connectors and how to use them.

## Available Connectors

The following connectors are currently supported:


1. [IRC](./connectors/irc.md)
2. [Slack](./connectors/slack.md)
3. [Discord](./connectors/discord.md)
4. [Microsoft Teams](./connectors/teams.md)
5. [Google Chat](./connectors/google_chat.md)
6. [Telegram](./connectors/telegram.md)
7. [Webhook](./connectors/webhook.md)
8. [Matrix](./connectors/matrix.md)
9. [WhatsApp](./connectors/whatsapp.md)
10. [Twitch](./connectors/twitch.md)
11. [REST Callback](./connectors/rest_callback.md)
12. [MCP](./connectors/mcp.md)
13. [SMTP](./connectors/smtp.md)
14. [MQTT](./connectors/mqtt.md)
15. [Mastodon](./connectors/mastodon.md)
16. [Steam Chat](./connectors/steam_chat.md)
17. [XMPP](./connectors/xmpp.md)
18. [Bluesky](./connectors/bluesky.md)
19. [Facebook Messenger](./connectors/facebook_messenger.md)
20. [LinkedIn](./connectors/linkedin.md)
21. [Skype](./connectors/skype.md)
22. [Rocket.Chat](./connectors/rocketchat.md)
23. [Mattermost](./connectors/mattermost.md)
24. [WeChat](./connectors/wechat.md)
25. [Reddit Chat](./connectors/reddit_chat.md)
26. [Signal](./connectors/signal.md)
27. [Instagram DM](./connectors/instagram_dm.md)
28. [X.com (Twitter)](./connectors/twitter.md)
29. [Apple RCS/iMessage](./connectors/imessage.md)
30. [APRS](./connectors/aprs.md)
31. [AX.25](./connectors/ax25.md)
32. [Zapier](./connectors/zapier.md)
33. [IFTTT](./connectors/ifttt.md)
34. [Salesforce](./connectors/salesforce.md)
35. [GitHub](./connectors/github.md)
36. [Gitter](./connectors/gitter.md)
37. [Jira Service Desk](./connectors/jira_service_desk.md)
38. [TAP/SNPP](./connectors/tap_snpp.md)
39. [ACARS](./connectors/acars.md)
40. [RFC 5425](./connectors/rfc5425.md)
41. [AMQP](./connectors/amqp.md)
42. [Redis Pub/Sub](./connectors/redis_pubsub.md)
43. [Kafka](./connectors/kafka.md)
44. [NATS](./connectors/nats.md)
45. [PagerDuty Events v2](./connectors/pagerduty.md)
46. [LINE Messaging](./connectors/line.md)
47. [Viber Bots](./connectors/viber.md)
48. [CoAP + OSCORE](./connectors/coap_oscore.md)
49. [OPC UA PubSub](./connectors/opcua_pubsub.md)
50. [AIS Safety-Related Text](./connectors/ais_safety_text.md)
51. [Common Alerting Protocol](./connectors/cap.md)
52. [Google Business Messages / RCS](./connectors/google_business_rcs.md)
53. [Apple Messages for Business](./connectors/apple_messages_business.md)
54. [Intercom](./connectors/intercom.md)
55. [SNMP](./connectors/snmp.md)
56. [Tox](./connectors/tox.md)
57. [Zulip](./connectors/zulip.md)
58. [AWS IoT Core](./connectors/aws_iot_core.md)
59. [AWS EventBridge](./connectors/aws_eventbridge.md)
60. [Google Pub/Sub](./connectors/google_pubsub.md)
61. [Azure Event Grid](./connectors/azure_eventgrid.md)
62. [SMS](./connectors/sms.md)
63. [Broadcast](./connectors/broadcast.md)
64. [X.com](./connectors/xcom.md)


## Usage

To use a specific connector, you'll need to provide the necessary configuration details and credentials for that platform. This usually involves creating a bot or app on the respective platform and obtaining API keys, tokens, or other authentication details.

### Configuration

You'll need to update the `config.yaml` file with the appropriate settings for the connector you want to use. The required settings may vary depending on the platform. Here's an example of what the configuration for a Slack connector might look like:

```yaml
connectors:
  - type: "slack"
    token: "your-slack-bot-token"
    channel: "your-slack-channel"
```

For other connectors, consult the platform-specific documentation for information on obtaining the necessary credentials and configuring the connector.

### Extending Norman with New Connectors

You can extend Norman with new connectors by creating a new class that inherits from `BaseConnector`. Implement `send_message` and optionally `connect` and `disconnect` for any setup or teardown logic. Messages can be queued with `queue_message` and will be dispatched while `run()` is active. Place the new file inside the `app/connectors` package with a name ending in `_connector.py` so it can be auto-discovered.

## More Information

For more detailed information on each connector, please refer to the platform-specific documentation:

- [IRC Connector](./connectors/irc.md)
- [Slack Connector](./connectors/slack.md)
- [Discord Connector](./connectors/discord.md)
- [Microsoft Teams Connector](./connectors/teams.md)
- [Google Chat Connector](./connectors/google_chat.md)
- [Telegram Connector](./connectors/telegram.md)
- [Signal Connector](./connectors/signal.md)
- [Matrix Connector](./connectors/matrix.md)
- [WhatsApp Connector](./connectors/whatsapp.md)
- [Twitch Connector](./connectors/twitch.md)
- [REST Callback Connector](./connectors/rest_callback.md)
- [MCP Connector](./connectors/mcp.md)
- [MQTT Connector](./connectors/mqtt.md)
- [Mastodon Connector](./connectors/mastodon.md)
- [Zapier Connector](./connectors/zapier.md)
- [IFTTT Connector](./connectors/ifttt.md)
- [Salesforce Connector](./connectors/salesforce.md)
- [GitHub Connector](./connectors/github.md)
- [Jira Service Desk Connector](./connectors/jira_service_desk.md)
- [TAP/SNPP Connector](./connectors/tap_snpp.md)
- [ACARS Connector](./connectors/acars.md)
- [RFC 5425 Connector](./connectors/rfc5425.md)
- [AMQP Connector](./connectors/amqp.md)
- [Redis Pub/Sub Connector](./connectors/redis_pubsub.md)
- [CoAP + OSCORE Connector](./connectors/coap_oscore.md)
- [OPC UA PubSub Connector](./connectors/opcua_pubsub.md)
- [AIS Safety-Related Text Connector](./connectors/ais_safety_text.md)
- [Common Alerting Protocol Connector](./connectors/cap.md)
- [Google Business Messages / RCS Connector](./connectors/google_business_rcs.md)
- [Apple Messages for Business Connector](./connectors/apple_messages_business.md)
- [Intercom Connector](./connectors/intercom.md)
- [SNMP Connector](./connectors/snmp.md)
- [Tox Connector](./connectors/tox.md)
- [Zulip Connector](./connectors/zulip.md)
- [AWS IoT Core Connector](./connectors/aws_iot_core.md)
- [AWS EventBridge Connector](./connectors/aws_eventbridge.md)
- [Google Pub/Sub Connector](./connectors/google_pubsub.md)
- [Azure Event Grid Connector](./connectors/azure_eventgrid.md)
- [SMS Connector](./connectors/sms.md)
- [Broadcast Connector](./connectors/broadcast.md)

Remember to follow the platform-specific guidelines and best practices when creating bots or apps for each service.
