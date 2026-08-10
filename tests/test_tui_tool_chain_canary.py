from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path

from scripts import tui_tool_chain_canary as canary


OPS_TOKEN_HELPER_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "norman_ops_mcp_canary_token.py"
)


def _load_ops_token_helper_module():
    module_name = f"norman_ops_mcp_canary_token_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, OPS_TOKEN_HELPER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _tool_response(response_id: str, name: str, call_id: str) -> dict:
    return {
        "id": response_id,
        "status": "completed",
        "output": [
            {
                "type": "function_call",
                "name": name,
                "call_id": call_id,
                "arguments": '{"private":"arguments"}',
            }
        ],
        "output_text": "",
        "usage": {"total_tokens": 999},
        "norman": {
            "responses_compatibility": {
                "tool_chain": {
                    "schema": "norman.responses-tool-chain.v1",
                    "turn_type": "after_tool_result",
                    "chain_depth": 1,
                    "tool_results_supplied": 1,
                    "tool_results_matched": 1,
                    "tool_calls_returned": 1,
                    "outcome": "tool_call",
                    "watchdog": {
                        "state": "normal",
                        "attempts": 0,
                    },
                    "arguments": {"private": "arguments"},
                }
            }
        },
    }


def _stream_response(
    response: dict,
    *,
    native_calls: list[dict] | None = None,
    completed: bool = True,
    done: bool = True,
    failed: bool = False,
    raw_tool_envelope_text: bool = False,
) -> dict:
    streamed = dict(response)
    streamed["_canary_stream"] = {
        "completed": completed,
        "done": done,
        "failed": failed,
        "native_function_calls": (
            native_calls
            if native_calls is not None
            else [
                {
                    "name": item["name"],
                    "call_id": item["call_id"],
                }
                for item in response.get("output", [])
                if item.get("type") == "function_call"
            ]
        ),
        "raw_tool_envelope_text": raw_tool_envelope_text,
    }
    return streamed


