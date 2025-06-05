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

Events can be delivered to Norman via a webhook. Configure EventBridge to send
notifications to `/api/v1/connectors/aws_eventbridge/webhooks/eventbridge`.

The connector still publishes events to EventBridge using `put_events`.  It
verifies connectivity by calling `DescribeEventBus` when `is_connected()` is
invoked. If the credentials or event bus are incorrect, this method returns
`False`.
