# Tox Connector

The Tox connector is a stub for the decentralized Tox messaging network.

## Requirements
- A Tox bootstrap node and friend ID
- Optional: Python bindings for `toxcore`

## Configuration
Add the following keys to your `config.yaml`:
```yaml
tox_bootstrap_host: "localhost"
tox_bootstrap_port: 33445
tox_friend_id: "your_friend_id"
```

## Usage
This connector currently does not implement full messaging functionality.
