import json
import time

from app.services.norllama import warm_policy


def sample_mesh():
    return {
        "schema": "norman.norllama.mesh.v1",
        "status": "ok",
        "models": [
            "gemma4:26b-a4b-it-q4_K_M",
            "qwen3-coder:30b-a3b-q4_K_M",
            "gemma3:1b",
        ],
        "frontdoor": {"status": "ok", "reachable": True},
        "workers": [
            {
                "id": "mac-mini-133",
                "base_url": "http://192.168.2.133:18151",
                "role": "fallback",
                "memory_gb": 16,
                "reachable": True,
                "models": ["gemma3:1b", "gemma3:4b"],
                "active_models": ["gemma3:1b"],
            },
            {
                "id": "spark-150",
                "role": "production",
                "memory_gb": 128,
                "reachable": True,
                "models": [
                    "gemma4:26b-a4b-it-q4_K_M",
                    "qwen3-coder:30b-a3b-q4_K_M",
                ],
                "active_models": ["gemma4:26b-a4b-it-q4_K_M"],
            },
            {
                "id": "spark-151",
                "base_url": "http://192.168.2.151:18151",
                "role": "production",
                "memory_gb": 128,
                "reachable": True,
                "models": ["gemma4:31b"],
                "active_models": [],
            },
        ],
        "cache": {"status": "hit"},
    }


def sample_packet():
    return {
        "generated_at": "2026-07-05T23:32:27Z",
        "shareable_view": {
            "recommended_roles": [
                {
                    "lane_id": "specialist_board",
                    "model": "gemma4:26b-a4b-it-q4_K_M",
                    "profile": "gemma4_local",
                    "score": 0.8804,
                    "coverage_ratio": 1.0,
                    "use_for": "status writeups",
                    "guardrail": "Verify before final use.",
                },
                {
                    "lane_id": "packet_188_full",
                    "model": "qwen3-coder:30b-a3b-q4_K_M",
                    "profile": "qwen3coder30_local",
                    "score": 0.7853,
                    "coverage_ratio": 1.0,
                    "use_for": "code flow",
                    "guardrail": "Run tests.",
                },
                {
                    "lane_id": "weak_planner",
                    "model": "hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M",
                    "profile": "openfugu_local",
                    "score": 0.21,
                    "coverage_ratio": 1.0,
                    "use_for": "planner canary",
                    "guardrail": "Do not use weak plans.",
                },
            ]
        },
        "capability_contracts": [
            {
                "contract_id": "safety_privacy_classify",
                "default_model": "gemma4:31b",
                "default_profile": "gemma4_31_local",
                "status": "benchmark_backed",
                "best_weighted_score": 1.2,
                "guardrail": "Keep approvals.",
            }
        ],
    }


