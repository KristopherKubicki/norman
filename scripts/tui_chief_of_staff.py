#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tui_fleet_alerts


DEFAULT_HEALTH_PATH = Path("/home/kristopher/.local/state/norman/tui-fleet-doctor.json")
DEFAULT_ROUTE_PROOF_PATH = Path(
    "/home/kristopher/.local/state/norman/tui-status-route-proof.json"
)
DEFAULT_OUTPUT_PATH = Path(
    "/home/kristopher/.local/state/norman/tui-chief-of-staff.json"
)
DEFAULT_MARKDOWN_PATH = Path(
    "/home/kristopher/.local/state/norman/tui-chief-of-staff.md"
)
DEFAULT_HISTORY_PATH = Path(
    "/home/kristopher/.local/state/norman/tui-chief-of-staff.jsonl"
)
DEFAULT_STATE_PATH = Path(
    "/home/kristopher/.local/state/norman/tui-chief-of-staff-state.json"
)
DEFAULT_ROLE_PATH = (
    Path(__file__).resolve().parents[1] / "config/norllama/model_roles.json"
)
DEFAULT_TOPOLOGY_PATH = (
    Path(__file__).resolve().parents[1] / "config/fleet/topology.json"
)
DEFAULT_BBS_URL = os.environ.get("SWITCHBOARD_URL", "http://127.0.0.1:8765")
DEFAULT_ACTOR = os.environ.get(
    "NORMAN_TUI_CHIEF_OF_STAFF_ACTOR",
    os.environ.get("NORMAN_TUI_FLEET_ALERT_ACTOR", "norman"),
)
DEFAULT_THREAD_ID = "th_tui_chief_of_staff"
DEFAULT_HEARTBEAT_SECONDS = 2 * 60 * 60
DEFAULT_MAX_HEALTH_AGE_SECONDS = 15 * 60
DEFAULT_MAX_PROOF_AGE_SECONDS = 45 * 60


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and value.strip().isdigit()
    ):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_seconds(value: Any, *, now: datetime) -> int | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def load_resident_role(path: Path = DEFAULT_ROLE_PATH) -> dict[str, Any]:
    payload = load_json(path)
    roles = payload.get("roles")
    resident = roles.get("resident") if isinstance(roles, dict) else None
    if not isinstance(resident, dict):
        raise ValueError("model-role registry is missing resident")
    model = str(resident.get("model") or "").strip()
    endpoints = resident.get("client_endpoints") or resident.get("endpoints") or []
    endpoint = next((str(item).strip() for item in endpoints if str(item).strip()), "")
    if not model or not endpoint:
        raise ValueError("resident role requires a model and client endpoint")
    return {"model": model, "endpoint": endpoint}


def resident_pool_status(topology: dict[str, Any]) -> dict[str, Any]:
    pool = topology.get("resident_pool")
    row = pool if isinstance(pool, dict) else {}
    schedulers = [
        str(item).strip()
        for item in row.get("scheduler_workers") or []
        if str(item).strip()
    ]
    runtimes = [
        str(item).strip()
        for item in row.get("runtime_workers") or []
        if str(item).strip()
    ]
    minimum = max(1, int(row.get("minimum_runtime_replicas") or 1))
    return {
        "scheduler_configured": len(set(schedulers)),
        "scheduler_replicas": len(set(schedulers)),
        "runtime_configured": len(set(runtimes)),
        "runtime_replicas": len(set(runtimes)),
        "minimum_runtime_replicas": minimum,
        "runtime_redundant": len(set(runtimes)) >= minimum,
    }


