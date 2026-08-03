"""Durable DynamoDB state for the Evergreen SMS conversation pipeline.

The table uses a composite key:

* ``KEY#<sha256(account,to,from)>`` / ``STATE`` identifies the active
  conversation for a phone-number pair.
* ``CONV#<conversation_id>`` / ``TURN#<turn_id>`` stores each BBS turn.
* ``MSG#<twilio_message_sid>`` / ``INBOUND`` makes Twilio retries idempotent.

The bridge receives a delayed SQS job for the first text in a burst. It loads
the turn record before submitting to the BBS, so later texts merged into that
burst are included even though the original SQS body is intentionally stale.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any


DEFAULT_IDLE_SECONDS = 24 * 60 * 60
DEFAULT_BURST_SECONDS = 8
DEFAULT_TTL_SECONDS = 31 * 24 * 60 * 60
DEFAULT_OUTBOUND_LEASE_SECONDS = 90


def now_epoch() -> int:
    return int(time.time())


def conversation_key(account_sid: str, destination: str, sender: str) -> str:
    """Return a stable, non-phone-number DynamoDB partition suffix."""
    source = "\x1f".join(
        [
            str(account_sid or "").strip(),
            str(destination or "").strip(),
            str(sender or "").strip(),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def new_conversation_id() -> str:
    return f"conv-{uuid.uuid4().hex}"


def new_turn_id() -> str:
    return f"turn-{uuid.uuid4().hex}"


def is_new_conversation_command(body: str) -> bool:
    return str(body or "").strip().lower() == "/new"


def joined_turn_body(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(message.get("body") or "").strip()
        for message in messages
        if str(message.get("body") or "").strip()
    ).strip()


@dataclass(frozen=True)
class IncomingSms:
    message_sid: str
    account_sid: str
    from_number: str
    to_number: str
    body: str
    received_at: int
    profile_name: str = ""

    @property
    def source(self) -> dict[str, Any]:
        return {
            "message_sid": self.message_sid,
            "account_sid": self.account_sid,
            "from": self.from_number,
            "to": self.to_number,
            "body": self.body,
            "received_at": self.received_at,
            "profile_name": self.profile_name,
        }

    @property
    def message_fragment(self) -> dict[str, Any]:
        return {
            "message_sid": self.message_sid,
            "body": self.body,
            "received_at": self.received_at,
        }


class ConversationStore:
    """DynamoDB-backed SMS state with conditional, retry-safe mutations."""

    def __init__(
        self,
        table: Any,
        *,
        idle_seconds: int = DEFAULT_IDLE_SECONDS,
        burst_seconds: int = DEFAULT_BURST_SECONDS,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        outbound_lease_seconds: int = DEFAULT_OUTBOUND_LEASE_SECONDS,
    ) -> None:
        self.table = table
        self.table_name = str(getattr(table, "name", "") or "")
        self.idle_seconds = max(60, int(idle_seconds))
        self.burst_seconds = max(1, min(900, int(burst_seconds)))
        self.ttl_seconds = max(3600, int(ttl_seconds))
        self.outbound_lease_seconds = max(30, int(outbound_lease_seconds))

    @staticmethod
    def _state_key(pair_key: str) -> dict[str, str]:
        return {"pk": f"KEY#{pair_key}", "sk": "STATE"}

    @staticmethod
    def _turn_key(conversation_id: str, turn_id: str) -> dict[str, str]:
        return {"pk": f"CONV#{conversation_id}", "sk": f"TURN#{turn_id}"}

    @staticmethod
    def _message_key(message_sid: str) -> dict[str, str]:
        return {"pk": f"MSG#{message_sid}", "sk": "INBOUND"}

    @staticmethod
    def _outbound_key(turn_id: str) -> dict[str, str]:
        return {"pk": f"OUTBOUND#{turn_id}", "sk": "STATUS"}

    def _get(self, key: dict[str, str]) -> dict[str, Any] | None:
        response = self.table.get_item(Key=key, ConsistentRead=True)
        item = response.get("Item")
        return item if isinstance(item, dict) else None

    @staticmethod
    def _is_conditional_failure(exc: Exception) -> bool:
        response = getattr(exc, "response", {}) or {}
        error = response.get("Error") if isinstance(response, dict) else {}
        code = str((error or {}).get("Code") or "")
        if code == "ConditionalCheckFailedException":
            return True
        if code != "TransactionCanceledException":
            return False
        reasons = response.get("CancellationReasons")
        if not isinstance(reasons, list) or not reasons:
            return False
        return all(
            isinstance(reason, dict)
            and str((reason or {}).get("Code") or "")
            in {"", "None", "ConditionalCheckFailed", "TransactionConflict"}
            for reason in reasons
        )

    def _put_if_absent(self, item: dict[str, Any]) -> bool:
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
            return True
        except Exception as exc:
            if self._is_conditional_failure(exc):
                return False
            raise

    def _state_is_stale(self, state: dict[str, Any], timestamp: int) -> bool:
        return timestamp - int(state.get("last_message_at") or 0) >= self.idle_seconds

    def _turn_payload(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        sequence: int,
        incoming: IncomingSms,
        timestamp: int,
    ) -> dict[str, Any]:
        messages = [incoming.message_fragment]
        return {
            **self._turn_key(conversation_id, turn_id),
            "entity_type": "turn",
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "sequence": sequence,
            "status": "buffering",
            "messages": messages,
            "body": joined_turn_body(messages),
            "source": incoming.source,
            "created_at": timestamp,
            "updated_at": timestamp,
            "last_message_at": timestamp,
            "buffering_until": timestamp + self.burst_seconds,
            "expires_at": timestamp + self.ttl_seconds,
        }

    def _state_payload(
        self,
        *,
        pair_key: str,
        conversation_id: str,
        turn_id: str,
        sequence: int,
        timestamp: int,
        version: int,
        status: str = "buffering",
    ) -> dict[str, Any]:
        return {
            **self._state_key(pair_key),
            "entity_type": "conversation_state",
            "conversation_id": conversation_id,
            "latest_turn_id": turn_id,
            "latest_turn_status": status,
            "next_sequence": sequence,
            "last_message_at": timestamp,
            "version": version,
            "expires_at": timestamp + self.ttl_seconds,
        }

    def _queue_event(self, turn: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source": "evergreen-sms-inbound",
            "conversation_id": turn["conversation_id"],
            "turn_id": turn["turn_id"],
            "sequence": int(turn["sequence"]),
            "source_message_sid": str(
                (turn.get("source") or {}).get("message_sid") or ""
            ),
        }

    def accept_inbound(
        self, incoming: IncomingSms, *, timestamp: int | None = None
    ) -> dict[str, Any]:
        """Persist one inbound SMS and return the delayed queue work, if any.

        A duplicate Twilio delivery returns the original dispatch record. The
        caller must resend it when its dispatch state is still pending; this
        avoids losing a text between DynamoDB persistence and SQS acceptance.
        """
        timestamp = now_epoch() if timestamp is None else int(timestamp)
        existing_message = self._get(self._message_key(incoming.message_sid))
        if existing_message:
            return self._duplicate_acceptance(existing_message)

        pair_key = conversation_key(
            incoming.account_sid, incoming.to_number, incoming.from_number
        )
        for attempt in range(8):
            if attempt:
                # A competing Twilio delivery may have committed the message
                # between the prior transaction and this retry. Re-read its
                # idempotency record before attempting another mutation.
                existing_message = self._get(self._message_key(incoming.message_sid))
                if existing_message:
                    return self._duplicate_acceptance(existing_message)
                time.sleep(min(0.01 * (2 ** (attempt - 1)), 0.25))
            state = self._get(self._state_key(pair_key))
            create_new_conversation = (
                not state
                or self._state_is_stale(state, timestamp)
                or is_new_conversation_command(incoming.body)
            )
            if create_new_conversation:
                conversation_id = new_conversation_id()
                turn_id = new_turn_id()
                sequence = 1
                state_version = int((state or {}).get("version") or 0) + 1
                turn = self._turn_payload(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    sequence=sequence,
                    incoming=incoming,
                    timestamp=timestamp,
                )
                dispatch = self._queue_event(turn)
                message_item = {
                    **self._message_key(incoming.message_sid),
                    "entity_type": "inbound_message",
                    "message_sid": incoming.message_sid,
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "dispatch": dispatch,
                    "dispatch_status": "pending",
                    "delay_seconds": self.burst_seconds,
                    "received_at": timestamp,
                    "expires_at": timestamp + self.ttl_seconds,
                }
                desired_state = self._state_payload(
                    pair_key=pair_key,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    version=state_version,
                )
                if self._write_new_turn(
                    existing_state=state,
                    state=desired_state,
                    turn=turn,
                    message=message_item,
                ):
                    return {
                        "duplicate": False,
                        "dispatch": dispatch,
                        "should_dispatch": True,
                        "delay_seconds": self.burst_seconds,
                    }
                continue

            assert state is not None
            current_conversation_id = str(state.get("conversation_id") or "")
            current_turn_id = str(state.get("latest_turn_id") or "")
            current_status = str(state.get("latest_turn_status") or "")
            current_turn = (
                self._get(self._turn_key(current_conversation_id, current_turn_id))
                if current_conversation_id and current_turn_id
                else None
            )
            can_merge = (
                current_status == "buffering"
                and current_turn is not None
                and str(current_turn.get("status") or "") == "buffering"
                and int(current_turn.get("buffering_until") or 0) >= timestamp
            )
            if can_merge:
                if self._append_to_buffer(
                    pair_key=pair_key,
                    state=state,
                    turn=current_turn,
                    incoming=incoming,
                    timestamp=timestamp,
                ):
                    return {
                        "duplicate": False,
                        "dispatch": self._queue_event(current_turn),
                        "should_dispatch": False,
                        "delay_seconds": 0,
                    }
                continue

            conversation_id = current_conversation_id
            turn_id = new_turn_id()
            sequence = int(state.get("next_sequence") or 0) + 1
            turn = self._turn_payload(
                conversation_id=conversation_id,
                turn_id=turn_id,
                sequence=sequence,
                incoming=incoming,
                timestamp=timestamp,
            )
            dispatch = self._queue_event(turn)
            message_item = {
                **self._message_key(incoming.message_sid),
                "entity_type": "inbound_message",
                "message_sid": incoming.message_sid,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "dispatch": dispatch,
                "dispatch_status": "pending",
                "delay_seconds": self.burst_seconds,
                "received_at": timestamp,
                "expires_at": timestamp + self.ttl_seconds,
            }
            desired_state = self._state_payload(
                pair_key=pair_key,
                conversation_id=conversation_id,
                turn_id=turn_id,
                sequence=sequence,
                timestamp=timestamp,
                version=int(state.get("version") or 0) + 1,
            )
            if self._write_new_turn(
                existing_state=state,
                state=desired_state,
                turn=turn,
                message=message_item,
            ):
                return {
                    "duplicate": False,
                    "dispatch": dispatch,
                    "should_dispatch": True,
                    "delay_seconds": self.burst_seconds,
                }

        raise RuntimeError("SMS conversation state was too contended; retry delivery")

    @staticmethod
    def _duplicate_acceptance(existing_message: dict[str, Any]) -> dict[str, Any]:
        dispatch_status = str(existing_message.get("dispatch_status") or "pending")
        return {
            "duplicate": True,
            "dispatch": dict(existing_message.get("dispatch") or {}),
            # Only the first message in a new turn has a pending SQS dispatch.
            # A duplicate of a merged message must not wake the bridge early.
            "should_dispatch": dispatch_status == "pending",
            "delay_seconds": int(existing_message.get("delay_seconds") or 0),
        }

    def _write_new_turn(
        self,
        *,
        existing_state: dict[str, Any] | None,
        state: dict[str, Any],
        turn: dict[str, Any],
        message: dict[str, Any],
    ) -> bool:
        """Use conditional writes so Twilio retries cannot create another turn."""
        client = getattr(getattr(self.table, "meta", None), "client", None)
        if client is not None and self.table_name:
            try:
                state_condition = "attribute_not_exists(pk)"
                state_names: dict[str, str] = {}
                state_values: dict[str, Any] = {}
                if existing_state is not None:
                    state_condition = "#version = :version"
                    state_names = {"#version": "version"}
                    state_values = {":version": int(existing_state.get("version") or 0)}

                # Table.meta.client is the DynamoDB resource client. It performs
                # its own type conversion, so transaction values must remain
                # native Python values here.
                client.transact_write_items(
                    TransactItems=[
                        {
                            "Put": {
                                "TableName": self.table_name,
                                "Item": message,
                                "ConditionExpression": "attribute_not_exists(pk)",
                            }
                        },
                        {
                            "Put": {
                                "TableName": self.table_name,
                                "Item": turn,
                                "ConditionExpression": "attribute_not_exists(pk)",
                            }
                        },
                        {
                            "Put": {
                                "TableName": self.table_name,
                                "Item": state,
                                "ConditionExpression": state_condition,
                                **(
                                    {
                                        "ExpressionAttributeNames": state_names,
                                        "ExpressionAttributeValues": state_values,
                                    }
                                    if state_names
                                    else {}
                                ),
                            }
                        },
                    ]
                )
                return True
            except Exception as exc:
                if self._is_conditional_failure(exc):
                    return False
                raise

        # Local test doubles do not expose the low-level transaction client.
        # They retain the same conditional checks, while Lambda always takes
        # the transaction path above.
        try:
            self.table.put_item(
                Item=message, ConditionExpression="attribute_not_exists(pk)"
            )
            self.table.put_item(
                Item=turn, ConditionExpression="attribute_not_exists(pk)"
            )
            if existing_state is None:
                self.table.put_item(
                    Item=state, ConditionExpression="attribute_not_exists(pk)"
                )
            else:
                self.table.put_item(
                    Item=state,
                    ConditionExpression="#version = :version",
                    ExpressionAttributeNames={"#version": "version"},
                    ExpressionAttributeValues={
                        ":version": int(existing_state.get("version") or 0)
                    },
                )
            return True
        except Exception as exc:
            if self._is_conditional_failure(exc):
                return False
            raise

    def _append_to_buffer(
        self,
        *,
        pair_key: str,
        state: dict[str, Any],
        turn: dict[str, Any],
        incoming: IncomingSms,
        timestamp: int,
    ) -> bool:
        messages = list(turn.get("messages") or []) + [incoming.message_fragment]
        message = {
            **self._message_key(incoming.message_sid),
            "entity_type": "inbound_message",
            "message_sid": incoming.message_sid,
            "conversation_id": turn["conversation_id"],
            "turn_id": turn["turn_id"],
            "dispatch": self._queue_event(turn),
            "dispatch_status": "merged",
            "delay_seconds": 0,
            "received_at": timestamp,
            "expires_at": timestamp + self.ttl_seconds,
        }
        client = getattr(getattr(self.table, "meta", None), "client", None)
        if client is not None and self.table_name:
            try:
                client.transact_write_items(
                    TransactItems=[
                        {
                            "Put": {
                                "TableName": self.table_name,
                                "Item": message,
                                "ConditionExpression": "attribute_not_exists(pk)",
                            }
                        },
                        {
                            "Update": {
                                "TableName": self.table_name,
                                "Key": self._turn_key(
                                    turn["conversation_id"], turn["turn_id"]
                                ),
                                "UpdateExpression": (
                                    "SET messages = :messages, body = :body, "
                                    "updated_at = :updated_at, "
                                    "last_message_at = :last_message_at"
                                ),
                                "ConditionExpression": (
                                    "#status = :status AND buffering_until >= :now"
                                ),
                                "ExpressionAttributeNames": {"#status": "status"},
                                "ExpressionAttributeValues": {
                                    ":messages": messages,
                                    ":body": joined_turn_body(messages),
                                    ":updated_at": timestamp,
                                    ":last_message_at": timestamp,
                                    ":status": "buffering",
                                    ":now": timestamp,
                                },
                            }
                        },
                        {
                            "Update": {
                                "TableName": self.table_name,
                                "Key": self._state_key(pair_key),
                                "UpdateExpression": (
                                    "SET last_message_at = :last_message_at, "
                                    "expires_at = :expires_at, "
                                    "#version = :new_version"
                                ),
                                "ConditionExpression": (
                                    "#version = :old_version "
                                    "AND latest_turn_id = :turn_id"
                                ),
                                "ExpressionAttributeNames": {"#version": "version"},
                                "ExpressionAttributeValues": {
                                    ":last_message_at": timestamp,
                                    ":expires_at": timestamp + self.ttl_seconds,
                                    ":new_version": int(state.get("version") or 0) + 1,
                                    ":old_version": int(state.get("version") or 0),
                                    ":turn_id": turn["turn_id"],
                                },
                            }
                        },
                    ]
                )
                return True
            except Exception as exc:
                if self._is_conditional_failure(exc):
                    return False
                raise

        try:
            self.table.put_item(
                Item=message, ConditionExpression="attribute_not_exists(pk)"
            )
            self.table.update_item(
                Key=self._turn_key(turn["conversation_id"], turn["turn_id"]),
                UpdateExpression=(
                    "SET messages = :messages, body = :body, "
                    "updated_at = :updated_at, last_message_at = :last_message_at"
                ),
                ConditionExpression="#status = :status AND buffering_until >= :now",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":messages": messages,
                    ":body": joined_turn_body(messages),
                    ":updated_at": timestamp,
                    ":last_message_at": timestamp,
                    ":status": "buffering",
                    ":now": timestamp,
                },
            )
            self.table.update_item(
                Key=self._state_key(pair_key),
                UpdateExpression=(
                    "SET last_message_at = :last_message_at, "
                    "expires_at = :expires_at, #version = :new_version"
                ),
                ConditionExpression="#version = :old_version AND latest_turn_id = :turn_id",
                ExpressionAttributeNames={"#version": "version"},
                ExpressionAttributeValues={
                    ":last_message_at": timestamp,
                    ":expires_at": timestamp + self.ttl_seconds,
                    ":new_version": int(state.get("version") or 0) + 1,
                    ":old_version": int(state.get("version") or 0),
                    ":turn_id": turn["turn_id"],
                },
            )
            return True
        except Exception as exc:
            if self._is_conditional_failure(exc):
                return False
            raise

    def mark_inbound_dispatched(self, dispatch: dict[str, Any]) -> None:
        source_message_sid = str(dispatch.get("source_message_sid") or "")
        if not source_message_sid:
            return
        self.table.update_item(
            Key=self._message_key(source_message_sid),
            UpdateExpression="SET dispatch_status = :status, dispatched_at = :now",
            ExpressionAttributeValues={
                ":status": "dispatched",
                ":now": now_epoch(),
            },
        )

    def load_turn(self, conversation_id: str, turn_id: str) -> dict[str, Any] | None:
        return self._get(self._turn_key(conversation_id, turn_id))

    def claim_turn(
        self, conversation_id: str, turn_id: str, *, claimed_at: int | None = None
    ) -> dict[str, Any] | None:
        """Mark a buffered turn claimed before the bridge calls the BBS."""
        claimed_at = now_epoch() if claimed_at is None else int(claimed_at)
        turn = self.load_turn(conversation_id, turn_id)
        if not turn:
            return None
        if str(turn.get("status") or "") not in {"buffering", "claimed"}:
            return turn
        try:
            self.table.update_item(
                Key=self._turn_key(conversation_id, turn_id),
                UpdateExpression=(
                    "SET #status = :claimed, claimed_at = :claimed_at, "
                    "updated_at = :claimed_at"
                ),
                ConditionExpression="#status IN (:buffering, :claimed)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":claimed": "claimed",
                    ":buffering": "buffering",
                    ":claimed_at": claimed_at,
                },
            )
        except Exception as exc:
            if not self._is_conditional_failure(exc):
                raise
        return self.load_turn(conversation_id, turn_id)

    def record_completion(self, completion: dict[str, Any]) -> dict[str, Any]:
        """Persist a bridge callback and return the outbound event to enqueue."""
        conversation_id = str(completion.get("conversation_id") or "")
        turn_id = str(completion.get("turn_id") or "")
        if not conversation_id or not turn_id:
            raise ValueError("completion must include conversation_id and turn_id")
        try:
            sequence = int(completion.get("sequence") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("completion sequence must be a positive integer") from exc
        if sequence <= 0:
            raise ValueError("completion sequence must be a positive integer")
        success = completion.get("success")
        if not isinstance(success, bool):
            raise ValueError("completion success must be a boolean")
        status = str(completion.get("status") or "")
        expected_status = "completed" if success else "failed"
        if status != expected_status:
            raise ValueError("completion status does not match success")
        body = str(completion.get("body") or "").strip()
        if not body:
            raise ValueError("completion body is required")
        incoming_completion = dict(completion)
        incoming_completion.update(
            {
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "sequence": sequence,
                "status": status,
                "success": success,
                "body": body,
            }
        )
        turn = self.load_turn(conversation_id, turn_id)
        if not turn:
            raise ValueError("completion references an unknown SMS turn")
        if int(turn.get("sequence") or 0) != sequence:
            raise ValueError("completion sequence does not match turn")

        existing = turn.get("completion")
        if isinstance(existing, dict):
            if not self._completion_matches(existing, incoming_completion):
                raise ValueError("stored completion does not match callback")
        else:
            try:
                self.table.update_item(
                    Key=self._turn_key(conversation_id, turn_id),
                    UpdateExpression=(
                        "SET completion = :completion, #status = :status, "
                        "updated_at = :updated_at, outbound_status = :outbound_status"
                    ),
                    ConditionExpression="attribute_not_exists(completion)",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":completion": incoming_completion,
                        ":status": status,
                        ":updated_at": now_epoch(),
                        ":outbound_status": "pending",
                    },
                )
            except Exception as exc:
                if not self._is_conditional_failure(exc):
                    raise
            turn = self.load_turn(conversation_id, turn_id) or turn
            existing = turn.get("completion")
            if not isinstance(existing, dict) or not self._completion_matches(
                existing, incoming_completion
            ):
                raise ValueError("stored completion does not match callback")

        source = dict(turn.get("source") or {})
        callback = dict(turn.get("completion") or incoming_completion)
        outbound_event = {
            "schema_version": 1,
            "source": "evergreen-sms-completion",
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "sequence": int(turn.get("sequence") or 0),
            "account_sid": str(source.get("account_sid") or ""),
            "from": str(source.get("to") or ""),
            "to": str(source.get("from") or ""),
            "in_reply_to_message_sid": str(source.get("message_sid") or ""),
            "body": str(callback.get("body") or ""),
            "success": bool(callback.get("success")),
            "status": str(callback.get("status") or ""),
        }
        return {
            "outbound_event": outbound_event,
            "should_enqueue": str(turn.get("outbound_status") or "pending")
            != "enqueued",
        }

    @staticmethod
    def _completion_matches(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
        try:
            existing_sequence = int(existing.get("sequence") or 0)
            incoming_sequence = int(incoming.get("sequence") or 0)
        except (TypeError, ValueError):
            return False
        return (
            str(existing.get("conversation_id") or "")
            == str(incoming.get("conversation_id") or "")
            and str(existing.get("turn_id") or "") == str(incoming.get("turn_id") or "")
            and existing_sequence == incoming_sequence
            and str(existing.get("status") or "") == str(incoming.get("status") or "")
            and existing.get("success") is incoming.get("success")
            and str(existing.get("body") or "") == str(incoming.get("body") or "")
        )

    def mark_outbound_enqueued(self, conversation_id: str, turn_id: str) -> None:
        self.table.update_item(
            Key=self._turn_key(conversation_id, turn_id),
            UpdateExpression=(
                "SET outbound_status = :status, outbound_enqueued_at = :now"
            ),
            ExpressionAttributeValues={":status": "enqueued", ":now": now_epoch()},
        )

    def begin_outbound(self, turn_id: str) -> dict[str, Any] | None:
        """Acquire an expiring exclusive lease for an outbound SMS delivery."""
        key = self._outbound_key(turn_id)
        for _attempt in range(3):
            now = now_epoch()
            lease_token = uuid.uuid4().hex
            lease_expires_at = now + self.outbound_lease_seconds
            item = {
                **key,
                "entity_type": "outbound_delivery",
                "turn_id": turn_id,
                "status": "sending",
                "lease_token": lease_token,
                "lease_expires_at": lease_expires_at,
                "updated_at": now,
                "expires_at": now + self.ttl_seconds,
            }
            try:
                self.table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(pk)",
                )
                return {
                    "turn_id": turn_id,
                    "lease_token": lease_token,
                    "lease_expires_at": lease_expires_at,
                }
            except Exception as exc:
                if not self._is_conditional_failure(exc):
                    raise

            existing = self._get(key)
            if not existing or str(existing.get("status") or "") == "sent":
                continue
            if str(existing.get("status") or "") != "sending":
                return None
            try:
                prior_lease_expires_at = int(existing.get("lease_expires_at") or 0)
            except (TypeError, ValueError):
                prior_lease_expires_at = 0
            if prior_lease_expires_at > now:
                return None
            try:
                self.table.update_item(
                    Key=key,
                    UpdateExpression=(
                        "SET #status = :sending, lease_token = :lease_token, "
                        "lease_expires_at = :lease_expires_at, "
                        "updated_at = :updated_at, expires_at = :expires_at"
                    ),
                    ConditionExpression=(
                        "#status = :sending AND "
                        "(attribute_not_exists(lease_expires_at) "
                        "OR lease_expires_at <= :now)"
                    ),
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":sending": "sending",
                        ":lease_token": lease_token,
                        ":lease_expires_at": lease_expires_at,
                        ":updated_at": now,
                        ":expires_at": now + self.ttl_seconds,
                        ":now": now,
                    },
                )
                return {
                    "turn_id": turn_id,
                    "lease_token": lease_token,
                    "lease_expires_at": lease_expires_at,
                }
            except Exception as exc:
                if not self._is_conditional_failure(exc):
                    raise
        return None

    def mark_outbound_sent(
        self, turn_id: str, provider_sid: str, lease_token: str
    ) -> None:
        self.table.update_item(
            Key=self._outbound_key(turn_id),
            UpdateExpression=(
                "SET #status = :status, provider_sid = :provider_sid, sent_at = :sent_at"
            ),
            ConditionExpression="#status = :sending AND lease_token = :lease_token",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "sent",
                ":sending": "sending",
                ":lease_token": lease_token,
                ":provider_sid": provider_sid,
                ":sent_at": now_epoch(),
            },
        )
