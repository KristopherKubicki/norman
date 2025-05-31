# app/connectors/__init__.py

from fastapi import FastAPI
from app.core.config import Settings

from .connector_utils import connector_classes, get_connector

def init_connectors(app: FastAPI, _settings: Settings) -> None:
    """Instantiate all connectors defined in :mod:`connector_utils`.

    Each connector is stored on ``app.state`` with a ``<name>_connector``
    attribute, where ``name`` is the key from ``connector_classes``.
    ``settings`` is accepted for backward compatibility but the instantiation
    relies on :func:`~app.core.config.get_settings` internally.
    """

    for name in connector_classes:
        connector = get_connector(name)
        setattr(app.state, f"{name}_connector", connector)

