# Flowdock Connector

The Flowdock connector allows Norman to interact with Flowdock flows.

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
flowdock_api_token: "your_flowdock_api_token"
flowdock_flow: "your_flowdock_flow"
```

## Usage

Norman now integrates directly with the Flowdock HTTP API. Messages are sent to
the configured flow using your API token. Listening for new messages is not yet
implemented, but outbound communication is fully functional.