def test_run_canary_exercises_the_three_turn_synthetic_tool_chain():
    requests = []
    responses = iter(
        [
            _tool_response("resp-search", "tool_search", "call-search"),
            _tool_response(
                "resp-synthetic",
                "mcp__norman_canary.status_lookup",
                "call-synthetic",
            ),
            {
                "id": "resp-final",
                "status": "completed",
                "output": [{"type": "message"}],
                "output_text": "Synthetic status is healthy.",
                "usage": {"total_tokens": 999},
                "norman": {
                    "responses_compatibility": {
                        "tool_chain": {
                            "schema": "norman.responses-tool-chain.v1",
                            "turn_type": "after_tool_result",
                            "chain_depth": 2,
                            "tool_results_supplied": 1,
                            "tool_results_matched": 1,
                            "tool_calls_returned": 0,
                            "outcome": "final_after_tool",
                            "watchdog": {
                                "state": "normal",
                                "attempts": 0,
                            },
                        }
                    }
                },
            },
        ]
    )

    def request_fn(endpoint, payload, token, timeout_seconds):
        requests.append((endpoint, payload, token, timeout_seconds))
        return 200, next(responses)

    receipt = canary.run_canary(
        endpoint="http://127.0.0.1:8000/v1/responses",
        token="private-token",
        pressure_guard=lambda: {"admission": {"action": "accept_new_work"}},
        request_fn=request_fn,
    )

    assert receipt["state"] == "passed"
    assert [turn["turn"] for turn in receipt["turns"]] == [
        "tool_search",
        "synthetic_status_lookup",
        "final_answer",
    ]
    assert receipt["turns"][0]["tool_names"] == ["tool_search"]
    assert receipt["turns"][1]["tool_names"] == ["mcp__norman_canary.status_lookup"]
    assert receipt["turns"][2]["function_call_count"] == 0
    assert requests[0][1]["tools"][0]["name"] == "tool_search"
    assert requests[1][1]["tools"][0] == {
        "type": "namespace",
        "name": "mcp__norman_canary",
        "tools": [
            {
                "type": "function",
                "name": "status_lookup",
                "description": "Return a synthetic canary status.",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    }
    assert (
        requests[2][1]["input"][2]["output"] == '{"status":"ok","source":"synthetic"}'
    )
    assert (
        requests[2][1]["input"][3]["content"]
        == "The synthetic result has been supplied. Return a concise final health "
        "result now. Do not call another tool."
    )
    replay = requests[1][1]["input"][:2]
    assert replay == [
        {
            "type": "function_call",
            "status": "in_progress",
            "call_id": "call-search",
            "name": "tool_search",
            "arguments": "",
        },
        {
            "type": "function_call",
            "status": "completed",
            "call_id": "call-search",
            "name": "tool_search",
            "arguments": '{"private":"arguments"}',
        },
    ]

    serialized = json.dumps(receipt, sort_keys=True)
    assert "private-token" not in serialized
    assert "private arguments" not in serialized
    assert "Synthetic status is healthy." not in serialized
    assert "total_tokens" not in serialized
    assert "undeclared_tool" not in serialized


def test_run_canary_allows_a_status_message_after_an_expected_function_call():
    requests = []
    first = _tool_response("resp-search", "tool_search", "call-search")
    first["output"].append({"type": "message", "content": "Searching."})
    responses = iter(
        [
            first,
            _tool_response(
                "resp-synthetic",
                "mcp__norman_canary.status_lookup",
                "call-synthetic",
            ),
            {
                "id": "resp-final",
                "status": "completed",
                "output": [{"type": "message"}],
                "output_text": "Synthetic status is healthy.",
            },
        ]
    )

    receipt = canary.run_canary(
        endpoint="http://127.0.0.1:8000/v1/responses",
        token="private-token",
        pressure_guard=lambda: {"admission": {"action": "accept_new_work"}},
        request_fn=lambda *args: requests.append(args) or (200, next(responses)),
    )

    assert receipt["state"] == "passed"
    assert len(requests) == 3
    assert receipt["turns"][0]["output_count"] == 2
    assert receipt["turns"][0]["tool_names"] == ["tool_search"]


def test_run_canary_allows_native_reasoning_before_an_expected_function_call():
    requests = []
    first = _tool_response("resp-search", "tool_search", "call-search")
    first["output"].insert(
        0,
        {
            "type": "reasoning",
            "id": "rs-private",
            "encrypted_content": "private-reasoning",
        },
    )
    responses = iter(
        [
            first,
            _tool_response(
                "resp-synthetic",
                "mcp__norman_canary.status_lookup",
                "call-synthetic",
            ),
            {
                "id": "resp-final",
                "status": "completed",
                "output": [{"type": "message"}],
                "output_text": "Synthetic status is healthy.",
            },
        ]
    )

    receipt = canary.run_canary(
        endpoint="http://127.0.0.1:8000/v1/responses",
        token="private-token",
        pressure_guard=lambda: {"admission": {"action": "accept_new_work"}},
        request_fn=lambda *args: requests.append(args) or (200, next(responses)),
    )

    assert receipt["state"] == "passed"
    assert len(requests) == 3
    assert receipt["turns"][0]["output_count"] == 2
    assert receipt["turns"][0]["tool_names"] == ["tool_search"]
    assert "private-reasoning" not in json.dumps(receipt, sort_keys=True)


def test_run_canary_streaming_exercises_native_sse_tool_calls():
    requests = []
    responses = iter(
        [
            _stream_response(
                _tool_response("resp-search", "tool_search", "call-search")
            ),
            _stream_response(
                _tool_response(
                    "resp-synthetic",
                    "mcp__norman_canary.status_lookup",
                    "call-synthetic",
                )
            ),
            _stream_response(
                {
                    "id": "resp-final",
                    "status": "completed",
                    "output": [{"type": "message"}],
                    "output_text": "Synthetic status is healthy.",
                }
            ),
        ]
    )

    def stream_request_fn(endpoint, payload, token, timeout_seconds):
        requests.append((endpoint, payload, token, timeout_seconds))
        return 200, next(responses)

    receipt = canary.run_canary(
        endpoint="https://cp.kris.openbrand.com/v1/responses",
        token="private-token",
        pressure_guard=lambda: {"admission": {"action": "accept_new_work"}},
        streaming=True,
        stream_request_fn=stream_request_fn,
    )

    assert receipt["state"] == "passed"
    assert receipt["mode"] == "streaming"
    assert all(request[1]["stream"] is True for request in requests)
    assert receipt["turns"][0]["stream"] == {
        "completed": True,
        "done": True,
        "failed": False,
        "native_function_call_count": 1,
        "native_tool_names": ["tool_search"],
        "raw_tool_envelope_text": False,
    }
    assert receipt["turns"][2]["stream"]["native_function_call_count"] == 0
    serialized = json.dumps(receipt, sort_keys=True)
    assert "private-token" not in serialized
    assert "private" not in serialized


def test_run_canary_streaming_fails_without_a_native_function_call_event():
    receipt = canary.run_canary(
        endpoint="https://cp.kris.openbrand.com/v1/responses",
        token="private-token",
        pressure_guard=lambda: {},
        streaming=True,
        stream_request_fn=lambda *args: (
            200,
            _stream_response(
                _tool_response("resp-search", "tool_search", "call-search"),
                native_calls=[],
            ),
        ),
    )

    assert receipt["state"] == "failed"
    assert receipt["failure_kind"] == "missing_native_function_event"
    assert receipt["turns"][0]["stream"]["native_function_call_count"] == 0


def test_run_canary_ops_mcp_exercises_read_only_native_sse_continuation():
    requests = []
    direct_smoke_result = {
        "status": "ok",
        "portal_status": "ok",
        "portal_lane": "production",
        "read_only": True,
        "mutations_supported": False,
        "mutation_tool_count": 0,
        "principal": "private-user@example.com",
        "roles": ["private-role"],
        "identity_verified": True,
        "tool_count": 9,
        "capability_count": 14,
        "timings_ms": {
            "initialize": 12,
            "ops_portal_health": 18,
            "private_phase": 99,
        },
    }
    responses = iter(
        [
            _stream_response(
                _tool_response(
                    "resp-ops",
                    "mcp__ops_openbrand.ops_portal_health",
                    "call-ops",
                )
            ),
            _stream_response(
                {
                    "id": "resp-final",
                    "status": "completed",
                    "output": [{"type": "message"}],
                    "output_text": "Ops health is normal.",
                    "norman": {
                        "responses_compatibility": {
                            "tool_chain": {
                                "schema": "norman.responses-tool-chain.v1",
                                "turn_type": "after_tool_result",
                                "chain_depth": 1,
                                "tool_results_supplied": 1,
                                "tool_results_matched": 1,
                                "tool_calls_returned": 0,
                                "outcome": "final_after_tool",
                                "watchdog": {
                                    "state": "normal",
                                    "attempts": 0,
                                },
                            }
                        }
                    },
                }
            ),
        ]
    )

    def stream_request_fn(endpoint, payload, token, timeout_seconds):
        requests.append((endpoint, payload, token, timeout_seconds))
        return 200, next(responses)

    receipt = canary.run_canary(
        endpoint="https://cp.kris.openbrand.com/v1/responses",
        token="private-token",
        pressure_guard=lambda: {"admission": {"action": "accept_new_work"}},
        streaming=True,
        stream_request_fn=stream_request_fn,
        ops_mcp=True,
        ops_direct_smoke=lambda timeout_seconds: direct_smoke_result,
    )

    assert receipt["state"] == "passed"
    assert receipt["workflow"] == "ops_mcp"
    assert [turn["turn"] for turn in receipt["turns"]] == [
        "ops_portal_health",
        "ops_final_answer",
    ]
    assert receipt["turns"][0]["tool_names"] == ["mcp__ops_openbrand.ops_portal_health"]
    assert receipt["turns"][0]["stream"]["native_tool_names"] == [
        "mcp__ops_openbrand.ops_portal_health"
    ]
    assert receipt["turns"][1]["tool_chain"]["watchdog_state"] == "normal"
    assert requests[0][1]["tools"] == [
        {
            "type": "namespace",
            "name": "mcp__ops_openbrand",
            "tools": [
                {
                    "type": "function",
                    "name": "ops_portal_health",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        }
    ]
    replay = requests[1][1]["input"][:2]
    assert replay == [
        {
            "type": "function_call",
            "status": "in_progress",
            "call_id": "call-ops",
            "name": "mcp__ops_openbrand.ops_portal_health",
            "arguments": "",
        },
        {
            "type": "function_call",
            "status": "completed",
            "call_id": "call-ops",
            "name": "mcp__ops_openbrand.ops_portal_health",
            "arguments": '{"private":"arguments"}',
        },
    ]
    assert json.loads(requests[1][1]["input"][2]["output"]) == {
        "status": "ok",
        "portal_status": "ok",
        "portal_lane": "production",
        "read_only": True,
        "mutations_supported": False,
        "mutation_tool_count": 0,
        "identity_verified": True,
        "tool_count": 9,
        "capability_count": 14,
        "timings_ms": {
            "initialize": 12,
            "ops_portal_health": 18,
        },
    }

    serialized = json.dumps(receipt, sort_keys=True)
    assert "private-token" not in serialized
    assert "private-user@example.com" not in serialized
    assert "private-role" not in serialized
    assert "private_phase" not in serialized
    assert "call-ops" not in serialized


def test_run_canary_ops_mcp_stops_before_public_call_when_direct_smoke_fails():
    receipt = canary.run_canary(
        endpoint="https://cp.kris.openbrand.com/v1/responses",
        token="private-token",
        pressure_guard=lambda: {},
        ops_mcp=True,
        ops_direct_smoke=lambda timeout_seconds: {
            "status": "error",
            "error_message": "private direct MCP failure",
            "read_only": False,
            "mutations_supported": True,
        },
        request_fn=lambda *args: (_ for _ in ()).throw(AssertionError("not called")),
    )

    assert receipt["state"] == "failed"
    assert receipt["failure_kind"] == "ops_direct_smoke_failed"
    assert receipt["turns"] == []
    assert "private direct MCP failure" not in json.dumps(receipt, sort_keys=True)


def test_ops_direct_smoke_uses_bundled_streamable_http_probe(monkeypatch):
    class Response:
        def __init__(self, payload, *, session_id=""):
            self.headers = {
                "Content-Type": "application/json",
            }
            if session_id:
                self.headers["Mcp-Session-Id"] = session_id
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.payload

    def rpc_result(payload):
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": payload}).encode(
            "utf-8"
        )

    def tool_result(payload):
        return rpc_result(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload),
                    }
                ]
            }
        )

    responses = iter(
        [
            Response(rpc_result({"protocolVersion": canary.OPS_MCP_PROTOCOL_VERSION})),
            Response(b""),
            Response(
                rpc_result(
                    {
                        "tools": [
                            {"name": "ops_portal_health"},
                            {"name": "read_only_policy"},
                            {"name": "session_start"},
                            {"name": "list_capabilities"},
                        ]
                    }
                )
            ),
            Response(tool_result({"status": "ok", "lane": "production"})),
            Response(
                tool_result(
                    {
                        "status": "ok",
                        "access_policy": {
                            "read_only": True,
                            "mutations_supported": False,
                            "mutation_tools": [],
                        },
                    }
                )
            ),
            Response(
                tool_result(
                    {
                        "status": "ok",
                        "session": {
                            "session_id": "private-session-id",
                            "caller_identity_verified": True,
                        },
                    }
                )
            ),
            Response(tool_result({"status": "ok", "capabilities": [{}, {}, {}]})),
        ]
    )
    requests = []

    def fake_run(command, **_kwargs):
        assert command == [
            canary.sys.executable,
            str(canary.DEFAULT_OPS_MCP_KEY_HELPER),
            "--secret",
            canary.DEFAULT_OPS_MCP_KEY_SECRET,
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            "private-bound-key\n",
            "",
        )

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return next(responses)

    monkeypatch.delenv("OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY", raising=False)
    monkeypatch.setattr(canary.subprocess, "run", fake_run)
    monkeypatch.setattr(canary.urllib.request, "urlopen", fake_urlopen)

    result = canary._run_ops_direct_smoke(30)

    assert result["status"] == "ok"
    assert result["read_only"] is True
    assert result["mutations_supported"] is False
    assert result["identity_verified"] is True
    assert result["tool_count"] == 4
    assert result["capability_count"] == 3
    assert [json.loads(request.data)["method"] for request, _timeout in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
        "tools/call",
        "tools/call",
        "tools/call",
    ]
    assert all(
        request.get_header("Mcp-session-id") is None for request, _timeout in requests
    )
    assert "private-bound-key" not in json.dumps(result, sort_keys=True)


