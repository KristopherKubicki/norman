# Redis Pub/Sub Connector

The Redis Pub/Sub connector enables Norman to send messages using Redis channels.

## Requirements

- A Redis server accessible from Norman
- The `redis` Python package installed

## Configuration

Include the following settings in your `config.yaml`:

```yaml
redis_host: "localhost"
redis_port: 6379
redis_channel: "norman"
```

## Usage

This connector currently publishes messages to the specified channel. Receiving messages is not yet implemented.
