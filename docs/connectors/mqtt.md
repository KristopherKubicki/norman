# MQTT Connector

The MQTT connector enables Norman to communicate over MQTT topics. This document explains how to configure the connector.

## Requirements

- An MQTT broker accessible to Norman.

## Configuration

Add the following to your `config.yaml`:

```yaml
connectors:
  - type: "mqtt"
    broker_url: "mqtt://localhost"
    topic: "norman/messages"
```

Replace the values with the URL of your broker and the topic to publish to or subscribe from.

## Usage

Once configured, Norman will publish messages to the configured topic and can be extended to listen for incoming MQTT messages.

