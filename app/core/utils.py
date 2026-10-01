import uuid
from typing import Any, Dict, Set

from pydantic import BaseModel, ConfigDict, Field


def generate_unique_id() -> str:
    return str(uuid.uuid4())


class CustomBaseModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
    )

    id: uuid.UUID = Field(default_factory=generate_unique_id, validate_default=True)


def get_subdict(d: Dict[str, Any], keys: Set[str]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if k in keys}
