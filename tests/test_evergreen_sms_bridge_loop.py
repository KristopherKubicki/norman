from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_bridge():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "projects"
        / "evergreen-sms-bridge"
        / "run-consumer.py"
    )
    spec = importlib.util.spec_from_file_location("evergreen_sms_bridge", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collector_prompt_routes_network_sms_to_netops(monkeypatch) -> None:
    module = _load_bridge()
    monkeypatch.setenv("SMS_REPLY_MAX_CHARS", "180")
    monkeypatch.setenv("SMS_REPLY_MAX_SENTENCES", "2")
    monkeypatch.setenv("SMS_REPLY_MODE_LABEL", "Operator SMS for Norman")

    prompt = module.format_collector_message(
        {
            "from": "+15551230001",
            "to": "+15551230002",
            "message_sid": "SM-test",
            "body": "network: router DNS looks down",
        }
    )

    assert "Operator SMS for Norman." in prompt
    assert "Preferred handling: NetOps via Subprime." in prompt
    assert "Reply as Norman directly to the operator." in prompt
    assert "Plain text only." in prompt
    assert "network: router DNS looks down" in prompt


def test_build_outbound_reply_captures_structured_sms_response() -> None:
    module = _load_bridge()

    payload = module.build_outbound_reply(
        message={
            "from": "+15551230001",
            "to": "+15551230002",
            "message_sid": "SM-test",
            "account_sid": "AC-test",
            "profile_name": "operator-test",
            "body": "router DNS looks down",
        },
        collector_snapshot={
            "state": "ready",
            "last_prompt": "Incoming SMS: router DNS looks down",
            "last_response": (
                "SMS: NetOps has the DNS check. Watch the Norman TUI.\n"
                "WHY: Router and DNS terms matched the NetOps routing policy."
            ),
            "last_finished_at": 1_780_000_000,
        },
        max_chars=80,
        max_sentences=1,
    )

    assert payload["source"] == "evergreen-sms-bridge"
    assert payload["from"] == "+15551230002"
    assert payload["to"] == "+15551230001"
    assert payload["in_reply_to_message_sid"] == "SM-test"
    assert payload["body"] == "NetOps has the DNS check."
    assert payload["why"] == "Router and DNS terms matched the NetOps routing policy."
    assert payload["route_hint"]["lane"] == "NetOps via Subprime"


def test_await_collector_result_polls_until_sms_prompt_finishes(monkeypatch) -> None:
    module = _load_bridge()
    snapshots: list[dict[str, Any]] = [
        {
            "state": "running",
            "pending": True,
            "running_prompt": "Incoming SMS: network test",
            "last_prompt": "",
        },
        {
            "state": "ready",
            "pending": False,
            "running_prompt": "",
            "last_prompt": "Incoming SMS: network test",
            "last_response": "SMS: Done.",
        },
    ]

    def fake_fetch_collector_status(**_kwargs):
        return snapshots.pop(0)

    monkeypatch.setattr(module, "fetch_collector_status", fake_fetch_collector_status)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    result = module.await_collector_result(
        collector_url="http://127.0.0.1:8796",
        collector_token="test-token",
        timeout_sec=3,
        poll_interval_sec=1,
        prompt_markers=["Incoming SMS: network test"],
    )

    assert result["state"] == "ready"
    assert result["last_response"] == "SMS: Done."


def test_enqueue_outbound_reply_writes_expected_sqs_payload() -> None:
    module = _load_bridge()

    class FakeSqs:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def send_message(self, **kwargs):
            self.calls.append(kwargs)
            return {"MessageId": "message-1"}

    sqs = FakeSqs()
    payload = {
        "source": "evergreen-sms-bridge",
        "from": "+15551230002",
        "to": "+15551230001",
        "body": "Done.",
        "why": "Closed-loop SMS test.",
    }

    result = module.enqueue_outbound_reply(
        sqs_client=sqs,
        queue_url="https://sqs.example.invalid/outbound",
        payload=payload,
    )

    assert result["message_id"] == "message-1"
    assert result["to"] == "+15551230001"
    assert json.loads(sqs.calls[0]["MessageBody"]) == payload
