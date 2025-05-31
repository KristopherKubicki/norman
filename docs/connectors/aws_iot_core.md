# AWS IoT Core Connector

The AWS IoT Core connector publishes messages to an AWS IoT Core topic.

## Requirements

- An AWS account with IoT Core enabled
- Credentials with permission to publish to the topic
- The `boto3` package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
aws_region: "us-east-1"
aws_iot_core_endpoint: "your_iot_endpoint"
aws_iot_core_topic: "your_iot_topic"
aws_access_key: "your_aws_access_key"
aws_secret_key: "your_aws_secret_key"
aws_session_token: "your_aws_session_token"
```

## Usage

Once configured, Norman will publish messages to the specified topic.
