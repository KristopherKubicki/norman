from __future__ import annotations

from app.services.console_runtime.adapters import norllama as norllama_adapter
from app.services.console_runtime.types import ModelRequest
from app.services.norllama.types import NorllamaRoute


def test_route_authority_headers_separate_policy_and_request_eligibility():
    request = ModelRequest(
        messages=[{"role": "user", "content": "canary"}],
        metadata={
            "route_lock": True,
            "route_policy": {
                "route_lock": True,
                "model": "qwen3.6:27b",
            },
        },
    )
    route = NorllamaRoute(
        lane="norllama_chat",
        provider="norllama",
        provider_kind="norllama",
        capability="chat",
        model="qwen3.6:27b",
        attribution={
            "model_selection": {
                "source": "explicit_route_lock",
                "production_route_eligible": False,
            }
        },
    )

    headers = norllama_adapter._route_authority_headers(
        request,
        route,
        {"production_route_eligible": True},
    )

    assert headers["X-Norman-Route-Lock"] == "1"
    assert headers["X-Norman-Route-Authority"] == "explicit_route_lock"
    assert headers["X-Norman-Policy-Production-Routes-Allowed"] == "1"
    assert headers["X-Norman-Request-Production-Eligible"] == "0"