def test_ops_mcp_api_key_uses_an_explicit_one_shot_override(monkeypatch):
    monkeypatch.setenv("OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY", "private-override")
    monkeypatch.setattr(
        canary.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("not called")),
    )

    assert canary._ops_mcp_api_key(30) == "private-override"


def test_ops_mcp_cli_flag_enables_the_streaming_canary():
    args = canary.parse_args(["--ops-mcp"])

    assert args.ops_mcp is True
    assert args.stream is False


def test_safe_tool_chain_reports_unknown_legacy_watchdog_state():
    response = _tool_response("resp-legacy", "tool_search", "call-search")
    response["norman"]["responses_compatibility"]["tool_chain"]["watchdog"] = {
        "state": "controlled",
        "attempts": 0,
        "reason": "external_workflow_continued",
    }

    assert canary._safe_tool_chain(response)["watchdog_state"] == "unknown"


def test_safe_tool_chain_preserves_transparent_passthrough_state():
    response = _tool_response("resp-passthrough", "tool_search", "call-search")
    response["norman"]["responses_compatibility"]["tool_chain"]["watchdog"] = {
        "state": "passthrough",
        "attempts": 0,
    }

    assert canary._safe_tool_chain(response)["watchdog_state"] == "passthrough"


def test_canary_receipt_exposes_only_sanitized_bridge_metadata():
    response = _tool_response("resp-bridge", "tool_search", "call-search")
    response.update({"model": "qwen3-coder:30b-a3b-q4_K_M"})
    response["norman"].update(
        {
            "route": {
                "selected_provider": "norllama",
                "selected_model": "qwen3-coder:30b-a3b-q4_K_M",
            },
            "output_token_budget": {
                "requested": 16384,
                "effective": 16384,
                "maximum": 32768,
            },
        }
    )
    response["norman"]["responses_compatibility"].update(
        {
            "tool_bridge_mode": "transparent",
            "tool_transport": "local_text_adapter",
            "state_retention": "ephemeral",
        }
    )

    bridge = canary._safe_bridge_receipt(response)

    assert bridge == {
        "mode": "transparent",
        "tool_transport": "local_text_adapter",
        "state_retention": "ephemeral",
        "effective_backend": {
            "provider": "norllama",
            "model": "qwen3-coder:30b-a3b-q4_K_M",
        },
        "output_token_budget": {
            "requested": 16384,
            "effective": 16384,
            "maximum": 32768,
        },
        "fallback_reason": "",
    }
    assert "private" not in json.dumps(bridge, sort_keys=True)


