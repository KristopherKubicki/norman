# Common Alerting Protocol Connector

This connector sends alerts using CAP version 1.2.

## Configuration

```yaml
cap_endpoint: "your_cap_endpoint"
```

## Usage

Specify the CAP endpoint in your configuration.  Messages passed to
``send_message`` are POSTed to this endpoint and ``listen_and_process`` will
fetch and parse any CAP alerts from the same URL.