def catalog_mesh():
    return {
        "schema": "norman.norllama.mesh.v1",
        "status": "ok",
        "models": [
            "qwen3.6:35b-a3b-q4_K_M",
            "qwen3.6:27b",
            "qwen3.5:122b-a10b-q4_K_M",
            "bge-m3:latest",
            "Qwen/Qwen3-Reranker-0.6B",
            "Qwen/Qwen3Guard-Stream-0.6B",
            "faster-whisper:distil-large-v3",
            "faster-whisper:large-v3",
            "Qwen/Qwen-AgentWorld-35B-A3B",
            "Qwen/WebWorld-8B",
        ],
        "frontdoor": {"status": "ok", "reachable": True},
        "workers": [
            {
                "id": "mac-mini-133",
                "role": "fallback",
                "base_url": "http://192.168.2.133:18151",
                "memory_gb": 16,
                "reachable": True,
                "models": [
                    "Qwen/Qwen3-Reranker-0.6B",
                ],
                "active_models": ["Qwen/Qwen3-Reranker-0.6B"],
            },
            {
                "id": "spark-150",
                "role": "production",
                "base_url": "http://192.168.2.150:18151",
                "memory_gb": 128,
                "reachable": True,
                "models": [
                    "bge-m3:latest",
                    "Qwen/Qwen3Guard-Stream-0.6B",
                ],
                "active_models": ["bge-m3:latest", "Qwen/Qwen3Guard-Stream-0.6B"],
                "endpoints": [{"path": "/v1/safety/classify", "kind": "safety"}],
                "safety": {
                    "model": "Qwen/Qwen3Guard-Stream-0.6B",
                    "base_url": "http://192.168.2.150:8103",
                },
            },
            {
                "id": "spark-151",
                "role": "production",
                "base_url": "http://192.168.2.151:18151",
                "memory_gb": 128,
                "reachable": True,
                "models": [
                    "qwen3.6:35b-a3b-q4_K_M",
                    "qwen3.6:27b",
                    "qwen3.5:122b-a10b-q4_K_M",
                    "faster-whisper:distil-large-v3",
                    "Qwen/Qwen3Guard-Stream-0.6B",
                    "Qwen/Qwen-AgentWorld-35B-A3B",
                    "Qwen/WebWorld-8B",
                ],
                "active_models": [
                    "qwen3.6:35b-a3b-q4_K_M",
                    "Qwen/Qwen3Guard-Stream-0.6B",
                ],
                "endpoints": [{"path": "/v1/safety/classify", "kind": "safety"}],
                "safety": {
                    "model": "Qwen/Qwen3Guard-Stream-0.6B",
                    "base_url": "http://192.168.2.151:8103",
                },
            },
        ],
        "cache": {"status": "hit"},
    }


def asr_service_mesh():
    return {
        "schema": "norman.norllama.mesh.v1",
        "status": "ok",
        "models": [],
        "frontdoor": {
            "status": "ok",
            "reachable": True,
            "models": [],
            "endpoints": [
                {"path": "/v1/audio/transcriptions", "kind": "asr"},
                {"path": "/transcribe", "kind": "asr"},
            ],
        },
        "workers": [
            {
                "id": "mac-mini-133",
                "role": "fallback",
                "memory_gb": 16,
                "reachable": True,
                "models": [],
                "active_models": [],
                "capabilities": {
                    "endpoints": [{"path": "/v1/audio/transcriptions", "kind": "asr"}],
                    "contracts": [
                        {
                            "contract_id": "audio_diarize",
                            "dispatch": "transcribe_proxy",
                            "status": "pending_benchmark",
                        }
                    ],
                },
                "overview": {
                    "fleet": [
                        {
                            "selected_lanes": ["transcribe"],
                            "transcribe": {
                                "model": "faster-whisper:base",
                                "status": "ok",
                            },
                        }
                    ]
                },
            },
            {
                "id": "spark-150",
                "role": "production",
                "memory_gb": 128,
                "reachable": True,
                "models": [],
                "active_models": [],
            },
        ],
        "cache": {"status": "hit"},
    }


