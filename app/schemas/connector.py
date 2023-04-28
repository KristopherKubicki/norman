from typing import List
from pydantic import BaseModel

class ConnectorBase(BaseModel):
    name: str
    type: str
    config: dict

class ConnectorCreate(ConnectorBase):
    pass

class ConnectorUpdate(ConnectorBase):
    pass

class Connector(ConnectorBase):
    id: int

    class Config:
        orm_mode = True

