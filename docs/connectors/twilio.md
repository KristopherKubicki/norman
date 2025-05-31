# Twilio SMS Connector

The Twilio connector allows Norman to send SMS messages via the Twilio REST API.

## Requirements

- A Twilio account with a valid Account SID and Auth Token
- An SMS-enabled Twilio phone number

## Configuration

Add the following configuration to your `config.yaml` file:

```yaml
connectors:
  - type: "twilio"
    account_sid: "your-account-sid"
    auth_token: "your-auth-token"
    from_number: "+10001112222"
    to_number: "+12223334444"
```

Replace the values with your actual Twilio credentials and phone numbers.

## Usage

Once configured, Norman can send SMS notifications using the Twilio connector. Incoming SMS messages should be handled via a webhook endpoint if needed.

