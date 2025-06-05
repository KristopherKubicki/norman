# Pinterest Connector

The Pinterest connector allows Norman to create pins on a specific board using the Pinterest REST API.

## Requirements

- A Pinterest API access token
- The ID of the board you want to post to

## Configuration

Add the access token and board ID to your `config.yaml` file:

```yaml
pinterest_access_token: "your_pinterest_access_token"
pinterest_board_id: "your_pinterest_board_id"
```

## Usage

When invoked, Norman will create a new pin on the configured board. The message
payload should include an `image_url`, and optionally a `title` and
`description`.

## Troubleshooting

1. Ensure your access token has permission to create pins.
2. Verify the board ID is correct and that the token has access to it.
