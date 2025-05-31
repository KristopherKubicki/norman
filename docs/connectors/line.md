# LINE Messaging Connector

The LINE connector sends messages via the LINE Messaging API.

## Requirements

- LINE channel access token
- The user ID to send messages to

## Configuration

```yaml
line_channel_access_token: "your_channel_access_token"
line_user_id: "target_user_id"
```

## Usage

Norman can push text messages to the specified user. Receiving messages is not implemented.
