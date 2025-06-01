# app/connectors/__init__.py

from fastapi import FastAPI
from app.core.config import Settings, get_settings

from .connector_utils import connector_classes, get_connector, _is_configured
import logging

def init_connectors(app: FastAPI, _settings: Settings) -> None:
    """Instantiate all connectors defined in :mod:`connector_utils`.

    Each connector is stored on ``app.state`` with a ``<name>_connector``
    attribute, where ``name`` is the key from ``connector_classes``.
    ``settings`` is accepted for backward compatibility but the instantiation
    relies on :func:`~app.core.config.get_settings` internally.
    """

    settings = get_settings()
    logger = logging.getLogger(__name__)

    for name in connector_classes:
        if not _is_configured(name, settings):
            setattr(app.state, f"{name}_connector", None)
            continue
        try:
            connector = get_connector(name)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to initialize connector %s", name)
            connector = None
        setattr(app.state, f"{name}_connector", connector)

