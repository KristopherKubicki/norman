#!/usr/bin/env python3
"""Read application counters on their host; emit no recordings, transcripts or secrets."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import urllib.request


def timestamp(value: object) -> dt.datetime | None:
    """Parse only explicit, timezone-aware source timestamps."""
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def metric(name: str, value: object, unit: str, stamp: str) -> dict:
    """Preserve missing measurements rather than inventing zeroes."""
    return dict(id=name, value=value, unit=unit, source_timestamp=stamp)


def earlybird(state: dict, now: dt.datetime) -> list[dict]:
    """Summarize retained run history and known retries, not total Drive backlog."""
    history = [
        r for r in state.get("run_history", []) if timestamp(r.get("finished_at"))
    ]
    recent = [
        r
        for r in history
        if 0 <= (now - timestamp(r["finished_at"])).total_seconds() <= 86400
    ]
    latest = max(history, key=lambda r: r["finished_at"], default={})
    stamp = latest.get("finished_at")
    success = [r["finished_at"] for r in history if r.get("transcribed", 0) > 0]
    retries = list(state.get("whisper_retries", {}).values())
    failed = [timestamp(r.get("last_failed_at")) for r in retries]
    failed = [t for t in failed if t and t <= now]
    completed = sum(r.get("transcribed", 0) for r in recent)
    errors = sum(r.get("whisper_errors", 0) for r in recent)
    health = state.get("whisper_remote_health", {})
    metrics = [
        metric("recordings_completed_24h", completed, "recordings", stamp),
        metric("transcription_failures_24h", errors, "attempts", stamp),
        metric("known_retry_records", len(retries), "recordings", stamp),
        metric(
            "oldest_retry_age",
            (now - min(failed)).total_seconds() if failed else None,
            "seconds",
            stamp,
        ),
        metric(
            "last_success_age",
            (now - timestamp(max(success))).total_seconds() if success else None,
            "seconds",
            stamp,
        ),
        metric(
            "completion_rate",
            completed / (completed + errors) if completed + errors else None,
            "ratio",
            stamp,
        ),
    ]
    detail = f"{completed} completed / {errors} failed attempts in retained 24h history; {len(retries)} known retry records. Total eligible backlog unknown."
    return [
        dict(
            application="earlybird",
            id="earlybird-throughput",
            name="Recording throughput",
            checked_at=stamp,
            max_age_seconds=1800,
            state="workflow-report",
            level="warn" if errors or retries else "ok",
            detail=detail,
            evidence_kind="output",
            metrics=metrics,
        ),
        dict(
            application="earlybird",
            id="earlybird-asr-preflight",
            name="Running worker ASR preflight",
            checked_at=health.get("checked_at"),
            max_age_seconds=1800,
            state="ready" if health.get("ready") else "unavailable",
            level="ok" if health.get("ready") else "bad",
            evidence_kind="workflow",
            detail="Last preflight recorded by the running worker; independent of gateway process health.",
        ),
    ]


def housebot(state: dict, now: dt.datetime) -> list[dict]:
    """Expose individual site access, inventory age and warning counts."""
    rows = []
    for site in state.get("sites", []):
        stamp = site.get("checked_at") or state.get("generated_at")
        inv = site.get("inventory", {})
        source = (
            inv.get("last_good_checked_at")
            if inv.get("source") == "last_good"
            else stamp
        )
        age = (now - timestamp(source)).total_seconds() if timestamp(source) else None
        warnings = site.get("logs", {}).get("warning_count")
        rows.append(
            dict(
                application="housebot",
                id="housebot-site-" + site["name"].lower(),
                name=site["name"],
                checked_at=stamp,
                max_age_seconds=7200,
                state="site-report",
                level=site.get("level", "unknown"),
                evidence_kind="output",
                detail=site.get("summary", ""),
                metrics=[
                    metric("inventory_age", age, "seconds", source),
                    metric("recent_device_warnings", warnings, "warnings", stamp),
                    metric(
                        "site_access",
                        int(bool(site.get("access", {}).get("ok"))),
                        "boolean",
                        stamp,
                    ),
                ],
            )
        )
    return rows


def gateway(now: dt.datetime) -> list[dict]:
    """Measure ASR readiness, socket backlog and bounded request-log counts."""
    stamp = now.isoformat()
    ready = None
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:18151/asr-readyz", timeout=8
        ) as response:
            ready = json.load(response)
    except (OSError, ValueError):
        pass
    socket = subprocess.run(
        ["ss", "-ltn", "sport", "=", ":18151"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    lines = socket.stdout.splitlines()[1:]
    queued, limit = (int(x) for x in lines[0].split()[1:3]) if lines else (None, None)
    result = subprocess.run(
        [
            "journalctl",
            "-u",
            "norllama-gateway.service",
            "--since",
            "15 minutes ago",
            "-n",
            "10000",
            "-o",
            "cat",
            "--no-pager",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    requests = []
    for line in result.stdout.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("method") == "POST" and record.get("path") in (
            "/transcribe",
            "/v1/audio/transcriptions",
        ):
            requests.append(record)
    capacity = (ready or {}).get("capacity", {})
    metrics = [
        metric("asr_ready", int(bool(ready and ready.get("ready"))), "boolean", stamp),
        metric("socket_backlog", queued, "connections", stamp),
        metric("socket_backlog_limit", limit, "connections", stamp),
        metric("asr_active", capacity.get("active"), "requests", stamp),
        metric("asr_queue_depth", capacity.get("queue_depth"), "requests", stamp),
        metric(
            "asr_requests_sample",
            len(requests) if result.returncode == 0 else None,
            "requests",
            stamp,
        ),
        metric(
            "asr_errors_sample",
            sum(r.get("status", 0) >= 400 for r in requests)
            if result.returncode == 0
            else None,
            "requests",
            stamp,
        ),
    ]
    return [
        dict(
            application="norllama",
            id="gateway-asr",
            name="ASR worker",
            checked_at=stamp,
            state="ready" if ready and ready.get("ready") else "unavailable",
            evidence_kind="workflow",
            level="bad"
            if not ready or not ready.get("ready") or (limit and queued >= limit)
            else "ok",
            detail="ASR readiness and accept queue; request counts cover at most 15 minutes / 10000 log lines. Secondary requests show use, not proof of failover cause.",
            metrics=metrics,
        )
    ]


def producer_reports() -> list[dict]:
    """Bind canonical publication receipts without recomputing business KPIs."""
    root = Path("/home/kristopher/code/control_plane/audit")
    specs = [
        ("leadership-kpis", "kpi_core", "timestamp_utc", 86400),
        ("leadership-kpis", "kpi_sync_health", "checked_at_utc", 21600),
        ("gold-book", "dq_goldbook_health", "observed_at", 108000),
        ("control-plane", "controller_snapshot", "generated_utc", 108000),
    ]
    rows = []
    for app, folder, field, max_age in specs:
        files = list((root / folder).glob("*.json"))
        if not files:
            rows.append(
                dict(application=app, id=folder, state="missing", level="unknown")
            )
            continue
        latest = max(files, key=lambda path: path.stat().st_mtime)
        data = json.loads(latest.read_text())
        stamp = data.get(field)
        errors = data.get("source_errors", [])
        ok = data.get(
            "ok", data.get("state") == "published" if "state" in data else not errors
        )
        counts = [("producer_ok", int(bool(ok)), "boolean")]
        for key in ("issues", "source_errors", "controllers", "rows"):
            value = data.get(key)
            if isinstance(value, (list, dict)):
                counts.append((key + "_count", len(value), "items"))
            elif isinstance(value, int):
                counts.append((key, value, "rows"))
        rows.append(
            dict(
                application=app,
                id=folder,
                name=folder + " publication receipt",
                checked_at=stamp,
                max_age_seconds=max_age,
                state="producer-report",
                level="ok" if ok else "bad",
                evidence_kind="output",
                detail="Canonical producer receipt: "
                + latest.name
                + "; business metrics remain owned by this producer.",
                metrics=[metric(k, v, unit, stamp) for k, v, unit in counts],
            )
        )
    return rows


def main() -> None:
    """Dispatch only known read-only application probes."""
    now = dt.datetime.now(dt.timezone.utc)
    mode = sys.argv[1]
    if mode == "producers":
        rows = producer_reports()
    elif mode == "gateway":
        rows = gateway(now)
    else:
        path = {
            "earlybird": "/home/kristopher/code/earlybird/state.json",
            "housebot": "/opt/housebot/out/hubitat_site_health/latest.json",
        }[mode]
        rows = {"earlybird": earlybird, "housebot": housebot}[mode](
            json.loads(Path(path).read_text()), now
        )
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
