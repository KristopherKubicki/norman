#!/usr/bin/env python3
"""Conservative janitor for Switchboard BBS queue hygiene."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_URL = os.environ.get("SWITCHBOARD_URL", "http://127.0.0.1:8765").rstrip("/")
DEFAULT_TOKEN = os.environ.get("SWITCHBOARD_TOKEN", "").strip()
DEFAULT_TOKEN_FILE = os.environ.get("SWITCHBOARD_TOKEN_FILE", "").strip()
DEFAULT_ENV_FILE = (
    os.environ.get("SWITCHBOARD_ENV_FILE")
    or os.environ.get("NORMAN_CODEX_BBS_ENV_FILE")
    or os.environ.get("HOUSEBOT_CODEX_BBS_ENV_FILE")
    or ""
).strip()
DEFAULT_ACTOR = os.environ.get("SWITCHBOARD_ACTOR", "").strip()
OPEN_STATUSES = {"open", "waiting", "blocked"}
DEFAULT_OWNER_ALIASES = {"eyebat": "glimpser"}
DEFAULT_ACK_SLA_SECONDS = max(
    60, int(os.environ.get("NORMAN_BBS_ACK_SLA_SECONDS", "900"))
)


def _load_env_file(path_text: str) -> dict[str, str]:
    path_text = (path_text or "").strip()
    if not path_text:
        return {}
    values: dict[str, str] = {}
    try:
        lines = Path(path_text).expanduser().read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def _read_token_file(path_text: str) -> str:
    path_text = (path_text or "").strip()
    if not path_text:
        return ""
    return Path(path_text).expanduser().read_text(encoding="utf-8").strip()


def _request_json(
    method: str,
    url: str,
    *,
    token: str = "",
    payload: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {
                "ok": False,
                "error": "http_error",
                "status": exc.code,
                "body": raw,
            }
        if isinstance(payload, dict):
            payload.setdefault("ok", False)
            payload.setdefault("status", exc.code)
        return payload


def _print(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


def _actor(value: str) -> str:
    actor = (value or os.environ.get("SWITCHBOARD_ACTOR", DEFAULT_ACTOR)).strip()
    if not actor:
        raise SystemExit("missing actor; set --actor or SWITCHBOARD_ACTOR")
    return actor


def _thread_url(args: argparse.Namespace, thread_id: str, suffix: str = "") -> str:
    return f"{args.url}/api/v1/threads/{urllib.parse.quote(thread_id)}{suffix}"


def _parse_aliases(
    values: list[str] | None, *, include_defaults: bool
) -> dict[str, str]:
    aliases = dict(DEFAULT_OWNER_ALIASES) if include_defaults else {}
    for value in values or []:
        raw = str(value or "").strip()
        if not raw:
            continue
        if "=" not in raw:
            raise ValueError("--owner-alias must be OLD=NEW")
        old, new = raw.split("=", 1)
        old = old.strip()
        new = new.strip()
        if not old or not new:
            raise ValueError("--owner-alias must be OLD=NEW")
        aliases[old] = new
    return aliases


def _parse_utc(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _thread_time(thread: dict[str, Any]) -> datetime | None:
    for key in ("last_message_at", "updated_at", "created_at"):
        parsed = _parse_utc(str(thread.get(key) or ""))
        if parsed:
            return parsed
    return None


def _thread_age_seconds(thread: dict[str, Any], now: datetime) -> int:
    thread_time = _thread_time(thread)
    if not thread_time:
        return 0
    return max(0, int((now - thread_time).total_seconds()))


def _tags(thread: dict[str, Any]) -> set[str]:
    return {str(tag or "").strip().lower() for tag in thread.get("tags") or [] if tag}


def _open_threads(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        thread
        for thread in threads
        if str(thread.get("status") or "").strip().lower() in OPEN_STATUSES
    ]


def _thread_brief(thread: dict[str, Any]) -> dict[str, Any]:
    return {
        "thread_id": thread.get("thread_id") or "",
        "title": thread.get("title") or "",
        "owner": thread.get("owner") or "",
        "status": thread.get("status") or "",
        "priority": thread.get("priority") or "",
        "last_message_at": thread.get("last_message_at") or "",
    }


def live_actors_from_bots(payload: dict[str, Any]) -> set[str]:
    actors: set[str] = set()
    for bot in payload.get("bots") or []:
        if not isinstance(bot, dict):
            continue
        actor = str(bot.get("actor") or "").strip()
        if not actor:
            continue
        if str(bot.get("directory_status") or "") == "deprecated":
            continue
        if bot.get("heartbeat_required") and not bot.get("heartbeat_ok"):
            continue
        if bot.get("token_present") is False:
            continue
        actors.add(actor)
    return actors


def parent_ids_with_children(threads: list[dict[str, Any]]) -> set[str]:
    parent_ids: set[str] = set()
    for thread in threads:
        for tag in _tags(thread):
            if tag.startswith("parent:"):
                parent_ids.add(tag.split(":", 1)[1].strip().lower())
    return {parent for parent in parent_ids if parent}


def _action(
    *,
    action: str,
    safety: str,
    thread: dict[str, Any],
    reason: str,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "action": action,
        "safety": safety,
        "reason": reason,
        **_thread_brief(thread),
    }
    payload.update(extra)
    return payload


def classify_threads(
    threads: list[dict[str, Any]],
    *,
    live_actors: set[str],
    owner_aliases: dict[str, str],
    now: datetime | None = None,
    stale_days: int = 7,
    ack_sla_seconds: int = DEFAULT_ACK_SLA_SECONDS,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    open_threads = _open_threads(threads)
    parent_ids = parent_ids_with_children(threads)
    actions: list[dict[str, Any]] = []
    live_actor_keys = {actor.lower() for actor in live_actors}
    ack_sla_seconds = max(60, int(ack_sla_seconds or DEFAULT_ACK_SLA_SECONDS))

    for thread in open_threads:
        thread_id = str(thread.get("thread_id") or "")
        owner = str(thread.get("owner") or "").strip()
        owner_key = owner.lower()
        loop = thread.get("loop") if isinstance(thread.get("loop"), dict) else {}
        loop_state = str(loop.get("state") or "").strip().lower()
        tags = _tags(thread)
        target_owner = owner_aliases.get(owner)
        age_seconds = _thread_age_seconds(thread, now)

        if target_owner:
            safety = "safe" if target_owner in live_actors else "review"
            reason = (
                f"Owner {owner!r} is an alias/retired actor; canonical live "
                f"owner is {target_owner!r}."
            )
            actions.append(
                _action(
                    action="owner_alias",
                    safety=safety,
                    thread=thread,
                    reason=reason,
                    target_owner=target_owner,
                )
            )
        elif loop_state == "owner_offline":
            actions.append(
                _action(
                    action="owner_offline",
                    safety="review",
                    thread=thread,
                    reason="Thread owner has no healthy heartbeat and no safe alias rule.",
                )
            )

        if (
            loop_state == "waiting_pickup"
            and owner_key in live_actor_keys
            and age_seconds >= ack_sla_seconds
        ):
            age_minutes = age_seconds / 60
            actions.append(
                _action(
                    action="unacked_handoff",
                    safety="review",
                    thread=thread,
                    reason=(
                        f"Owner TUI {owner!r} is live but has not ACKed pickup "
                        f"for {age_minutes:.1f} minutes. Next step: the owner "
                        "ACKs only if picking up; otherwise a coordinator should "
                        "fork, reassign, mark BLOCKED, or close DONE. Observers "
                        "should not ACK just to clear the alert."
                    ),
                    age_seconds=age_seconds,
                    ack_sla_seconds=ack_sla_seconds,
                )
            )

        if thread_id.lower() in parent_ids and "work:task" not in tags:
            actions.append(
                _action(
                    action="broad_parent_has_child",
                    safety="review",
                    thread=thread,
                    reason=(
                        "Thread has at least one finite child task. Review whether "
                        "the parent should be closed as reference/superseded."
                    ),
                )
            )

        if (
            "work:governance" in tags
            and "work:task" not in tags
            and str(thread.get("status") or "") == "open"
        ):
            actions.append(
                _action(
                    action="standing_governance_reference",
                    safety="review",
                    thread=thread,
                    reason=(
                        "Standing governance record is open. Review whether it should "
                        "be closed as a readable reference instead of active work."
                    ),
                )
            )

        last_time = _thread_time(thread)
        if last_time and loop_state == "picked_up":
            age_days = (now - last_time).total_seconds() / 86400
            if age_days >= stale_days:
                actions.append(
                    _action(
                        action="stale_picked_up",
                        safety="review",
                        thread=thread,
                        reason=(
                            f"Thread has been picked up for {age_days:.1f} days "
                            "without closure."
                        ),
                        age_days=round(age_days, 1),
                    )
                )

        if (
            "work:task" in tags
            and not thread.get("message_count")
            and loop_state == "waiting_pickup"
        ):
            actions.append(
                _action(
                    action="empty_task_waiting_pickup",
                    safety="review",
                    thread=thread,
                    reason=(
                        "Finite task has no messages yet. Review whether the owner "
                        "should ack pickup or the creator should add context."
                    ),
                )
            )

    actions.sort(
        key=lambda item: (
            0 if item["safety"] == "safe" else 1,
            str(item["owner"]),
            str(item["thread_id"]),
            str(item["action"]),
        )
    )
    return actions


def apply_safe_actions(
    args: argparse.Namespace, actions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    actor = _actor(args.actor)
    results: list[dict[str, Any]] = []
    for action in actions:
        if action.get("safety") != "safe":
            continue
        if action.get("action") != "owner_alias":
            continue
        thread_id = str(action.get("thread_id") or "")
        target_owner = str(action.get("target_owner") or "")
        if not thread_id or not target_owner:
            continue
        payload = {
            "owner": target_owner,
            "posted_by": actor,
            "reason": str(action.get("reason") or ""),
        }
        response = _request_json(
            "POST",
            _thread_url(args, thread_id, "/owner"),
            token=args.token,
            payload=payload,
        )
        results.append(
            {
                "thread_id": thread_id,
                "action": action.get("action"),
                "target_owner": target_owner,
                "ok": bool(response.get("ok")),
                "response": response,
            }
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--token", default=DEFAULT_TOKEN)
    ap.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    ap.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    ap.add_argument("--actor")
    ap.add_argument("--owner-alias", action="append", help="Safe alias rule OLD=NEW.")
    ap.add_argument("--no-default-owner-aliases", action="store_true")
    ap.add_argument("--stale-days", type=int, default=7)
    ap.add_argument("--ack-sla-seconds", type=int, default=DEFAULT_ACK_SLA_SECONDS)
    ap.add_argument("--apply-safe", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    env_file = _load_env_file(args.env_file or "")
    if env_file:
        if args.url == DEFAULT_URL and env_file.get("SWITCHBOARD_URL"):
            args.url = str(env_file["SWITCHBOARD_URL"]).rstrip("/")
        if args.token == DEFAULT_TOKEN and env_file.get("SWITCHBOARD_TOKEN"):
            args.token = str(env_file["SWITCHBOARD_TOKEN"]).strip()
        if args.token_file == DEFAULT_TOKEN_FILE and env_file.get(
            "SWITCHBOARD_TOKEN_FILE"
        ):
            args.token_file = str(env_file["SWITCHBOARD_TOKEN_FILE"]).strip()
        if not args.actor and env_file.get("SWITCHBOARD_ACTOR"):
            args.actor = str(env_file["SWITCHBOARD_ACTOR"]).strip()
    if not args.token and args.token_file:
        args.token = _read_token_file(args.token_file)

    try:
        owner_aliases = _parse_aliases(
            args.owner_alias,
            include_defaults=not args.no_default_owner_aliases,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    threads_payload = _request_json(
        "GET", f"{args.url}/api/v1/threads", token=args.token
    )
    if not threads_payload.get("ok"):
        return _print(threads_payload)
    bots_payload = _request_json("GET", f"{args.url}/api/v1/bots", token=args.token)
    live_actors = (
        live_actors_from_bots(bots_payload) if bots_payload.get("ok") else set()
    )
    threads = [
        thread
        for thread in threads_payload.get("threads") or []
        if isinstance(thread, dict)
    ]
    actions = classify_threads(
        threads,
        live_actors=live_actors,
        owner_aliases=owner_aliases,
        stale_days=max(args.stale_days, 1),
        ack_sla_seconds=max(args.ack_sla_seconds, 60),
    )
    applied = apply_safe_actions(args, actions) if args.apply_safe else []
    payload = {
        "ok": all(item.get("ok") for item in applied) if applied else True,
        "mode": "apply-safe" if args.apply_safe else "dry-run",
        "open_thread_count": len(_open_threads(threads)),
        "action_count": len(actions),
        "safe_count": sum(1 for item in actions if item.get("safety") == "safe"),
        "review_count": sum(1 for item in actions if item.get("safety") != "safe"),
        "live_actor_count": len(live_actors),
        "actions": actions,
        "applied": applied,
    }
    return _print(payload)


if __name__ == "__main__":
    raise SystemExit(main())
