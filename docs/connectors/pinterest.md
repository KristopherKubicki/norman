# Pinterest Connector

This connector posts pins or reads updates from Pinterest boards.

## Configuration
Add the following settings to your `config.yaml` file:
```yaml
pinterest_access_token: "your_pinterest_access_token"
pinterest_board_id: "your_pinterest_board_id"
```

## Usage
The connector now creates pins on the specified board by calling the Pinterest API.
Each message sent becomes the ``note`` field of the new pin.
