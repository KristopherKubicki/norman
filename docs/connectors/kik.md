# Kik Connector

This connector enables Norman to interact with the Kik messaging platform via the official HTTP API.

## Configuration

Add the following settings to your `config.yaml` file:
```yaml
kik_username: "your_kik_username"
kik_api_key: "your_kik_api_key"
```

## Usage

With these values provided, Norman can send messages through Kik using the built-in API integration. Incoming messages should be delivered to Norman via a webhook endpoint.
