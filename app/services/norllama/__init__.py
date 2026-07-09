"""Norllama task routing and provider proxy helpers."""

from app.services.norllama.capability_catalog import (
    catalog_payload,
    default_model_for_task_kind,
    warm_policy_recommendations,
)
from app.services.norllama.gateway import invoke_text_chat
from app.services.norllama.proxy import NorllamaProxy, invoke_task
from app.services.norllama.routing import (
    CLOUD_PROXY_PROVIDERS,
    NORLLAMA_PROVIDER_ALIASES,
    TOOL_TASK_KINDS,
    build_task_receipt,
    route_task,
)
from app.services.norllama.route_proof import (
    audit_route_receipt,
    receipt_completion_gate_passes,
)
from app.services.norllama.specialist_lanes import (
    specialist_lane_proof_from_warm_policy,
    specialist_registry_payload,
)
from app.services.norllama.types import (
    NorllamaReceipt,
    NorllamaRoute,
    NorllamaTaskKind,
    NorllamaTaskRequest,
)

__all__ = [
    "CLOUD_PROXY_PROVIDERS",
    "NORLLAMA_PROVIDER_ALIASES",
    "TOOL_TASK_KINDS",
    "catalog_payload",
    "default_model_for_task_kind",
    "warm_policy_recommendations",
    "NorllamaReceipt",
    "NorllamaRoute",
    "NorllamaTaskKind",
    "NorllamaTaskRequest",
    "NorllamaProxy",
    "build_task_receipt",
    "audit_route_receipt",
    "invoke_text_chat",
    "invoke_task",
    "receipt_completion_gate_passes",
    "route_task",
    "specialist_lane_proof_from_warm_policy",
    "specialist_registry_payload",
]
