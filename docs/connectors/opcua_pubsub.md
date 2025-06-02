# OPC UA PubSub Connector

This connector publishes messages via OPC UA PubSub using UDP datagrams.

## Configuration

```yaml
opcua_pubsub_endpoint: "your_opcua_pubsub_endpoint"
```

## Usage

Messages are transmitted as UDP datagrams to the configured ``endpoint``. The
connector can also listen on the endpoint's port for incoming datagrams and
forward them to Norman.
