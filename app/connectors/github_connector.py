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
            payload = {"title": message.get("title", "Norman Issue"), "body": message.get("body", "")}
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
        await self.send_message(message)
        return message
