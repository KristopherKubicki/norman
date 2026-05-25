#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "norman.queue-resource-meter.v1"
DONE_STATUSES = {"done", "complete", "completed", "succeeded", "success"}
ACCEPTED_STATUSES = {"accepted", "received"}
QUEUED_STATUSES = {"queued", "pending"}
RUNNING_STATUSES = {"running", "active", "in_progress", "in-progress"}
BLOCKED_STATUSES = {"blocked", "failed_blocked"}


def coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def parse_timestamp(value: Any) -> int:
    if value in {None, ""}:
        return 0
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 100000000000 else int(value)
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return parse_timestamp(int(text))
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return 0


def read_json(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def nested_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "requests",
        "agent_requests",
        "items",
        "jobs",
        "data",
        "results",
        "records",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def first_count(payload: Any, *keys: str) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            for nested in ("count", "total", "value"):
                count = coerce_int(value.get(nested))
                if count:
                    return count
        count = coerce_int(value)
        if count:
            return count
    return 0


def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def count_agent_requests(payload: Any) -> dict[str, int]:
    direct = {
        "accepted": first_count(payload, "accepted", "accepted_count"),
        "queued": first_count(payload, "queued", "queue", "queued_count"),
        "running": first_count(payload, "running", "active", "running_count"),
        "done": first_count(payload, "done", "complete", "completed", "done_count"),
        "blocked": first_count(payload, "blocked", "blocked_count"),
    }
    if any(direct.values()):
        return direct
    counts = {key: 0 for key in direct}
    for item in nested_items(payload):
        status = normalize_status(item.get("status") or item.get("state"))
        if status in ACCEPTED_STATUSES:
            counts["accepted"] += 1
        elif status in QUEUED_STATUSES:
            counts["queued"] += 1
        elif status in RUNNING_STATUSES:
            counts["running"] += 1
        elif status in DONE_STATUSES:
            counts["done"] += 1
        elif status in BLOCKED_STATUSES:
            counts["blocked"] += 1
    return counts


def count_pp_jobs(payload: Any) -> dict[str, int]:
    direct = {
        "queued": first_count(payload, "queued", "queue", "pending"),
        "blocked": first_count(payload, "blocked", "blocked_count"),
        "captured": first_count(payload, "captured", "capture", "captured_count"),
        "submitted": first_count(payload, "submitted", "submitted_count"),
        "normalized": first_count(payload, "normalized", "normalized_count"),
    }
    if any(direct.values()):
        return direct
    counts = {key: 0 for key in direct}
    for item in nested_items(payload):
        status = normalize_status(item.get("status") or item.get("state"))
        if status in QUEUED_STATUSES:
            counts["queued"] += 1
        elif status in BLOCKED_STATUSES:
            counts["blocked"] += 1
        elif status == "captured":
            counts["captured"] += 1
        elif status == "submitted":
            counts["submitted"] += 1
        elif status == "normalized":
            counts["normalized"] += 1
    return counts


def warning_messages(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, str):
        return [payload] if payload.strip() else []
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    if not isinstance(payload, dict):
        return []
    messages: list[str] = []
    for key in ("warnings", "alerts", "blocked_reasons", "reasons"):
        value = payload.get(key)
        if isinstance(value, list):
            messages.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            messages.append(value.strip())
    return messages


def oldest_request_age_seconds(payload: Any, *, now_ts: int) -> int:
    oldest = 0
    for item in nested_items(payload):
        status = normalize_status(item.get("status") or item.get("state"))
        if status not in ACCEPTED_STATUSES | QUEUED_STATUSES | RUNNING_STATUSES:
            continue
        created_at = 0
        for key in (
            "accepted_at",
            "queued_at",
            "created_at",
            "started_at",
            "updated_at",
        ):
            created_at = parse_timestamp(item.get(key))
            if created_at:
                break
        if created_at and (not oldest or created_at < oldest):
            oldest = created_at
    return max(0, now_ts - oldest) if oldest else 0


def tone_for_oldest(age_seconds: int) -> str:
    if age_seconds >= 4 * 60 * 60:
        return "danger"
    if age_seconds >= 60 * 60:
        return "warn"
    return "ok"


def format_age(age_seconds: int) -> str:
    if age_seconds <= 0:
        return "n/a"
    if age_seconds >= 24 * 60 * 60:
        return f"{age_seconds // (24 * 60 * 60)}d"
    if age_seconds >= 60 * 60:
        return f"{age_seconds // (60 * 60)}h"
    if age_seconds >= 60:
        return f"{age_seconds // 60}m"
    return f"{age_seconds}s"


def build_resource_meter(
    *,
    agent_requests: Any = None,
    pp_status: Any = None,
    monitor: Any = None,
    generated_at: str | None = None,
    now_ts: int | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    now_ts = now_ts or int(datetime.now(timezone.utc).timestamp())
    generated_at = generated_at or utc_now_iso()
    agent_counts = count_agent_requests(agent_requests)
    pp_counts = count_pp_jobs(pp_status)
    warnings = warning_messages(monitor)
    oldest_age = oldest_request_age_seconds(agent_requests, now_ts=now_ts)
    has_capture_blocker = any("pp_job_not_captured" in item for item in warnings)
    tone = "ok"
    if pp_counts["blocked"] or agent_counts["blocked"] or has_capture_blocker:
        tone = "danger"
    elif agent_counts["accepted"] or agent_counts["queued"] or pp_counts["queued"]:
        tone = "warn"
    kpi_meters = [
        {
            "id": "scout_accepted",
            "label": "Accepted",
            "value": agent_counts["accepted"],
            "unit": "requests",
            "tone": "warn" if agent_counts["accepted"] else "ok",
            "detail": "Accepted Scout requests have been received but are not done.",
            "source": "agent_requests_latest.json",
            "updated_at": generated_at,
            "stale_after_seconds": 900,
        },
        {
            "id": "pp_queued",
            "label": "PP Queued",
            "value": pp_counts["queued"],
            "unit": "jobs",
            "tone": "warn" if pp_counts["queued"] else "ok",
            "detail": "Perplexity mining jobs waiting outside the chat queue.",
            "source": "pp_mining_status",
            "updated_at": generated_at,
            "stale_after_seconds": 900,
        },
        {
            "id": "pp_blocked",
            "label": "PP Blocked",
            "value": pp_counts["blocked"],
            "unit": "jobs",
            "tone": "danger" if pp_counts["blocked"] else "ok",
            "detail": "Blocked mining/capture work that can prevent accepted requests from advancing.",
            "source": "pp_mining_status",
            "updated_at": generated_at,
            "stale_after_seconds": 900,
        },
    ]
    if oldest_age:
        kpi_meters.append(
            {
                "id": "scout_oldest",
                "label": "Oldest",
                "value": format_age(oldest_age),
                "unit": "age",
                "tone": tone_for_oldest(oldest_age),
                "detail": "Oldest accepted, queued, or running Scout request age.",
                "source": "agent_requests_latest.json",
                "updated_at": generated_at,
                "stale_after_seconds": 900,
            }
        )
    summary = (
        f"Scout accepted {agent_counts['accepted']}; PP queued {pp_counts['queued']}; "
        f"PP blocked {pp_counts['blocked']}"
    )
    return {
        "version": VERSION,
        "generated_at": generated_at,
        "read_only": True,
        "label": "Scout Queues",
        "tone": tone,
        "summary": summary,
        "conversation": {},
        "domain": {
            "accepted": agent_counts["accepted"],
            "queued": agent_counts["queued"] + pp_counts["queued"],
            "backlog": agent_counts["accepted"]
            + agent_counts["queued"]
            + pp_counts["queued"],
            "done": agent_counts["done"],
            "blocked": agent_counts["blocked"],
            "stale": 0,
            "oldest_age_seconds": oldest_age,
        },
        "executor": {
            "running": agent_counts["running"],
            "blocked": pp_counts["blocked"],
            "captured": pp_counts["captured"],
            "submitted": pp_counts["submitted"],
            "oldest_age_seconds": oldest_age,
        },
        "kpi_meters": kpi_meters[:4],
        "warnings": warnings,
        "sources": sources or [],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a read-only Scout/Ranger resource_meter JSON payload."
    )
    parser.add_argument("--agent-requests", type=Path)
    parser.add_argument("--pp-status", type=Path)
    parser.add_argument("--monitor", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    sources = [
        str(path)
        for path in (args.agent_requests, args.pp_status, args.monitor)
        if path is not None
    ]
    meter = build_resource_meter(
        agent_requests=read_json(args.agent_requests),
        pp_status=read_json(args.pp_status),
        monitor=read_json(args.monitor),
        sources=sources,
    )
    indent = 2 if args.pretty else None
    payload = json.dumps(meter, indent=indent, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
