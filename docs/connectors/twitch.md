# Twitch Connector

The Twitch connector allows Norman to interact with Twitch chat channels over IRC.
This connector requires a Twitch IRC token and the channel you want the bot to
join.

## Requirements

- A Twitch account
- An OAuth token for IRC (usually begins with `oauth:`). You can generate one at
  <https://twitchapps.com/tmi/>.

## Configuration

Add the following configuration to your `config.yaml` file:

```yaml
connectors:
  - type: "twitch"
    token: "oauth:your-token"
    nickname: "your-twitch-username"
    channel: "your-channel"
```

Replace the values with your actual credentials and the channel name (without the
`#` prefix).

## Usage

Once configured, Norman will connect to the specified Twitch chat channel and can
send and receive messages just like any other connector.