def gateway_asr_mesh():
    return {
        "schema": "norman.norllama.mesh.v1",
        "status": "ok",
        "models": [],
        "frontdoor": {
            "status": "ok",
            "reachable": True,
            "models": [],
            "endpoints": [{"path": "/v1/audio/transcriptions", "kind": "asr"}],
            "overview": {
                "routing": {"transcribe": "http://192.168.2.151:8095"},
                "fleet": [
                    {
                        "base_url": "http://127.0.0.1:8097",
                        "selected_lanes": ["transcribe"],
                        "transcribe": {
                            "model": "faster-whisper:base",
                            "status": "ok",
                        },
                    },
                    {
                        "base_url": "http://192.168.2.151:8095",
                        "selected_lanes": ["transcribe"],
                        "transcribe": {
                            "model": "distil-large-v3",
                            "status": "ok",
                        },
                    },
                ],
            },
        },
        "workers": [
            {
                "id": "mac-mini-133",
                "role": "fallback",
                "memory_gb": 16,
                "reachable": True,
                "models": [],
                "active_models": [],
                "endpoints": [{"path": "/v1/audio/transcriptions", "kind": "asr"}],
                "overview": {
                    "routing": {"transcribe": "http://192.168.2.151:8095"},
                    "fleet": [
                        {
                            "base_url": "http://127.0.0.1:8097",
                            "selected_lanes": ["transcribe"],
                            "transcribe": {
                                "model": "faster-whisper:base",
                                "status": "ok",
                            },
                        },
                        {
                            "base_url": "http://192.168.2.151:8095",
                            "selected_lanes": ["transcribe"],
                            "transcribe": {
                                "model": "distil-large-v3",
                                "status": "ok",
                            },
                        },
                    ],
                },
            },
            {
                "id": "spark-151",
                "role": "production",
                "memory_gb": 128,
                "reachable": True,
                "models": [],
                "active_models": [],
                "endpoints": [{"path": "/v1/audio/transcriptions", "kind": "asr"}],
                "overview": {
                    "routing": {"transcribe": "http://127.0.0.1:8095"},
                    "fleet": [
                        {
                            "base_url": "http://127.0.0.1:8095",
                            "selected_lanes": ["transcribe"],
                            "transcribe": {
                                "model": "distil-large-v3",
                                "status": "ok",
                            },
                        }
                    ],
                },
            },
        ],
        "cache": {"status": "hit"},
    }


def test_benchmark_recommendations_extract_shareable_and_contract_models():
    recommendations = warm_policy.benchmark_recommendations(sample_packet())

    assert [item["model"] for item in recommendations] == [
        "gemma4:26b-a4b-it-q4_K_M",
        "qwen3-coder:30b-a3b-q4_K_M",
        "hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M",
        "gemma4:31b",
    ]
    assert recommendations[0]["priority"] == "p0"
    assert recommendations[3]["priority"] == "p1"


def test_build_warm_policy_marks_active_prefetch_and_unavailable():
    policy = warm_policy.build_warm_policy(mesh=sample_mesh(), packet=sample_packet())

    by_model = {item["model"]: item for item in policy["recommendations"]}
    guardrails = policy["route_guardrails"]["lanes"]

    assert policy["schema"] == "norman.norllama.warm-policy.v1"
    assert policy["route_guardrails"]["schema"] == (
        "norman.norllama.route-guardrail-matrix.v1"
    )
    assert policy["route_posture"] == "ready"
    assert policy["residency_posture"] == "warm"
    assert by_model["gemma4:26b-a4b-it-q4_K_M"]["action"] == "keep_warm"
    assert (
        by_model["gemma4:26b-a4b-it-q4_K_M"]["route_guardrail"]["authority"]
        == "preflight_or_draft"
    )
    assert by_model["qwen3-coder:30b-a3b-q4_K_M"]["action"] == "prefetch"
    assert by_model["qwen3-coder:30b-a3b-q4_K_M"]["target_worker"] == "spark-150"
    assert (
        by_model["hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M"]["action"]
        == "skip_unavailable"
    )
    assert by_model["gemma4:31b"]["action"] == "prefetch"
    assert by_model["gemma4:31b"]["target_worker"] == "spark-151"
    assert policy["prefetch_candidates"][0]["model"] == "qwen3-coder:30b-a3b-q4_K_M"
    assert policy["counts"]["skip_unavailable"] == 1
    assert guardrails["summarizer"]["eligible_models"][0]["model"] == (
        "gemma4:26b-a4b-it-q4_K_M"
    )
    assert any(
        item["model"] == "qwen3-coder:30b-a3b-q4_K_M"
        for item in guardrails["coder"]["eligible_models"]
    )
    assert guardrails["planner"]["blocked_count"] == 1


