# TAP/SNPP Connector

The TAP/SNPP connector sends pages using the Telocator Alphanumeric Protocol or the Simple Network Paging Protocol.

## Configuration

Add these keys to your `config.yaml`:

```yaml
tap_snpp_host: "your_tap_snpp_host"
tap_snpp_port: 444
tap_snpp_password: "your_tap_snpp_password"
```

## Usage

Messages are delivered over a TCP connection to the configured ``host`` and ``port``.
The connector does not currently implement inbound paging support.
