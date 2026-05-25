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
from typing import Any, Dict, List, Optional, get_args, get_origin, Union

from app.core.config import get_settings, Settings
from app.core.logging import setup_logger
from app.services.connector_oauth import oauth_capability

# Import BaseConnector for subclass checks
from .base_connector import BaseConnector

# Registry of available connectors keyed by their identifier.
connector_classes: Dict[str, type] = {}
logger = setup_logger(__name__)


def _discover_connectors() -> None:
    """Populate :data:`connector_classes` by scanning the package."""

    package = __name__.rsplit(".", 1)[0]
    package_path = os.path.dirname(__file__)
    for _, mod_name, _ in pkgutil.iter_modules([package_path]):
        if not mod_name.endswith("_connector"):
            continue
        try:
            module = importlib.import_module(f"{package}.{mod_name}")
        except Exception as exc:
            logger.warning("Skipping connector %s: %s", mod_name, exc)
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseConnector) and obj is not BaseConnector:
                connector_classes[obj.id] = obj


_discover_connectors()


def _resolve_expected_type(param: inspect.Parameter):
    annotation = param.annotation
    if annotation is inspect._empty:
        if param.default is not inspect._empty and param.default is not None:
            return type(param.default)
        return None

    origin = get_origin(annotation)
    if origin is Union:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            annotation = args[0]
            origin = get_origin(annotation)

    if origin in (list, List):
        return list
    if annotation in (bool, int, float, str):
        return annotation

    return None


def _coerce_parameter_value(param: inspect.Parameter, value: Any) -> Any:
    expected = _resolve_expected_type(param)
    if expected is None or value is None:
        return value

    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "y", "on"}:
                return True
            if lowered in {"0", "false", "no", "n", "off"}:
                return False
        return value

    if expected is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                try:
                    return int(stripped)
                except ValueError:
                    return value
        return value

    if expected is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                try:
                    return float(stripped)
                except ValueError:
                    return value
        return value

    if expected is list:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("[") and stripped.endswith("]"):
                return value
            return [part.strip() for part in value.split(",") if part.strip()]

    return value


def _connector_constructor_defaults(signature: inspect.Signature) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    for param in signature.parameters.values():
        if param.name in {"self", "config"}:
            continue
        if param.default is inspect._empty or param.default is None:
            continue
        if isinstance(param.default, (str, int, float, bool)):
            defaults[param.name] = param.default
    return defaults


def _connector_capabilities(connector_cls: type) -> Dict[str, Any]:
    supports_inbound = (
        connector_cls.listen_and_process is not BaseConnector.listen_and_process
    )
    supports_outbound = connector_cls.send_message is not BaseConnector.send_message
    supports_healthcheck = connector_cls.is_connected is not BaseConnector.is_connected
    supports_webhook_setup = hasattr(connector_cls, "set_webhook")
    has_queue_worker = True
    mode = "bidirectional"
    if supports_inbound and not supports_outbound:
        mode = "inbound_only"
    elif supports_outbound and not supports_inbound:
        mode = "outbound_only"

    return {
        "mode": mode,
        "supports_inbound": supports_inbound,
        "supports_outbound": supports_outbound,
        "supports_healthcheck": supports_healthcheck,
        "supports_webhook_setup": supports_webhook_setup,
        "has_queue_worker": has_queue_worker,
    }


def get_connector(
    connector_name: str, config: Optional[Dict[str, Any]] = None
) -> BaseConnector:
    """Return an instantiated connector."""

    if connector_name not in connector_classes:
        raise ValueError(f"Invalid connector name: {connector_name}")

    connector_class = connector_classes[connector_name]

    signature = inspect.signature(connector_class.__init__)
    valid_params = {p.name for p in signature.parameters.values() if p.name != "self"}

    if config is None:
        settings = get_settings()
        kwargs: Dict[str, Any] = {}
        for param in signature.parameters.values():
            if param.name == "self":
                continue
            setting_name = f"{connector_name}_{param.name}"
            value = getattr(settings, setting_name, None)
            kwargs[param.name] = _coerce_parameter_value(param, value)
    else:
        kwargs = {}
        for param_name, value in config.items():
            if param_name not in valid_params:
                continue
            param = signature.parameters.get(param_name)
            if param is None:
                continue
            kwargs[param_name] = _coerce_parameter_value(param, value)
        if "config" in valid_params:
            kwargs["config"] = config

    return connector_class(**kwargs)


def get_connectors_data() -> List[Dict[str, Any]]:
    """Return metadata about all available connectors.

    This endpoint is used by the UI to build connector forms. It should reflect
    the connector registry, not static configuration files.
    """

    settings = get_settings()
    connectors_data: List[Dict[str, Any]] = []
    configured_entries: Dict[str, List[Dict[str, Any]]] = {}
    if settings.connectors is not None:
        for item in settings.connectors:
            name = item.get("type")
            if not name:
                continue
            config = {k: v for k, v in item.items() if k != "type"}
            configured_entries.setdefault(name, []).append(config)

    for name, connector_cls in connector_classes.items():
        signature = inspect.signature(connector_cls.__init__)
        fields = [
            p.name
            for p in signature.parameters.values()
            if p.name not in {"self", "config"}
        ]
        defaults = _connector_constructor_defaults(signature)
        capabilities = _connector_capabilities(connector_cls)
        status = "missing_config"
        enabled = False
        if settings.connectors is not None:
            configs = configured_entries.get(name, [])
            if any(_is_configured(name, settings, config) for config in configs):
                enabled = True
                status = "down"
                for config in configs:
                    if not _is_configured(name, settings, config):
                        continue
                    try:
                        connector = get_connector(name, config)
                    except Exception:
                        continue
                    if (
                        getattr(connector, "is_connected", None)
                        and connector.is_connected()
                    ):
                        status = "up"
                        break
        else:
            if _is_configured(name, settings):
                enabled = True
                status = "down"
                try:
                    connector = get_connector(name)
                except Exception:
                    connector = None
                if connector and getattr(connector, "is_connected", None):
                    if connector.is_connected():
                        status = "up"
        connectors_data.append(
            {
                "id": connector_cls.id,
                "name": connector_cls.name,
                "status": status,
                "fields": fields,
                "defaults": defaults,
                "capabilities": capabilities,
                "last_message_sent": None,
                "enabled": enabled,
                "oauth": oauth_capability(connector_cls.id),
            }
        )
    return sorted(connectors_data, key=lambda item: item["name"].lower())


def _is_configured(
    name: str, settings: Settings, config: Optional[Dict[str, Any]] = None
) -> bool:
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

    if settings.connectors is not None:
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
