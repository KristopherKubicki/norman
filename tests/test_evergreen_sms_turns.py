from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_sms_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_sms.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_console_sms_for_tests", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _turn(
    conversation_id: str,
    turn_id: str,
    sequence: int,
    message: str,
) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "sequence": sequence,
        "message": message,
        "callback_url": "http://127.0.0.1:8797/callbacks/sms",
        "callback_token": "callback-token",
        "source": {"message_sid": f"SM-{turn_id}"},
    }


def test_sms_turns_keep_distinct_codex_threads_per_conversation(tmp_path) -> None:
    module = _load_sms_module()
    executions: list[tuple[str, str, str]] = []

    def executor(turn: dict[str, Any], bbs_thread_id: str) -> dict[str, Any]:
        executions.append((turn["conversation_id"], turn["turn_id"], bbs_thread_id))
        return {
            "body": f"Reply for {turn['turn_id']}",
            "bbs_thread_id": bbs_thread_id or f"thread-{turn['conversation_id']}",
        }

    processor = module.SmsTurnProcessor(
        state_dir=tmp_path / "sms-turns",
        executor=executor,
        callback_sender=lambda *_args: None,
    )
    processor.submit(_turn("conv-a", "turn-a-1", 1, "first a"))
    processor.submit(_turn("conv-b", "turn-b-1", 1, "first b"))
    processor.process_pending()
    processor.submit(_turn("conv-a", "turn-a-2", 2, "second a"))
    processor.submit(_turn("conv-b", "turn-b-2", 2, "second b"))
    processor.process_pending()

    assert executions == [
        ("conv-a", "turn-a-1", ""),
        ("conv-b", "turn-b-1", ""),
        ("conv-a", "turn-a-2", "thread-conv-a"),
        ("conv-b", "turn-b-2", "thread-conv-b"),
    ]


def test_sms_turns_execute_one_conversation_in_sequence(tmp_path) -> None:
    module = _load_sms_module()
    executions: list[str] = []
    callbacks: list[str] = []

    def executor(turn: dict[str, Any], bbs_thread_id: str) -> dict[str, Any]:
        executions.append(turn["turn_id"])
        return {
            "body": f"Reply for {turn['turn_id']}",
            "bbs_thread_id": bbs_thread_id or "thread-conv-a",
        }

    processor = module.SmsTurnProcessor(
        state_dir=tmp_path / "sms-turns",
        executor=executor,
        callback_sender=lambda _url, _token, completion: callbacks.append(
            completion["turn_id"]
        ),
    )
    processor.submit(_turn("conv-a", "turn-a-1", 1, "first"))
    processor.submit(_turn("conv-a", "turn-a-2", 2, "second"))

    processor.process_pending()

    assert executions == ["turn-a-1"]
    assert callbacks == ["turn-a-1"]

    processor.process_pending()

    assert executions == ["turn-a-1", "turn-a-2"]
    assert callbacks == ["turn-a-1", "turn-a-2"]


def test_duplicate_sms_turn_submission_does_not_execute_again(tmp_path) -> None:
    module = _load_sms_module()
    executions: list[str] = []

    def executor(turn: dict[str, Any], bbs_thread_id: str) -> dict[str, Any]:
        executions.append(turn["turn_id"])
        return {"body": "Done.", "bbs_thread_id": bbs_thread_id or "thread-a"}

    processor = module.SmsTurnProcessor(
        state_dir=tmp_path / "sms-turns",
        executor=executor,
        callback_sender=lambda *_args: None,
    )
    payload = _turn("conv-a", "turn-a-1", 1, "retry me")

    assert processor.submit(payload) == processor.submit(payload)
    processor.process_pending()
    processor.process_pending()

    assert executions == ["turn-a-1"]


