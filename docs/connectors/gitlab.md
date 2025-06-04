# GitLab Connector

The GitLab connector allows Norman to create issues or comments in a GitLab project.

## Requirements

- A GitLab personal access token
- The project ID for your GitLab project

## Configuration

Add these settings to your `config.yaml` file:

```yaml
gitlab_token: "your_gitlab_token"
gitlab_project_id: "123456"
```

## Usage

When invoked, Norman will create a new issue or comment on an existing issue.
Include `issue_iid` in the message payload to comment, otherwise a new issue is opened.

## Troubleshooting

1. Ensure the token has the `api` scope.
2. Verify the project ID is correct and accessible.
