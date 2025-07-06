# Microsoft Teams Connector

The Microsoft Teams connector enables Norman to interact with Microsoft Teams channels. This document provides
information on how to set up and configure the Microsoft Teams connector for use with Norman.

## Requirements

To use the Microsoft Teams connector, you need the following:

- A Microsoft Teams workspace
- A Microsoft Azure account to create and manage your app

## Configuration

To configure the Microsoft Teams connector, follow these steps:

1. Go to the [Azure Portal](https://portal.azure.com/) and sign in with your Microsoft account.
2. Create a new App Registration, or use an existing one, in the "App registrations" section under "Azure Active
   Directory".
3. In the "Overview" section, note the Application (client) ID and Directory (tenant) ID.
4. In the "Certificates & secrets" section, create a new Client secret and note its value.
5. Set up the necessary API permissions for the Microsoft Graph API under "API permissions".
6. Add the Microsoft Teams channel(s) where you want to deploy the bot.

Add the following configuration to your `config.yaml` file:

```yaml
teams_app_id: "your_teams_app_id"
teams_app_password: "your_teams_app_password"
teams_tenant_id: "your_teams_tenant_id"
teams_bot_endpoint: "your_teams_bot_endpoint"
```

Replace the values with the appropriate information for your Microsoft Teams setup. The fields in the configuration are:

- `teams_app_id`: Your App Registration's Application (client) ID.
- `teams_app_password`: Your App Registration's Client secret.
- `teams_tenant_id`: Your App Registration's Directory (tenant) ID.
- `teams_bot_endpoint`: The publicly reachable endpoint for your bot.

## Usage

Once you have configured the Microsoft Teams connector, Norman will connect to the specified Microsoft Teams workspace
and channels, and start listening for incoming messages. When a message is received, Norman will process it according to
the configured channel filters and actions, and send a response back to the Microsoft Teams channel.

## Troubleshooting

If you encounter issues when using the Microsoft Teams connector, please check the following:

1. Ensure your App Registration's Application (client) ID, Client secret, and Directory (tenant) ID are correct.
2. Make sure the necessary API permissions are granted for the Microsoft Graph API.
3. Check that the channels you want to join are spelled correctly and exist in the workspace.

If you continue to experience issues, consult the Norman logs for any error messages or warnings that might provide more
information about the problem.
