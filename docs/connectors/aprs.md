# APRS Connector

The APRS connector allows Norman to send and receive packets over the APRS-IS network.

## Configuration

Add these keys to your `config.yaml`:

```yaml
aprs_host: "rotate.aprs.net"
aprs_port: 14580
aprs_callsign: "N0CALL"
aprs_passcode: "00000"
```

## Usage

Once configured, Norman can publish APRS packets to the specified server and listen for incoming packets.

## Limitations

This connector relies on the optional `aprslib` library. Ensure it is installed in your environment.
