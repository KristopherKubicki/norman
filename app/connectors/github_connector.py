import requests
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class GitHubConnector(BaseConnector):
    """Connector for interacting with GitHub issues and pull requests."""

    id = "github"
    name = "GitHub"

    def __init__(self, token: str, repo: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.token = token
        self.repo = repo
        self.api_url = "https://api.github.com"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Create an issue or comment on GitHub."""
        issue_number = message.get("issue_number") or message.get("pr_number")
        if issue_number:
            url = f"{self.api_url}/repos/{self.repo}/issues/{issue_number}/comments"
            payload = {"body": message.get("body", "")}
        else:
            url = f"{self.api_url}/repos/{self.repo}/issues"
            payload = {"title": message.get("title", "Norman Issue"), "body": message.get("body", "")}
        try:
            response = requests.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:  # pragma: no cover - network
            print(f"Error communicating with GitHub: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """GitHub connector does not listen for inbound messages."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        self.send_message(message)
        return message
