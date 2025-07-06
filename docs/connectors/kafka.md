# Kafka Connector

The Kafka connector publishes and consumes messages using the `confluent-kafka` library.

## Requirements

- A Kafka-compatible broker (Kafka or Redpanda)
- The `confluent-kafka` Python package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
kafka_bootstrap_servers: "localhost:9092"
kafka_topic: "norman"
```

## Usage

The connector publishes messages to the configured topic and also listens on the same topic to process incoming
messages.
