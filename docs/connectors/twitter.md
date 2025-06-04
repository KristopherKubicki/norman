# X.com (Twitter) Connector

This connector allows Norman to interact with X.com (formerly Twitter) via direct messages.

## Configuration

Add the following settings to your `config.yaml` file:

```yaml
twitter_api_key: "your_twitter_api_key"
twitter_api_secret: "your_twitter_api_secret"
twitter_access_token: "your_twitter_access_token"
twitter_access_token_secret: "your_twitter_access_token_secret"
twitter_recipient_id: "the_user_id_to_message"
```

## Usage

With these values provided, Norman can send direct messages using the Twitter API via Tweepy. Incoming message support is not yet implemented.
