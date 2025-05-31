# Kafka Connector

The Kafka connector publishes messages to a Kafka or Redpanda cluster using the `confluent-kafka` library.

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

This connector currently only supports publishing messages to the configured topic.
