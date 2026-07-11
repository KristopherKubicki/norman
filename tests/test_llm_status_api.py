from app.services.llm_runtime import record_llm_success


def test_llm_status_endpoint_returns_runtime_payload(test_app, monkeypatch):
    import app.app_routes as app_routes

    monkeypatch.setattr(
        app_routes,
        "get_mesh_overview",
        lambda timeout_seconds=2: {
            "schema": "norman.norllama.mesh.v1",
            "status": "ok",
            "healthy_worker_count": 2,
            "worker_count": 3,
        },
    )
    monkeypatch.setattr(
        app_routes,
        "build_warm_policy",
        lambda mesh=None: {
            "schema": "norman.norllama.warm-policy.v1",
            "route_posture": "ready",
        },
    )
    monkeypatch.setattr(
        app_routes,
        "fetch_tool_activity",
        lambda limit=200, timeout_seconds=2: {
            "schema": "norman.norllama.tool-activity.v1",
            "status": "active",
            "tool_call_count": 1,
            "latest_tool_call": {"capability": "embed"},
        },
    )
    record_llm_success(
        provider_slot="backup",
        provider_kind="openai_compatible",
        active_model="qwen3:latest",
        fallback_reason="primary unavailable",
        provider_label="Backup",
    )
    response = test_app.get("/api/llm/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "backup_online"
    assert payload["fallback_active"] is True
    assert payload["active_model"] == "qwen3:latest"
    assert "providers" in payload
    assert payload["norllama_mesh"]["status"] == "ok"
    assert payload["norllama_mesh"]["healthy_worker_count"] == 2
    assert payload["norllama_warm_policy"]["route_posture"] == "ready"
    assert payload["norllama_tool_activity"]["tool_call_count"] == 1
    assert (
        payload["norllama_tool_activity"]["latest_tool_call"]["capability"] == "embed"
    )


def test_llm_mesh_endpoint_returns_norllama_mesh(test_app, monkeypatch):
    import app.app_routes as app_routes

    monkeypatch.setattr(
        app_routes,
        "get_mesh_overview",
        lambda force_refresh=False, timeout_seconds=2: {
            "schema": "norman.norllama.mesh.v1",
            "status": "degraded",
            "worker_count": 3,
            "healthy_worker_count": 2,
            "workers": [{"id": "spark-150", "reachable": True}],
        },
    )

    response = test_app.get("/api/llm/mesh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "norman.norllama.mesh.v1"
    assert payload["status"] == "degraded"
    assert payload["workers"][0]["id"] == "spark-150"


def test_llm_warm_policy_endpoint_returns_policy(test_app, monkeypatch):
    import app.app_routes as app_routes

    monkeypatch.setattr(
        app_routes,
        "build_warm_policy",
        lambda: {
            "schema": "norman.norllama.warm-policy.v1",
            "route_posture": "prefetch_or_wait",
        },
    )

    response = test_app.get("/api/llm/warm-policy")

    assert response.status_code == 200
    assert response.json()["route_posture"] == "prefetch_or_wait"


def test_llm_tool_activity_endpoint_returns_filtered_activity(test_app, monkeypatch):
    import app.app_routes as app_routes

    monkeypatch.setattr(
        app_routes,
        "fetch_tool_activity",
        lambda limit=200, timeout_seconds=2: {
            "schema": "norman.norllama.tool-activity.v1",
            "status": "active",
            "tool_call_count": 2,
            "capability_counts": {"embed": 1, "rerank": 1},
            "latest_tool_call": {"capability": "embed"},
            "items": [],
        },
    )

    response = test_app.get("/api/llm/tool-activity?limit=25")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "norman.norllama.tool-activity.v1"
    assert payload["capability_counts"] == {"embed": 1, "rerank": 1}


def test_llm_warm_policy_prefetch_defaults_to_dry_run(test_app, monkeypatch):
    import app.app_routes as app_routes

    monkeypatch.setattr(
        app_routes,
        "apply_warm_policy",
        lambda dry_run=True, prefetch_limit=None, priority="background": {
            "schema": "norman.norllama.warm-apply.v1",
            "dry_run": dry_run,
            "prefetch_limit": prefetch_limit,
            "priority": priority,
        },
    )

    response = test_app.post(
        "/api/llm/warm-policy/prefetch",
        json={"prefetch_limit": 2, "priority": "background"},
    )

    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert response.json()["prefetch_limit"] == 2


def test_llm_ping_targets_endpoint_returns_public_targets(test_app, monkeypatch):
    import app.app_routes as app_routes

    monkeypatch.setattr(
        app_routes,
        "list_model_ping_targets",
        lambda: [
            {
                "id": "local-qwen",
                "name": "Local Qwen",
                "provider": "openai_compatible",
                "model": "qwen3:8b",
                "configured": True,
            }
        ],
    )

    response = test_app.get("/api/llm/ping/targets")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "local-qwen"


def test_llm_ping_endpoint_runs_model_ping(test_app, monkeypatch):
    import app.app_routes as app_routes

    async def fake_ping_model_targets(target_id=""):
        return {
            "count": 1,
            "ok": 1,
            "warn": 0,
            "error": 0,
            "items": [{"id": target_id or "all", "status": "ok"}],
        }

    monkeypatch.setattr(app_routes, "ping_model_targets", fake_ping_model_targets)

    response = test_app.post("/api/llm/ping", json={"target_id": "local-qwen"})

    assert response.status_code == 200
    assert response.json()["items"][0] == {"id": "local-qwen", "status": "ok"}
