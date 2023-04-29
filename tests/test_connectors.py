import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud, models
from app.core.config import settings
from app.schemas.connector import ConnectorCreate
from app.tests.utils.utils import random_lower_string

def test_create_connector(client: TestClient, db: Session) -> None:
    connector_type = "irc"
    name = random_lower_string()
    connector_in = ConnectorCreate(connector_type=connector_type, name=name)
    connector = crud.connector.create(db, obj_in=connector_in)
    assert connector.connector_type == connector_type
    assert connector.name == name

def test_get_connector(client: TestClient, db: Session) -> None:
    connector_type = "irc"
    name = random_lower_string()
    connector_in = ConnectorCreate(connector_type=connector_type, name=name)
    connector = crud.connector.create(db, obj_in=connector_in)
    connector_2 = crud.connector.get(db, connector.id)
    assert connector_2
    assert connector.connector_type == connector_2.connector_type
    assert connector.name == connector_2.name
    assert connector.id == connector_2.id
