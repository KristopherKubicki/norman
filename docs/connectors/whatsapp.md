# WhatsApp Connector

The WhatsApp connector uses Twilio to send and receive WhatsApp messages.

## Requirements

- A Twilio account with WhatsApp support
- Your Twilio Account SID and Auth Token
- A WhatsApp-enabled `from` number and a destination `to` number

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
whatsapp_account_sid: "your_whatsapp_account_sid"
whatsapp_auth_token: "your_whatsapp_auth_token"
whatsapp_from_number: "whatsapp:+1234567890"
whatsapp_to_number: "whatsapp:+0987654321"
```

The fields are:

- `whatsapp_account_sid`: Your Twilio account SID
- `whatsapp_auth_token`: Your Twilio Auth Token
- `whatsapp_from_number`: The WhatsApp-enabled number sending messages
- `whatsapp_to_number`: The destination number for messages

## Usage

After configuration, Norman can send messages via Twilio to WhatsApp and process incoming messages.

The connector also checks the Twilio Account API at startup to verify your
credentials. If the credentials are invalid, the connector will appear as
"down" in the connectors status list.

## Troubleshooting

1. Confirm the Twilio credentials are correct.
2. Ensure the `from` and `to` numbers are authorized in your Twilio account.
3. Review Twilio logs for delivery errors if messages fail to send.
