# Twitch Connector

The Twitch connector allows Norman to join a Twitch chat channel using the IRC interface provided by Twitch. It requires a bot token, the bot's nickname and the channel to join.

## Configuration

Update your `config.yaml` with the following fields:

```yaml
twitch_token: "your_twitch_oauth_token"
twitch_nickname: "your_bot_nickname"
twitch_channel: "your_channel_name"
```

These values can be obtained from the Twitch developer console. The OAuth token typically starts with `oauth:`.

## Usage

Once configured, Norman can send and receive messages in your Twitch channel. The implementation currently provides only basic functionality and can be extended to support more Twitch-specific features.
