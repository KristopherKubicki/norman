import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, EmailStr, validator


def generate_unique_id() -> str:
    return str(uuid.uuid4())


class CustomBaseModel(BaseModel):
    class Config:
        allow_mutation = False
        arbitrary_types_allowed = True

        json_encoders = {
            uuid.UUID: str,
        }

    id: Optional[uuid.UUID] = None

    @validator("id", pre=True, always=True)
    def default_id(cls, value: Any) -> Any:
        return value or generate_unique_id()


def get_subdict(d: Dict[str, Any], keys: set[str]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if k in keys}
