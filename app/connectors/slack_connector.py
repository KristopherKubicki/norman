import asyncio
import importlib
from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class SlackConnector(BaseConnector):
    id = "slack"
    name = "Slack"

    def __init__(self, token: str, channel_id: str, config=None):
        super().__init__(config)
        self.token = token
        self.channel_id = channel_id
        self.client = None

    def _get_client(self):
        """Lazily import and return the Slack WebClient."""
        if self.client is None:
            slack_sdk = importlib.import_module("slack_sdk")
            self.client = slack_sdk.WebClient(token=self.token)
        return self.client

    def connect(self):
        pass  # No need for a separate connect method, as WebClient will handle it.

    def disconnect(self):
        pass  # No need for a separate disconnect method, as WebClient will handle it.

    async def listen_and_process(self):
        """Poll for messages asynchronously and process them."""

        errors_mod = importlib.import_module("slack_sdk.errors")

        try:
            loop = asyncio.get_running_loop()
            messages = await loop.run_in_executor(None, self.receive_message)
        except errors_mod.SlackApiError as exc:
            logger.error("Error receiving messages: %s", exc)
            return []

        results = []
        for message in messages:
            try:
                processed = self.process_incoming(message)
                if asyncio.iscoroutine(processed):
                    processed = await processed
                if processed:
                    results.append(processed)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error processing message: %s", exc)
        return results

    def process_incoming(self, payload: dict):
        """Extract the useful fields from a Slack event payload."""
        if not isinstance(payload, dict):
            logger.error("Invalid payload type")
            return {}

        event = payload.get("event", payload)
        if not isinstance(event, dict):
            return {}

        event_type = event.get("type") or payload.get("type") or "message"
        subtype = event.get("subtype")
        user = event.get("user") or (event.get("bot_profile") or {}).get("id")
        text = event.get("text") or ""
        channel = event.get("channel") or self.channel_id

        summary_parts = [event_type]
        if subtype:
            summary_parts.append(subtype)
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "event": event_type,
            "subtype": subtype,
            "text": text,
            "user": user,
            "channel": channel,
            "ts": event.get("ts"),
            "thread_ts": event.get("thread_ts"),
            "text_summary": summary,
        }

    def send_message(self, message):
        errors_mod = importlib.import_module("slack_sdk.errors")
        client = self._get_client()
        try:
            response = client.chat_postMessage(channel=self.channel_id, text=message)
            return response
        except errors_mod.SlackApiError as exc:
            logger.error("Error sending message: %s", exc)

    def receive_message(self):
        """Retrieve the most recent message from the Slack channel."""
        errors_mod = importlib.import_module("slack_sdk.errors")
        client = self._get_client()
        try:
            response = client.conversations_history(channel=self.channel_id, limit=1)
            return response.get("messages", [])
        except errors_mod.SlackApiError as exc:
            logger.error("Error receiving message: %s", exc)
            return []

    def is_connected(self):
        errors_mod = importlib.import_module("slack_sdk.errors")
        client = self._get_client()
        try:
            client.auth_test()
            return True
        except errors_mod.SlackApiError:
            return False
