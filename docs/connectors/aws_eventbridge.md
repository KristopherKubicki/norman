# AWS EventBridge Connector

The AWS EventBridge connector sends events to Amazon EventBridge using `boto3`.

## Requirements

- An AWS account with an EventBridge event bus
- The `boto3` Python package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
aws_eventbridge_region: "us-east-1"
aws_eventbridge_event_bus_name: "default"
```

## Usage

Incoming messages are not supported. The connector only publishes events.
