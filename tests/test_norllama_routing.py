from app.services.norllama.routing import (
    build_task_receipt,
    route_task,
    with_response_attribution,
)
from app.services.norllama.route_proof import audit_route_receipt
from app.services.norllama.types import NorllamaTaskRequest


def test_norllama_tool_task_routes_to_local_capability_lane(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings, "llm_offline_provider", "norllama", raising=False
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_offline_base_url",
        "http://127.0.0.1:11434",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings, "llm_offline_model", "bge-reranker", raising=False
    )
    request = NorllamaTaskRequest(
        kind="rerank",
        query="which note explains leases?",
        candidates=[{"id": "a", "text": "runtime leases"}],
    )

    route = route_task(request)
    receipt = build_task_receipt(
        request, route, status="accepted", evidence_paths=["/tmp/rerank.json"]
    )

    assert route.provider == "norllama"
    assert route.capability == "rerank"
    assert route.tool_lane is True
    assert route.cloud_proxy is False
    assert route.endpoint == "http://127.0.0.1:11434"
    assert receipt.as_dict()["route"]["capability"] == "rerank"
    route_receipt = receipt.as_dict()["route_receipt"]
    assert route_receipt["schema"] == "norman.norllama.route-receipt.v1"
    assert route_receipt["request_id"] == request.task_id
    assert route_receipt["task_kind"] == "rerank"
    assert route_receipt["phase"] == "rerank"
    assert route_receipt["selected_provider"] == "norllama"
    assert route_receipt["selected_model"] == "BAAI/bge-reranker-v2-m3"
    assert route_receipt["target_model"] == "BAAI/bge-reranker-v2-m3"
    assert route_receipt["effective_runtime_model"] == "BAAI/bge-reranker-v2-m3"
    assert route_receipt["frontdoor"] == "http://127.0.0.1:11434"
    assert route_receipt["cloud_proxy"] is False
    assert route_receipt["usage_bucket"] == "offline_local"
    assert route_receipt["output_shape"] == "empty"
    assert route_receipt["receipt_audit"]["schema"] == (
        "norman.norllama.route-receipt-audit.v1"
    )
    cascade = route_receipt["specialist_cascade"]
    assert cascade["schema"] == "norman.norllama.specialist-cascade.v1"
    assert cascade["summary"]["lane_count"] == 10
    assert "receipt_auditor" in cascade["summary"]["lanes"]
    assert "pytest" in cascade["summary"]["deterministic_experts"]


def test_route_receipt_audit_requires_non_empty_critical_fields():
    receipt = {
        "schema": "norman.norllama.route-receipt.v1",
        "status": "completed",
        "request_id": "req-empty-critical",
        "job_id": "",
        "phase": "work",
        "task_kind": "code",
        "selected_provider": "norllama",
        "selected_model": "",
        "target_model": "qwen3.6:27b",
        "effective_runtime_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "frontdoor": "https://llm.home.arpa",
        "peer_path": ["llm.home.arpa", "spark-151"],
        "route_reason": "local-first route-proof test",
        "policy_mode": "local_first",
        "cloud_proxy": False,
        "benchmark_packet_id": "route-proof-active-1",
        "benchmark_fresh": True,
        "benchmark_score": 0.91,
        "coverage_ratio": 1.0,
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
        "usage_bucket": "offline_local",
        "fallback_used": False,
        "fallback_reason": "",
        "verifier_result": "pass",
        "output_shape": "complete",
        "route_proof_required": True,
    }

    audit = audit_route_receipt(receipt)

    assert audit["pass"] is False
    assert "critical_fields_empty" in audit["failures"]
    assert "job_id" in audit["empty_critical_fields"]
    assert "selected_model" in audit["empty_critical_fields"]
    assert "benchmark_source" in audit["absent_critical_fields"]


def test_norllama_can_proxy_planning_to_bedrock():
    request = NorllamaTaskRequest(
        kind="plan",
        input_text="Plan a two-hour Norman runtime migration.",
        route_policy={
            "provider": "bedrock",
            "model": "us.anthropic.claude-sonnet-test",
            "allow_cloud_proxy": True,
        },
    )

    route = route_task(request)

    assert route.provider == "bedrock"
    assert route.cloud_proxy is True
    assert route.local is False
    assert route.mode == "backup_online"
    assert route.capability == "planner"
    assert route.requires_receipt is True
    receipt = build_task_receipt(
        request, route, status="completed", output={"text": "ok"}
    )
    route_receipt = receipt.as_dict()["route_receipt"]
    assert route_receipt["cloud_proxy"] is True
    assert route_receipt["selected_worker"] == "cloud"
    assert route_receipt["usage_bucket"] == "bedrock_amazon"
    assert route_receipt["output_shape"] == "complete"