def test_run_canary_streaming_fails_when_raw_tool_json_reaches_output_text():
    receipt = canary.run_canary(
        endpoint="https://cp.kris.openbrand.com/v1/responses",
        token="private-token",
        pressure_guard=lambda: {},
        streaming=True,
        stream_request_fn=lambda *args: (
            200,
            _stream_response(
                _tool_response("resp-search", "tool_search", "call-search"),
                raw_tool_envelope_text=True,
            ),
        ),
    )

    assert receipt["state"] == "failed"
    assert receipt["failure_kind"] == "raw_tool_envelope_text"
    assert receipt["turns"][0]["stream"]["raw_tool_envelope_text"] is True
    assert '{"tool_call"' not in json.dumps(receipt, sort_keys=True)


def test_sse_parser_tracks_native_calls_and_completion_markers():
    function_item = {
        "type": "function_call",
        "name": "tool_search",
        "call_id": "private-call-id",
        "arguments": "",
    }
    completed = {
        "id": "resp-private",
        "status": "completed",
        "output": [
            {
                **function_item,
                "arguments": '{"query":"private"}',
            }
        ],
        "output_text": "",
    }
    body = "\n\n".join(
        [
            "event: response.output_item.added\n"
            f"data: {json.dumps({'type': 'response.output_item.added', 'item': function_item})}",
            "event: response.completed\n"
            f"data: {json.dumps({'type': 'response.completed', 'response': completed})}",
            "data: [DONE]",
        ]
    )

    parsed = canary._parse_sse_events(body)
    response = canary._stream_response_from_sse_events(parsed)

    stream = response["_canary_stream"]
    assert stream["completed"] is True
    assert stream["done"] is True
    assert stream["failed"] is False
    assert stream["raw_tool_envelope_text"] is False
    assert stream["native_function_calls"] == [
        {"name": "tool_search", "call_id": "private-call-id"}
    ]


