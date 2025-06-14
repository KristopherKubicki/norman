# Azure Event Grid Connector

The Azure Event Grid connector posts events to an Event Grid topic.

## Requirements

- An Azure subscription with Event Grid enabled
- The `azure-eventgrid` Python package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
azure_eventgrid_endpoint: "https://<topic>.<region>.eventgrid.azure.net/api/events"
azure_eventgrid_key: "your-access-key"
```

## Usage

Configure Azure Event Grid to post events to
`/api/v1/connectors/azure_eventgrid/webhooks/eventgrid`. The connector will
process these incoming events in addition to publishing events to the configured
topic.

Connectivity is verified by making a simple HTTP request to the configured
endpoint when :code:`is_connected()` is called. If the request fails or returns
an error status code, the method returns ``False``.