def _http_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def live_resident_pool_status(
    topology: dict[str, Any],
    *,
    resident_model: str,
    timeout: float = 2.0,
) -> dict[str, Any]:
    configured = resident_pool_status(topology)
    pool = topology.get("resident_pool")
    pool_row = pool if isinstance(pool, dict) else {}
    workers = topology.get("workers")
    worker_rows = workers if isinstance(workers, dict) else {}
    healthy_schedulers: list[str] = []
    healthy_runtimes: list[str] = []
    scheduler_errors: dict[str, str] = {}
    runtime_errors: dict[str, str] = {}

    for worker_id in pool_row.get("scheduler_workers") or []:
        clean_id = str(worker_id or "").strip()
        raw = worker_rows.get(clean_id)
        row = raw if isinstance(raw, dict) else {}
        address = str(row.get("address") or "").strip()
        port = int(row.get("resident_scheduler_port") or 0)
        try:
            payload = _http_json(
                f"http://{address}:{port}/readyz",
                timeout=timeout,
            )
            if payload.get("ready") is True:
                healthy_schedulers.append(clean_id)
            else:
                scheduler_errors[clean_id] = "not_ready"
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            scheduler_errors[clean_id] = "unreachable"

    for worker_id in pool_row.get("runtime_workers") or []:
        clean_id = str(worker_id or "").strip()
        raw = worker_rows.get(clean_id)
        row = raw if isinstance(raw, dict) else {}
        address = str(row.get("address") or "").strip()
        port = int(row.get("resident_runtime_port") or 0)
        try:
            payload = _http_json(
                f"http://{address}:{port}/api/tags",
                timeout=timeout,
            )
            available = {
                str(item.get("name") or item.get("model") or "").strip()
                for item in payload.get("models") or []
                if isinstance(item, dict)
            }
            if resident_model in available:
                healthy_runtimes.append(clean_id)
            else:
                runtime_errors[clean_id] = "resident_model_missing"
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            runtime_errors[clean_id] = "unreachable"

    minimum = configured["minimum_runtime_replicas"]
    return {
        **configured,
        "scheduler_replicas": len(set(healthy_schedulers)),
        "runtime_replicas": len(set(healthy_runtimes)),
        "runtime_redundant": len(set(healthy_runtimes)) >= minimum,
        "scheduler_workers_healthy": sorted(set(healthy_schedulers)),
        "runtime_workers_healthy": sorted(set(healthy_runtimes)),
        "scheduler_errors": scheduler_errors,
        "runtime_errors": runtime_errors,
        "observed_live": True,
    }


def compact_packet(
    health: dict[str, Any],
    route_proof: dict[str, Any],
    *,
    now: datetime,
    topology: dict[str, Any] | None = None,
    resident_pool: dict[str, Any] | None = None,
    max_health_age_seconds: int = DEFAULT_MAX_HEALTH_AGE_SECONDS,
    max_proof_age_seconds: int = DEFAULT_MAX_PROOF_AGE_SECONDS,
) -> dict[str, Any]:
    health_age = age_seconds(health.get("checked_at"), now=now)
    proof_age = age_seconds(
        route_proof.get("generated_at") or route_proof.get("checked_at"), now=now
    )
    hosts = []
    for item in health.get("hosts") or []:
        if not isinstance(item, dict):
            continue
        host = {
            "host": str(item.get("host") or ""),
            "active": int(item.get("active_count") or 0),
            "expected": int(item.get("expected_count") or 0),
            "fail": int(item.get("fail_count") or 0),
            "warn": int(item.get("warn_count") or 0),
        }
        if host["active"] or host["expected"] or host["fail"] or host["warn"]:
            hosts.append(host)
    route_results = []
    for item in route_proof.get("results") or []:
        if not isinstance(item, dict):
            continue
        route_results.append(
            {
                "target": str(item.get("target") or ""),
                "host": str(item.get("host") or ""),
                "passed": bool(item.get("passed")),
                "outcome": str(item.get("outcome") or ""),
                "planner_ready": bool(
                    (item.get("final") or {})
                    .get("local_planner_readiness", {})
                    .get("ready")
                ),
            }
        )
    issues = []
    for item in health.get("issues") or []:
        if not isinstance(item, dict):
            continue
        issues.append(
            {
                "severity": str(item.get("severity") or ""),
                "host": str(item.get("host") or ""),
                "instance": str(item.get("instance") or ""),
                "check": str(item.get("check") or ""),
                "detail": tui_fleet_alerts.display_issue_detail(item, max_chars=180),
            }
        )
    coverage_active = sum(item["active"] for item in hosts)
    coverage_expected = sum(item["expected"] for item in hosts)
    stale_sources = []
    if health_age is None or health_age > max_health_age_seconds:
        stale_sources.append("fleet_health")
    if proof_age is None or proof_age > max_proof_age_seconds:
        stale_sources.append("route_proof")
    return {
        "schema": "norman.tui-chief-input.v1",
        "observed_at": now.isoformat().replace("+00:00", "Z"),
        "fleet": {
            "status": str(health.get("status") or "unknown"),
            "active": coverage_active,
            "expected": coverage_expected,
            "coverage_complete": coverage_active == coverage_expected
            and coverage_expected > 0,
            "health_age_seconds": health_age,
            "hosts": hosts,
            "issues": issues,
        },
        "route_proof": {
            "age_seconds": proof_age,
            "passed": int((route_proof.get("summary") or {}).get("passed") or 0),
            "failed": int((route_proof.get("summary") or {}).get("failed") or 0),
            "targets": route_results,
        },
        "resident_pool": resident_pool or resident_pool_status(topology or {}),
        "stale_sources": stale_sources,
    }


