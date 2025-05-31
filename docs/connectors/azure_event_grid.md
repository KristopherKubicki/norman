# Azure Event Grid Connector

This connector posts events to Azure Event Grid.

## Requirements

- An Event Grid topic endpoint and access key
- The `azure-eventgrid` package installed

## Configuration

```yaml
azure_event_grid_endpoint: "https://your-eventgrid-endpoint"
azure_event_grid_access_key: "your_event_grid_key"
```

## Usage

Messages are published as Event Grid events to the configured topic.
