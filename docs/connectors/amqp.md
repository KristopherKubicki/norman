# AMQP Connector

The AMQP connector allows Norman to publish messages to an AMQP broker such as RabbitMQ.

## Requirements

- An AMQP broker accessible from Norman
- The `pika` Python package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
amqp_url: "amqp://guest:guest@localhost:5672/"
amqp_queue: "norman"
```

## Usage

This connector currently only supports sending messages to the configured queue. Listening for incoming messages is not implemented.
