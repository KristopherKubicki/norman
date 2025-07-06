# REST Callback Connector

The REST Callback connector allows Norman to forward messages to an arbitrary REST endpoint. It is useful for
integrating with external services that expose a simple HTTP interface.

## Requirements

- An HTTP endpoint that accepts JSON payloads

## Configuration

Add the callback URL to your `config.yaml` file:

```yaml
rest_callback_url: "https://example.com/callback"
```

`rest_callback_url` should contain the full URL that will receive the POST requests.

## Usage

When enabled, Norman will send POST requests with the message data to the configured endpoint whenever this connector is
used.

## Troubleshooting

1. Ensure the callback URL is reachable from the Norman server.
2. Check HTTP response codes in the logs for any errors.
3. Verify any authentication or secrets required by your callback service.
