from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "codex_bridge_parity", scripts_dir / "codex_bridge_parity.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["codex_bridge_parity"] = module
    spec.loader.exec_module(module)
    return module


def _execution(
    module,
    *,
    route: str,
    answer: str,
    tools: int,
    status: str = "completed",
):
    return module.RouteExecution(
        route=route,
        status=status,
        returncode=0 if status == "completed" else 1,
        duration_ms=100,
        answer=answer,
        answer_sha256=module._sha256(answer) if answer else "",
        answer_chars=len(answer),
        tool_events=tools,
        retry_events=0,
        usage={"output_tokens": 10},
        prompt_context={},
        short_stop=module.response_has_unfinished_promise(answer),
    )


def _case() -> dict[str, object]:
    return {
        "id": "policy",
        "title": "Policy",
        "category": "policy",
        "requires_repository_tools": True,
        "prompt": "SECRET PROMPT TEXT",
        "required_facts": [{"id": "fact", "all_terms": ["dry-run"]}],
        "required_evidence": [{"id": "evidence", "all_terms": ["README.md"]}],
        "wisdom_checks": [{"id": "wisdom", "all_terms": ["approval"]}],
        "answer_contract": {
            "min_response_words": 3,
            "required_sections": ["Evidence"],
        },
    }


def test_case_fixture_is_complete_and_read_only(monkeypatch) -> None:
    module = _load_module(monkeypatch)

    cases = module.read_cases(module.DEFAULT_CASES)

    assert len(cases) == 5
    assert all(case["requires_repository_tools"] is True for case in cases)
    assert all(case["answer_contract"] for case in cases)


def test_event_parser_counts_unique_tool_calls_and_usage(tmp_path, monkeypatch) -> None:
    module = _load_module(monkeypatch)
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "call-1",
                            "type": "command_execution",
                            "usage": {"output_tokens": 8},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"id": "call-1", "type": "command_execution"},
                    }
                ),
                json.dumps(
                    {
                        "type": "retrying",
                        "usage": {"output_tokens": 11, "input_tokens": 20},
                        "response": {
                            "id": "resp-bridge",
                            "norman": {
                                "responses_compatibility": {
                                    "prompt_context": {
                                        "schema": "norman.responses-prompt-context.v1",
                                        "groups": {
                                            "history": {
                                                "message_count": 2,
                                                "chars": 80,
                                                "tool_output_chars": 60,
                                                "function_call_chars": 10,
                                                "text_chars": 10,
                                            },
                                            "tool_contract": {
                                                "message_count": 1,
                                                "chars": 120,
                                                "tool_output_chars": 0,
                                                "function_call_chars": 0,
                                                "text_chars": 120,
                                            },
                                        },
                                        "total_message_count": 3,
                                        "total_content_chars": 200,
                                        "rendered_prompt_chars": 220,
                                        "private": "SECRET PROMPT",
                                    }
                                }
                            },
                        },
                    }
                ),
            )
        ),
        encoding="utf-8",
    )

    tool_events, retry_events, usage, prompt_context = module.parse_event_metrics(
        events
    )

    assert tool_events == 1
    assert retry_events == 1
    assert usage == {"input_tokens": 20, "output_tokens": 11}
    assert prompt_context == {
        "schema": "norman.responses-prompt-context.v1",
        "hop_count": 1,
        "groups": {
            "history": {
                "message_count": 2,
                "chars": 80,
                "tool_output_chars": 60,
                "function_call_chars": 10,
                "text_chars": 10,
            },
            "tool_contract": {
                "message_count": 1,
                "chars": 120,
                "tool_output_chars": 0,
                "function_call_chars": 0,
                "text_chars": 120,
            },
            "structured_output": {
                "message_count": 0,
                "chars": 0,
                "tool_output_chars": 0,
                "function_call_chars": 0,
                "text_chars": 0,
            },
            "current_input": {
                "message_count": 0,
                "chars": 0,
                "tool_output_chars": 0,
                "function_call_chars": 0,
                "text_chars": 0,
            },
        },
        "total_message_count": 3,
        "total_content_chars": 200,
        "rendered_prompt_chars_total": 220,
        "rendered_prompt_chars_max": 220,
    }
    assert "SECRET PROMPT" not in json.dumps(prompt_context)


def test_report_redacts_prompt_and_answer_text(monkeypatch, tmp_path: Path) -> None:
    module = _load_module(monkeypatch)
    case = _case()
    native = _execution(
        module,
        route="native",
        answer="Evidence: README.md says dry-run before approval.",
        tools=1,
    )
    transparent = _execution(
        module,
        route="transparent",
        answer="Evidence: README.md says dry-run before approval. SUPER SECRET ANSWER",
        tools=1,
    )
    row = {
        "id": case["id"],
        "title": case["title"],
        "category": case["category"],
        "requires_repository_tools": True,
        "route_order": ["native", "transparent"],
        "native": module._execution_payload(native, case),
        "transparent": module._execution_payload(transparent, case),
    }
    report = module.build_report(
        cases=[case],
        workspace=tmp_path / "control_plane",
        live=True,
        rows=[row],
        native=module.RouteSpec("native", Path("/bin/codex"), tmp_path / "home"),
        transparent=module.RouteSpec("transparent", Path("/bin/codex-work")),
        timeout_seconds=60,
        min_completed_pairs=1,
        max_score_regression=5,
    )
    report_json = json.dumps(report)

    assert "SECRET PROMPT TEXT" not in report_json
    assert "SUPER SECRET ANSWER" not in report_json
    assert "answer_sha256" in report_json
    assert report["gate"]["state"] == "pass"
    assert "Raw prompts" in module.render_markdown(report)


def test_gate_fails_on_short_stop_score_and_tool_regression(monkeypatch) -> None:
    module = _load_module(monkeypatch)
    rows = [
        {
            "id": "policy",
            "requires_repository_tools": True,
            "native": {
                "status": "completed",
                "answer_chars": 20,
                "duration_ms": 100,
                "short_stop": False,
                "tool_events": 2,
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "score": {"score": 90},
            },
            "transparent": {
                "status": "completed",
                "answer_chars": 20,
                "duration_ms": 200,
                "short_stop": True,
                "tool_events": 0,
                "usage": {"input_tokens": 20, "output_tokens": 4},
                "score": {"score": 70},
            },
        }
    ]

    summary = module.build_summary(rows)
    gate = module.evaluate_gate(
        live=True,
        summary=summary,
        min_completed_pairs=1,
        max_score_regression=5,
    )

    assert summary["tool_continuity_regression_case_ids"] == ["policy"]
    assert gate["state"] == "fail"
    assert set(gate["reason_codes"]) == {
        "score_regression",
        "short_stop_regression",
        "tool_continuity_regression",
    }
    assert summary["native_duration_ms"] == {"total_ms": 100, "average_ms": 100}
    assert summary["transparent_duration_ms"] == {
        "total_ms": 200,
        "average_ms": 200,
    }
    assert summary["duration_delta_ms"] == 100
    assert summary["native_usage"]["output_tokens"] == 5
    assert summary["transparent_usage"]["input_tokens"] == 20


def test_dry_run_writes_private_sanitized_artifacts(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module(monkeypatch)
    output_json = tmp_path / "parity.json"
    output_md = tmp_path / "parity.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codex_bridge_parity.py",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))

    assert report["schema"] == module.SCHEMA
    assert report["gate"]["state"] == "hold"
    assert report["summary"]["completed_pairs"] == 0
    assert output_json.stat().st_mode & 0o777 == 0o600
    assert output_md.stat().st_mode & 0o777 == 0o600
