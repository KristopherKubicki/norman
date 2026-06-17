from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


DEFAULT_HEALTH_PATH = Path(
    os.environ.get(
        "NORMAN_TUI_FLEET_HEALTH_JSON",
        "/home/kristopher/.local/state/norman/tui-fleet-doctor.json",
    )
)
DEFAULT_STALE_AFTER_SECONDS = 15 * 60


def tui_fleet_health_path() -> Path:
    return Path(
        os.environ.get("NORMAN_TUI_FLEET_HEALTH_JSON", str(DEFAULT_HEALTH_PATH))
    )


def tui_fleet_health_stale_after_seconds() -> int:
    try:
        return max(
            0,
            int(
                os.environ.get(
                    "NORMAN_TUI_FLEET_HEALTH_STALE_AFTER_SECONDS",
                    str(DEFAULT_STALE_AFTER_SECONDS),
                )
            ),
        )
    except ValueError:
        return DEFAULT_STALE_AFTER_SECONDS


def _empty_health(*, status: str, detail: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "available": False,
        "status": status,
        "checked_at": None,
        "expected_ui_version": "",
        "summary": {
            "active": 0,
            "expected": 0,
            "fail": 0,
            "warn": 0,
            "hosts": 0,
            "ok": False,
        },
        "hosts": [],
        "issues": [],
    }
    if detail:
        payload["detail"] = detail
    return payload


def _coerce_nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(str(value or "").strip()))
    except (TypeError, ValueError):
        return default


def _normalize_health(payload: dict[str, Any], *, path: Path) -> dict[str, Any]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    issues = payload.get("issues")
    if not isinstance(issues, list):
        issues = []
    hosts = payload.get("hosts")
    if not isinstance(hosts, list):
        hosts = []

    stat = path.stat()
    age_seconds = max(0, int(time.time() - stat.st_mtime))
    stale_after_seconds = tui_fleet_health_stale_after_seconds()
    is_stale = stale_after_seconds > 0 and age_seconds > stale_after_seconds
    if is_stale:
        issues = [
            *issues,
            {
                "severity": "warn",
                "host": "<fleet>",
                "instance": "<doctor>",
                "check": "freshness",
                "detail": (
                    "doctor health state is stale: "
                    f"{age_seconds}s old > {stale_after_seconds}s"
                ),
            },
        ]

    issue_fail_count = sum(
        1
        for issue in issues
        if isinstance(issue, dict) and issue.get("severity") == "fail"
    )
    issue_warn_count = sum(
        1
        for issue in issues
        if isinstance(issue, dict) and issue.get("severity") == "warn"
    )
    fail_count = _coerce_nonnegative_int(summary.get("fail"), issue_fail_count)
    warn_count = _coerce_nonnegative_int(summary.get("warn"), issue_warn_count)
    status = str(payload.get("status") or "").strip().lower()
    if status not in {"ok", "warn", "fail"}:
        status = "fail" if fail_count else "warn" if warn_count else "ok"
    if is_stale and status == "ok":
        status = "warn"
    if is_stale and warn_count < issue_warn_count:
        warn_count = issue_warn_count

    return {
        **payload,
        "available": True,
        "status": status,
        "summary": {
            "active": _coerce_nonnegative_int(summary.get("active")),
            "expected": _coerce_nonnegative_int(summary.get("expected")),
            "fail": fail_count,
            "warn": warn_count,
            "hosts": _coerce_nonnegative_int(summary.get("hosts"), len(hosts)),
            "ok": bool(summary.get("ok", fail_count == 0)) and fail_count == 0,
        },
        "hosts": hosts,
        "issues": issues,
        "source": {
            "mtime": int(stat.st_mtime),
            "age_seconds": age_seconds,
            "stale": is_stale,
            "stale_after_seconds": stale_after_seconds,
        },
    }


def read_tui_fleet_health(path: Path | None = None) -> dict[str, Any]:
    health_path = path or tui_fleet_health_path()
    if not health_path.exists():
        return _empty_health(status="missing")
    try:
        raw_payload = json.loads(health_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _empty_health(status="invalid", detail=f"{type(exc).__name__}: {exc}")
    if not isinstance(raw_payload, dict):
        return _empty_health(status="invalid", detail="health payload is not an object")
    try:
        return _normalize_health(raw_payload, path=health_path)
    except OSError as exc:
        return _empty_health(status="unreadable", detail=f"{type(exc).__name__}: {exc}")
