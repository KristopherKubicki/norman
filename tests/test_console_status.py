import json

from app.services.console_status import (
    classify_console_credit_assessment,
    console_audit_url,
    console_status_url,
    fetch_console_audit,
    console_usage_state,
)


def test_classify_console_credit_assessment_detects_usage_limit() -> None:
    assessment = classify_console_credit_assessment(
        {
            "status_message": "You've hit your usage limit. To get more access now, send a request to your admin or try again at Apr 8th, 2026 9:54 AM.",
            "last_error": "",
            "default_speed": "balanced",
            "pending": False,
            "queue_depth": 0,
            "state": "ok",
        }
    )
    assert assessment.issue_code == "needs_billing"
    assert assessment.billing_url
    assert assessment.limits_url


def test_classify_console_credit_assessment_flags_fast_idle_bot() -> None:
    assessment = classify_console_credit_assessment(
        {
            "status_message": "Ready.",
            "last_error": "",
            "default_speed": "fast",
            "pending": False,
            "queue_depth": 0,
            "state": "ok",
        }
    )
    assert assessment.recommended_speed == "balanced"
    assert "preserve quota" in assessment.recommended_speed_reason.lower()


def test_console_usage_state_flattens_snapshot_usage() -> None:
    usage = console_usage_state(
        {
            "usage": {
                "tracked": True,
                "window_seconds": 86400,
                "totals": {
                    "turns": 9,
                    "successful_turns": 8,
                    "failed_turns": 1,
                    "input_tokens": 1200,
                    "cached_input_tokens": 400,
                    "output_tokens": 180,
                    "total_tokens": 1380,
                },
                "last_24h": {
                    "turns": 4,
                    "input_tokens": 700,
                    "cached_input_tokens": 200,
                    "output_tokens": 90,
                    "total_tokens": 790,
                },
                "last_turn": {
                    "finished_at": 1234567890,
                    "total_tokens": 111,
                },
            }
        }
    )

    assert usage["usage_tracked"] is True
    assert usage["usage_turns"] == 9
    assert usage["usage_total_tokens"] == 1380
    assert usage["usage_window_turns"] == 4
    assert usage["usage_window_total_tokens"] == 790
    assert usage["usage_last_turn_at"] == 1234567890
    assert usage["usage_last_turn_total_tokens"] == 111


def test_console_audit_url_preserves_token_and_since() -> None:
    url = console_audit_url(
        "https://keystone.home.arpa/?token=test-token",
        since_ts=123,
        limit=50,
    )
    assert (
        url
        == "https://keystone.home.arpa/api/audit?token=test-token&since=123&limit=50"
    )


def test_console_audit_url_accepts_explicit_access_token() -> None:
    url = console_audit_url(
        "https://keystone.home.arpa/",
        since_ts=123,
        limit=50,
        access_token="collector-token",
    )
    assert (
        url
        == "https://keystone.home.arpa/api/audit?token=collector-token&since=123&limit=50"
    )


def test_console_status_url_accepts_explicit_access_token() -> None:
    url = console_status_url(
        "https://keystone.home.arpa/",
        access_token="collector-token",
    )
    assert url == "https://keystone.home.arpa/api/status?token=collector-token"


def test_fetch_console_audit_normalizes_payload(monkeypatch) -> None:
    body = {
        "count": 1,
        "items": [
            {
                "id": "evt-1",
                "event_type": "chat.completed",
                "summary": "Done",
                "event_at": 123,
            }
        ],
        "session_name": "keystone-codex",
        "agent_name": "Keystone",
        "host_name": "private-host",
        "ui_version": "2026.04.08.1",
    }

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(body).encode("utf-8")

    monkeypatch.setattr(
        "app.services.console_status.urlopen", lambda *args, **kwargs: _Resp()
    )

    payload = fetch_console_audit(
        "https://keystone.home.arpa/?token=test-token",
        since_ts=100,
        limit=25,
    )

    assert payload["reachable"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["id"] == "evt-1"
    assert payload["agent_name"] == "Keystone"


def test_fetch_console_audit_uses_explicit_access_token(monkeypatch) -> None:
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"count": 0, "items": []}).encode("utf-8")

    def _fake_urlopen(request, **kwargs):
        seen["url"] = request.full_url
        return _Resp()

    monkeypatch.setattr("app.services.console_status.urlopen", _fake_urlopen)

    fetch_console_audit(
        "https://keystone.home.arpa/",
        since_ts=100,
        limit=25,
        access_token="collector-token",
    )

    assert seen["url"] == (
        "https://keystone.home.arpa/api/audit"
        "?token=collector-token&since=100&limit=25"
    )
