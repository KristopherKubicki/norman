# BlueSky Connector

The BlueSky connector enables Norman to interact with the hypothetical BlueSky platform. This file outlines the minimal configuration required to enable the connector.

## Requirements

- A BlueSky account with API access
- The token and channel identifier where the bot will operate

## Configuration

Add the following configuration to your `config.yaml` file:

```yaml
connectors:
  - type: "bluesky"
    token: "your-bluesky-token"
    channel: "your-bluesky-channel-id"
```

Replace the values with your actual BlueSky credentials.

## Usage

Once configured, Norman will be able to send and receive messages via BlueSky using the connector. Implementation details are left to the developer.
