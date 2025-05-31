# Matrix Connector

The Matrix connector enables Norman to communicate within Matrix rooms.

## Requirements

- Access to a Matrix homeserver
- A Matrix user account and access token
- The ID of the Matrix room where Norman should operate

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
matrix_homeserver: "https://matrix.example.com"
matrix_user_id: "@bot:example.com"
matrix_access_token: "your_matrix_access_token"
matrix_room_id: "!yourRoom:example.com"
```

The fields are:

- `matrix_homeserver`: URL of the Matrix homeserver
- `matrix_user_id`: User ID for the bot account
- `matrix_access_token`: Access token for the bot account
- `matrix_room_id`: ID of the Matrix room to join

## Usage

Once configured, Norman will join the specified room and can send and receive messages via Matrix.

## Troubleshooting

1. Verify that the homeserver URL and credentials are correct.
2. Ensure the bot account has access to the room.
3. Check the logs for authentication errors if messages fail to appear.
