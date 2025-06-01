# Gitter Connector

The Gitter connector allows Norman to post messages to Gitter rooms.

## Requirements
- A personal access token from Gitter
- The ID of the room you want to post in

## Configuration
Add the following settings to your `config.yaml`:

```yaml
gitter_token: "your_gitter_token"
gitter_room_id: "your_gitter_room_id"
```

## Usage
Once configured, Norman can send messages to the specified Gitter room using the connector.

## Troubleshooting
- Ensure the access token is valid and has the required scopes
- Verify the room ID is correct
