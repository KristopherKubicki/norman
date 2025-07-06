# Slack Connector

The Slack connector allows Norman to interact with Slack workspaces and channels. This document provides information on
how to set up and configure the Slack connector for use with Norman.

## Requirements

To use the Slack connector, you need the following:

- A Slack workspace that you have admin access to
- A Slack App with a Bot Token

## Configuration

To configure the Slack connector, follow these steps:

1. Create a new Slack App or use an existing one in your workspace. Visit the [Slack API
   website](https://api.slack.com/apps) to create or manage your apps.
2. In the "OAuth & Permissions" section of your app, add the following Bot Token Scopes: `app_mentions:read`,
   `channels:history`, `channels:join`, `chat:write`, and `users:read`.
3. Install your app to your workspace and obtain the Bot Token (starts with `xoxb-`).

Add the following configuration to your `config.yaml` file:

```yaml
connectors:
  - type: "slack"
    bot_token: "xoxb-your-bot-token"
    channels:
      - "your-slack-channel"
```

Replace the values with the appropriate information for your Slack workspace and channels. The fields in the
configuration are:

- `type`: The type of the connector, in this case, `"slack"`.
- `bot_token`: Your Slack App Bot Token.
- `channels`: A list of Slack channels you want to join.

## Usage

Once you have configured the Slack connector, Norman will connect to the specified Slack workspace and channels, and
start listening for incoming messages. When a message is received, Norman will process it according to the configured
channel filters and actions, and send a response back to the Slack channel.

The connector polls Slack asynchronously so it can be used together with other
connectors running on the same event loop.

## Troubleshooting

If you encounter issues when using the Slack connector, please check the following:

1. Ensure your Bot Token is correct and has the necessary scopes.
2. Make sure the Slack App is installed in your workspace.
3. Check that the channels you want to join are spelled correctly and exist in the workspace.

If you continue to experience issues, consult the Norman logs for any error messages or warnings that might provide more
information about the problem.
