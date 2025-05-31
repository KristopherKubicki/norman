# PagerDuty Events v2 Connector

This connector triggers PagerDuty incidents via the Events v2 REST API.

## Requirements

- A PagerDuty account with an integration key

## Configuration

Add the following to your `config.yaml`:

```yaml
pagerduty_routing_key: "your_integration_key"
```

## Usage

Sending a dictionary with `summary`, `source`, and `severity` fields will create or update incidents in PagerDuty.
