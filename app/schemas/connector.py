from typing import List, Dict, Any, Optional
from pydantic import BaseModel, constr, Field


class ConnectorBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1)
    config: Dict[str, Any] = Field(default_factory=dict)
    connector_type: constr(strip_whitespace=True, min_length=1)


class ConnectorCreate(ConnectorBase):
    pass


class ConnectorUpdate(BaseModel):
    """Model for updating an existing connector."""

    name: Optional[constr(strip_whitespace=True, min_length=1)] = None
    config: Optional[Dict[str, Any]] = None
    connector_type: Optional[constr(strip_whitespace=True, min_length=1)] = None


class Connector(ConnectorBase):
    id: int

    class Config:
        orm_mode = True
