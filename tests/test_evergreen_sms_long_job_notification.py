from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_sender():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "projects"
        / "evergreen-sms-bridge"
        / "enqueue-outbound-notification.py"
    )
    spec = importlib.util.spec_from_file_location(
        "enqueue_outbound_notification", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_notification_body_uses_safe_long_job_summary() -> None:
    module = _load_sender()

    body = module.notification_body(
        {
            "agent": "Panelbot",
            "status": "completed",
            "duration_label": "1h 12m",
        }
    )

    assert (
        body == "Panelbot finished after 1h 12m: completed. Open the TUI for details."
    )


def test_outbound_payload_can_infer_reply_route_from_spool(
    monkeypatch, tmp_path
) -> None:
    module = _load_sender()
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "message.json").write_text(
        json.dumps({"message": {"from": "inbound-sender", "to": "sms-bridge"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SPOOL_DIR", str(spool))
    monkeypatch.delenv("SMS_NOTIFY_FROM", raising=False)
    monkeypatch.delenv("SMS_NOTIFY_TO", raising=False)

    payload = module.build_outbound_payload(
        {
            "type": "codex.long_job.completed",
            "agent": "Panelbot",
            "host": "work-special",
            "status": "completed",
            "duration_label": "1h 12m",
            "duration_seconds": 4320,
        }
    )

    assert payload["from"] == "sms-bridge"
    assert payload["to"] == "inbound-sender"
    assert payload["body"].startswith("Panelbot finished after 1h 12m")
    assert payload["notification"]["host"] == "work-special"


def test_load_env_file_does_not_override_existing_environment(
    monkeypatch, tmp_path
) -> None:
    module = _load_sender()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SMS_NOTIFY_TO=configured-recipient\nSMS_NOTIFY_FROM=configured-sender\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SMS_NOTIFY_TO", "existing-recipient")
    monkeypatch.delenv("SMS_NOTIFY_FROM", raising=False)

    module.load_env_file(env_path)

    assert os.environ["SMS_NOTIFY_TO"] == "existing-recipient"
    assert os.environ["SMS_NOTIFY_FROM"] == "configured-sender"
