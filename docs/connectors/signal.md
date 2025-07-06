# Signal Connector

The Signal connector enables Norman to interact with Signal chats. This document outlines the basic configuration needed
to enable the connector.

## Requirements

To use the Signal connector you will need:

- Access to a running instance of `signal-cli` or another Signal service gateway
- The phone number associated with your Signal account

## Configuration

Add the following settings to your `config.yaml` file:

```yaml
signal_service_url: "your_signal_service_url"
signal_phone_number: "your_signal_phone_number"
```

`signal_service_url` should point to the HTTP endpoint for sending and receiving messages. `signal_phone_number` is the
number registered with the Signal service.

## Usage

Once configured, Norman will be able to send and receive messages through Signal when the connector is enabled. The
current implementation is a stub and can be extended to integrate with your preferred Signal gateway.
