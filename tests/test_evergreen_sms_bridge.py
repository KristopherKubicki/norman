from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib import error, request

import pytest


def _load_bridge_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "projects"
        / "evergreen-sms-bridge"
        / "sms_bridge.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evergreen_sms_bridge_for_tests", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TurnsTable:
    def __init__(self, turn: dict[str, Any]) -> None:
        self.turn = dict(turn)

    def get_item(self, *, Key: dict[str, str], ConsistentRead: bool) -> dict[str, Any]:
        if (
            Key["pk"] == f"CONV#{self.turn['conversation_id']}"
            and Key["sk"] == f"TURN#{self.turn['turn_id']}"
        ):
            return {"Item": dict(self.turn)}
        return {}

    def update_item(self, **_kwargs: Any) -> None:
        self.turn["status"] = "claimed"


class BridgeSqs:
    def __init__(self) -> None:
        self.deleted: list[dict[str, str]] = []
        self.sent: list[dict[str, str]] = []
        self.fail_next_send = False

    def delete_message(self, **kwargs: str) -> None:
        self.deleted.append(kwargs)

    def send_message(self, **kwargs: str) -> dict[str, str]:
        if self.fail_next_send:
            self.fail_next_send = False
            raise OSError("completion queue unavailable")
        self.sent.append(kwargs)
        return {"MessageId": "completion-1"}


def _settings(module, state_dir: Path):
    return module.BridgeSettings(
        inbound_queue_url="https://sqs.example.invalid/inbound",
        completion_queue_url="https://sqs.example.invalid/completion",
        conversations_table="evergreen-sms-conversations",
        bbs_url="http://127.0.0.1:8796",
        bbs_token="bbs-token",
        callback_bind="127.0.0.1",
        callback_port=0,
        callback_url="http://127.0.0.1:8797/callbacks/sms",
        callback_token="callback-token",
        state_dir=state_dir,
        request_timeout_seconds=5,
        poll_wait_seconds=0,
        visibility_timeout_seconds=30,
        max_messages=1,
        outbox_retry_seconds=1,
        run_once=True,
    )


def _turn() -> dict[str, Any]:
    return {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "sequence": 1,
        "status": "buffering",
        "body": "Hello",
        "source": {
            "from": "+15550000001",
            "to": "+15550000002",
            "message_sid": "SM-1",
        },
    }


def _callback(sequence: int = 1, body: str = "Reply.") -> dict[str, Any]:
    return {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "sequence": sequence,
        "status": "completed",
        "success": True,
        "body": body,
        "bbs_thread_id": "thread-1",
    }


def test_bridge_deletes_inbound_sqs_only_after_durable_bbs_acceptance(
    monkeypatch, tmp_path
) -> None:
    module = _load_bridge_module()
    sqs = BridgeSqs()
    bridge = module.SmsBridge(
        _settings(module, tmp_path),
        sqs_client=sqs,
        turns_table=TurnsTable(_turn()),
    )

    def accepted_bbs(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["payload"]["turn_id"] == "turn-1"
        return {"accepted": True, "conversation_id": "conv-1", "turn_id": "turn-1"}

    monkeypatch.setattr(module, "post_bbs_turn", accepted_bbs)
    result = bridge.consume_inbound_sqs_message(
        {
            "ReceiptHandle": "receipt-1",
            "Body": json.dumps(
                {"conversation_id": "conv-1", "turn_id": "turn-1", "sequence": 1}
            ),
        }
    )

    assert result["bbs_status"] == "accepted"
    assert sqs.deleted == [
        {
            "QueueUrl": "https://sqs.example.invalid/inbound",
            "ReceiptHandle": "receipt-1",
        }
    ]
    assert module.read_json(bridge._turn_path("turn-1"))["bbs_status"] == "accepted"


def test_bridge_keeps_sqs_message_when_bbs_acceptance_fails(
    monkeypatch, tmp_path
) -> None:
    module = _load_bridge_module()
    sqs = BridgeSqs()
    bridge = module.SmsBridge(
        _settings(module, tmp_path),
        sqs_client=sqs,
        turns_table=TurnsTable(_turn()),
    )
    monkeypatch.setattr(
        module,
        "post_bbs_turn",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("BBS offline")),
    )

    with pytest.raises(OSError, match="BBS offline"):
        bridge.consume_inbound_sqs_message(
            {
                "ReceiptHandle": "receipt-1",
                "Body": json.dumps(
                    {"conversation_id": "conv-1", "turn_id": "turn-1", "sequence": 1}
                ),
            }
        )

    assert sqs.deleted == []


