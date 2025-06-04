# Instagram DM Connector

The Instagram DM connector enables Norman to interact with Instagram direct messages.

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
instagram_access_token: "your_instagram_access_token"
instagram_user_id: "your_instagram_user_id"
```

## Usage

Once configured, Norman can send direct messages using the Instagram Graph API.
The connector issues a ``POST`` request to the Graph API endpoint for your
configured ``instagram_user_id``. Incoming messages are not yet supported, so
``listen_and_process`` currently returns ``None``.
