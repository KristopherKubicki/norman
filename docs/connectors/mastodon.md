# Mastodon Connector

The Mastodon connector posts updates to a Mastodon server using its REST API.

## Requirements

- A Mastodon account and access token

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
mastodon_base_url: "https://mastodon.example.com"
mastodon_access_token: "your_mastodon_token"
```

## Usage

After configuration, Norman can send status updates to Mastodon. Incoming message processing is not yet implemented.
