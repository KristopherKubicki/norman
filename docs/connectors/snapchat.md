# Snapchat Connector

The Snapchat connector allows Norman to post updates or send messages via Snapchat.
It relies on a lightweight client library that authenticates with your Snapchat credentials.

## Configuration
Add the following keys to your `config.yaml` file:
```yaml
snapchat_username: "your_snapchat_username"
snapchat_password: "your_snapchat_password"
snapchat_recipient: "friend_to_message"
```

## Usage

With these settings, Norman can send basic text messages to the configured
`snapchat_recipient` and poll for new incoming snaps.  The implementation uses a
hypothetical Python package named `snapchat`.  In the unit tests a dummy version
of this package is injected so no real network access is required.
