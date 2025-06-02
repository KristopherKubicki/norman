# AWS IoT Core Connector

The AWS IoT Core connector publishes MQTT messages using the `boto3` IoT Data client and can optionally subscribe to topics via MQTT.

## Requirements

- An AWS account with IoT Core enabled
- The `boto3` Python package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
aws_iot_core_region: "us-east-1"
aws_iot_core_topic: "norman"
aws_iot_core_endpoint: "https://your-endpoint.amazonaws.com"  # optional
aws_iot_core_client_id: "your-client-id"            # optional
aws_iot_core_cert_path: "path/to/certificate.pem"    # optional
aws_iot_core_key_path: "path/to/private.key"         # optional
aws_iot_core_ca_path: "path/to/ca.pem"               # optional
```

## Usage

If the optional certificate paths are provided and the `paho-mqtt` library is installed, the connector will also subscribe to the configured topic using TLS.
