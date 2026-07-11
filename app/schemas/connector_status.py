from typing import List, Optional

from pydantic import BaseModel


class ConnectorStatusHistoryEntry(BaseModel):
    connector_id: int
    connector_type: str
    status: str
    checked_at: float
    failures: int = 0
    error: str = ""


class ConnectorStatusHistoryResponse(BaseModel):
    connector_id: int
    connector_name: Optional[str] = None
    connector_type: str
    history: List[ConnectorStatusHistoryEntry] = []
    recent_errors: List[ConnectorStatusHistoryEntry] = []
