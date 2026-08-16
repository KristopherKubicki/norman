from __future__ import annotations

from pathlib import Path

from app.core.estate_registry import (
    available_cloud_models,
    default_cloud_model,
    host_realm_for_route,
    load_fleet_topology,
    load_model_registry,
    mesh_worker_defaults,
    model_capability,
    pricing_for_model,
    resident_client_endpoint,
    resident_model,
    worker_id_from_endpoint,
)
from app.services.norllama.route_policy_artifact import (
    generate_route_policy_artifact,
    validate_route_policy_artifact,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_model_registry_drives_current_roles_capabilities_and_prices() -> None:
    registry = load_model_registry()

    assert registry["schema"] == "norman.norllama.model-roles.v1"
    assert resident_model() == registry["roles"]["resident"]["model"]
    assert resident_client_endpoint() == "https://llm.home.arpa/resident"
    assert default_cloud_model() == registry["roles"]["authority"]["model"]
    assert available_cloud_models()[:3] == [
        registry["roles"]["economy"]["model"],
        registry["roles"]["authority"]["model"],
        registry["roles"]["frontier"]["model"],
    ]
    assert "gpt-5-mini" in available_cloud_models()
    assert model_capability(resident_model(), "native_non_thinking_bridge") is True
    assert pricing_for_model(
        registry["roles"]["economy"]["model"],
        channel="openai_direct",
    ) == {"input": 0.2, "cached_input": 0.02, "output": 1.2}


def test_fleet_topology_drives_workers_realms_and_mesh_defaults() -> None:
    topology = load_fleet_topology()
    workers = mesh_worker_defaults()

    assert topology["schema"] == "norman.fleet-topology.v1"
    assert worker_id_from_endpoint("http://192.168.2.151:18161") == "spark-151"
    assert worker_id_from_endpoint("http://spark-150:18151") == "spark-150"
    assert host_realm_for_route("https://toy-box.home.arpa") == "Personal"
    assert host_realm_for_route("http://192.168.2.147:8781") == "Work"
    assert {row["id"] for row in workers} == set(topology["workers"])


def test_generated_route_policy_uses_runtime_lifecycle_not_compiled_dates() -> None:
    artifact = generate_route_policy_artifact()
    validation = validate_route_policy_artifact(artifact)

    assert artifact["issued_at"] == artifact["compiled_at"]
    assert artifact["expires_at"] > artifact["issued_at"]
    assert validation["integrity_valid"] is True
    assert validation["default_route_allowed"] is True


def test_serving_paths_do_not_reintroduce_upgrade_sensitive_literals() -> None:
    forbidden_by_path = {
        "app/core/config.py": ("gpt-5.5", "192.168.2.151"),
        "app/models/bot.py": ("gpt-5.5",),
        "app/schemas/bot.py": ("gpt-5.5",),
        "app/app_routes.py": ("gpt-5.5",),
        "app/services/norllama/gateway.py": (
            "qwen3.5:",
            "qwen3.6:",
            "qwen3.8:",
        ),
        "app/services/norllama/capability_catalog.py": (
            "qwen3-coder:30b-a3b-q4_K_M",
        ),
        "app/services/norllama/route_policy.py": (
            "2026-08-11",
            "manual-only-qwen3.5",
            "gemma4-or-qwen",
        ),
        "app/services/prompt_provider_facade.py": (
            "192.168.2.150",
            "192.168.2.151",
        ),
        "app/services/norllama/route_outcomes.py": (
            "192.168.2.150",
            "192.168.2.151",
        ),
        "app/static/js/home.js": ("192.168.2.146", "192.168.2.147"),
        "app/static/js/systems.js": ("192.168.2.146", "192.168.2.147"),
        "scripts/ticket_token_cost_ledger.py": (
            '"gpt-5.5":',
            '"openai.gpt-5.5":',
        ),
        "scripts/norllama/refresh_fleet_route_policy.py": (
            "192.168.2.133",
            "192.168.2.150",
            "192.168.2.151",
        ),
        "scripts/norllama/fleet_health.py": (
            "192.168.2.133",
            "192.168.2.150",
            "192.168.2.151",
        ),
    }
    for relative, forbidden in forbidden_by_path.items():
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for literal in forbidden:
            assert literal not in source, f"{relative} contains {literal}"