def test_sse_parser_records_sanitized_stream_liveness_timing():
    completed = {
        "id": "resp-private",
        "status": "completed",
        "output": [{"type": "message"}],
        "output_text": "private final output",
    }
    events = [
        {
            "event": "response.in_progress",
            "data": {
                "type": "response.in_progress",
                "response": {
                    "norman": {
                        "cloud_fallback": {
                            "request_id": "private-request-id",
                            "state": "in_progress",
                            "heartbeat": True,
                        }
                    }
                },
            },
            "_received_ms": 7.0,
        },
        {
            "event": "response.in_progress",
            "data": {
                "type": "response.in_progress",
                "response": {
                    "norman": {
                        "cloud_fallback": {
                            "request_id": "private-request-id",
                            "state": "in_progress",
                            "heartbeat": True,
                        }
                    }
                },
            },
            "_received_ms": 18.5,
        },
        {
            "event": "response.completed",
            "data": {
                "type": "response.completed",
                "response": completed,
            },
            "_received_ms": 25.0,
        },
        {"event": "", "data": "[DONE]", "_received_ms": 31.5},
    ]

    response = canary._stream_response_from_sse_events(events)

    assert response["_canary_stream"]["timing"] == {
        "event_count": 4,
        "time_to_first_event_ms": 7.0,
        "max_inter_event_gap_ms": 11.5,
        "cloud_progress_count": 2,
        "cloud_heartbeat_count": 2,
        "local_stream_open_progress_count": 0,
        "local_stream_open_heartbeat_count": 0,
        "first_cloud_heartbeat_ms": 7.0,
        "last_cloud_heartbeat_ms": 18.5,
    }
    serialized = json.dumps(response["_canary_stream"], sort_keys=True)
    assert "private-request-id" not in serialized
    assert "private final output" not in serialized