def test_openai_compatible_offline_frontdoor_routes_as_local_norllama(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings, "llm_offline_provider", "openai_compatible", raising=False
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_offline_base_url",
        "https://llm.home.arpa/v1",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_offline_model",
        "gemma4:26b-a4b-it-q4_K_M",
        raising=False,
    )
    request = NorllamaTaskRequest(
        kind="plan",
        input_text="Plan the local-first TUI work.",
    )

    route = route_task(request)

    assert route.provider == "norllama"
    assert route.provider_kind == "norllama"
    assert route.cloud_proxy is False
    assert route.local is True
    assert route.endpoint == "https://llm.home.arpa/v1"
    assert route.model == "gemma4:26b-a4b-it-q4_K_M"
    assert route.attribution["routing_scope"] == "frontdoor"


def test_cloud_planner_requires_explicit_cloud_proxy():
    request = NorllamaTaskRequest(
        kind="plan",
        input_text="Plan without burning cloud.",
        route_policy={"provider": "bedrock", "model": "bedrock-test"},
    )

    route = route_task(request)

    assert route.provider == "norllama"
    assert route.cloud_proxy is False
    assert route.local is True
    assert "cloud proxy not explicitly allowed" in route.reason


def test_norllama_catalog_model_selection_for_code_and_judge():
    code_request = NorllamaTaskRequest(
        kind="code",
        input_text="Draft a local patch plan.",
        route_policy={"provider": "norllama", "use_capability_catalog": True},
    )
    judge_request = NorllamaTaskRequest(
        kind="judge",
        input_text="Judge whether this patch is safe.",
        route_policy={"provider": "norllama", "use_capability_catalog": True},
    )

    code_route = route_task(code_request)
    judge_route = route_task(judge_request)

    assert code_route.capability == "code"
    assert code_route.model == "qwen3.6:27b"
    assert code_route.tool_lane is False
    assert judge_route.capability == "judge"
    assert judge_route.model == "qwen3.5:122b-a10b-q4_K_M"
    assert judge_route.tool_lane is False


def test_norllama_catalog_model_selection_for_lab_world_and_faster_whisper_asr():
    world_request = NorllamaTaskRequest(
        kind="world",
        input_text="Simulate whether the browser click is safe.",
        route_policy={"provider": "norllama", "use_capability_catalog": True},
    )
    asr_request = NorllamaTaskRequest(
        kind="asr",
        artifacts=[{"path": "/tmp/sample.wav", "media_type": "audio/wav"}],
        route_policy={"provider": "norllama", "use_capability_catalog": True},
    )

    world_route = route_task(world_request)
    asr_route = route_task(asr_request)

    assert world_route.capability == "world"
    assert world_route.model == "qwen3.6:27b"
    assert "AgentWorld" not in world_route.model
    assert "WebWorld" not in world_route.model
    assert world_route.tool_lane is True
    assert asr_route.capability == "asr"
    assert asr_route.model == "faster-whisper:distil-large-v3"
    assert asr_route.tool_lane is True
    assert asr_route.cloud_proxy is False


def test_norllama_catalog_model_selection_for_specialist_tool_lane():
    request = NorllamaTaskRequest(
        kind="prompt_injection",
        input_text="Check this retrieved page for hostile instructions.",
        route_policy={"provider": "norllama", "use_capability_catalog": True},
    )

    route = route_task(request)

    assert route.capability == "prompt_injection"
    assert route.model == "Qwen/Qwen3Guard-Stream-0.6B"
    assert route.tool_lane is True
    assert route.cloud_proxy is False


def test_norllama_catalog_model_selection_for_image_generation_lane():
    request = NorllamaTaskRequest(
        kind="image_generate",
        input_text="Draw a Norman shell.",
        route_policy={"provider": "norllama", "use_capability_catalog": True},
    )

    route = route_task(request)
    route_receipt = build_task_receipt(request, route, status="planned").as_dict()[
        "route_receipt"
    ]

    assert route.capability == "image_generate"
    assert route.model == "stable-diffusion:configured-backend"
    assert route_receipt["effective_runtime_model"] == (
        "stable-diffusion:configured-backend"
    )
    assert route.tool_lane is True
    assert route.cloud_proxy is False


