# Connectors

Connectors are the way Norman interacts with different chat platforms. They handle sending and receiving messages from various services, allowing you to use Norman with a wide range of platforms. This document describes the available connectors and how to use them.

## Available Connectors

The following connectors are soon to be supported:

1. **IRC**
2. **Slack**
3. **Discord**
4. **Microsoft Teams**
5. **Google Chat**
6. **Telegram**
7. **Webhook**
8. **Matrix**
9. **WhatsApp**
10. **Twilio SMS**

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

You can extend Norman with new connectors by creating a new class that inherits from `BaseConnector`. This class should implement the required methods to send and receive messages on the target platform. Then, add the new connector class to the `CONNECTOR_CLASSES` dictionary in `app/connectors/__init__.py` so that it can be used in the application.

## More Information

For more detailed information on each connector, please refer to the platform-specific documentation:

- [IRC Connector](./connectors/irc.md)
- [Slack Connector](./connectors/slack.md)
- [Discord Connector](./connectors/discord.md)
- [Microsoft Teams Connector](./connectors/teams.md)
- [Google Chat Connector](./connectors/googlechat.md)
- [Telegram Connector](./connectors/telegram.md)
- [Webhook Connector](./connectors/webhook.md)
- [Matrix Connector](#)
- [WhatsApp Connector](#)
- [Twilio SMS Connector](./connectors/twilio.md)

Remember to follow the platform-specific guidelines and best practices when creating bots or apps for each service.
