from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_consoles_template_exposes_runtime_panel() -> None:
    source = (ROOT / "app/templates/consoles.html").read_text(encoding="utf-8")

    assert 'data-consoles-pane="runtime"' in source
    assert 'id="consoles-runtime-status-badge"' in source
    assert 'id="consoles-runtime-jobs"' in source
    assert 'id="consoles-runtime-timeline"' in source
    assert 'id="consoles-runtime-run-live"' in source
    assert 'id="consoles-runtime-confirm"' in source
    assert "Run dry goal" in source


def test_consoles_js_streams_runtime_events_and_controls_worker() -> None:
    source = (ROOT / "app/static/js/consoles.js").read_text(encoding="utf-8")

    assert "/api/v1/console-runtime/worker/status" in source
    assert "/api/v1/console-runtime/worker/control" in source
    assert "/api/v1/console-runtime/jobs" in source
    assert "/approval" in source
    assert "confirm_live_execution" in source
    assert "continuous: true" in source
    assert "max_steps: maxSteps" in source
    assert "goal_phase_sequence: ['plan', 'work', 'verify']" in source
    assert "cloud_token_budget: 0" in source
    assert '"model_selection": "warm_policy"' in source
    assert "goal_loop: true" in source
    assert "ENABLE LIVE RUNTIME" in source
    assert "function appendRuntimeEvent(event)" in source
    assert "compactRuntimeRouteSummary" in source
    assert "route_summary" in source
    assert "usage_ledger" in source
    assert "local_first_kpi" in source
    assert "local_first_proof" in source
    assert "local-first" in source
    assert "proof" in source
    assert "cloud llm" in source
    assert "cloud tok" in source
    assert "local_evidence_percent" in source
    assert "workers.by_id" in source
    assert "payload.norllama" in source
    assert "residency_posture" in source
    assert "prefetch_count" in source
    assert "behavior" in source
    assert "tool" in source
    assert "model" in source
    assert "planner" in source
    assert "approval" in source
    assert "goal" in source
    assert "policy" in source
    assert "route" in source
    assert "shell" in source


def test_consoles_css_marks_runtime_event_categories() -> None:
    source = (ROOT / "app/static/css/styles.css").read_text(encoding="utf-8")

    assert ".consoles-runtime-event--behavior" in source
    assert ".consoles-runtime-event--tool" in source
    assert ".consoles-runtime-event--model" in source
    assert ".consoles-runtime-event--planner" in source
    assert ".consoles-runtime-event--approval" in source
    assert ".consoles-runtime-event--goal" in source
    assert ".consoles-runtime-metric.is-warn" in source
    assert '[data-mobile-pane="runtime"] .consoles-col--runtime' in source