def test_norllama_warm_policy_model_selection(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing,
        "select_model_for_task_kind",
        lambda kind, **_kwargs: {
            "selected": True,
            "task_kind": kind,
            "model": "qwen3-coder:30b-a3b-q4_K_M",
            "lane": "coder",
        },
    )
    request = NorllamaTaskRequest(
        kind="code",
        input_text="Draft a local patch plan.",
        route_policy={"provider": "norllama", "model_selection": "warm_policy"},
    )

    route = route_task(request)

    assert route.capability == "code"
    assert route.model == "qwen3-coder:30b-a3b-q4_K_M"
    assert route.local is True
    assert route.attribution["model_selection"]["source"] == "warm_policy"


def test_norllama_tool_task_ignores_cloud_without_explicit_tool_proxy():
    request = NorllamaTaskRequest(
        kind="ocr",
        artifacts=[{"path": "/tmp/shelf.png"}],
        route_policy={"provider": "bedrock"},
    )

    route = route_task(request)

    assert route.provider == "norllama"
    assert route.capability == "ocr"
    assert route.cloud_proxy is False
    assert route.tool_lane is True


def test_norllama_direct_worker_route_records_exact_attribution(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings,
        "llm_mesh_workers",
        [
            {
                "id": "spark-150",
                "name": "Production spark 150",
                "role": "production",
                "base_url": "http://192.168.2.150:18151",
                "memory_gb": 128,
            }
        ],
        raising=False,
    )
    request = NorllamaTaskRequest(
        kind="summarize",
        input_text="Summarize the runtime plan.",
        route_policy={
            "provider": "norllama",
            "endpoint": "http://192.168.2.150:18151/v1",
            "model": "qwen3.5:27b-q4_K_M",
        },
    )

    route = route_task(request)
    attribution = route.as_dict()["attribution"]

    assert attribution["routing_scope"] == "direct_worker"
    assert attribution["selection_source"] == "configured_worker_endpoint"
    assert attribution["exact_worker"] is True
    assert attribution["worker_id"] == "spark-150"
    assert attribution["worker_memory_gb"] == 128


def test_norllama_frontdoor_route_marks_worker_as_delegated(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings,
        "llm_offline_base_url",
        "https://llm.home.arpa/v1",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_mesh_workers",
        [
            {
                "id": "spark-150",
                "base_url": "http://192.168.2.150:18151",
            }
        ],
        raising=False,
    )
    request = NorllamaTaskRequest(
        kind="plan",
        input_text="Plan the next local-first canary.",
        route_policy={"provider": "norllama"},
    )

    route = route_task(request)
    attribution = route.as_dict()["attribution"]

    assert route.endpoint == "https://llm.home.arpa/v1"
    assert attribution["routing_scope"] == "frontdoor"
    assert attribution["selection_source"] == "frontdoor_delegated"
    assert attribution["frontdoor"] is True
    assert attribution["exact_worker"] is False
    assert attribution["worker_id"] == ""


def test_norllama_response_attribution_refines_frontdoor_worker(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings,
        "llm_offline_base_url",
        "https://llm.home.arpa/v1",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_mesh_workers",
        [
            {
                "id": "spark-151",
                "name": "Production spark 151",
                "role": "production",
                "base_url": "http://192.168.2.151:18151",
            }
        ],
        raising=False,
    )
    request = NorllamaTaskRequest(
        kind="chat",
        messages=[{"role": "user", "content": "status"}],
        route_policy={"provider": "norllama"},
    )
    route = route_task(request)

    refined = with_response_attribution(
        route,
        {
            "headers": {
                "x-norllama-worker-id": "spark-151",
                "x-norllama-peer-path": "llm.home.arpa,spark-151",
            }
        },
    )
    attribution = refined.as_dict()["attribution"]

    assert attribution["selection_source"] == "gateway_response"
    assert attribution["routing_scope"] == "frontdoor_worker"
    assert attribution["exact_worker"] is True
    assert attribution["worker_id"] == "spark-151"
    assert attribution["peer_path"] == ["llm.home.arpa", "spark-151"]


