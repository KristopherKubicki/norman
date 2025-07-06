# Google Chat Connector

The Google Chat connector allows Norman to send messages to Google Chat spaces. This document describes how to set up
and configure the connector.

## Requirements

- A Google Cloud project with the Google Chat API enabled
- A service account with access to the desired space
- A service account key JSON file
- The ID of the Google Chat space you want to use

## Configuration

1. Create or select a service account in your Google Cloud project and enable the Google Chat API.
2. Download the service account key JSON file and note its path.
3. Add the service account to the target Google Chat space.
4. Update your `config.yaml` with the following keys:

```yaml
google_chat_service_account_key_path: "/path/to/service_account.json"
google_chat_space: "spaces/AAAAExample"
```

The fields are:

- `google_chat_service_account_key_path`: Path to the service account key file.
- `google_chat_space`: Identifier of the Google Chat space.

## Usage

After configuration, Norman will connect to the specified space and can send and receive messages via Google Chat.

## Troubleshooting

1. Ensure the service account key path is correct and readable.
2. Confirm the service account has permission to post in the Google Chat space.
3. Check the Norman logs for any authentication or API errors.
