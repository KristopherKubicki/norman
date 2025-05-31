# IFTTT Connector

The IFTTT connector integrates Norman with the IFTTT Webhooks service.

## Requirements

- An IFTTT Webhooks URL

## Configuration

Add the webhook URL to your `config.yaml` file:

```yaml
ifttt_webhook_url: "https://maker.ifttt.com/trigger/your-event/json"
```

## Usage

Norman posts JSON payloads to the configured IFTTT webhook.

## Troubleshooting

1. Ensure the event name and key in the webhook URL are correct.
2. Check the IFTTT activity log if requests fail.
