# GroupMe Connector

The GroupMe connector sends messages using the GroupMe bot API.

## Configuration
Add the following key to your `config.yaml` file:
```yaml
groupme_bot_id: "your_groupme_bot_id"
```

## Usage
``GroupMeConnector`` posts text messages to the configured bot. Listening for
incoming messages is not implemented because GroupMe delivers messages via a
webhook callback.
