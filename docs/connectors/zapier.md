# Zapier Connector

The Zapier connector allows Norman to trigger Zapier workflows using the Zapier Webhooks service.

## Requirements

- A Zapier Webhooks URL

## Configuration

Add the webhook URL to your `config.yaml` file:

```yaml
zapier_webhook_url: "https://hooks.zapier.com/hooks/catch/your-id"
```

## Usage

When enabled, Norman sends POST requests with message data to the configured Zapier webhook.

## Troubleshooting

1. Verify the webhook URL is correct.
2. Check the Zapier task history for any failures.
