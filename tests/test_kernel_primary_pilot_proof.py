from __future__ import annotations

from scripts import kernel_primary_pilot_proof as proof


def _event(case_id: str, event_type: str, *, job_id: str = "job-1", payload=None):
    return {
        "sequence": len(event_type),
        "job_id": job_id,
        "event_type": event_type,
        "payload": {"pilot_case": case_id, **(payload or {})},
    }


def _receipt(*, fallback=""):
    receipt = {
        "usage_bucket": "offline_local",
        "observed_worker": "spark-150",
        "observed_worker_source": "gateway_response",
        "cloud_proxy": False,
        "receipt_audit": {"pass": True},
        "completion_gate": {"gate_passed": True},
    }
    if fallback:
        receipt["fallback_reason"] = fallback
    return receipt


def _route(case_id: str, *, fallback="", job_id="job-1"):
    return _event(
        case_id,
        "route.receipt_audited",
        job_id=job_id,
        payload={"route_receipt": _receipt(fallback=fallback)},
    )


def _complete_route(case_id: str, *, job_id="job-1"):
    return _event(
        case_id,
        "route.completion_gate",
        job_id=job_id,
        payload={"route_receipt": _receipt()},
    )


def _passing_events():
    return [
        _event("planner", "model.completed"),
        _route("planner"),
        _complete_route("planner"),
        _event("tool_loop", "tool.completed", payload={"tool_name": "shell.read"}),
        _event("tool_loop", "model.completed"),
        _event("tool_loop", "reasoning.tool_gate"),
        _route("tool_loop"),
        _complete_route("tool_loop"),
        _event("parallel", "workstream.created", job_id="parent"),
        _event(
            "parallel",
            "workstream.subtasks_delegated",
            job_id="parent",
            payload={"count": 2},
        ),
        _route("parallel", job_id="parent"),
        _complete_route("parallel", job_id="parent"),
        _event("verifier", "model.completed"),
        _event("verifier", "verification.completed"),
        _route("verifier"),
        _complete_route("verifier"),
        _event("degraded", "model.completed"),
        _route("degraded", fallback="spark-151 unavailable; used spark-150"),
        _complete_route("degraded"),
    ]


def test_build_report_accepts_all_five_safe_cases():
    report = proof.build_report(_passing_events(), source="fixture")

    assert report["schema"] == proof.SCHEMA
    assert report["offline_only"] is True
    assert report["rollout_settings_changed"] is False
    assert report["passed"] is True
    assert report["summary"] == {
        "required_cases": 5,
        "passed_cases": 5,
        "failed_cases": 0,
    }
    assert "NOT YET PROVEN" not in proof.render_markdown(report)


def test_tool_loop_requires_a_real_tool_and_following_model_completion():
    events = [
        _event(
            "tool_loop", "tool.completed", payload={"tool_name": "model_adapter.invoke"}
        ),
        _event("tool_loop", "model.completed"),
        _event("tool_loop", "reasoning.tool_gate"),
        _route("tool_loop"),
        _complete_route("tool_loop"),
    ]

    row = proof.evaluate_case(
        next(case for case in proof.CASES if case["id"] == "tool_loop"), events
    )

    assert row["passed"] is False
    assert "no non-model tool completion was observed" in row["failures"]


def test_degraded_case_requires_visible_fallback_evidence():
    events = [
        _event("degraded", "model.completed"),
        _route("degraded"),
        _complete_route("degraded"),
    ]

    row = proof.evaluate_case(
        next(case for case in proof.CASES if case["id"] == "degraded"), events
    )

    assert row["passed"] is False
    assert (
        "degraded/fallback state was not visible in exported events" in row["failures"]
    )


def test_load_events_accepts_api_payload_and_jsonl(tmp_path):
    event = _event("planner", "model.completed")
    api_path = tmp_path / "events.json"
    api_path.write_text(__import__("json").dumps({"events": [event]}), encoding="utf-8")
    assert proof.load_events(api_path) == ([event], [])

    jsonl_path = tmp_path / "events.jsonl"
    jsonl_path.write_text(__import__("json").dumps(event) + "\n", encoding="utf-8")
    assert proof.load_events(jsonl_path) == ([event], [])
