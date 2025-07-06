# Salesforce Connector

The Salesforce connector posts data to a Salesforce REST endpoint. Use it to integrate Norman with your Salesforce
workflows.

## Requirements

- A Salesforce instance with API access
- An OAuth access token for REST API calls

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
salesforce_instance_url: "https://your_instance.salesforce.com"
salesforce_access_token: "your_salesforce_access_token"
salesforce_endpoint: "services/data/vXX.X/sobjects/Lead"
```

`salesforce_endpoint` is appended to the instance URL when sending requests.

## Usage

Norman will POST JSON payloads to the specified Salesforce endpoint using the provided access token.

## Troubleshooting

1. Ensure the access token and instance URL are valid.
2. Review Salesforce logs for any API errors.
