# Bluesky Connector

Post updates to Bluesky using the AT Protocol APIs and an app password.

## Configuration

```yaml
bluesky_handle: "user.bsky.social"
bluesky_app_password: "your_app_password"
bluesky_service_url: "https://bsky.social"  # optional
```

Once configured, messages queued for the ``bluesky`` connector will be
published to your feed.
