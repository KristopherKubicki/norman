"""Connector for interacting with GitLab projects."""

from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class GitLabConnector(BaseConnector):
    """Connector for creating issues or comments in GitLab."""

    id = "gitlab"
    name = "GitLab"

    def __init__(
        self,
        token: str,
        project_id: str,
        api_url: str = "https://gitlab.com/api/v4",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.token = token
        self.project_id = project_id
        self.api_url = api_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"PRIVATE-TOKEN": self.token}

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Create an issue or comment on GitLab."""
        issue_iid = message.get("issue_iid")
        if issue_iid:
            url = f"{self.api_url}/projects/{self.project_id}/issues/{issue_iid}/notes"
            payload = {"body": message.get("body", "")}
        else:
            url = f"{self.api_url}/projects/{self.project_id}/issues"
            payload = {
                "title": message.get("title", "Norman Issue"),
                "description": message.get("body", ""),
            }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error communicating with GitLab: %s", exc)
            return None

    async def listen_and_process(self) -> None:
        """Listening is not implemented for GitLab."""
        return None

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize GitLab webhook payloads."""
        if not isinstance(message, dict):
            return {"text": str(message)}

        meta = message.get("_meta") or {}
        headers = meta.get("headers") or {}
        event_type = (
            headers.get("x-gitlab-event")
            or message.get("event_type")
            or message.get("object_kind")
            or "gitlab"
        )
        user = (message.get("user") or {}).get("username") or message.get(
            "user_username"
        )
        project = message.get("project") or {}
        attrs = message.get("object_attributes") or {}
        title = (
            attrs.get("title")
            or message.get("title")
            or attrs.get("message")
            or attrs.get("name")
        )
        url = attrs.get("url") or attrs.get("target_url") or attrs.get("noteable_url")
        body = attrs.get("description") or attrs.get("note") or ""

        summary_parts = [event_type]
        if title:
            summary_parts.append(title)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "event": event_type,
            "user": user,
            "project": project.get("path_with_namespace") or project.get("name"),
            "title": title,
            "body": body,
            "url": url,
            "text": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the token can access the GitLab API."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                f"{self.api_url}/user", headers=self._headers(), timeout=10
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
