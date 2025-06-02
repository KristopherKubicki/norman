# app/connectors/connector_utils.py

"""Utility helpers for working with connector classes.

This module centralizes the available connector implementations and provides
helpers for instantiating them from the application configuration.  The
previous version of :func:`get_connectors_data` returned static placeholder
information.  It now inspects the connector constructors and configuration to
return real metadata about each connector.
"""

import inspect
import pkgutil
import importlib
import os
from typing import Any, Dict, List, Optional

from app.core.config import get_settings, Settings

# Import BaseConnector for subclass checks
from .base_connector import BaseConnector

# Registry of available connectors keyed by their identifier.
connector_classes: Dict[str, type] = {}


def _discover_connectors() -> None:
    """Populate :data:`connector_classes` by scanning the package."""

    package = __name__.rsplit(".", 1)[0]
    package_path = os.path.dirname(__file__)
    for _, mod_name, _ in pkgutil.iter_modules([package_path]):
        if not mod_name.endswith("_connector"):
            continue
        module = importlib.import_module(f"{package}.{mod_name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseConnector) and obj is not BaseConnector:
                connector_classes[obj.id] = obj


_discover_connectors()


def get_connector(connector_name: str, config: Optional[Dict[str, Any]] = None) -> BaseConnector:
    """Return an instantiated connector."""

    if connector_name not in connector_classes:
        raise ValueError(f"Invalid connector name: {connector_name}")

    connector_class = connector_classes[connector_name]

    if config is None:
        settings = get_settings()
        signature = inspect.signature(connector_class.__init__)
        kwargs: Dict[str, Any] = {}
        for param in signature.parameters.values():
            if param.name == "self":
                continue
            setting_name = f"{connector_name}_{param.name}"
            kwargs[param.name] = getattr(settings, setting_name, None)
    else:
        kwargs = config

    return connector_class(**kwargs)


def get_connectors_data() -> List[Dict[str, Any]]:
    """Return metadata about all available connectors.

    The configuration values are inspected to determine whether each connector
    is enabled.  No network calls are made, so the ``status`` field simply
    reflects whether the connector has been configured.
    """

    settings = get_settings()
    connectors_data: List[Dict[str, Any]] = []

    if settings.connectors:
        for item in settings.connectors:
            name = item.get("type")
            connector_cls = connector_classes.get(name)
            if not connector_cls:
                continue
            signature = inspect.signature(connector_cls.__init__)
            fields = [p.name for p in signature.parameters.values() if p.name != "self"]
            configured = all(
                item.get(f) not in (None, "", f"your_{name}_{f}") for f in fields
            )
            connectors_data.append(
                {
                    "id": connector_cls.id,
                    "name": connector_cls.name,
                    "status": "configured" if configured else "missing_config",
                    "fields": fields,
                    "last_message_sent": None,
                    "enabled": configured,
                }
            )
    else:
        for name, connector_cls in connector_classes.items():
            signature = inspect.signature(connector_cls.__init__)
            fields = [p.name for p in signature.parameters.values() if p.name != "self"]

            configured = True
            for field in fields:
                setting_name = f"{name}_{field}"
                value = getattr(settings, setting_name, None)
                if value in (None, "", f"your_{setting_name}"):
                    configured = False
            connectors_data.append(
                {
                    "id": connector_cls.id,
                    "name": connector_cls.name,
                    "status": "configured" if configured else "missing_config",
                    "fields": fields,
                    "last_message_sent": None,
                    "enabled": configured,
                }
            )

    return connectors_data


def _is_configured(name: str, settings: Settings, config: Optional[Dict[str, Any]] = None) -> bool:
    """Return ``True`` if the connector ``name`` is fully configured."""

    if name not in connector_classes:
        raise ValueError(f"Invalid connector name: {name}")

    connector_cls = connector_classes[name]
    signature = inspect.signature(connector_cls.__init__)
    if config is None:
        for param in signature.parameters.values():
            if param.name == "self":
                continue
            if param.default is not inspect._empty and param.default is None:
                continue
            setting_name = f"{name}_{param.name}"
            value = getattr(settings, setting_name, None)
            if value in (None, "") or str(value).startswith("your_"):
                return False
    else:
        for param in signature.parameters.values():
            if param.name == "self":
                continue
            if param.default is not inspect._empty and param.default is None:
                continue
            value = config.get(param.name)
            if value in (None, "") or str(value).startswith("your_"):
                return False
    return True


def get_configured_connectors() -> Dict[str, List[BaseConnector]]:
    """Return mapping of configured connector instances keyed by type."""

    settings = get_settings()
    configured: Dict[str, List[BaseConnector]] = {}

    if settings.connectors:
        for item in settings.connectors:
            name = item.get("type")
            config = {k: v for k, v in item.items() if k != "type"}
            if not _is_configured(name, settings, config):
                continue
            try:
                conn = get_connector(name, config)
            except Exception:  # pragma: no cover
                continue
            configured.setdefault(name, []).append(conn)
    else:
        for name in connector_classes:
            if _is_configured(name, settings):
                configured.setdefault(name, []).append(get_connector(name))

    return configured

