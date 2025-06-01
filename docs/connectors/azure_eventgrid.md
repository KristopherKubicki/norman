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

This connector only sends events and does not listen for incoming messages.
