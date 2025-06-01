# AWS IoT Core Connector

The AWS IoT Core connector publishes MQTT messages using the `boto3` IoT Data client.

## Requirements

- An AWS account with IoT Core enabled
- The `boto3` Python package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
aws_iot_core_region: "us-east-1"
aws_iot_core_topic: "norman"
aws_iot_core_endpoint: "https://your-endpoint.amazonaws.com"  # optional
```

## Usage

This connector currently only supports publishing messages. Listening for inbound MQTT traffic is not implemented.
