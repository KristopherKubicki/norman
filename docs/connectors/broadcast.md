# Broadcast Connector

The Broadcast connector forwards outgoing messages to multiple other connectors. It does not support receiving messages.

## Configuration

Add a comma-separated list of connector names to `broadcast_connectors` in your `config.yaml`:

```yaml
broadcast_connectors: "slack,discord"
```

## Usage

When instantiated, `BroadcastConnector` sends each message to all configured connectors. Use this to mirror output
across several platforms.
