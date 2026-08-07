from __future__ import annotations

import json

from scripts import tui_tool_chain_canary as canary


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
                        "state": "repaired",
                        "attempts": 1,
                        "reason": "undeclared_tool",
                    },
                    "arguments": {"private": "arguments"},
                }
            }
        },
    }


def test_run_canary_exercises_the_three_turn_synthetic_tool_chain():
    requests = []
    responses = iter(
        [
            _tool_response("resp-search", "tool_search", "call-search"),
            _tool_response(
                "resp-synthetic",
                "synthetic.status_lookup",
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
                                "state": "not_required",
                                "attempts": 0,
                                "reason": "",
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
    assert receipt["turns"][1]["tool_names"] == ["synthetic.status_lookup"]
    assert receipt["turns"][2]["function_call_count"] == 0
    assert requests[0][1]["tools"][0]["name"] == "tool_search"
    assert requests[1][1]["tools"][0]["name"] == "synthetic.status_lookup"
    assert (
        requests[2][1]["input"][0]["output"] == '{"status":"ok","source":"synthetic"}'
    )
    assert (
        requests[2][1]["input"][1]["content"]
        == "The synthetic result has been supplied. Return a concise final health "
        "result now. Do not call another tool."
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert "private-token" not in serialized
    assert "private arguments" not in serialized
    assert "Synthetic status is healthy." not in serialized
    assert "total_tokens" not in serialized
    assert "undeclared_tool" not in serialized


def test_run_canary_skips_without_making_requests_when_pressure_defers_work():
    calls = []

    receipt = canary.run_canary(
        endpoint="http://127.0.0.1:8000/v1/responses",
        token="private-token",
        pressure_guard=lambda: {"admission": {"action": "defer_heavy_work"}},
        request_fn=lambda *args: calls.append(args) or (200, {}),
    )

    assert receipt["state"] == "skipped"
    assert receipt["skip_reason"] == "host_pressure"
    assert receipt["pressure_admission"] == "defer_heavy_work"
    assert calls == []


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


def test_canary_systemd_wrapper_uses_the_encrypted_credential_path():
    root = canary.Path(__file__).resolve().parents[1]
    wrapper = (root / "scripts/run_norman_tui_tool_chain_canary.sh").read_text(
        encoding="utf-8"
    )
    service = (root / "scripts/systemd/norman-tui-tool-chain-canary.service").read_text(
        encoding="utf-8"
    )
    timer = (root / "scripts/systemd/norman-tui-tool-chain-canary.timer").read_text(
        encoding="utf-8"
    )

    assert "CREDENTIALS_DIRECTORY" in wrapper
    assert "norman/prompt-proxy-token" in wrapper
    assert "--passphrase-file" in wrapper
    assert "NORMAN_PROMPT_PROXY_TOKEN" in wrapper
    assert "/usr/local/libexec/tui_tool_chain_canary.py" in wrapper
    assert "/home/kristopher/code/norman" not in wrapper
    assert "http://127.0.0.1:8000/v1/responses" in service
    assert "LoadCredentialEncrypted=norman-cred-passphrase" in service
    assert "WorkingDirectory=" not in service
    assert "OnUnitActiveSec=1h" in timer
