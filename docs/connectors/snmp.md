# SNMP Connector

The SNMP connector emits simple SNMP traps to a management system.

## Requirements
- An SNMP manager reachable from Norman
- Optional: the `pysnmp` Python package

## Configuration
Add these keys to your `config.yaml`:
```yaml
snmp_host: "localhost"
snmp_port: 162
snmp_community: "public"
```

## Usage
This implementation sends a basic trap with the message text as payload. Listening for traps is not implemented.
