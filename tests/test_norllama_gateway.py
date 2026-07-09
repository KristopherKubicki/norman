from __future__ import annotations

from app.services.norllama import gateway


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = dict(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self):
        return self._payload


class EmptyResponse(FakeResponse):
    def __init__(self, *, status_code=204):
        super().__init__({}, status_code=status_code)


def test_tls_verification_stays_on_for_public_https():
    assert gateway._verify_tls_for_url("https://api.openai.com/v1/models") is True
    assert gateway._verify_tls_for_url("http://192.168.2.150:18151/v1/overview") is True


def test_tls_verification_is_disabled_for_internal_https():
    assert gateway._verify_tls_for_url("https://llm.home.arpa/v1/overview") is False
    assert (
        gateway._verify_tls_for_url("https://192.168.2.150:18151/v1/overview") is False
    )
    assert gateway._verify_tls_for_url("https://127.0.0.1:18151/v1/overview") is False


def test_frontdoor_urls_do_not_duplicate_v1_prefix():
    assert (
        gateway._generate_url("https://llm.home.arpa/v1")
        == "https://llm.home.arpa/api/generate"
    )
    assert (
        gateway._api_ps_url("https://llm.home.arpa/v1")
        == "https://llm.home.arpa/api/ps"
    )
    assert (
        gateway._prefetch_url("https://llm.home.arpa/v1")
        == "https://llm.home.arpa/v1/prefetch"
    )
    assert (
        gateway._rerank_url("https://llm.home.arpa/v1")
        == "https://llm.home.arpa/v1/rerank"
    )
    assert (
        gateway._safety_classify_url("https://llm.home.arpa/v1")
        == "https://llm.home.arpa/v1/safety/classify"
    )
    assert (
        gateway._image_generation_url("https://llm.home.arpa/v1")
        == "https://llm.home.arpa/v1/images/generations"
    )
    assert gateway._capability_urls("https://llm.home.arpa/v1")[:3] == [
        "https://llm.home.arpa/v1/capabilities",
        "https://llm.home.arpa/api/capabilities",
        "https://llm.home.arpa/api/tags",
    ]
    assert gateway._overview_urls("https://llm.home.arpa/v1")[:3] == [
        "https://llm.home.arpa/v1/overview",
        "https://llm.home.arpa/api/overview",
        "https://llm.home.arpa/healthz",
    ]
    assert not any(
        "/v1/v1/" in url or "/v1/api/" in url
        for url in (
            gateway._capability_urls("https://llm.home.arpa/v1")
            + gateway._overview_urls("https://llm.home.arpa/v1")
        )
    )


def test_fetch_capabilities_uses_native_endpoint(monkeypatch):
    calls = []

    def fake_get(url, headers, timeout, verify):
        calls.append((url, headers, timeout, verify))
        return FakeResponse(
            {
                "provider": "norllama",
                "models": [{"name": "qwen3:8b"}, "bge-reranker"],
                "tool_lanes": ["ocr", "rerank"],
                "task_kinds": ["chat", "plan", "rerank"],
                "modalities": ["text", "image"],
                "capabilities": {"streaming": True},
            }
        )

    monkeypatch.setattr(gateway.requests, "get", fake_get)

    payload = gateway.fetch_capabilities(
        base_url="http://127.0.0.1:11434",
        api_key="token",
        timeout_seconds=3,
    )

    assert calls[0][0] == "http://127.0.0.1:11434/api/capabilities"
    assert calls[0][1]["Authorization"] == "Bearer token"
    assert calls[0][2] == 3
    assert calls[0][3] is True
    assert payload["models"] == ["qwen3:8b", "bge-reranker"]
    assert payload["tool_lanes"] == ["ocr", "rerank"]
    assert payload["supports"] == {
        "tools": True,
        "streaming": True,
        "files": True,
    }


