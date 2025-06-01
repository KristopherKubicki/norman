# Webhook Connector

The Webhook connector forwards messages from Norman to an arbitrary HTTP endpoint.

## Requirements

- An HTTP endpoint capable of receiving JSON payloads

## Configuration

Add the webhook URL to your `config.yaml` file:

```yaml
webhook_secret: "https://your-webhook-url.example.com/"
webhook_auth_token: "your_webhook_auth_token"
```

`webhook_secret` should contain the full URL of the endpoint that will receive the messages.
`webhook_auth_token` is optional but recommended. When set, requests to the
`/api/v1/connectors/webhook/webhooks/webhook` endpoint must include this token in
the `X-Webhook-Token` header.

## Usage

When enabled, Norman will send POST requests with message data to the configured webhook URL.

## Troubleshooting

1. Ensure the webhook URL is reachable from the Norman server.
2. Check HTTP response codes in the logs for any errors.
3. Verify any authentication or secrets required by your webhook service.
