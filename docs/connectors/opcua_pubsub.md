# OPC UA PubSub Connector

This connector sends and receives messages using the OPC UA PubSub UDP profile.

## Configuration

```yaml
opcua_pubsub_endpoint: "opc.tcp://localhost:4840"
```

## Usage

Instantiate ``OPCUAPubSubConnector`` with the desired endpoint. Messages sent via
``send_message`` are transmitted as UDP datagrams. When
``listen_and_process`` is run, the connector opens a UDP socket on the port
extracted from the endpoint and forwards incoming datagrams to
``process_incoming``.
