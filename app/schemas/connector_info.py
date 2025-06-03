from typing import List, Optional
from pydantic import BaseModel


class ConnectorInfo(BaseModel):
    """Metadata about an available connector."""

    id: str
    name: str
    status: str
    fields: List[str]
    last_message_sent: Optional[str] = None
    enabled: bool

    class Config:
        orm_mode = True
