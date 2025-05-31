# MQTT Connector

The MQTT connector allows Norman to publish and subscribe to topics on an MQTT broker.

## Requirements

- An MQTT broker accessible from Norman
- Credentials (if required by the broker)

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
mqtt_host: "mqtt.example.com"
mqtt_port: 1883
mqtt_topic: "norman"
mqtt_username: "your_username"
mqtt_password: "your_password"
```

## Usage

Once configured, Norman can publish messages to the configured topic and listen for incoming messages.

## Limitations

This connector uses the `paho-mqtt` library. Ensure it is installed in your environment.
