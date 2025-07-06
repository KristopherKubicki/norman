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

    connectors: dict = {}

    if settings.connectors:
        for item in settings.connectors:
            name = item.get("type")
            cfg = {k: v for k, v in item.items() if k != "type"}
            if name not in connector_classes:
                logger.warning("Unknown connector %s", name)
                continue
            try:
                conn = get_connector(name, cfg)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Failed to initialize connector %s", name)
                conn = None
            connectors.setdefault(name, []).append(conn)
    else:
        for name in connector_classes:
            if not _is_configured(name, settings):
                connectors[name] = []
                continue
            try:
                conn = get_connector(name)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Failed to initialize connector %s", name)
                conn = None
            connectors.setdefault(name, []).append(conn)

    app.state.connectors = connectors
