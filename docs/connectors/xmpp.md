# XMPP Connector

The XMPP connector allows Norman to interact with XMPP (Jabber) servers and rooms. This document outlines how to configure and use the XMPP connector.

## Requirements

To use the XMPP connector you will need:

- An XMPP server address
- Credentials for a Jabber account (JID and password)
- The room or user you wish Norman to communicate with

## Configuration

Add the following settings to your `config.yaml`:

```yaml
xmpp_jid: "your_xmpp_jid"
xmpp_password: "your_xmpp_password"
xmpp_server: "your_xmpp_server"
xmpp_port: 5222
xmpp_room: "your_xmpp_room"
```

Replace the placeholder values with the details for your server and account.

## Usage

With the configuration in place, Norman can connect to the specified XMPP server and listen for messages in the configured room. Incoming messages will be processed according to your filters and actions.

## Troubleshooting

If you encounter issues using the XMPP connector, verify that the JID and password are correct and that the server and port are reachable.
