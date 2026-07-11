"""Sample connector for local demo channels."""

from typing import Any, Optional

from .base_connector import BaseConnector


class SampleConnector(BaseConnector):
    """Local-only connector that always reports as connected."""

    name = "Sample (Local)"
    id = "sample"

    def __init__(self, config: Optional[dict] = None) -> None:
        super().__init__(config=config)

    def send_message(self, message: Any) -> None:
        return None

    async def listen_and_process(self) -> None:
        return None

    async def process_incoming(self, message: Any) -> Any:
        if not isinstance(message, dict):
            text = str(message)
            summary = f"sample • {text}" if text else "sample"
            return {"text": text, "text_summary": summary}
        text = message.get("text") or message.get("message") or ""
        summary_parts = ["sample"]
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {"text": text, "text_summary": summary}