def test_build_warm_policy_includes_capability_catalog_and_spark_affinity():
    policy = warm_policy.build_warm_policy(mesh=catalog_mesh(), packet={})
    by_model = {item["model"]: item for item in policy["recommendations"]}
    guardrails = policy["route_guardrails"]["lanes"]

    assert policy["capability_catalog"]["schema"] == (
        "norman.norllama.capability-catalog.v1"
    )
    assert policy["capability_catalog"]["defaults"]["code"] == ("qwen3.6:27b")
    assert policy["capability_catalog"]["defaults"]["asr"] == (
        "faster-whisper:distil-large-v3"
    )
    assert policy["capability_catalog"]["defaults"]["world"] == (
        "qwen3.6:35b-a3b-q4_K_M"
    )
    assert policy["model_reality"]["schema"] == "norman.norllama.model-reality.v1"
    assert by_model["qwen3.6:35b-a3b-q4_K_M"]["action"] == "skip_quality_gate"
    assert (
        by_model["qwen3.6:35b-a3b-q4_K_M"]["model_reality"]["proof_status"]
        == "installed_unproven"
    )
    assert by_model["qwen3.6:27b"]["action"] == "skip_quality_gate"
    assert by_model["qwen3.6:27b"]["target_worker"] == "spark-151"
    assert by_model["qwen3.5:122b-a10b-q4_K_M"]["action"] == ("skip_quality_gate")
    assert by_model["qwen3.5:122b-a10b-q4_K_M"]["target_worker"] == "spark-151"
    assert by_model["Qwen/Qwen3-Reranker-0.6B"]["target_worker"] == "mac-mini-133"
    assert by_model["qwen3.6:35b-a3b-q4_K_M"]["target_worker"] == "spark-151"
    assert (
        policy["capability_catalog"]["defaults"]["prompt_injection"]
        == "Qwen/Qwen3Guard-Stream-0.6B"
    )
    assert by_model["Qwen/Qwen3Guard-Stream-0.6B"]["target_worker"] == "spark-150"
    assert (
        by_model["Qwen/Qwen3Guard-Stream-0.6B"]["model_reality"]["service"]["reason"]
        == "service endpoint advertised"
    )
    assert (
        by_model["qualifire/prompt-injection-sentinel"]["action"] == "skip_unavailable"
    )
    assert by_model["faster-whisper:distil-large-v3"]["target_worker"] == "spark-151"
    assert by_model["faster-whisper:large-v3"]["target_worker"] == "spark-150"
    assert (
        "Qwen/Qwen-AgentWorld-35B-A3B"
        in by_model["qwen3.6:35b-a3b-q4_K_M"]["desired_models"]
    )
    assert guardrails["coder"]["eligible_count"] == 0
    assert guardrails["judge"]["eligible_count"] == 0
    assert guardrails["rerank"]["eligible_count"] == 0
    assert guardrails["prompt_injection"]["eligible_count"] == 0
    assert guardrails["speech"]["eligible_count"] == 0
    assert guardrails["world"]["eligible_count"] == 0
    assert policy["counts"]["prefetch"] == 0


def test_service_backed_asr_is_servable_without_ollama_model_inventory():
    policy = warm_policy.build_warm_policy(mesh=asr_service_mesh(), packet={})
    by_model = {item["model"]: item for item in policy["recommendations"]}

    fast = by_model["faster-whisper:base"]
    quality = by_model["faster-whisper:large-v3"]

    assert fast["available"] is True
    assert fast["action"] == "skip_quality_gate"
    assert fast["service_evidence"]["installed"] is True
    assert fast["model_reality"]["state"] == "servable"
    assert fast["model_reality"]["proof_status"] == "installed_unproven"
    assert fast["model_reality"]["service"]["worker_ids"] == ["mac-mini-133"]
    assert fast["model_reality"]["service"]["service_models"] == ["faster-whisper:base"]
    assert quality["available"] is False
    assert quality["target_worker"] == "spark-150"
    assert quality["service_evidence"]["installed"] is False
    assert quality["model_reality"]["state"] == "aspirational"