def test_normalize_capabilities_payload_promotes_contracts_to_tool_lanes():
    payload = gateway.normalize_capabilities_payload(
        {
            "service": "norllama",
            "contracts": [
                {
                    "contract_id": "embed",
                    "dispatch": "embedding_proxy",
                    "default_model": "bge-m3:latest",
                    "status": "benchmark_backed",
                },
                {
                    "contract_id": "rerank",
                    "dispatch": "rerank_proxy",
                    "default_model": "qllama/bge-reranker-v2-m3:q8_0",
                    "status": "benchmark_backed",
                },
                {
                    "contract_id": "safety_privacy_classify",
                    "dispatch": "safety_proxy",
                    "default_model": "Qwen/Qwen3Guard-Stream-0.6B",
                    "status": "live_tool_lane",
                },
                {
                    "contract_id": "audio_diarize",
                    "dispatch": "transcribe_proxy",
                    "default_model": "faster-whisper:distil-large-v3",
                    "status": "pending_benchmark",
                },
                {
                    "contract_id": "vision_grounding",
                    "dispatch": "media_proxy",
                    "default_model": "qwen3-vl:30b-a3b-instruct-q4_K_M",
                    "status": "indirect_benchmark",
                },
                {
                    "contract_id": "image_generate",
                    "dispatch": "image_generation_proxy",
                    "default_model": "stable-diffusion:configured-backend",
                    "status": "live_tool_lane",
                },
                {
                    "contract_id": "web_world",
                    "dispatch": "world_proxy",
                    "default_model": "Qwen/WebWorld-8B",
                    "status": "catalog_recommended",
                },
            ],
            "endpoints": [
                {"kind": "transcribe", "path": "/v1/audio/transcriptions"},
                {"kind": "safety", "path": "/v1/safety/classify"},
                {"kind": "image_generate", "path": "/v1/images/generations"},
                {"kind": "world", "path": "/v1/world"},
            ],
        }
    )

    assert payload["models"] == [
        "bge-m3:latest",
        "qllama/bge-reranker-v2-m3:q8_0",
        "Qwen/Qwen3Guard-Stream-0.6B",
        "faster-whisper:distil-large-v3",
        "qwen3-vl:30b-a3b-instruct-q4_K_M",
        "stable-diffusion:configured-backend",
        "Qwen/WebWorld-8B",
    ]
    assert set(payload["tool_lanes"]) >= {
        "asr",
        "doc_parse",
        "embed",
        "gui_ground",
        "image_generate",
        "ocr",
        "prompt_injection",
        "rerank",
        "safety",
        "stt",
        "world",
    }
    assert set(payload["task_kinds"]) >= {
        "asr",
        "embed",
        "image_generate",
        "prompt_injection",
        "rerank",
        "safety",
        "world",
    }
    assert set(payload["modalities"]) >= {"audio", "file", "image", "pdf"}
    assert payload["supports"]["tools"] is True
    assert payload["supports"]["files"] is True
    assert payload["contracts"][3]["contract_id"] == "audio_diarize"


def test_prefetch_model_posts_to_frontdoor(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout, verify):
        calls.append((url, headers, json, timeout, verify))
        return EmptyResponse()

    monkeypatch.setattr(gateway.requests, "post", fake_post)

    payload = gateway.prefetch_model(
        model="gemma4:26b-a4b-it-q4_K_M",
        base_url="https://llm.home.arpa/v1",
        api_key="token",
        priority="background",
        timeout_seconds=4,
    )

    assert payload["status"] == "accepted"
    assert calls[0][0] == "https://llm.home.arpa/v1/prefetch"
    assert calls[0][1]["Authorization"] == "Bearer token"
    assert calls[0][1]["X-Norllama-Priority"] == "background"
    assert calls[0][2]["model"] == "gemma4:26b-a4b-it-q4_K_M"
    assert calls[0][3] == 4
    assert calls[0][4] is False


def test_prefetch_model_includes_target_worker_hints(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout, verify):
        calls.append((url, headers, json, timeout, verify))
        return FakeResponse({"status": "accepted"})

    monkeypatch.setattr(gateway.requests, "post", fake_post)

    payload = gateway.prefetch_model(
        model="qwen3-coder:30b-a3b-q4_K_M",
        base_url="https://llm.home.arpa/v1",
        target_worker="spark-150",
        target_endpoint="http://192.168.2.150:18151",
        timeout_seconds=4,
    )

    assert payload["status"] == "accepted"
    assert calls[0][1]["X-Norllama-Target-Worker"] == "spark-150"
    assert calls[0][1]["X-Norllama-Target-Endpoint"] == "http://192.168.2.150:18151"
    assert calls[0][2]["target_worker"] == "spark-150"
    assert calls[0][2]["target_endpoint"] == "http://192.168.2.150:18151"


