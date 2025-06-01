# app/connectors/__init__.py

from fastapi import FastAPI
from app.core.config import Settings

from .connector_utils import connector_classes, get_connector
from app.core.config import load_connector_instances
import logging

def init_connectors(app: FastAPI, _settings: Settings) -> None:
    """Instantiate connectors defined in the database.

    Instances are stored on ``app.state.connectors`` as a mapping from
    connector ID to the instantiated connector object. ``Settings`` is
    accepted for backward compatibility but is currently unused.
    """

    logger = logging.getLogger(__name__)

    try:
        connectors = load_connector_instances()
    except Exception:  # pylint: disable=broad-except
        logger.exception("Failed to load connector instances")
        connectors = []
    app.state.connectors = {}

    for conn in connectors:
        try:
            instance = get_connector(conn.connector_type, conn.config)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to initialize connector %s", conn.name)
            instance = None
        app.state.connectors[conn.id] = instance