def test_bridge_normalizes_dynamodb_decimals_before_durable_write(
    monkeypatch, tmp_path
) -> None:
    module = _load_bridge_module()
    sqs = BridgeSqs()
    turn = _turn()
    turn.update(
        {
            "sequence": Decimal("1"),
            "received_at": Decimal("1700000000"),
            "messages": [
                {
                    "message_sid": "SM-1",
                    "body": "Hello",
                    "received_at": Decimal("1700000000"),
                }
            ],
        }
    )
    bridge = module.SmsBridge(
        _settings(module, tmp_path),
        sqs_client=sqs,
        turns_table=TurnsTable(turn),
    )
    monkeypatch.setattr(
        module,
        "post_bbs_turn",
        lambda **_kwargs: {
            "accepted": True,
            "conversation_id": "conv-1",
            "turn_id": "turn-1",
        },
    )

    bridge.consume_inbound_sqs_message(
        {
            "ReceiptHandle": "receipt-1",
            "Body": json.dumps(
                {"conversation_id": "conv-1", "turn_id": "turn-1", "sequence": 1}
            ),
        }
    )

    persisted = module.read_json(bridge._turn_path("turn-1"))
    assert persisted["turn"]["sequence"] == 1
    assert persisted["turn"]["received_at"] == 1700000000
    assert persisted["turn"]["messages"][0]["received_at"] == 1700000000


def test_bridge_callback_auth_correlation_and_outbox_retry(tmp_path) -> None:
    module = _load_bridge_module()
    sqs = BridgeSqs()
    bridge = module.SmsBridge(
        _settings(module, tmp_path),
        sqs_client=sqs,
        turns_table=TurnsTable(_turn()),
    )
    module.atomic_write_json(
        bridge._turn_path("turn-1"),
        {
            "conversation_id": "conv-1",
            "turn_id": "turn-1",
            "sequence": 1,
            "bbs_status": "accepted",
        },
    )
    server = module.start_callback_server(bridge)
    url = f"http://127.0.0.1:{server.server_address[1]}/callbacks/sms"

    def post(payload: dict[str, Any], token: str = "") -> tuple[int, dict[str, Any]]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=2) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        assert post(_callback()) == (403, {"ok": False, "error": "forbidden"})
        status, payload = post(_callback(sequence=2), "callback-token")
        assert status == 400
        assert payload["ok"] is False
        status, payload = post(_callback(), "callback-token")
        assert status == 202
        assert payload == {"ok": True, "turn_id": "turn-1", "outbox_status": "pending"}
        assert post(_callback(), "callback-token")[0] == 202
        status, payload = post(_callback(body="Conflicting reply."), "callback-token")
        assert status == 400
        assert payload["ok"] is False

        sqs.fail_next_send = True
        assert bridge.flush_completion_outbox() == 0
        assert bridge.flush_completion_outbox() == 1
    finally:
        server.shutdown()
        server.server_close()

    persisted = module.read_json(bridge._completion_path("turn-1"))
    assert persisted["outbox_status"] == "sent"
    assert persisted["attempts"] == 2
    assert len(sqs.sent) == 1


def test_bridge_does_not_send_callback_token_to_bbs() -> None:
    module = _load_bridge_module()
    turn = _turn()
    turn["callback_token"] = "never-forward-this"

    payload = module.bbs_turn_payload(
        turn=turn,
        callback_url="http://127.0.0.1:8797/callbacks/sms",
    )

    assert "callback_token" not in payload
    assert "never-forward-this" not in json.dumps(payload)


def test_legacy_installer_refuses_quoted_sms_mode(tmp_path) -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "projects"
        / "evergreen-sms-bridge"
        / "install.sh"
    )
    installer = tmp_path / "install.sh"
    shutil.copy2(source, installer)
    (tmp_path / ".env").write_text('DELIVERY_MODE="sms"\n', encoding="utf-8")

    completed = subprocess.run(
        ["bash", str(installer), "--legacy"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "Refusing to install DELIVERY_MODE=sms" in completed.stderr