def packet_signature(packet: dict[str, Any]) -> str:
    stable = json.loads(json.dumps(packet))
    stable.pop("observed_at", None)
    fleet = stable.get("fleet") or {}
    fleet.pop("health_age_seconds", None)
    route_proof = stable.get("route_proof") or {}
    route_proof.pop("age_seconds", None)
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def deterministic_brief(packet: dict[str, Any]) -> dict[str, Any]:
    fleet = packet["fleet"]
    proof = packet["route_proof"]
    resident_pool = packet["resident_pool"]
    stale = packet["stale_sources"]
    issues = fleet["issues"]
    planner_unready = [
        target
        for target in proof["targets"]
        if target["passed"] and not target["planner_ready"]
    ]
    if stale:
        status = "stale"
        headline = "TUI status evidence needs refresh."
    elif (
        issues
        or proof["failed"]
        or planner_unready
        or not fleet["coverage_complete"]
        or not resident_pool["runtime_redundant"]
    ):
        status = "attention"
        headline = "The TUI estate needs attention."
    else:
        status = "healthy"
        headline = "The TUI estate is healthy."
    highlights = [
        f"{fleet['active']}/{fleet['expected']} managed TUIs are active.",
        f"Scheduled route proof passed {proof['passed']} target(s).",
        (
            "Resident scheduling has "
            f"{resident_pool['scheduler_replicas']} replica(s); model runtime has "
            f"{resident_pool['runtime_replicas']}/"
            f"{resident_pool['minimum_runtime_replicas']} required replica(s)."
        ),
    ]
    attention = [
        f"{item['host']}/{item['instance']}: {item['detail']}" for item in issues[:5]
    ]
    if not fleet["coverage_complete"]:
        attention.append(
            "Fleet coverage is incomplete; active and expected counts differ."
        )
    if not resident_pool["runtime_redundant"]:
        attention.append(
            "Resident model runtime redundancy is below policy; scheduler failover "
            "does not protect against loss of the sole inference host."
        )
    if planner_unready:
        targets = ", ".join(
            f"{item['host']}/{item['target']}" for item in planner_unready[:5]
        )
        attention.append(
            "Local planner readiness is unavailable for route-proof target(s): "
            f"{targets}."
        )
    if stale:
        attention.append("Stale evidence: " + ", ".join(stale) + ".")
    return {
        "status": status,
        "headline": headline,
        "highlights": highlights,
        "attention": attention,
        "next_check": "Continue the scheduled 30-minute background review.",
        "source": "deterministic",
    }


