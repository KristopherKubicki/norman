import sys
import types
from fastapi import FastAPI

from app.connectors import init_connectors
from app.connectors.connector_utils import connector_classes
from app.core.test_settings import test_settings

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


def test_init_connectors_adds_all_connectors():
    app = FastAPI()
    init_connectors(app, test_settings)
    for name, cls in connector_classes.items():
        attr = f"{name}_connector"
        assert hasattr(app.state, attr)
        connector = getattr(app.state, attr)
        assert isinstance(connector, cls)

