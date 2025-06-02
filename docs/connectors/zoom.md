# Zoom Connector

The Zoom connector allows Norman to send messages to Zoom chat via the Zoom REST API.
It does not currently support receiving messages.

## Requirements

- A Zoom account with chat capabilities enabled
- A JWT or OAuth access token that grants permission to post chat messages
- The recipient's JID (for example, a channel or user ID)

## Configuration

Add the following to your `config.yaml` file:

```yaml
connectors:
  - type: "zoom"
    token: "your-access-token"
    to_jid: "recipient-jid"
    account_id: "me"  # optional
```

`token` is the access token used for authentication. `to_jid` is the JID of the
chat recipient. `account_id` is optional and defaults to `me` which addresses the
authenticated account.

## Usage

Once configured, Norman can send outbound messages to the specified JID. Incoming
messages are not handled, so the connector is primarily useful for notifications
or one-way alerts.

## Troubleshooting

If messages fail to send:

1. Verify that the access token is valid and has not expired.
2. Ensure that the recipient JID is correct and that your account has permission
   to message it.
3. Check the Norman logs for any error details returned by the Zoom API.

