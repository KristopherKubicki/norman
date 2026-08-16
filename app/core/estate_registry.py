from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_REGISTRY_ENV = "NORMAN_MODEL_ROLE_CONFIG"
LEGACY_MODEL_REGISTRY_ENV = "NORMAN_NORLLAMA_MODEL_ROLE_CONFIG"
TOPOLOGY_REGISTRY_ENV = "NORMAN_FLEET_TOPOLOGY_CONFIG"
DEFAULT_MODEL_REGISTRY_PATH = REPO_ROOT / "config/norllama/model_roles.json"
DEFAULT_TOPOLOGY_REGISTRY_PATH = REPO_ROOT / "config/fleet/topology.json"
ROLE_ORDER = ("resident", "economy", "authority", "frontier")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"registry must contain an object: {path}")
    return payload


@lru_cache(maxsize=4)
def load_model_registry(path: str = "") -> dict[str, Any]:
    registry_path = Path(
        path
        or os.getenv(MODEL_REGISTRY_ENV)
        or os.getenv(LEGACY_MODEL_REGISTRY_ENV)
        or DEFAULT_MODEL_REGISTRY_PATH
    )
    payload = _load_json(registry_path)
    if payload.get("schema") != "norman.norllama.model-roles.v1":
        raise ValueError("unsupported Norllama model registry schema")
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        raise ValueError("Norllama model registry is missing roles")
    for role in ROLE_ORDER:
        row = roles.get(role)
        if not isinstance(row, dict) or not str(row.get("model") or "").strip():
            raise ValueError(f"Norllama model registry is missing {role}")
    return payload


@lru_cache(maxsize=4)
def load_fleet_topology(path: str = "") -> dict[str, Any]:
    registry_path = Path(
        path or os.getenv(TOPOLOGY_REGISTRY_ENV) or DEFAULT_TOPOLOGY_REGISTRY_PATH
    )
    payload = _load_json(registry_path)
    if payload.get("schema") != "norman.fleet-topology.v1":
        raise ValueError("unsupported Norman fleet topology schema")
    if not isinstance(payload.get("workers"), dict):
        raise ValueError("Norman fleet topology is missing workers")
    if not isinstance(payload.get("hosts"), dict):
        raise ValueError("Norman fleet topology is missing hosts")
    return payload


def model_role(role: str) -> dict[str, Any]:
    row = load_model_registry()["roles"].get(str(role or "").strip().lower())
    return dict(row) if isinstance(row, dict) else {}


def model_for_role(role: str) -> str:
    return str(model_role(role).get("model") or "").strip()


def default_cloud_model() -> str:
    return model_for_role("authority")


def available_cloud_models() -> list[str]:
    models = [
        model_for_role(role)
        for role in ("economy", "authority", "frontier")
        if model_for_role(role)
    ]
    compatibility = load_model_registry().get("models")
    if isinstance(compatibility, dict):
        models.extend(
            str(model_id)
            for model_id, raw in compatibility.items()
            if isinstance(raw, dict)
            and model_capability(str(model_id), "bot_selectable", False)
        )
    return list(dict.fromkeys(models))


def resident_model() -> str:
    return model_for_role("resident")


def resident_client_endpoint() -> str:
    row = model_role("resident")
    endpoints = row.get("client_endpoints") or row.get("endpoints") or []
    return str(endpoints[0] if endpoints else "").strip()


def model_row(model: str) -> dict[str, Any]:
    requested = str(model or "").strip().lower()
    for role in ROLE_ORDER:
        row = model_role(role)
        identifiers = {
            str(row.get("model") or "").strip().lower(),
            *{
                str(alias or "").strip().lower()
                for alias in row.get("aliases") or []
            },
        }
        if requested in identifiers:
            return row
    models = load_model_registry().get("models")
    if isinstance(models, dict):
        for model_id, raw in models.items():
            row = raw if isinstance(raw, dict) else {}
            identifiers = {
                str(model_id or "").strip().lower(),
                *{
                    str(alias or "").strip().lower()
                    for alias in row.get("aliases") or []
                },
            }
            if requested in identifiers:
                return {"model": str(model_id), **row}
    return {}


def model_capability(model: str, name: str, default: Any = None) -> Any:
    capabilities = model_row(model).get("capabilities")
    if not isinstance(capabilities, dict):
        return default
    return capabilities.get(name, default)


def pricing_for_model(
    model: str,
    *,
    channel: str = "openai_direct",
) -> dict[str, float] | None:
    pricing = model_row(model).get("pricing_usd_per_1m")
    row = pricing.get(channel) if isinstance(pricing, dict) else None
    if not isinstance(row, dict):
        return None
    try:
        return {
            key: float(row[key])
            for key in ("input", "cached_input", "output")
        }
    except (KeyError, TypeError, ValueError):
        return None


def _endpoint_host(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    parsed = urlsplit(clean if "://" in clean else f"//{clean}")
    return str(parsed.hostname or "").strip().lower()


def worker_id_from_endpoint(value: str) -> str:
    host = _endpoint_host(value)
    if not host:
        return ""
    for worker_id, raw in load_fleet_topology()["workers"].items():
        row = raw if isinstance(raw, dict) else {}
        identities = {
            str(row.get("address") or "").strip().lower(),
            *{
                str(alias or "").strip().lower()
                for alias in row.get("aliases") or []
            },
        }
        if host in identities:
            return str(worker_id)
    return ""


def host_realm_for_route(value: str) -> str:
    host = _endpoint_host(value)
    if not host:
        return ""
    for raw in load_fleet_topology()["hosts"].values():
        row = raw if isinstance(raw, dict) else {}
        identities = {
            str(row.get("address") or "").strip().lower(),
            *{
                str(alias or "").strip().lower()
                for alias in row.get("aliases") or []
            },
        }
        if host in identities:
            return str(row.get("realm") or "").strip()
    return ""


def topology_section(name: str) -> Mapping[str, Any]:
    row = load_fleet_topology().get(name)
    return row if isinstance(row, dict) else {}


def mesh_worker_defaults() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for priority, (worker_id, raw) in enumerate(
        load_fleet_topology()["workers"].items(),
        start=1,
    ):
        row = raw if isinstance(raw, dict) else {}
        address = str(row.get("address") or "").strip()
        port = int(row.get("gateway_port") or 0)
        if not address or not port:
            continue
        rows.append(
            {
                "id": str(worker_id),
                "name": str(row.get("name") or worker_id),
                "role": str(row.get("role") or "production"),
                "base_url": f"http://{address}:{port}",
                "memory_gb": int(row.get("memory_gb") or 0),
                "priority": priority,
            }
        )
    return rows
