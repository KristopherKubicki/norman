import base64
import requests
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class JiraServiceDeskConnector(BaseConnector):
    """Connector for Jira Service Desk comments and issues."""

    id = "jira_service_desk"
    name = "Jira Service Desk"

    def __init__(self, url: str, email: str, api_token: str, project_key: str, config: Optional[dict] = None) -> None:
        super().__init__(config)
        self.url = url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.project_key = project_key

    def _headers(self) -> Dict[str, str]:
        token = base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }

    def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        issue_key = message.get("issue_key")
        if issue_key:
            url = f"{self.url}/rest/api/3/issue/{issue_key}/comment"
            payload = {"body": message.get("body", "")}
        else:
            url = f"{self.url}/rest/api/3/issue"
            payload = {
                "fields": {
                    "project": {"key": self.project_key},
                    "summary": message.get("summary", "Norman Ticket"),
                    "description": message.get("body", ""),
                    "issuetype": {"name": "Task"},
                }
            }
        try:
            resp = requests.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - network
            print(f"Error communicating with Jira Service Desk: {exc}")
            return None

    async def listen_and_process(self) -> None:
        """This connector does not listen for inbound messages."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        self.send_message(message)
        return message