def test_gateway_asr_service_attributes_upstream_worker_not_gateway():
    policy = warm_policy.build_warm_policy(mesh=gateway_asr_mesh(), packet={})
    by_model = {item["model"]: item for item in policy["recommendations"]}

    distil = by_model["faster-whisper:distil-large-v3"]
    fast = by_model["faster-whisper:base"]

    assert distil["available"] is True
    assert distil["target_worker"] == "spark-151"
    assert distil["model_reality"]["service"]["worker_ids"] == ["spark-151"]
    assert distil["model_reality"]["state"] == "servable"
    assert fast["available"] is True
    assert fast["target_worker"] == "mac-mini-133"
    assert fast["model_reality"]["service"]["worker_ids"] == ["mac-mini-133"]


def test_benchmark_backed_asr_service_can_be_prefetch_eligible():
    packet = {
        "generated_at": "2026-07-08T00:00:00Z",
        "results": [
            {
                "model": "faster-whisper:base",
                "priority": "canary",
                "status": "accepted",
                "score": 0.91,
                "coverage_ratio": 1.0,
                "lane_id": "asr_command_capture",
                "target_worker": "mac-mini-133",
            }
        ],
    }

    policy = warm_policy.build_warm_policy(mesh=asr_service_mesh(), packet=packet)
    by_model = {item["model"]: item for item in policy["recommendations"]}

    fast = by_model["faster-whisper:base"]
    assert fast["available"] is True
    assert fast["route_guardrail"]["authority"] == "canary_only"
    assert fast["model_reality"]["proof_status"] == "ready"
    assert fast["model_reality"]["state"] == "resident"
    assert fast["model_reality"]["route_eligible"] is True


def test_load_benchmark_packet_reads_configured_path(tmp_path):
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(sample_packet()), encoding="utf-8")

    packet, meta = warm_policy.load_benchmark_packet(path=str(packet_path))

    assert packet["generated_at"] == "2026-07-05T23:32:27Z"
    assert meta["status"] == "loaded"
    assert meta["source"] == "path"


def test_apply_warm_policy_dry_run_uses_prefetch_candidates(monkeypatch):
    monkeypatch.setattr(
        warm_policy,
        "build_warm_policy",
        lambda: {
            "prefetch_candidates": [
                {"model": "qwen3-coder:30b-a3b-q4_K_M"},
                {"model": "gemma4:31b"},
            ]
        },
    )

    payload = warm_policy.apply_warm_policy(dry_run=True, prefetch_limit=1)

    assert payload["dry_run"] is True
    assert payload["attempted"] == 1
    assert payload["results"] == [
        {
            "model": "qwen3-coder:30b-a3b-q4_K_M",
            "status": "planned",
            "dry_run": True,
            "priority": "background",
            "target_worker": "",
            "target_endpoint": "",
            "residency_confirmed_at_policy_build": False,
        }
    ]


def test_apply_warm_policy_records_prefetch_target_mismatch(monkeypatch):
    monkeypatch.setattr(
        warm_policy,
        "build_warm_policy",
        lambda: {
            "prefetch_candidates": [
                {
                    "model": "gemma4:26b-a4b-it-q4_K_M",
                    "target_worker": "spark-151",
                    "target_endpoint": "http://192.168.2.151:18151",
                }
            ]
        },
    )

    def fake_prefetch_model(**_kwargs):
        return {
            "ok": True,
            "status": "running",
            "job_id": "warm-gemma",
            "upstream": "http://192.168.2.150:18151",
        }

    monkeypatch.setattr(warm_policy.gateway, "prefetch_model", fake_prefetch_model)

    payload = warm_policy.apply_warm_policy(dry_run=False, prefetch_limit=1)
    result = payload["results"][0]

    assert result["status"] == "running"
    assert result["target_worker"] == "spark-151"
    assert result["response_upstream"] == "http://192.168.2.150:18151"
    assert result["target_honored"] is False
    assert "instead of http://192.168.2.151:18151" in result["target_mismatch"]
    assert result["job_id"] == "warm-gemma"