def test_sse_parser_counts_local_stream_open_heartbeats():
    events = [
        {
            "event": "response.in_progress",
            "data": {
                "type": "response.in_progress",
                "response": {
                    "norman": {
                        "local_stream_open": {
                            "state": "in_progress",
                            "heartbeat": True,
                        }
                    }
                },
            },
            "_received_ms": 4.0,
        },
        {
            "event": "response.in_progress",
            "data": {
                "type": "response.in_progress",
                "response": {
                    "norman": {
                        "local_stream_open": {
                            "state": "in_progress",
                            "heartbeat": True,
                        }
                    }
                },
            },
            "_received_ms": 12.0,
        },
        {
            "event": "response.completed",
            "data": {
                "type": "response.completed",
                "response": {"status": "completed"},
            },
            "_received_ms": 18.0,
        },
        {"event": "", "data": "[DONE]", "_received_ms": 20.0},
    ]

    response = canary._stream_response_from_sse_events(events)

    assert response["_canary_stream"]["timing"] == {
        "event_count": 4,
        "time_to_first_event_ms": 4.0,
        "max_inter_event_gap_ms": 8.0,
        "cloud_progress_count": 0,
        "cloud_heartbeat_count": 0,
        "local_stream_open_progress_count": 2,
        "local_stream_open_heartbeat_count": 2,
        "first_local_stream_open_heartbeat_ms": 4.0,
        "last_local_stream_open_heartbeat_ms": 12.0,
    }


