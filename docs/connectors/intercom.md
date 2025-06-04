# Intercom Connector

Send notifications through the Intercom API and poll for new conversations.

## Configuration

```yaml
intercom_access_token: "your_access_token"
intercom_app_id: "your_app_id"
```

## Usage

The connector posts simple in-app messages to Intercom and now polls the
`/conversations` API for new messages. Norman verifies your access token
via the `/me` endpoint, so the connector status shows **up** only when the
credentials are valid.