def test_apply_warm_policy_flags_stale_duplicate_warm_job(monkeypatch):
    monkeypatch.setattr(
        warm_policy,
        "build_warm_policy",
        lambda: {
            "prefetch_candidates": [
                {
                    "model": "qwen3-coder-next:q4_K_M",
                    "target_worker": "spark-151",
                    "target_endpoint": "http://192.168.2.151:18151",
                    "active": False,
                }
            ]
        },
    )

    def fake_prefetch_model(**_kwargs):
        return {
            "ok": True,
            "status": "accepted",
            "job_status": "warm",
            "started": False,
            "job_id": "warm-qwen-next",
            "upstream": "http://192.168.2.151:18151",
            "job": {"status": "warm", "duplicate_count": 1},
        }

    monkeypatch.setattr(warm_policy.gateway, "prefetch_model", fake_prefetch_model)

    payload = warm_policy.apply_warm_policy(dry_run=False, prefetch_limit=1)
    result = payload["results"][0]

    assert result["status"] == "accepted"
    assert result["target_honored"] is True
    assert result["residency_confirmed_at_policy_build"] is False
    assert "existing prefetch job" in result["residency_warning"]


def test_build_warm_policy_skips_low_benchmark_score_when_available():
    mesh = sample_mesh()
    mesh["models"].append("hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M")
    mesh["workers"][2]["models"].append(
        "hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M"
    )

    policy = warm_policy.build_warm_policy(mesh=mesh, packet=sample_packet())
    by_model = {item["model"]: item for item in policy["recommendations"]}
    openfugu = by_model["hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M"]

    assert openfugu["available"] is True
    assert openfugu["action"] == "skip_quality_gate"
    assert openfugu["benchmark_quality"]["state"] == "low_score"
    assert openfugu["target_worker"] == "spark-151"


def test_build_warm_policy_rejects_timeout_heavy_benchmark_rows():
    packet = sample_packet()
    packet["shareable_view"]["recommended_roles"][1].update(
        {
            "accepted_count": 5,
            "total_count": 20,
            "timeout_rate": 0.75,
            "empty_response_rate": 0,
            "zero_token_rate": 0,
            "progress_only_rate": 0,
        }
    )

    policy = warm_policy.build_warm_policy(mesh=sample_mesh(), packet=packet)
    by_model = {item["model"]: item for item in policy["recommendations"]}
    qwen = by_model["qwen3-coder:30b-a3b-q4_K_M"]

    assert qwen["action"] == "skip_quality_gate"
    assert qwen["benchmark_quality"]["state"] == "timeout_heavy"
    assert qwen["benchmark_quality"]["quality_metrics"]["timeout_rate"] == 0.75
    assert all(
        item["model"] != "qwen3-coder:30b-a3b-q4_K_M"
        for item in policy["prefetch_candidates"]
    )


def test_build_warm_policy_rejects_zero_token_benchmark_rows():
    packet = sample_packet()
    packet["shareable_view"]["recommended_roles"][1].update(
        {
            "accepted_count": 10,
            "total_count": 10,
            "timeout_rate": 0,
            "empty_response_rate": 0,
            "zero_token_count": 1,
            "progress_only_rate": 0,
        }
    )

    policy = warm_policy.build_warm_policy(mesh=sample_mesh(), packet=packet)
    by_model = {item["model"]: item for item in policy["recommendations"]}
    qwen = by_model["qwen3-coder:30b-a3b-q4_K_M"]

    assert qwen["action"] == "skip_quality_gate"
    assert qwen["benchmark_quality"]["state"] == "zero_token"


