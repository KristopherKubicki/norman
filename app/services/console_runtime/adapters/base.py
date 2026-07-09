from __future__ import annotations

from typing import Protocol

from app.services.console_runtime.types import (
    ModelCapabilities,
    ModelRequest,
    ModelResult,
)


class ModelAdapter(Protocol):
    """Provider adapter contract used by the Norman console runtime."""

    @property
    def name(self) -> str:
        """Stable provider name, such as codex, bedrock, ollama, or fake."""

    @property
    def capabilities(self) -> ModelCapabilities:
        """Runtime capabilities exposed for route policy decisions."""

    def invoke(self, request: ModelRequest) -> ModelResult:
        """Run one model request and return normalized output."""
