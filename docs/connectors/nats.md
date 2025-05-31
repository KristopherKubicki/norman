# NATS Connector

The NATS connector sends messages over NATS or JetStream using the `nats-py` library.

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

The connector currently publishes messages to the specified subject. Listening for messages is not implemented.
