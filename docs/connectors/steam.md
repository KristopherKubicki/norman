# Steam Chat Connector

The Steam Chat connector enables Norman to interact with Steam's chat system.

## Requirements

- A Steam account
- An API key obtained from the Steam community
- The chat ID or user ID that Norman should message

## Configuration

Add the following to your `config.yaml`:

```yaml
steam_api_key: "your_steam_api_key"
steam_chat_id: "your_steam_chat_id"
```

- `steam_api_key`: Your Steam Web API key.
- `steam_chat_id`: The ID of the user or chat to send messages to.

## Usage

Once configured, Norman can send messages to the specified Steam Chat and process incoming messages.

## Troubleshooting

1. Verify that your API key is correct.
2. Ensure the chat ID or user ID is valid and that your account has permission to send messages.
