# REST Callback Connector

The REST Callback connector allows Norman to communicate with external services using HTTP callbacks. It supports sending outbound requests and processing inbound callbacks.

## Requirements

- An HTTP endpoint capable of receiving JSON payloads

## Configuration

Add the callback URLs to your `config.yaml` file:

```yaml
rest_callback_inbound_url: "https://your-app.example.com/inbound"
rest_callback_outbound_url: "https://external-service.example.com/callback"
```

## Usage

When enabled, Norman will POST outbound messages to the configured outbound URL. Incoming HTTP callbacks can be sent to Norman's `/api/v1/connectors/rest_callback/webhooks/rest_callback` endpoint.

## Troubleshooting

1. Ensure the URLs are reachable from the Norman server.
2. Check HTTP response codes in the logs for any errors.