def test_sse_parser_flags_native_function_call_json_leaked_as_text():
    leaked_native_call = json.dumps(
        {
            "arguments": '{"query":"synthetic"}',
            "call_id": "private-call-id",
            "id": "fc-private",
            "name": "tool_search",
            "type": "function_call",
        }
    )
    completed = {
        "id": "resp-private",
        "status": "completed",
        "output": [{"type": "message"}],
        "output_text": leaked_native_call,
    }
    body = "\n\n".join(
        [
            "event: response.output_text.delta\n"
            "data: "
            f"{json.dumps({'type': 'response.output_text.delta', 'delta': leaked_native_call})}",
            "event: response.completed\n"
            f"data: {json.dumps({'type': 'response.completed', 'response': completed})}",
            "data: [DONE]",
        ]
    )

    parsed = canary._parse_sse_events(body)
    response = canary._stream_response_from_sse_events(parsed)

    assert response["_canary_stream"]["raw_tool_envelope_text"] is True


def test_run_canary_runs_when_pressure_defers_heavy_work():
    calls = []

    receipt = canary.run_canary(
        endpoint="http://127.0.0.1:8000/v1/responses",
        token="private-token",
        pressure_guard=lambda: {"admission": {"action": "defer_heavy_work"}},
        request_fn=lambda *args: calls.append(args) or (200, {}),
    )

    assert receipt["state"] == "failed"
    assert receipt["failure_kind"] == "unexpected_function_call"
    assert len(calls) == 1


def test_run_canary_ignores_an_invalid_pressure_guard_result():
    receipt = canary.run_canary(
        endpoint="http://127.0.0.1:8000/v1/responses",
        token="",
        pressure_guard=lambda: "not a mapping",
    )

    assert receipt["state"] == "failed"
    assert receipt["failure_kind"] == "token_unavailable"


def test_run_canary_sanitizes_a_failed_unexpected_tool_response():
    receipt = canary.run_canary(
        endpoint="http://127.0.0.1:8000/v1/responses",
        token="private-token",
        pressure_guard=lambda: {},
        request_fn=lambda *args: (
            200,
            _tool_response(
                "resp-bad",
                "mcp__codex_apps__private_tool",
                "call-private",
            ),
        ),
    )

    assert receipt["state"] == "failed"
    assert receipt["failure_kind"] == "unexpected_function_call"
    assert receipt["turns"][0]["tool_names"] == ["unexpected"]
    serialized = json.dumps(receipt, sort_keys=True)
    assert "mcp__codex_apps__private_tool" not in serialized
    assert "call-private" not in serialized
    assert "private" not in serialized


