# Flowdock Connector

The Flowdock connector allows Norman to interact with Flowdock flows.

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
flowdock_api_token: "your_flowdock_api_token"
flowdock_flow: "your_flowdock_flow"
```

## Usage

Once configured, Norman can send chat messages using Flowdock's push API.
Incoming message polling is not implemented.