def test_generate_image_posts_to_frontdoor(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout, verify):
        calls.append((url, headers, json, timeout, verify))
        return FakeResponse(
            {
                "model": "sdxl-local",
                "data": [{"b64_json": "abc"}],
                "usage": {"image_count": 1, "usage_bucket": "offline_local"},
                "norllama": {"selected_worker": "spark-150"},
            },
            headers={
                "X-Norllama-Worker-Id": "spark-150",
                "X-Norllama-Upstream": "http://192.168.2.150:18151",
            },
        )

    monkeypatch.setattr(gateway.requests, "post", fake_post)

    payload = gateway.generate_image(
        prompt="draw a shell",
        base_url="https://llm.home.arpa/v1",
        api_key="token",
        model="stable-diffusion:configured-backend",
        negative_prompt="watermark",
        size="768x768",
        n=2,
        steps=28,
        cfg_scale=7.5,
        seed=123,
        sampler="DPM++ 2M",
        allow_nsfw=True,
        content_rating="adult",
        safety_profile="adult_opt_in",
        timeout_seconds=12,
    )

    assert calls[0][0] == "https://llm.home.arpa/v1/images/generations"
    assert calls[0][1]["Authorization"] == "Bearer token"
    assert calls[0][2]["prompt"] == "draw a shell"
    assert calls[0][2]["negative_prompt"] == "watermark"
    assert calls[0][2]["n"] == 2
    assert calls[0][2]["steps"] == 28
    assert calls[0][2]["cfg_scale"] == 7.5
    assert calls[0][2]["seed"] == 123
    assert calls[0][2]["sampler"] == "DPM++ 2M"
    assert calls[0][2]["allow_nsfw"] is True
    assert calls[0][2]["content_rating"] == "adult"
    assert calls[0][2]["safety_profile"] == "adult_opt_in"
    assert calls[0][3] == 12
    assert calls[0][4] is False
    assert payload["image_count"] == 1
    assert payload["data"] == [{"b64_json": "abc"}]
    assert payload["headers"]["x-norllama-worker-id"] == "spark-150"


def test_fetch_tool_activity_filters_probe_noise(monkeypatch):
    calls = []

    def fake_get(url, headers, timeout, verify):
        calls.append((url, headers, timeout, verify))
        return FakeResponse(
            {
                "count": 5,
                "items": [
                    {
                        "method": "GET",
                        "path": "/v1/overview",
                        "status": 200,
                        "duration_ms": 8,
                    },
                    {
                        "method": "POST",
                        "path": "/v1/embeddings",
                        "status": 200,
                        "duration_ms": 42.4,
                        "model": "bge-m3:latest",
                        "upstream": "http://192.168.2.150:18151",
                        "request_id": "req-embed",
                    },
                    {
                        "method": "POST",
                        "path": "/v1/rerank",
                        "status": 200,
                        "duration_ms": 78.2,
                        "score_method": "embedding_cosine",
                    },
                    {
                        "method": "POST",
                        "path": "/v1/safety/classify",
                        "status": 200,
                        "duration_ms": 35.1,
                        "selected_model": "Qwen/Qwen3Guard-Stream-0.6B",
                        "selected_worker": "spark150",
                    },
                    {
                        "method": "POST",
                        "path": "/v1/images/generations",
                        "status": 200,
                        "duration_ms": 5120,
                        "selected_model": "sdxl-local",
                        "selected_worker": "spark151",
                        "image_count": 1,
                    },
                ],
            }
        )

    monkeypatch.setattr(gateway.requests, "get", fake_get)

    payload = gateway.fetch_tool_activity(
        base_url="https://llm.home.arpa/v1",
        api_key="token",
        limit=200,
        timeout_seconds=3,
    )

    assert calls[0][0] == "https://llm.home.arpa/v1/activity?limit=200"
    assert calls[0][1]["Authorization"] == "Bearer token"
    assert calls[0][3] is False
    assert payload["schema"] == "norman.norllama.tool-activity.v1"
    assert payload["status"] == "active"
    assert payload["tool_call_count"] == 4
    assert payload["dropped_probe_count"] == 1
    assert payload["capability_counts"] == {
        "embed": 1,
        "image_generate": 1,
        "rerank": 1,
        "safety": 1,
    }
    assert payload["latest_tool_call"]["capability"] == "embed"
    assert payload["latest_tool_call"]["model"] == "bge-m3:latest"
    assert payload["latest_tool_call"]["upstream"] == "http://192.168.2.150:18151"
    assert payload["items"][2]["capability"] == "safety"
    assert payload["items"][2]["worker_id"] == "spark150"
    assert payload["items"][3]["capability"] == "image_generate"
    assert payload["items"][3]["worker_id"] == "spark151"


def test_fetch_tool_activity_tracks_asr_and_world_paths(monkeypatch):
    def fake_get(url, headers, timeout, verify):
        return FakeResponse(
            {
                "count": 3,
                "items": [
                    {
                        "method": "POST",
                        "path": "/v1/audio/transcriptions",
                        "status": 200,
                        "duration_ms": 1320,
                        "model": "faster-whisper:distil-large-v3",
                        "upstream": "http://192.168.2.150:18151",
                    },
                    {
                        "method": "POST",
                        "path": "/v1/world",
                        "status": 200,
                        "duration_ms": 840,
                        "model": "Qwen/WebWorld-8B",
                    },
                ],
            }
        )

    monkeypatch.setattr(gateway.requests, "get", fake_get)

    payload = gateway.fetch_tool_activity(
        base_url="https://llm.home.arpa/v1",
        limit=25,
        timeout_seconds=3,
    )

    assert payload["capability_counts"] == {"asr": 1, "world": 1}
    assert payload["latest_tool_call"]["capability"] == "asr"
    assert payload["latest_tool_call"]["model"] == "faster-whisper:distil-large-v3"


