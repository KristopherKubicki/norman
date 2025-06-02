# CoAP + OSCORE Connector

This connector sends CoAP-style messages over UDP secured with OSCORE.

## Configuration

Add the following settings to your `config.yaml`:

```yaml
coap_oscore_host: "your_coap_oscore_host"
coap_oscore_port: 5684
```

## Usage

The connector will transmit messages to the configured ``host`` and ``port``
using UDP. It can also listen on that port for incoming datagrams which are
passed to Norman for processing.
