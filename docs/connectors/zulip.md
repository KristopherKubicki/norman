# Zulip Connector

The Zulip connector enables Norman to post messages to a Zulip stream.

## Requirements

- A Zulip account with an API key
- The URL of your Zulip server
- The stream and topic where Norman should post messages

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
zulip_email: "bot@example.com"
zulip_api_key: "your_zulip_api_key"
zulip_site: "https://zulip.example.com"
zulip_stream: "general"
zulip_topic: "Norman"
```

## Usage

With these values provided, Norman will be able to send messages to the given stream and topic. Receiving messages has
not been implemented yet.

## Troubleshooting

1. Verify the email and API key are correct.
2. Ensure the server URL is reachable from your Norman instance.
3. Check Zulip server logs if messages fail to send.
