# GitHub Connector

The GitHub connector lets Norman create issues or comments in a GitHub repository.

## Requirements

- A GitHub personal access token
- The repository name in `owner/repo` format

## Configuration

Add these settings to your `config.yaml` file:

```yaml
github_token: "your_github_token"
github_repo: "owner/repo"
```

## Usage

When invoked, Norman will create a new issue or comment on an existing issue or pull request.
Include `issue_number` or `pr_number` in the message payload to comment, otherwise a new issue is opened.

## Troubleshooting

1. Ensure the token has the `repo` scope.
2. Check the repository name is correct and the bot has access.
