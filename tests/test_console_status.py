from app.services.console_status import classify_console_credit_assessment


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
