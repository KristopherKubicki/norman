# Google Business Messages / RCS Connector

This connector is a simple wrapper around the Google Business Messages API.

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
google_business_access_token: "your_access_token"
google_business_phone_number: "your_phone_number"
```

## Usage

After configuration, Norman can send outbound messages over the Google
Business Messages (RCS) channel. Incoming message handling is not yet
implemented.
