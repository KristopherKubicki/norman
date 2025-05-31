# Steam Connector

The Steam connector enables Norman to interact with Steam Chat groups. This document outlines how to configure the connector for use with Norman.

## Requirements

To use the Steam connector you will need:

- A Steam account with access to the desired chat group
- An API key generated from the [Steam Community](https://steamcommunity.com/dev/apikey)

## Configuration

Add the following to your `config.yaml` file:

```yaml
connectors:
  - type: "steam"
    api_key: "your-steam-api-key"
    chat_id: "your-steam-chat-id"
```

Replace the values with your Steam API key and the identifier for the chat you want Norman to join.

## Usage

Once configured, Norman will connect to the specified Steam Chat and listen for incoming messages. Incoming messages are processed using the configured channel filters and actions, and responses are sent back to the chat.

## Troubleshooting

If you experience issues with the Steam connector, check the following:

1. Verify that the API key is correct and has not been revoked.
2. Ensure the chat ID is valid and that your account has access to the chat group.
3. Review the application logs for any error messages that can help diagnose the problem.