def _json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def generate_brief(
    packet: dict[str, Any],
    *,
    model: str,
    endpoint: str,
    timeout: float = 45.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deterministic = deterministic_brief(packet)
    prompt = (
        "Write one concise chief-of-staff headline for this metadata-only packet. "
        "Do not add counts, ages, host names, work items, or recommendations. "
        "Do not claim healthy status when the packet has attention or stale evidence. "
        'Return only JSON in the form {"headline":"..."}. The application renders all '
        "facts deterministically.\n" + json.dumps(packet, sort_keys=True)
    )
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/api/chat",
        data=json.dumps(
            {
                "model": model,
                "stream": False,
                "think": False,
                "format": "json",
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_predict": 80, "temperature": 0.1},
            }
        ).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Norllama-Priority": "background",
            "X-Norllama-Work-Class": "background",
            "X-Norllama-Max-Queue-Wait-Ms": "750",
        },
        method="POST",
    )
    started = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
            content = str((raw.get("message") or {}).get("content") or "")
            candidate = _json_object(content)
            headers = dict(response.headers.items())
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return deterministic, {
            "status": "fallback",
            "model": model,
            "latency_ms": int(
                (datetime.now(timezone.utc) - started).total_seconds() * 1000
            ),
        }
    brief = {
        "status": deterministic["status"],
        "headline": str(candidate.get("headline") or deterministic["headline"])[:240],
        "highlights": deterministic["highlights"],
        "attention": deterministic["attention"],
        "next_check": deterministic["next_check"],
        "source": "resident",
    }
    return brief, {
        "status": "completed",
        "model": model,
        "latency_ms": int(
            (datetime.now(timezone.utc) - started).total_seconds() * 1000
        ),
        "admission": headers.get("X-Norllama-Admission", ""),
        "queue_wait_ms": headers.get("X-Norllama-Queue-Wait-Ms", ""),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    brief = payload["brief"]
    lines = [
        "# TUI Chief of Staff",
        "",
        f"Updated: {payload['generated_at']}",
        f"Freshness: {payload['freshness']}",
        f"Status: {brief['status']}",
        "",
        f"## {brief['headline']}",
        "",
        *[f"- {item}" for item in brief["highlights"]],
    ]
    if brief["attention"]:
        lines.extend(
            ["", "## Attention", "", *[f"- {item}" for item in brief["attention"]]]
        )
    lines.extend(["", f"Next: {brief['next_check']}", ""])
    return "\n".join(lines)


def should_publish(
    *,
    signature: str,
    state: dict[str, Any],
    now: datetime,
    heartbeat_seconds: int,
    force: bool = False,
) -> tuple[bool, str]:
    if force:
        return True, "forced"
    if signature != str(state.get("last_published_signature") or ""):
        return True, "material_change"
    last = parse_timestamp(state.get("last_published_at"))
    if last is None or (now - last).total_seconds() >= heartbeat_seconds:
        return True, "heartbeat"
    return False, "deduplicated"


def write_outputs(
    payload: dict[str, Any],
    *,
    output_path: Path,
    markdown_path: Path,
    history_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def post_brief(
    payload: dict[str, Any],
    *,
    base_url: str,
    actor: str,
    token: str,
    thread_id: str,
) -> None:
    tui_fleet_alerts.ensure_thread(
        base_url=base_url,
        token=token,
        actor=actor,
        thread_id=thread_id,
        priority="normal",
        title="TUI chief of staff",
        watchers=["norman"],
    )
    status, response = tui_fleet_alerts._request(
        "POST",
        tui_fleet_alerts._join_url(base_url, f"/api/v1/threads/{thread_id}/messages"),
        token=token,
        payload={
            "posted_by": actor,
            "kind": "status",
            "body": render_markdown(payload),
            "metadata": {
                "source": "tui_chief_of_staff",
                "status": payload["brief"]["status"],
                "freshness": payload["freshness"],
                "publish_reason": payload["publish_reason"],
            },
        },
    )
    if status not in {200, 201} or response.get("ok") is not True:
        raise RuntimeError(f"chief-of-staff post failed: status={status}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the TUI chief-of-staff brief."
    )
    parser.add_argument("--health", type=Path, default=DEFAULT_HEALTH_PATH)
    parser.add_argument("--route-proof", type=Path, default=DEFAULT_ROUTE_PROOF_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN_PATH)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--role-registry", type=Path, default=DEFAULT_ROLE_PATH)
    parser.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY_PATH)
    parser.add_argument("--url", default=DEFAULT_BBS_URL)
    parser.add_argument("--actor", default=DEFAULT_ACTOR)
    parser.add_argument("--thread-id", default=DEFAULT_THREAD_ID)
    parser.add_argument(
        "--heartbeat-seconds", type=int, default=DEFAULT_HEARTBEAT_SECONDS
    )
    parser.add_argument("--force-publish", action="store_true")
    parser.add_argument("--no-post", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    now = datetime.now(timezone.utc)
    health = load_json(args.health)
    route_proof = load_json(args.route_proof)
    topology = load_json(args.topology)
    role = load_resident_role(args.role_registry)
    packet = compact_packet(
        health,
        route_proof,
        now=now,
        topology=topology,
        resident_pool=live_resident_pool_status(
            topology,
            resident_model=role["model"],
        ),
    )
    signature = packet_signature(packet)
    state = load_json(args.state)
    publish, reason = should_publish(
        signature=signature,
        state=state,
        now=now,
        heartbeat_seconds=max(60, args.heartbeat_seconds),
        force=args.force_publish,
    )
    brief, inference = generate_brief(
        packet, model=role["model"], endpoint=role["endpoint"]
    )
    freshness = "stale" if packet["stale_sources"] else "fresh"
    payload = {
        "schema": "norman.tui-chief-of-staff.v1",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "freshness": freshness,
        "signature": signature,
        "publish": publish,
        "publish_reason": reason,
        "brief": brief,
        "inference": inference,
        "evidence": packet,
    }
    write_outputs(
        payload,
        output_path=args.output,
        markdown_path=args.markdown,
        history_path=args.history,
    )
    if publish and not args.no_post:
        token, errors = tui_fleet_alerts.resolve_brokered_token(
            f"bbs.{args.actor}.post-token"
        )
        if not token:
            print("; ".join(errors) or "BBS token unavailable", file=sys.stderr)
            return 1
        post_brief(
            payload,
            base_url=str(args.url).rstrip("/"),
            actor=args.actor,
            token=token,
            thread_id=args.thread_id,
        )
        state = {
            "last_published_at": payload["generated_at"],
            "last_published_signature": signature,
        }
    state["last_generated_at"] = payload["generated_at"]
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
