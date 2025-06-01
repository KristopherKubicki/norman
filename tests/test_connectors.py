import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.schemas.connector import ConnectorCreate
from app.tests.utils.utils import random_lower_string

def test_create_connector(test_app: TestClient, db: Session) -> None:
    connector_type = "irc"
    name = random_lower_string()
    connector_in = ConnectorCreate(connector_type=connector_type, name=name, config={})
    connector = crud.connector.create(db, obj_in=connector_in)
    assert connector.connector_type == connector_type
    assert connector.name == name

def test_get_connector(test_app: TestClient, db: Session) -> None:
    connector_type = "irc"
    name = random_lower_string()
    connector_in = ConnectorCreate(connector_type=connector_type, name=name, config={})
    connector = crud.connector.create(db, obj_in=connector_in)
    connector_2 = crud.connector.get(db, connector.id)
    assert connector_2
    assert connector.connector_type == connector_2.connector_type
    assert connector.name == connector_2.name
    assert connector.id == connector_2.id


def test_api_create_and_get_connector(test_app: TestClient) -> None:
    payload = {"connector_type": "irc", "name": "irc1", "config": {}}
    resp = test_app.post("/api/v1/connectors/connectors/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "irc1"
    connector_id = data["id"]

    resp = test_app.get(f"/api/v1/connectors/connectors/{connector_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == connector_id
