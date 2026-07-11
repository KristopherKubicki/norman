import asyncio
import httpx
from typing import Any, Dict, List, Optional

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


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

    async def send_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Create an issue or comment on GitHub."""
        issue_number = message.get("issue_number") or message.get("pr_number")
        if issue_number:
            url = f"{self.api_url}/repos/{self.repo}/issues/{issue_number}/comments"
            payload = {"body": message.get("body", "")}
        else:
            url = f"{self.api_url}/repos/{self.repo}/issues"
            payload = {
                "title": message.get("title", "Norman Issue"),
                "body": message.get("body", ""),
            }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.error("Error communicating with GitHub: %s", exc)
            return None

    async def _fetch_events(self) -> List[Dict[str, Any]]:
        """Return recent issue events for the configured repository."""

        url = f"{self.api_url}/repos/{self.repo}/issues/events"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()

    async def listen_and_process(self) -> None:
        """Poll GitHub events and process them when new ones appear."""

        last_seen: Optional[int] = None
        while True:
            try:
                events = await self._fetch_events()
            except httpx.HTTPError as exc:  # pragma: no cover - network
                logger.error("Error fetching GitHub events: %s", exc)
                await asyncio.sleep(30)
                continue

            for event in reversed(events):
                event_id = int(event.get("id", 0))
                if last_seen is not None and event_id <= last_seen:
                    continue
                last_seen = event_id
                result = self.process_incoming(event)
                if asyncio.iscoroutine(result):
                    await result

            await asyncio.sleep(30)

    async def process_incoming(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize GitHub webhook or API event payloads."""
        if not isinstance(message, dict):
            return {"text": str(message)}

        meta = message.get("_meta") or {}
        headers = meta.get("headers") or {}
        event_type = headers.get("x-github-event") or message.get("event") or "github"
        action = message.get("action")

        repo = message.get("repository") or {}
        sender = message.get("sender") or {}
        issue = message.get("issue") or {}
        pr = message.get("pull_request") or {}
        comment = message.get("comment") or {}
        release = message.get("release") or {}

        title = (
            issue.get("title")
            or pr.get("title")
            or release.get("name")
            or message.get("ref")
            or message.get("head")
        )
        body = (
            comment.get("body")
            or issue.get("body")
            or pr.get("body")
            or release.get("body")
            or ""
        )
        url = (
            comment.get("html_url")
            or issue.get("html_url")
            or pr.get("html_url")
            or release.get("html_url")
            or message.get("compare")
        )
        user = sender.get("login") or issue.get("user", {}).get("login")

        summary_parts = [event_type]
        if action:
            summary_parts.append(action)
        if title:
            summary_parts.append(title)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "event": event_type,
            "action": action,
            "repository": repo.get("full_name") or repo.get("name"),
            "user": user,
            "title": title,
            "body": body,
            "url": url,
            "text": summary,
        }

    def is_connected(self) -> bool:
        """Return ``True`` if the token can access the GitHub API."""
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
