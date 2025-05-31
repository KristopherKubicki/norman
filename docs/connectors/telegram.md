# Telegram Connector

The Telegram connector enables Norman to interact with Telegram chats and groups.

## Requirements

- A Telegram account
- A bot token obtained from [@BotFather](https://t.me/BotFather)
- The chat ID of the target chat or group

## Configuration

1. Use @BotFather to create a new bot and obtain its token.
2. Add the bot to the chat or group you want Norman to use and note the chat ID.
3. Update your `config.yaml` with the following keys:

```yaml
telegram_token: "your_telegram_token"
telegram_chat_id: "your_telegram_chat_id"
```

The fields are:

- `telegram_token`: The token provided by BotFather.
- `telegram_chat_id`: The chat or group ID where messages will be sent.

## Usage

Once configured, Norman will send messages to the specified chat and process incoming updates from Telegram.

## Troubleshooting

1. Verify that the bot token is correct.
2. Ensure the chat ID is accurate and that the bot has permission to post in the chat.
3. Check Norman's logs if messages fail to send or if updates are not received.
