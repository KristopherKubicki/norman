# Connectors

Connectors are the way Norman interacts with different chat platforms. They handle sending and receiving messages from various services, allowing you to use Norman with a wide range of platforms. This document describes the available connectors and how to use them.

## Available Connectors

The following connectors are soon to be supported:


1. [IRC](./connectors/irc.md)
2. [Slack](./connectors/slack.md)
3. [Discord](./connectors/discord.md)
4. [Microsoft Teams](./connectors/teams.md)
5. [Google Chat](./connectors/googlechat.md)
6. [Telegram](./connectors/telegram.md)
7. [Webhook](./connectors/webhook.md)
8. [Matrix](./connectors/matrix.md)
9. [WhatsApp](./connectors/whatsapp.md)
10. [Twitch](./connectors/twitch.md)
11. [REST Callback](./connectors/rest_callback.md)
12. [MCP](./connectors/mcp.md)


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
- [Signal Connector](./connectors/signal.md)
- [Matrix Connector](./connectors/matrix.md)
- [WhatsApp Connector](./connectors/whatsapp.md)
- [Twitch Connector](./connectors/twitch.md)
- [REST Callback Connector](./connectors/rest_callback.md)
- [MCP Connector](./connectors/mcp.md)

Remember to follow the platform-specific guidelines and best practices when creating bots or apps for each service.
