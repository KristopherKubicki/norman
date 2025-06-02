# Discord Connector

The Discord connector enables Norman to interact with Discord channels. This document provides information on how to set up and configure the Discord connector for use with Norman.

## Requirements

To use the Discord connector, you need the following:

- A Discord server
- A Discord bot account with the necessary permissions

## Configuration

To configure the Discord connector, follow these steps:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and sign in with your Discord account.
2. Create a new application, or use an existing one, and go to the "Bot" section.
3. Click on "Add Bot" to create a new bot account, or use an existing one.
4. Note the bot token for later use.
5. Invite the bot to your Discord server by generating an OAuth2 URL with the appropriate permissions (at least "Send Messages" and "Read Message History").
6. Add the Discord channel(s) where you want to deploy the bot.

Add the following configuration to your `config.yaml` file:

```yaml
connectors:
  - type: "discord"
    token: "your-bot-token"
    channels:
      - "your-discord-channel"
```

Replace the values with the appropriate information for your Discord server and channels. The fields in the configuration are:

- `type`: The type of the connector, in this case, `"discord"`.
- `token`: Your Discord bot account's token.
- `channels`: A list of Discord channels you want to join.

## Usage

Once you have configured the Discord connector, Norman will poll the specified Discord channel for new messages. Incoming messages are processed according to your configured filters and actions, and a response is sent back to the channel when appropriate. Polling occurs every few seconds using the Discord HTTP API.

## Troubleshooting

If you encounter issues when using the Discord connector, please check the following:

1. Ensure your Discord bot account's token is correct.
2. Make sure the bot has the necessary permissions to read and send messages in the Discord server.
3. Check that the channels you want to join are spelled correctly and exist in the server.

If you continue to experience issues, consult the Norman logs for any error messages or warnings that might provide more information about the problem.
