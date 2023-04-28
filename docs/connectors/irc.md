# IRC Connector

The IRC (Internet Relay Chat) connector allows Norman to interact with IRC chatrooms. This document provides information on how to set up and configure the IRC connector for use with Norman.

## Requirements

To use the IRC connector, you need to have the following:

- An IRC server you want to connect to
- A registered IRC nickname (optional, but recommended)

## Configuration

To configure the IRC connector, add the following to your `config.yaml` file:

```yaml
connectors:
  - type: "irc"
    server: "irc.example.com"
    port: 6667
    ssl: false
    nickname: "your-irc-nickname"
    password: "your-irc-password"
    channels:
      - "#your-irc-channel"
```

Replace the values with the appropriate information for your IRC server and channels. The fields in the configuration are:

- `type`: The type of the connector, in this case, `"irc"`.
- `server`: The address of the IRC server you want to connect to.
- `port`: The port number for the IRC server (default: 6667).
- `ssl`: Whether to use SSL for the connection (default: false).
- `nickname`: Your registered IRC nickname.
- `password`: The password for your registered IRC nickname.
- `channels`: A list of IRC channels you want to join.

## Usage

Once you have configured the IRC connector, Norman will connect to the specified IRC server and channels, and start listening for incoming messages. When a message is received, Norman will process it according to the configured channel filters and actions, and send a response back to the IRC channel.

## Limitations

Keep in mind that IRC has some limitations compared to more modern chat platforms. For example, message formatting is limited, and there may be restrictions on the length of messages that can be sent.

## Troubleshooting

If you encounter issues when using the IRC connector, please check the following:

1. Ensure your IRC server and port are correct.
2. Make sure your IRC nickname is registered and the password is correct.
3. Check that the channels you want to join are spelled correctly and exist on the server.

If you continue to experience issues, consult the Norman logs for any error messages or warnings that might provide more information about the problem.