def test_build_warm_policy_blocks_recent_failed_route_cooldown():
    now = int(time.time())
    policy = warm_policy.build_warm_policy(
        mesh=sample_mesh(),
        packet=sample_packet(),
        route_outcomes=[
            {
                "recorded_at": now - 60,
                "status": "timeout",
                "ok": False,
                "model": "qwen3-coder:30b-a3b-q4_K_M",
                "worker_id": "spark-150",
                "reason": "TUI planner timed out",
            }
        ],
        cooldown_seconds=900,
    )
    by_model = {item["model"]: item for item in policy["recommendations"]}
    qwen = by_model["qwen3-coder:30b-a3b-q4_K_M"]

    assert qwen["available"] is True
    assert qwen["target_worker"] == "spark-150"
    assert qwen["action"] == "skip_cooldown"
    assert qwen["cooldown"]["active"] is True
    assert qwen["route_guardrail"]["route_state"] == "cooldown"
    assert qwen["route_guardrail"]["authority"] == "blocked"
    assert policy["counts"]["skip_cooldown"] == 1
    assert policy["route_outcomes"]["cooldown_count"] == 1
    assert "qwen3-coder:30b-a3b-q4_K_M" in {
        item["model"]
        for item in policy["route_guardrails"]["lanes"]["coder"]["blocked_models"]
    }
    assert all(
        item["model"] != "qwen3-coder:30b-a3b-q4_K_M"
        for item in policy["prefetch_candidates"]
    )


def test_select_model_for_task_kind_prefers_warm_benchmark_lane():
    policy = warm_policy.build_warm_policy(mesh=sample_mesh(), packet=sample_packet())

    selection = warm_policy.select_model_for_task_kind(
        "code",
        warm_policy_payload=policy,
    )

    assert selection["schema"] == "norman.norllama.warm-policy-selection.v1"
    assert selection["selected"] is True
    assert selection["lane"] == "coder"
    assert selection["model"] == "qwen3-coder:30b-a3b-q4_K_M"
    assert selection["action"] == "prefetch"
    assert selection["target_worker"] == "spark-150"
    assert selection["pool_strategy"] == "balanced"
    assert selection["pool_size"] >= 1
    assert selection["selected_score"] > 0
    assert selection["pool"][0]["model"] == "qwen3-coder:30b-a3b-q4_K_M"


def test_select_model_for_task_kind_uses_recent_outcomes_for_dynamic_pool():
    mesh = sample_mesh()
    mesh["models"].append("deepseek-coder:16b")
    mesh["workers"][1]["models"].append("deepseek-coder:16b")
    packet = sample_packet()
    packet["shareable_view"]["recommended_roles"].append(
        {
            "lane_id": "packet_code_backup",
            "model": "deepseek-coder:16b",
            "profile": "deepseek_local",
            "score": 0.74,
            "coverage_ratio": 1.0,
            "use_for": "code patch flow",
            "guardrail": "Run tests.",
        }
    )
    now = int(time.time())
    route_outcomes = [
        {
            "recorded_at": now - index,
            "status": "slow-response",
            "ok": False,
            "model": "qwen3-coder:30b-a3b-q4_K_M",
            "worker_id": "spark-150",
            "latency_ms": 22000,
        }
        for index in range(1, 6)
    ] + [
        {
            "recorded_at": now - index,
            "status": "success",
            "ok": True,
            "model": "deepseek-coder:16b",
            "worker_id": "spark-150",
            "latency_ms": 900,
        }
        for index in range(10, 13)
    ]
    policy = warm_policy.build_warm_policy(
        mesh=mesh,
        packet=packet,
        route_outcomes=route_outcomes,
    )

    selection = warm_policy.select_model_for_task_kind(
        "code",
        policy={"model_pool_strategy": "fast"},
        warm_policy_payload=policy,
    )

    assert selection["selected"] is True
    assert selection["pool_strategy"] == "fast"
    assert selection["model"] == "deepseek-coder:16b"
    assert selection["pool_size"] >= 2
    pool_by_model = {item["model"]: item for item in selection["pool"]}
    assert (
        pool_by_model["qwen3-coder:30b-a3b-q4_K_M"]["route_outcome_stats"]["fail"] == 5
    )
    assert pool_by_model["deepseek-coder:16b"]["route_outcome_stats"]["ok"] == 3


