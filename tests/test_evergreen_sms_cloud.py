from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _load_conversation_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "projects"
        / "evergreen-sms-cloud"
        / "conversation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evergreen_sms_conversation_for_tests", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ConditionalFailure(RuntimeError):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class TransactionValidationFailure(RuntimeError):
    response = {
        "Error": {"Code": "TransactionCanceledException"},
        "CancellationReasons": [{"Code": "ValidationError"}],
    }


class MemoryTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.race_completion = False

    @staticmethod
    def _item_key(key: dict[str, str]) -> tuple[str, str]:
        return str(key["pk"]), str(key["sk"])

    def get_item(self, *, Key: dict[str, str], ConsistentRead: bool) -> dict[str, Any]:
        item = self.items.get(self._item_key(Key))
        return {"Item": copy.deepcopy(item)} if item else {}

    def put_item(
        self, *, Item: dict[str, Any], ConditionExpression: str | None = None
    ) -> None:
        key = self._item_key(Item)
        if ConditionExpression == "attribute_not_exists(pk)" and key in self.items:
            raise ConditionalFailure()
        self.items[key] = copy.deepcopy(Item)

    def update_item(
        self,
        *,
        Key: dict[str, str],
        UpdateExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        ConditionExpression: str | None = None,
        ExpressionAttributeNames: dict[str, str] | None = None,
    ) -> None:
        item = self.items[self._item_key(Key)]
        values = ExpressionAttributeValues
        if "completion = :completion" in UpdateExpression:
            if self.race_completion:
                item["completion"] = copy.deepcopy(values[":completion"])
                item["status"] = values[":status"]
                item["outbound_status"] = values[":outbound_status"]
                self.race_completion = False
                raise ConditionalFailure()
            if "completion" in item:
                raise ConditionalFailure()
            item["completion"] = copy.deepcopy(values[":completion"])
            item["status"] = values[":status"]
            item["updated_at"] = values[":updated_at"]
            item["outbound_status"] = values[":outbound_status"]
            return
        if "outbound_enqueued_at" in UpdateExpression:
            item["outbound_status"] = values[":status"]
            item["outbound_enqueued_at"] = values[":now"]
            return
        if "provider_sid = :provider_sid" in UpdateExpression:
            if (
                item.get("status") != values[":sending"]
                or item.get("lease_token") != values[":lease_token"]
            ):
                raise ConditionalFailure()
            item["status"] = values[":status"]
            item["provider_sid"] = values[":provider_sid"]
            item["sent_at"] = values[":sent_at"]
            return
        if "lease_expires_at = :lease_expires_at" in UpdateExpression:
            if (
                item.get("status") != values[":sending"]
                or int(item.get("lease_expires_at") or 0) > values[":now"]
            ):
                raise ConditionalFailure()
            item["status"] = values[":sending"]
            item["lease_token"] = values[":lease_token"]
            item["lease_expires_at"] = values[":lease_expires_at"]
            item["updated_at"] = values[":updated_at"]
            item["expires_at"] = values[":expires_at"]
            return
        raise AssertionError(f"unexpected update expression: {UpdateExpression}")


class ResourceTransactionClient:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    def transact_write_items(self, *, TransactItems: list[dict[str, Any]]) -> None:
        self.calls.append(copy.deepcopy(TransactItems))


class ResourceTransactionTable(MemoryTable):
    def __init__(self) -> None:
        super().__init__()
        self.name = "resource-style-table"
        self.client = ResourceTransactionClient()
        self.meta = SimpleNamespace(client=self.client)


def _turn(conversation_id: str = "conv-1", turn_id: str = "turn-1") -> dict[str, Any]:
    return {
        "pk": f"CONV#{conversation_id}",
        "sk": f"TURN#{turn_id}",
        "entity_type": "turn",
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "sequence": 1,
        "status": "claimed",
        "source": {
            "message_sid": "SM-1",
            "account_sid": "AC-1",
            "from": "+15550000001",
            "to": "+15550000002",
        },
    }


def _completion(body: str = "Done.") -> dict[str, Any]:
    return {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "sequence": 1,
        "status": "completed",
        "success": True,
        "body": body,
    }


def test_completion_race_is_idempotent_but_conflicting_callback_is_rejected() -> None:
    module = _load_conversation_module()
    table = MemoryTable()
    table.items[("CONV#conv-1", "TURN#turn-1")] = _turn()
    table.race_completion = True
    store = module.ConversationStore(table)

    outcome = store.record_completion(_completion())

    assert outcome["should_enqueue"] is True
    assert outcome["outbound_event"]["to"] == "+15550000001"
    assert outcome["outbound_event"]["from"] == "+15550000002"
    store.mark_outbound_enqueued("conv-1", "turn-1")
    assert store.record_completion(_completion())["should_enqueue"] is False

    with pytest.raises(ValueError, match="does not match"):
        store.record_completion(_completion("Different response."))


def test_outbound_lease_has_single_owner_and_requires_its_token(monkeypatch) -> None:
    module = _load_conversation_module()
    now = [100]
    monkeypatch.setattr(module, "now_epoch", lambda: now[0])
    table = MemoryTable()
    store = module.ConversationStore(table, outbound_lease_seconds=30)

    lease = store.begin_outbound("turn-1")

    assert lease
    assert store.begin_outbound("turn-1") is None
    with pytest.raises(ConditionalFailure):
        store.mark_outbound_sent("turn-1", "SM-outbound", "not-the-owner")
    store.mark_outbound_sent("turn-1", "SM-outbound", lease["lease_token"])
    assert store.begin_outbound("turn-1") is None

    table.items[("OUTBOUND#turn-2", "STATUS")] = {
        "pk": "OUTBOUND#turn-2",
        "sk": "STATUS",
        "turn_id": "turn-2",
        "status": "sending",
        "lease_token": "expired-owner",
        "lease_expires_at": 99,
    }
    replacement = store.begin_outbound("turn-2")

    assert replacement
    assert replacement["lease_token"] != "expired-owner"
    assert (
        table.items[("OUTBOUND#turn-2", "STATUS")]["lease_token"]
        == replacement["lease_token"]
    )


