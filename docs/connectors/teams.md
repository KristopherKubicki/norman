# Microsoft Teams Connector

The Microsoft Teams connector enables Norman to interact with Microsoft Teams channels. This document provides information on how to set up and configure the Microsoft Teams connector for use with Norman.

## Requirements

To use the Microsoft Teams connector, you need the following:

- A Microsoft Teams workspace
- A Microsoft Azure account to create and manage your app

## Configuration

To configure the Microsoft Teams connector, follow these steps:

1. Go to the [Azure Portal](https://portal.azure.com/) and sign in with your Microsoft account.
2. Create a new App Registration, or use an existing one, in the "App registrations" section under "Azure Active Directory".
3. In the "Overview" section, note the Application (client) ID and Directory (tenant) ID.
4. In the "Certificates & secrets" section, create a new Client secret and note its value.
5. Set up the necessary API permissions for the Microsoft Graph API under "API permissions".
6. Add the Microsoft Teams channel(s) where you want to deploy the bot.

Add the following configuration to your `config.yaml` file:

```yaml
connectors:
  - type: "msteams"
    client_id: "your-client-id"
    client_secret: "your-client-secret"
    tenant_id: "your-tenant-id"
    channels:
      - "your-microsoft-teams-channel"
```

Replace the values with the appropriate information for your Microsoft Teams workspace and channels. The fields in the configuration are:

- `type`: The type of the connector, in this case, `"msteams"`.
- `client_id`: Your App Registration's Application (client) ID.
- `client_secret`: Your App Registration's Client secret.
- `tenant_id`: Your App Registration's Directory (tenant) ID.
- `channels`: A list of Microsoft Teams channels you want to join.

## Usage

Once you have configured the Microsoft Teams connector, Norman will connect to the specified Microsoft Teams workspace and channels, and start listening for incoming messages. When a message is received, Norman will process it according to the configured channel filters and actions, and send a response back to the Microsoft Teams channel.

## Troubleshooting

If you encounter issues when using the Microsoft Teams connector, please check the following:

1. Ensure your App Registration's Application (client) ID, Client secret, and Directory (tenant) ID are correct.
2. Make sure the necessary API permissions are granted for the Microsoft Graph API.
3. Check that the channels you want to join are spelled correctly and exist in the workspace.

If you continue to experience issues, consult the Norman logs for any error messages or warnings that might provide more information about the problem.