def test_invoke_text_chat_preserves_norllama_routing_headers(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout, verify):
        calls.append((url, headers, json, timeout, verify))
        return FakeResponse(
            {
                "model": json["model"],
                "response": "hello",
                "prompt_eval_count": 3,
                "eval_count": 4,
            },
            headers={
                "X-Norllama-Worker-Id": "spark-150",
                "X-Norllama-Peer-Path": "llm.home.arpa,spark-150",
                "X-Norllama-Upstream": "http://192.168.2.150:18151",
                "X-Norllama-Attempts": (
                    "http://192.168.2.133:18151," "http://192.168.2.150:18151"
                ),
                "Authorization": "secret",
            },
        )

    monkeypatch.setattr(gateway.requests, "post", fake_post)

    payload = gateway.invoke_text_chat(
        messages=[{"role": "user", "content": "hi"}],
        model="qwen3.5:27b-q4_K_M",
        base_url="https://llm.home.arpa/v1",
        max_tokens=32,
    )

    assert payload["headers"] == {
        "x-norllama-attempts": (
            "http://192.168.2.133:18151," "http://192.168.2.150:18151"
        ),
        "x-norllama-worker-id": "spark-150",
        "x-norllama-peer-path": "llm.home.arpa,spark-150",
        "x-norllama-upstream": "http://192.168.2.150:18151",
    }
    assert calls[0][2]["think"] is False
    assert "secret" not in str(payload)


def test_normalize_capabilities_payload_accepts_ollama_tags():
    payload = gateway.normalize_capabilities_payload(
        {
            "models": [
                {"model": "qwen3:8b"},
                {"name": "nomic-embed-text"},
                {"id": "bge-reranker"},
            ],
            "capabilities": {"supports_tools": True, "supports_files": False},
        }
    )

    assert payload["provider"] == "norllama"
    assert payload["models"] == ["qwen3:8b", "nomic-embed-text", "bge-reranker"]
    assert payload["supports"]["tools"] is True
    assert payload["supports"]["files"] is False


def test_fetch_capabilities_accepts_openai_model_list():
    payload = gateway.normalize_capabilities_payload(
        {
            "data": [
                {"id": "gemma4:26b-a4b-it-q4_K_M"},
                {"name": "qwen3.5:27b-q4_K_M"},
            ],
            "capabilities": {"supports_streaming": True},
        }
    )

    assert payload["models"] == [
        "gemma4:26b-a4b-it-q4_K_M",
        "qwen3.5:27b-q4_K_M",
    ]
    assert payload["supports"]["streaming"] is True


def test_build_mesh_overview_reports_degraded_worker_roster(monkeypatch):
    def fake_get(url, headers, timeout, verify):
        if "192.168.2.151" in url:
            raise gateway.requests.Timeout("worker down")
        if url.endswith("/api/ps"):
            return FakeResponse({"models": [{"name": "gemma4:26b-a4b-it-q4_K_M"}]})
        if "overview" in url or url.endswith("/healthz"):
            return FakeResponse(
                {
                    "status": "ok",
                    "gateway": {"name": "norllama", "version": "test"},
                    "catalog_summary": {"visible_model_count": 2},
                    "model_highlights": [{"id": "gemma4:26b-a4b-it-q4_K_M"}],
                }
            )
        return FakeResponse(
            {
                "provider": "norllama",
                "models": [
                    {"name": "gemma4:26b-a4b-it-q4_K_M"},
                    {"name": "qwen3.5:27b-q4_K_M"},
                ],
                "capabilities": {"streaming": True},
            }
        )

    monkeypatch.setattr(gateway.requests, "get", fake_get)

    payload = gateway.build_mesh_overview(
        base_url="https://llm.home.arpa/v1",
        api_key="token",
        workers=[
            {
                "id": "spark-150",
                "role": "production",
                "base_url": "http://192.168.2.150:18151",
            },
            {
                "id": "spark-151",
                "role": "production",
                "base_url": "http://192.168.2.151:18151",
            },
        ],
        timeout_seconds=0.5,
    )

    assert payload["schema"] == "norman.norllama.mesh.v1"
    assert payload["status"] == "degraded"
    assert payload["worker_count"] == 2
    assert payload["healthy_worker_count"] == 1
    assert payload["frontdoor"]["reachable"] is True
    assert payload["workers"][0]["id"] == "spark-150"
    assert payload["workers"][0]["reachable"] is True
    assert payload["workers"][0]["active_models"] == ["gemma4:26b-a4b-it-q4_K_M"]
    assert payload["workers"][1]["id"] == "spark-151"
    assert payload["workers"][1]["status"] == "error"
    assert "token" not in str(payload)
