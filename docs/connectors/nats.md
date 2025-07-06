# NATS Connector

The NATS connector sends and receives messages over NATS or JetStream using the `nats-py` library.

## Requirements

- A running NATS server
- The `nats-py` Python package installed

## Configuration

Add the following settings to your `config.yaml`:

```yaml
nats_servers: "nats://127.0.0.1:4222"
nats_subject: "norman"
```

## Usage

The connector publishes messages to the configured subject and can also subscribe to that subject to process incoming
messages.
