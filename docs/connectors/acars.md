# ACARS Connector

The ACARS connector sends and receives messages over UDP to communicate with
ACARS ground stations or other services. Messages are transmitted as raw text
datagrams.

## Configuration

Add these keys to your `config.yaml`:

```yaml
acars_host: "your_acars_host"
acars_port: 429
```

## Usage

Instantiate ``ACARSConnector`` with the host and port of the remote station.
Messages sent via ``send_message`` will be transmitted using UDP. Running
``listen_and_process`` opens a UDP server that forwards incoming messages to
``process_incoming`` for further handling.