def test_transaction_validation_errors_are_not_retried_as_contention() -> None:
    module = _load_conversation_module()

    assert not module.ConversationStore._is_conditional_failure(
        TransactionValidationFailure()
    )


def test_new_inbound_transaction_uses_native_resource_client_values() -> None:
    module = _load_conversation_module()
    table = ResourceTransactionTable()
    store = module.ConversationStore(table)
    incoming = module.IncomingSms(
        message_sid="SM-resource-new",
        account_sid="AC-resource",
        from_number="+15550000001",
        to_number="+15550000002",
        body="First message",
        received_at=100,
    )

    outcome = store.accept_inbound(incoming, timestamp=100)

    assert outcome["should_dispatch"] is True
    transaction = table.client.calls[0]
    message = transaction[0]["Put"]["Item"]
    turn = transaction[1]["Put"]["Item"]
    state = transaction[2]["Put"]["Item"]
    assert isinstance(message["pk"], str)
    assert isinstance(turn["pk"], str)
    assert isinstance(state["pk"], str)
    assert state["version"] == 1


def test_buffer_merge_transaction_uses_native_resource_client_values() -> None:
    module = _load_conversation_module()
    table = ResourceTransactionTable()
    store = module.ConversationStore(table)
    initial = module.IncomingSms(
        message_sid="SM-resource-initial",
        account_sid="AC-resource",
        from_number="+15550000001",
        to_number="+15550000002",
        body="First message",
        received_at=100,
    )
    conversation_id = "conv-resource"
    turn_id = "turn-resource"
    pair_key = module.conversation_key(
        initial.account_sid, initial.to_number, initial.from_number
    )
    state = store._state_payload(
        pair_key=pair_key,
        conversation_id=conversation_id,
        turn_id=turn_id,
        sequence=1,
        timestamp=100,
        version=1,
    )
    turn = store._turn_payload(
        conversation_id=conversation_id,
        turn_id=turn_id,
        sequence=1,
        incoming=initial,
        timestamp=100,
    )
    table.items[(state["pk"], state["sk"])] = state
    table.items[(turn["pk"], turn["sk"])] = turn
    next_message = module.IncomingSms(
        message_sid="SM-resource-merged",
        account_sid=initial.account_sid,
        from_number=initial.from_number,
        to_number=initial.to_number,
        body="Second message",
        received_at=101,
    )

    outcome = store.accept_inbound(next_message, timestamp=101)

    assert outcome["should_dispatch"] is False
    transaction = table.client.calls[0]
    assert isinstance(transaction[0]["Put"]["Item"]["pk"], str)
    turn_update = transaction[1]["Update"]
    state_update = transaction[2]["Update"]
    assert turn_update["ExpressionAttributeValues"][":status"] == "buffering"
    assert state_update["ExpressionAttributeValues"][":old_version"] == 1


def test_inbound_retry_recovers_concurrent_duplicate_merged_message() -> None:
    module = _load_conversation_module()
    table = MemoryTable()
    store = module.ConversationStore(table)
    initial = module.IncomingSms(
        message_sid="SM-initial",
        account_sid="AC-1",
        from_number="+15550000001",
        to_number="+15550000002",
        body="First message",
        received_at=100,
    )
    pair_key = module.conversation_key(
        initial.account_sid, initial.to_number, initial.from_number
    )
    state = store._state_payload(
        pair_key=pair_key,
        conversation_id="conv-1",
        turn_id="turn-1",
        sequence=1,
        timestamp=100,
        version=1,
    )
    turn = store._turn_payload(
        conversation_id="conv-1",
        turn_id="turn-1",
        sequence=1,
        incoming=initial,
        timestamp=100,
    )
    table.items[(state["pk"], state["sk"])] = state
    table.items[(turn["pk"], turn["sk"])] = turn
    duplicate = module.IncomingSms(
        message_sid="SM-merged",
        account_sid=initial.account_sid,
        from_number=initial.from_number,
        to_number=initial.to_number,
        body="Second message",
        received_at=101,
    )
    append_attempts = 0

    def contend_once(**_kwargs: Any) -> bool:
        nonlocal append_attempts
        append_attempts += 1
        table.items[("MSG#SM-merged", "INBOUND")] = {
            "pk": "MSG#SM-merged",
            "sk": "INBOUND",
            "dispatch": {
                "conversation_id": "conv-1",
                "turn_id": "turn-1",
                "sequence": 1,
            },
            "dispatch_status": "merged",
            "delay_seconds": 0,
        }
        return False

    store._append_to_buffer = contend_once  # type: ignore[method-assign]

    outcome = store.accept_inbound(duplicate, timestamp=101)

    assert append_attempts == 1
    assert outcome == {
        "duplicate": True,
        "dispatch": {
            "conversation_id": "conv-1",
            "turn_id": "turn-1",
            "sequence": 1,
        },
        "should_dispatch": False,
        "delay_seconds": 0,
    }
