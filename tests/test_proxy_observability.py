from __future__ import annotations

import json

from app.services import proxy_observability


def _record_event(*, status: str = "success", error: dict | None = None) -> None:
    proxy_observability.record_proxy_event(
        endpoint="/v1/responses",
        method="POST",
        request_id=f"event-{status}",
        status=status,
        http_status=200 if status == "success" else 503,
        payload={
            "model": "norman-code",
            "input": "private prompt text must not be written",
        },
        error=error,
    )


def test_event_log_uses_the_state_directory_by_default(monkeypatch):
    monkeypatch.delenv(proxy_observability.EVENT_LOG_ENV, raising=False)

    assert proxy_observability._event_log_path() == (
        proxy_observability.DEFAULT_EVENT_LOG_PATH
    )


def test_event_log_can_be_explicitly_disabled(monkeypatch):
    monkeypatch.setenv(proxy_observability.EVENT_LOG_ENV, "OFF")

    assert proxy_observability._event_log_path() is None


def test_event_log_writes_jsonl_to_configured_path(tmp_path, monkeypatch):
    event_log = tmp_path / "proxy-events.jsonl"
    monkeypatch.setenv(proxy_observability.EVENT_LOG_ENV, str(event_log))
    proxy_observability.reset_proxy_events()

    _record_event()

    records = [
        json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["schema"] == "norman.proxy.event.v1"
    assert records[0]["prompt_sha256"]
    assert "private prompt text" not in event_log.read_text(encoding="utf-8")


def test_event_log_restores_bounded_events_after_a_facade_restart(
    tmp_path, monkeypatch
):
    event_log = tmp_path / "proxy-events.jsonl"
    monkeypatch.setenv(proxy_observability.EVENT_LOG_ENV, str(event_log))
    proxy_observability.reset_proxy_events()

    _record_event(
        status="local_timeout",
        error={
            "code": "local_model_timeout",
            "norman": {
                "selected_model": "qwen3-coder:30b-a3b-q4_K_M",
                "retryable": True,
            },
        },
    )
    proxy_observability.reset_proxy_events()

    assert proxy_observability.proxy_events_snapshot() == []
    assert proxy_observability.restore_proxy_events_from_log(force=True) == 1
    restored = proxy_observability.proxy_events_snapshot()
    assert len(restored) == 1
    assert restored[0]["selected_model"] == "qwen3-coder:30b-a3b-q4_K_M"
    assert restored[0]["error_code"] == "local_model_timeout"


def test_event_log_rotates_to_one_prior_generation(tmp_path, monkeypatch):
    event_log = tmp_path / "proxy-events.jsonl"
    monkeypatch.setenv(proxy_observability.EVENT_LOG_ENV, str(event_log))
    monkeypatch.setenv(proxy_observability.EVENT_LOG_MAX_BYTES_ENV, "4096")
    proxy_observability.reset_proxy_events()

    for index in range(12):
        proxy_observability.record_proxy_event(
            endpoint="/v1/responses",
            method="POST",
            request_id=f"rotation-{index}",
            status="success",
            http_status=200,
            payload={"model": "norman-code", "input": f"prompt {index}"},
        )

    prior = event_log.with_name(f"{event_log.name}.1")
    assert event_log.exists()
    assert prior.exists()
    assert event_log.stat().st_size <= 4096
    assert prior.stat().st_size <= 4096
    assert len(event_log.read_text(encoding="utf-8").splitlines()) >= 1
    assert len(prior.read_text(encoding="utf-8").splitlines()) >= 1


def test_capacity_timeout_and_gateway_errors_are_counted_and_alerted(monkeypatch):
    monkeypatch.setenv(proxy_observability.EVENT_LOG_ENV, "0")
    proxy_observability.reset_proxy_events()

    _record_event(
        status="capacity_unavailable",
        error={"code": "local_capacity_unavailable"},
    )
    _record_event(
        status="local_timeout",
        error={"code": "local_model_timeout"},
    )
    _record_event(
        status="local_gateway_error",
        error={"code": "local_gateway_unreachable"},
    )

    summary = proxy_observability.proxy_observability_summary()
    alert_kinds = {alert["kind"] for alert in summary["alerts"]}

    assert summary["capacity_unavailable_count"] == 1
    assert summary["local_timeout_count"] == 1
    assert summary["local_gateway_error_count"] == 1
    assert "proxy_local_capacity_unavailable" in alert_kinds
    assert "proxy_local_model_timeouts" in alert_kinds
    assert "proxy_local_gateway_errors" in alert_kinds
