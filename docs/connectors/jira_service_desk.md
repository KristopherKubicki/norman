# Jira Service Desk Connector

This connector posts new issues or comments to Jira Service Desk.

## Requirements

- Jira Cloud instance and API token
- Project key where issues should be created

## Configuration

Add the following keys to `config.yaml`:

```yaml
jira_service_desk_url: "https://your-domain.atlassian.net"
jira_service_desk_email: "your_email@example.com"
jira_service_desk_api_token: "your_jira_api_token"
jira_service_desk_project_key: "PROJ"
```

## Usage

Provide `issue_key` in the message payload to add a comment to an existing issue.
If omitted, a new issue is created using the `summary` and `body` fields.

## Troubleshooting

1. Verify the API token and email are correct.
2. Ensure the project key exists and the user has permission to create issues.
