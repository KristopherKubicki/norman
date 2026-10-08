#!/usr/bin/env python3
"""Observe and renew an already-resident, policy-approved model on its owning worker."""

from __future__ import annotations

import argparse
from datetime import datetime
import ipaddress
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.parse
import urllib.request

SCOPE_WORKER = {"work": "spark-151", "personal": "spark-150"}
ALLOWED_MODELS = {"qwen3.8:27b"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Worker redirects are not permitted")


def request(base: str, path: str, payload: dict | None = None) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Content-Type": "application/json",
            "X-Norllama-Peer-Hop": "2147483647",
            "X-Norllama-Priority": "background",
        },
    )
    with opener.open(req, timeout=8) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Worker response exceeds observation limit")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Invalid worker response")
    return result


def owned_host(url: str, address: str) -> bool:
    host = urllib.parse.urlsplit(url).hostname
    if host == "localhost" or host == address:
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def resident_row(document: dict, model: str) -> dict | None:
    return next(
        (
            row
            for row in document.get("models", [])
            if row.get("model", row.get("name")) == model
        ),
        None,
    )


def observe(scope: str, topology: dict) -> dict:
    worker = topology["workers"][SCOPE_WORKER[scope]]
    address = str(ipaddress.ip_address(worker["address"]))
    port = int(worker["gateway_port"])
    if not 1 <= port <= 65535:
        raise ValueError("Invalid worker port")
    base = f"http://{address}:{port}"
    ready = request(base, "/readyz")
    if (
        ready.get("ready") is not True
        or ready.get("policy", {}).get("production_route_eligible") is not True
    ):
        raise ValueError("Worker or signed policy is not ready")
    policy = request(base, "/v1/warm-policy")
    if policy.get("policy_authorization", {}).get("allowed") is not True:
        raise ValueError("Warming is not authorized by worker policy")
    model = policy.get("route_policy", {}).get("models", {}).get("router")
    if model not in ALLOWED_MODELS:
        raise ValueError("Resident model is not approved for automatic maintenance")
    catalog = request(base, "/v1/models")
    row = next(
        (item for item in catalog.get("data", []) if item.get("id") == model), {}
    )
    hosts = row.get("hosts", [])
    if (
        row.get("provider") != "ollama"
        or not hosts
        or not all(owned_host(host, address) for host in hosts)
    ):
        raise ValueError("Resident model is not installed on the owning worker")
    resident = resident_row(request(base, "/api/ps"), model)
    lanes = policy.get("route_guardrails", {}).get("lanes", {})
    return {
        "scope": scope,
        "worker": SCOPE_WORKER[scope],
        "endpoint": base,
        "model": model,
        "policy_id": policy.get("policy_id"),
        "resident": resident is not None,
        "expires_at": (resident or {}).get("expires_at"),
        "task_admission": {
            lane: lanes.get(lane, {}).get("status", "unknown")
            for lane in ("coder", "planner")
        },
        "warm_policy_posture": policy.get("route_posture", "unknown"),
    }


def renewal_due(observation: dict, now: float) -> bool:
    expiry = observation.get("expires_at")
    if not expiry:
        return False  # Fixed resident runtimes have no eviction deadline.
    try:
        parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return False
        return parsed.timestamp() - now <= 600
    except (ValueError, TypeError, AttributeError):
        return False


def prefetch(observation: dict, *, timeout: float = 90) -> dict:
    base, model = observation["endpoint"], observation["model"]
    submitted = request(
        base,
        "/v1/prefetch",
        {
            "model": model,
            "keep_alive": "30m",
            "timeout_s": 60,
        },
    )
    job_id = submitted.get("job_id")
    if not isinstance(job_id, str) or not job_id or len(job_id) > 200:
        raise ValueError("Prefetch did not return a bounded job identity")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        report = request(
            base, "/v1/prefetch/status?job_id=" + urllib.parse.quote(job_id, safe="")
        )
        job = next(
            (item for item in report.get("items", []) if item.get("job_id") == job_id),
            {},
        )
        status = job.get("status")
        if status in {"completed", "warm", "resident", "keep_warm"}:
            if resident_row(request(base, "/api/ps"), model) is None:
                raise ValueError("Prefetch claimed success without observed residency")
            return {"status": "warm", "job_id": job_id, "resident_verified": True}
        if status in {"failed", "cancelled", "timeout"}:
            return {"status": status, "job_id": job_id, "resident_verified": False}
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    return {"status": "timeout", "job_id": job_id, "resident_verified": False}


def run(scope: str, topology: dict, previous: dict, *, warm_now: bool = False) -> dict:
    now = time.time()
    result = {
        "schema": "norman.resident-prefetch.v1",
        "checked_at": now,
        "scope": scope,
    }
    if previous.get("invalid_state"):
        return {**result, "status": "invalid_state", "invalid_state": True}
    attempts = [
        stamp
        for stamp in previous.get("attempts", [])
        if isinstance(stamp, (int, float)) and now - stamp < 3600
    ]
    result["attempts"] = attempts
    try:
        result.update(observe(scope, topology))
        if not result["resident"]:
            result.update(
                status="cold",
                reason="Cold loading requires a separate capacity decision; no model was loaded.",
            )
        elif not warm_now and not renewal_due(result, now):
            result["status"] = "resident"
        elif attempts and (now - max(attempts) < 300 or len(attempts) >= 6):
            result["status"] = "cooldown"
        else:
            result["status"] = "prefetch_due"
    except (OSError, ValueError, KeyError, TypeError) as error:
        result.update(status="unavailable", error=type(error).__name__)
    return result


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(state, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run_locked(args: argparse.Namespace) -> int:
    try:
        previous = json.loads(args.state.read_text())
    except FileNotFoundError:
        previous = {}
    except (OSError, ValueError):
        previous = {"invalid_state": True}
    if not isinstance(previous, dict) or not isinstance(
        previous.get("attempts", []), list
    ):
        previous = {"invalid_state": True}
    result = run(
        args.scope,
        json.loads(args.topology.read_text()),
        previous,
        warm_now=args.warm_now,
    )
    if result["status"] == "prefetch_due":
        result["attempts"].append(time.time())
        write_state(args.state, result)  # Persist the attempt before submitting work.
        try:
            result["prefetch"] = prefetch(result)
            result["status"] = result["prefetch"]["status"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            result.update(status="failed", error=type(error).__name__)
    result["checked_at"] = time.time()
    write_state(args.state, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"resident", "warm", "cooldown"} else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=SCOPE_WORKER, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--warm-now", action="store_true")
    args = parser.parse_args()
    args.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with args.state.with_suffix(".lock").open("a+") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Resident maintenance is already running for this state file.")
            return 0
        return run_locked(args)


if __name__ == "__main__":
    raise SystemExit(main())
