# DingTalk Connector

The DingTalk connector allows Norman to interact with Alibaba DingTalk chats.

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
dingtalk_access_token: "your_dingtalk_access_token"
```

## Usage

The connector uses the DingTalk robot HTTP API to send text messages. Provide
your bot access token in the configuration and Norman will post directly to the
chat. Receiving messages has not yet been implemented.
