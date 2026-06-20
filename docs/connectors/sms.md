# SMS Connector

The SMS connector uses Twilio to send text messages.

## Requirements

- A Twilio account with an SMS-capable number
- The `requests` Python package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
sms_account_sid: "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
sms_auth_token: "your_token"
sms_from_number: "<E164_FROM_NUMBER>"
sms_to_number: "<E164_TO_NUMBER>"
```

## Usage

Incoming SMS messages are delivered via webhooks and are not handled directly by this connector.
