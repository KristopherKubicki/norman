# AWS EventBridge Connector

This connector sends events to an AWS EventBridge bus.

## Requirements

- An AWS account with EventBridge enabled
- Credentials allowing `events:PutEvents`
- The `boto3` package installed

## Configuration

```yaml
aws_region: "us-east-1"
eventbridge_event_bus_name: "default"
eventbridge_source: "norman"
aws_access_key: "your_aws_access_key"
aws_secret_key: "your_aws_secret_key"
aws_session_token: "your_aws_session_token"
```

## Usage

Norman posts JSON events to the configured EventBridge bus.
