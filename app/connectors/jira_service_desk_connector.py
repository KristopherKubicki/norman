import asyncio
import base64
import httpx
from typing import Any, Dict, List, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class JiraServiceDeskConnector(BaseConnector):
    """Connector for Jira Service Desk comments and issues."""

    id = "jira_service_desk"
    name = "Jira Service Desk"

    def __init__(
        self,
        url: str,
        email: str,
        api_token: str,
        project_key: str,
        config: Optional[dict] = None,
    ) -> None:
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

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
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
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error communicating with Jira Service Desk: %s", exc)
            return None

    async def _fetch_issues(self) -> List[Dict[str, Any]]:
        """Return recently created issues for the configured project."""

        jql = f"project={self.project_key} ORDER BY created DESC"
        url = f"{self.url}/rest/api/3/search"
        params = {"jql": jql, "maxResults": 10}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=self._headers())
        response.raise_for_status()
        return response.json().get("issues", [])

    async def listen_and_process(self) -> None:
        """Poll Jira for new issues and process them."""

        last_seen: Optional[str] = None
        while True:
            try:
                issues = await self._fetch_issues()
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error fetching Jira issues: %s", exc)
                await asyncio.sleep(30)
                continue

            for issue in reversed(issues):
                key = issue.get("id")
                if last_seen is not None and key <= last_seen:
                    continue
                last_seen = key
                result = self.process_incoming(issue)
                if asyncio.iscoroutine(result):
                    await result

            await asyncio.sleep(30)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Jira webhook payloads."""
        if not isinstance(message, dict):
            return {"text": str(message)}

        issue = message.get("issue") or {}
        fields = issue.get("fields") or {}
        comment = message.get("comment") or {}
        author = (comment.get("author") or {}).get("displayName") or (
            fields.get("reporter") or {}
        ).get("displayName")

        summary = fields.get("summary") or ""
        body = (comment.get("body") or {}).get("content")
        if isinstance(body, list):
            body = " ".join(
                chunk.get("text", "")
                for block in body
                for chunk in block.get("content", [])
                if isinstance(chunk, dict)
            )

        status = (fields.get("status") or {}).get("name")
        issue_key = issue.get("key")

        summary_parts = ["jira"]
        if issue_key:
            summary_parts.append(issue_key)
        if summary:
            summary_parts.append(summary)
        summary_text = " • ".join(part for part in summary_parts if part)

        return {
            "event": message.get("webhookEvent") or "jira",
            "issue_key": issue_key,
            "summary": summary,
            "body": body or "",
            "status": status,
            "user": author,
            "text": summary_text,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if credentials can access Jira."""
        if not super().is_connected():
            return False
        try:
            resp = httpx.get(
                f"{self.url}/rest/api/3/myself",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