def test_sms_turn_restart_recovers_running_turn(tmp_path) -> None:
    module = _load_sms_module()
    processor = module.SmsTurnProcessor(
        state_dir=tmp_path / "sms-turns",
        executor=lambda *_args: {"body": "unused", "bbs_thread_id": "unused"},
        callback_sender=lambda *_args: None,
    )
    processor.submit(_turn("conv-a", "turn-a-1", 1, "recover me"))
    state = processor._load_conversation("conv-a")
    state["turns"][0]["status"] = "running"
    processor._write_conversation(state)
    executions: list[str] = []

    def executor(turn: dict[str, Any], bbs_thread_id: str) -> dict[str, Any]:
        executions.append(turn["turn_id"])
        return {"body": "Recovered.", "bbs_thread_id": bbs_thread_id or "thread-a"}

    restarted = module.SmsTurnProcessor(
        state_dir=tmp_path / "sms-turns",
        executor=executor,
        callback_sender=lambda *_args: None,
    )
    restarted.process_pending()

    persisted = restarted._load_conversation("conv-a")
    assert executions == ["turn-a-1"]
    assert persisted["turns"][0]["status"] == "completed"
    assert persisted["turns"][0]["attempts"] == 1


def test_sms_callback_failure_retries_without_rerunning_codex(tmp_path) -> None:
    module = _load_sms_module()
    now = [100.0]
    executions: list[str] = []
    callback_attempts: list[str] = []

    def executor(turn: dict[str, Any], bbs_thread_id: str) -> dict[str, Any]:
        executions.append(turn["turn_id"])
        return {"body": "Done.", "bbs_thread_id": bbs_thread_id or "thread-a"}

    def callback_sender(_url: str, _token: str, completion: dict[str, Any]) -> None:
        callback_attempts.append(completion["turn_id"])
        if len(callback_attempts) == 1:
            raise OSError("bridge is unavailable")

    processor = module.SmsTurnProcessor(
        state_dir=tmp_path / "sms-turns",
        executor=executor,
        callback_sender=callback_sender,
        callback_retry_seconds=10,
        clock=lambda: now[0],
    )
    processor.submit(_turn("conv-a", "turn-a-1", 1, "retry callback"))
    processor.process_pending()
    now[0] = 109
    processor.process_pending()
    now[0] = 110
    processor.process_pending()

    persisted = processor._load_conversation("conv-a")["turns"][0]
    assert executions == ["turn-a-1"]
    assert callback_attempts == ["turn-a-1", "turn-a-1"]
    assert persisted["callback_status"] == "sent"
    assert persisted["callback_attempts"] == 2


def test_sms_turn_processor_leaves_normal_ui_state_untouched(tmp_path) -> None:
    module = _load_sms_module()
    ui_thread = tmp_path / "thread-id.txt"
    ui_response = tmp_path / "last-response.txt"
    ui_thread.write_text("normal-ui-thread\n", encoding="utf-8")
    ui_response.write_text("normal response\n", encoding="utf-8")
    processor = module.SmsTurnProcessor(
        state_dir=tmp_path / "sms-turns",
        executor=lambda _turn, bbs_thread_id: {
            "body": "SMS only.",
            "bbs_thread_id": bbs_thread_id or "sms-thread",
        },
        callback_sender=lambda *_args: None,
    )
    processor.submit(_turn("conv-a", "turn-a-1", 1, "do not touch UI"))
    processor.process_pending()

    assert ui_thread.read_text(encoding="utf-8") == "normal-ui-thread\n"
    assert ui_response.read_text(encoding="utf-8") == "normal response\n"


def test_configured_callback_token_is_not_persisted_or_sent_in_turn_payload(
    monkeypatch, tmp_path
) -> None:
    module = _load_sms_module()
    sent: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setenv("NORMAN_CODEX_SMS_CALLBACK_TOKEN", "host-only-token")
    payload = _turn("conv-a", "turn-a-1", 1, "credential from host")
    payload.pop("callback_token")
    processor = module.SmsTurnProcessor(
        state_dir=tmp_path / "sms-turns",
        executor=lambda _turn, thread_id: {
            "body": "Done.",
            "bbs_thread_id": thread_id or "thread-a",
        },
        callback_sender=lambda url, token, completion: sent.append(
            (url, token, completion)
        ),
    )

    processor.submit(payload)
    processor.process_pending()

    persisted = (tmp_path / "sms-turns" / "conversations" / "conv-a.json").read_text(
        encoding="utf-8"
    )
    assert sent[0][1] == "host-only-token"
    assert "host-only-token" not in persisted
    assert "callback_token" not in persisted
