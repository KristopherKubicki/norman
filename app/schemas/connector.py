from typing import List, Dict, Any
from pydantic import BaseModel

class ConnectorBase(BaseModel):
    description: str
    config: Dict[str, Any]
    connector_type: str

class ConnectorCreate(ConnectorBase):
    pass

class ConnectorUpdate(ConnectorBase):
    pass

class Connector(ConnectorBase):
    id: int

    class Config:
        orm_mode = True

