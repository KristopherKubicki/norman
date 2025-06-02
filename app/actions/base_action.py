from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseAction(ABC):
    """Base class for all action plugins."""

    def __init__(self, config: Optional[dict] = None) -> None:
        self.config = config or {}

    @abstractmethod
    async def execute(self, message: Any, context: dict) -> Any:
        """Perform the action for ``message`` and return a result."""
        raise NotImplementedError