def test_build_warm_policy_routes_around_high_pressure_hint_worker():
    mesh = sample_mesh()
    mesh["workers"][1]["models"].append("deepseek-coder:16b")
    mesh["workers"][1]["active_models"] = [
        "gemma4:26b-a4b-it-q4_K_M",
        "qwen3-coder:30b-a3b-q4_K_M",
    ]
    mesh["workers"][2]["models"].append("deepseek-coder:16b")
    packet = sample_packet()
    packet["shareable_view"]["recommended_roles"].append(
        {
            "lane_id": "packet_code_pool",
            "model": "deepseek-coder:16b",
            "profile": "deepseek_local",
            "score": 0.82,
            "coverage_ratio": 1.0,
            "target_worker": "spark-150",
            "use_for": "code patch flow",
            "guardrail": "Run tests.",
        }
    )

    policy = warm_policy.build_warm_policy(mesh=mesh, packet=packet)
    by_model = {item["model"]: item for item in policy["recommendations"]}
    deepseek = by_model["deepseek-coder:16b"]

    assert deepseek["target_worker"] == "spark-151"
    assert deepseek["worker_pressure"]["state"] == "low"


def test_select_model_for_task_kind_skips_cooled_down_candidate():
    policy = warm_policy.build_warm_policy(
        mesh=sample_mesh(),
        packet=sample_packet(),
        route_outcomes=[
            {
                "recorded_at": int(time.time()) - 30,
                "status": "timeout",
                "ok": False,
                "model": "qwen3-coder:30b-a3b-q4_K_M",
                "worker_id": "spark-150",
            }
        ],
    )

    selection = warm_policy.select_model_for_task_kind(
        "code",
        warm_policy_payload=policy,
    )

    assert selection["selected"] is False
    assert "no eligible" in selection["reason"]


def test_mac_mini_only_gets_tiny_canary_prefetch_from_fallbacks(monkeypatch):
    monkeypatch.setattr(
        warm_policy.settings,
        "llm_warm_policy_fallback_prefetch",
        False,
        raising=False,
    )
    mesh = sample_mesh()
    mesh["workers"][0]["active_models"] = []

    policy = warm_policy.build_warm_policy(mesh=mesh, packet={})
    by_model = {item["model"]: item for item in policy["recommendations"]}

    assert by_model["gemma3:1b"]["target_worker"] == "mac-mini-133"
    assert by_model["gemma3:1b"]["action"] == "skip_model_reality"
    assert by_model["gemma3:1b"]["model_reality"]["proof_status"] == (
        "installed_unproven"
    )
    assert by_model["qwen3.6:27b"]["action"] == "skip_unavailable"
    assert by_model["qwen3.6:27b"]["model_reality"]["proof_status"] == "catalog_only"
    assert "hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M" not in by_model


def test_build_warm_policy_blocks_heavy_model_on_fallback_node():
    mesh = sample_mesh()
    mesh["models"].append("qwen3-coder:30b-a3b-q4_K_M")
    mesh["workers"][1]["models"].remove("qwen3-coder:30b-a3b-q4_K_M")
    mesh["workers"][0]["models"].append("qwen3-coder:30b-a3b-q4_K_M")

    packet = sample_packet()
    packet["shareable_view"]["recommended_roles"][1]["target_worker"] = "mac-mini-133"

    policy = warm_policy.build_warm_policy(mesh=mesh, packet=packet)
    by_model = {item["model"]: item for item in policy["recommendations"]}
    qwen = by_model["qwen3-coder:30b-a3b-q4_K_M"]

    assert qwen["target_worker"] == "mac-mini-133"
    assert qwen["action"] == "skip_model_reality"
    assert qwen["model_reality"]["proof_status"] == "worker_fit_blocked"
    assert "heavy model cannot be warmed on fallback node" in qwen["action_reason"]