def test_canary_systemd_wrapper_uses_the_brokered_token_path():
    root = canary.Path(__file__).resolve().parents[1]
    installer = (root / "scripts/deploy_norman_tui_tool_chain_canary.sh").read_text(
        encoding="utf-8"
    )
    wrapper = (root / "scripts/run_norman_tui_tool_chain_canary.sh").read_text(
        encoding="utf-8"
    )
    service = (root / "scripts/systemd/norman-tui-tool-chain-canary.service").read_text(
        encoding="utf-8"
    )
    timer = (root / "scripts/systemd/norman-tui-tool-chain-canary.timer").read_text(
        encoding="utf-8"
    )

    assert "NORMAN_TUI_TOOL_CHAIN_TOKEN_HELPER" in wrapper
    assert "control-plane/prompt-proxy-token" in wrapper
    assert "--secret" in wrapper
    assert "NORMAN_PROMPT_PROXY_TOKEN" in wrapper
    assert "/usr/local/libexec/norman_codex_gateway_token.py" in wrapper
    assert "/usr/local/libexec/tui_tool_chain_canary.py" in wrapper
    assert "/home/kristopher/code/norman" not in wrapper
    assert "https://cp.kris.openbrand.com/v1/responses" in service
    assert "norman-tui-tool-chain-canary --stream" in service
    assert "EnvironmentFile=-/etc/norman/codex-route-proof.env" in service
    assert "LoadCredentialEncrypted=" not in service
    assert (
        "NORMAN_TUI_TOOL_CHAIN_CANARY_TOKEN_SECRET=control-plane/prompt-proxy-token"
        in service
    )
    assert "NoNewPrivileges=true" not in service
    assert "WorkingDirectory=" not in service
    assert "OnUnitActiveSec=1h" in timer
    assert "sudo --non-interactive" in installer
    assert "norman_codex_gateway_token.py" in installer
    assert "norman_ops_mcp_canary_token.py" in installer
    assert "norman_codex_gateway_broker.sh" in installer
    assert "codex-route-proof.env" not in installer
    assert "systemctl start norman-tui-tool-chain-canary.service" in installer
    assert 'receipt.get("state") != "passed"' in installer


def test_ops_mcp_canary_broker_is_fixed_alias_and_never_uses_aws():
    root = canary.Path(__file__).resolve().parents[1]
    token_helper = (root / "scripts/norman_ops_mcp_canary_token.py").read_text(
        encoding="utf-8"
    )
    broker = (root / "scripts/norman_ops_mcp_canary_broker.py").read_text(
        encoding="utf-8"
    )
    launcher = (root / "scripts/norman_ops_mcp_canary_broker_launch.sh").read_text(
        encoding="utf-8"
    )
    installer = (root / "scripts/deploy_norman_ops_mcp_canary_key_broker.sh").read_text(
        encoding="utf-8"
    )
    provisioner = (root / "scripts/provision_norman_ops_mcp_canary_key.sh").read_text(
        encoding="utf-8"
    )

    assert "control-plane/ops-mcp-canary-key" in token_helper
    assert "control-plane/ops-mcp-canary-key" in broker
    assert "secretsmanager" not in token_helper
    assert "aws" not in broker
    assert "systemd-run" in launcher
    assert "norman-ops-mcp-canary-broker" in launcher
    assert "/usr/local/libexec/norman-ops-mcp-canary-broker" in installer
    assert "visudo -cf" in installer
    assert "--stdin" in broker
    assert "aws secretsmanager get-secret-value" in provisioner
    assert "ssh -o BatchMode=yes" in provisioner


def test_ops_mcp_canary_token_helper_uses_narrow_noninteractive_sudo(monkeypatch):
    module = _load_ops_token_helper_module()
    monkeypatch.setattr(module.Path, "is_file", lambda _path: True)
    monkeypatch.setattr(module.os, "access", lambda *_args: True)

    assert module._broker_command() == [
        "/usr/bin/sudo",
        "--non-interactive",
        "/usr/local/sbin/norman-ops-mcp-canary-broker",
        "get",
    ]


def test_ops_mcp_canary_broker_sudoers_allows_only_the_get_command():
    sudoers = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norman_ops_mcp_canary_broker.sudoers"
    ).read_text(encoding="utf-8")

    assert (
        "kristopher ALL=(root) NOPASSWD: "
        "/usr/local/sbin/norman-ops-mcp-canary-broker get" in sudoers
    )
    assert "provision" not in sudoers
