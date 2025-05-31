# Mastodon Connector

The Mastodon connector lets Norman post updates to a Mastodon instance. You will need a Mastodon access token and the base URL of the instance you want to use.

## Configuration

Add the following settings to your `config.yaml` file:

```yaml
mastodon_api_base_url: "https://mastodon.example.com"
mastodon_access_token: "your-access-token"
```

## Usage

Once configured, Norman can send messages to Mastodon. Incoming message processing is not yet implemented.
