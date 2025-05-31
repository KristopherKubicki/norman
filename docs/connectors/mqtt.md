# MQTT Connector

The MQTT connector allows Norman to publish and subscribe to messages using an MQTT broker.

## Requirements

- Access to an MQTT broker
- The broker URL, port, and topic you wish to use

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
mqtt_broker_url: "your_mqtt_broker_url"
mqtt_port: 1883
mqtt_topic: "your_mqtt_topic"
```

The fields are:

- `mqtt_broker_url`: Hostname or IP address of the MQTT broker.
- `mqtt_port`: Port for the broker (default `1883`).
- `mqtt_topic`: MQTT topic to publish and subscribe to.

## Usage

Once configured, Norman can send messages to the configured topic and process incoming MQTT messages.

## Troubleshooting

1. Verify the broker URL and port are correct.
2. Ensure the topic exists and that the broker is reachable from the running environment.
