import sys
import types
from fastapi import FastAPI

from app.connectors import init_connectors
from app.core.test_settings import test_settings
from app.connectors.slack_connector import SlackConnector
from app import crud
from app.schemas.connector import ConnectorCreate

# Provide a minimal slack_sdk stub if the real package isn't installed
if 'slack_sdk' not in sys.modules:
    slack_sdk = types.ModuleType('slack_sdk')

    class DummyClient:
        def __init__(self, token=None):
            self.token = token
        def auth_test(self):
            return {'ok': True}
    slack_sdk.WebClient = DummyClient
    errors_mod = types.ModuleType('slack_sdk.errors')
    slack_sdk.errors = errors_mod
    sys.modules['slack_sdk'] = slack_sdk
    sys.modules['slack_sdk.errors'] = errors_mod


def test_init_connectors_empty(monkeypatch, db):
    """No connectors in the DB should result in an empty mapping."""
    # Ensure table is empty
    db.query(crud.connector.ConnectorModel).delete()
    db.commit()

    monkeypatch.setattr("app.connectors.connector_utils.get_settings", lambda: test_settings)

    app = FastAPI()
    init_connectors(app, test_settings)
    assert app.state.connectors == {}


def test_init_connectors_with_slack(monkeypatch, db):
    """Connector instances should be created from the database."""
    slack = ConnectorCreate(name="slack-1", connector_type="slack", config={"token": "x", "channel_id": "C1"})
    created = crud.connector.create(db, slack)

    monkeypatch.setattr("app.connectors.connector_utils.get_settings", lambda: test_settings)

    app = FastAPI()
    init_connectors(app, test_settings)
    assert created.id in app.state.connectors
    assert isinstance(app.state.connectors[created.id], SlackConnector)