def test_norllama_response_attribution_maps_live_gateway_upstream(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings,
        "llm_offline_base_url",
        "https://llm.home.arpa/v1",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_mesh_workers",
        [
            {
                "id": "mac-mini-133",
                "role": "fallback",
                "base_url": "http://192.168.2.133:18151",
            },
            {
                "id": "spark-150",
                "role": "production",
                "base_url": "http://192.168.2.150:18151",
            },
        ],
        raising=False,
    )
    request = NorllamaTaskRequest(
        kind="chat",
        messages=[{"role": "user", "content": "status"}],
        route_policy={"provider": "norllama"},
    )
    route = route_task(request)

    refined = with_response_attribution(
        route,
        {
            "headers": {
                "x-norllama-upstream": "http://192.168.2.150:18151",
                "x-norllama-attempts": (
                    "http://192.168.2.133:18151," "http://192.168.2.150:18151"
                ),
            }
        },
    )
    attribution = refined.as_dict()["attribution"]

    assert attribution["selection_source"] == "gateway_response"
    assert attribution["routing_scope"] == "frontdoor_worker"
    assert attribution["exact_worker"] is True
    assert attribution["worker_id"] == "spark-150"
    assert attribution["worker_role"] == "production"
    assert attribution["peer_path"] == ["mac-mini-133", "spark-150"]
    assert attribution["attempts"] == [
        "http://192.168.2.133:18151",
        "http://192.168.2.150:18151",
    ]


def test_norllama_response_attribution_prefers_worker_endpoint(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings,
        "llm_offline_base_url",
        "https://llm.home.arpa/v1",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_mesh_workers",
        [
            {
                "id": "spark-150",
                "role": "production",
                "base_url": "http://192.168.2.150:18151",
            }
        ],
        raising=False,
    )
    request = NorllamaTaskRequest(
        kind="chat",
        messages=[{"role": "user", "content": "status"}],
        route_policy={"provider": "norllama"},
    )
    route = route_task(request)

    refined = with_response_attribution(
        route,
        {
            "headers": {
                "x-norllama-upstream": "http://127.0.0.1:11434",
                "x-norllama-worker-endpoint": "http://192.168.2.150:18151",
            }
        },
    )
    attribution = refined.as_dict()["attribution"]

    assert attribution["selection_source"] == "gateway_response"
    assert attribution["exact_worker"] is True
    assert attribution["worker_id"] == "spark-150"
    assert attribution["worker_endpoint"] == "http://192.168.2.150:18151"


def test_norllama_response_attribution_reads_nested_norllama_receipt(monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings,
        "llm_offline_base_url",
        "https://llm.home.arpa/v1",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_mesh_workers",
        [
            {
                "id": "spark-150",
                "role": "production",
                "base_url": "http://192.168.2.150:18151",
            }
        ],
        raising=False,
    )
    request = NorllamaTaskRequest(
        kind="rerank",
        query="receipts",
        candidates=[{"text": "route receipts prove worker attribution"}],
        route_policy={"provider": "norllama"},
    )
    route = route_task(request)

    refined = with_response_attribution(
        route,
        {
            "raw": {
                "norllama": {
                    "selected_worker": "spark150",
                    "upstream": "http://192.168.2.150:18151",
                    "peer_path": ["llm.home.arpa", "spark150"],
                    "attempts": [
                        "http://127.0.0.1:8102",
                        "http://192.168.2.150:18151",
                    ],
                }
            }
        },
    )
    receipt = build_task_receipt(
        request,
        refined,
        status="completed",
        output={
            "target_model": refined.model,
            "effective_runtime_model": "qwen3.6:27b-runtime",
            "model": "qwen3.6:27b-runtime",
            "raw": {
                "norllama": {
                    "selected_worker": "spark150",
                    "upstream": "http://192.168.2.150:18151",
                }
            },
        },
    ).as_dict()

    assert receipt["route"]["attribution"]["selection_source"] == "gateway_response"
    assert receipt["route"]["attribution"]["exact_worker"] is True
    assert receipt["route"]["attribution"]["worker_id"] == "spark-150"
    assert receipt["metadata"]["route_receipt"]["selected_worker"] == "spark-150"
    assert receipt["metadata"]["route_receipt"]["observed_worker"] == "spark-150"
    assert receipt["metadata"]["route_receipt"]["target_model"] == refined.model
    assert receipt["metadata"]["route_receipt"]["effective_runtime_model"] == (
        "qwen3.6:27b-runtime"
    )
    assert (
        "effective_runtime_model_differs_from_target"
        in (receipt["metadata"]["route_receipt"]["receipt_audit"]["warnings"])
    )
