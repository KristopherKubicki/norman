from __future__ import annotations

from typing import Iterable, List, Union

from app.services.console_runtime.types import (
    ModelCapabilities,
    ModelRequest,
    ModelResult,
    ModelUsage,
)


FakeResponse = Union[str, ModelResult]


class FakeModelAdapter:
    """Deterministic adapter used by unit tests and dry-run workers."""

    def __init__(
        self,
        *,
        responses: Iterable[FakeResponse] | None = None,
        name: str = "fake",
        model: str = "fake-model",
        supports_tools: bool = False,
    ) -> None:
        self._name = name
        self._model = model
        self._responses: List[FakeResponse] = list(responses or [])
        self._supports_tools = supports_tools
        self.invocations: List[ModelRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            provider=self._name,
            models=[self._model],
            supports_tools=self._supports_tools,
            supports_streaming=False,
            supports_files=False,
            local=False,
        )

    def invoke(self, request: ModelRequest) -> ModelResult:
        self.invocations.append(request)
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, ModelResult):
                return response
            text = response
        else:
            text = ""
        return ModelResult(
            provider=self._name,
            model=request.model or self._model,
            text=str(text),
            stop_reason="stop",
            usage=ModelUsage(),
        )
