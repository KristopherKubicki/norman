#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_HEALTH_JSON = Path(
    os.environ.get(
        "NORMAN_TUI_FLEET_HEALTH_JSON",
        "/home/kristopher/.local/state/norman/tui-fleet-doctor.json",
    )
)
DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "NORMAN_TUI_FLEET_ALERT_STATE",
        "/home/kristopher/.local/state/norman/tui-fleet-alerts-state.json",
    )
)
DEFAULT_BBS_URL = os.environ.get("SWITCHBOARD_URL", "http://127.0.0.1:8765").rstrip("/")
DEFAULT_ACTOR = os.environ.get("NORMAN_TUI_FLEET_ALERT_ACTOR", "norman")
DEFAULT_ACTOR_ENV = Path(
    os.environ.get(
        "NORMAN_TUI_FLEET_ALERT_ACTOR_ENV",
        f"/root/.config/networking/switchboard-bbs/actors/{DEFAULT_ACTOR}.env",
    )
)
DEFAULT_THREAD_ID = os.environ.get(
    "NORMAN_TUI_FLEET_ALERT_THREAD_ID", "th_tui_fleet_health"
)
DEFAULT_WARN_THRESHOLD = 2


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _token_from_env(path: Path) -> str:
    env = _load_env_file(path)
    token = str(env.get("SWITCHBOARD_TOKEN") or "").strip()
    if token:
        return token
    token_file = str(env.get("SWITCHBOARD_TOKEN_FILE") or "").strip()
    if token_file:
        return Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    raise RuntimeError(f"{path} has no SWITCHBOARD_TOKEN or SWITCHBOARD_TOKEN_FILE")


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _request(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else {"ok": True}
            return int(response.status), body if isinstance(body, dict) else {
                "body": body
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"body": raw}
        if not isinstance(body, dict):
            body = {"body": body}
        body.setdefault("ok", False)
        body.setdefault("status", exc.code)
        return int(exc.code), body


def normalized_issue_detail(issue: dict[str, Any]) -> str:
    detail = str(issue.get("detail") or "").strip()
    if detail.startswith("busy/running"):
        return "busy/running"
    if detail.startswith("queue has "):
        return "queue has items but no prompt is running"
    if detail.startswith("recovered queue requires review"):
        return "recovered queue requires review"
    if detail.startswith("CalledProcessError: Command '['ssh'") or (
        "python3 - <<" in detail and "ssh" in detail
    ):
        return "ssh scan failed; remote probe did not complete"
    return detail


def display_issue_detail(issue: dict[str, Any], *, max_chars: int = 280) -> str:
    detail = normalized_issue_detail(issue)
    if len(detail) <= max_chars:
        return detail
    return detail[: max(0, max_chars - 3)].rstrip() + "..."


def issue_location(issue: dict[str, Any]) -> str:
    host = str(issue.get("host") or "unknown").strip() or "unknown"
    instance = str(issue.get("instance") or "").strip()
    if instance and instance != "<host>":
        return f"{host}/{instance}"
    return host


def issue_signature(issue: dict[str, Any]) -> str:
    parts = [
        str(issue.get("severity") or "").strip().lower(),
        str(issue.get("host") or "").strip(),
        str(issue.get("instance") or "").strip(),
        str(issue.get("check") or "").strip(),
        normalized_issue_detail(issue),
    ]
    return "|".join(parts)


def _issue_severity(issue: dict[str, Any]) -> str:
    return str(issue.get("severity") or "").strip().lower()


def warning_is_alertable(issue: dict[str, Any]) -> bool:
    detail = normalized_issue_detail(issue)
    if detail == "busy/running":
        return False
    if detail.startswith("last prompt failed: Web prompt was abandoned after restart"):
        return False
    return True


def evaluate_alerts(
    health: dict[str, Any],
    state: dict[str, Any],
    *,
    warn_threshold: int = DEFAULT_WARN_THRESHOLD,
) -> dict[str, Any]:
    checked_at = str(health.get("checked_at") or "")
    if checked_at and str(state.get("last_checked_at") or "") == checked_at:
        return {
            "new_alerts": [],
            "alert_issues": [],
            "suppressed_warnings": [],
            "ignored_warnings": [],
            "resolved_signatures": [],
            "next_state": state,
            "already_seen": True,
        }

    issues = [issue for issue in health.get("issues") or [] if isinstance(issue, dict)]
    previous_warning_counts = state.get("warning_counts")
    if not isinstance(previous_warning_counts, dict):
        previous_warning_counts = {}
    previous_active = {
        str(item)
        for item in state.get("active_alert_signatures") or []
        if str(item).strip()
    }

    warning_counts: dict[str, int] = {}
    alert_issues: list[dict[str, Any]] = []
    suppressed_warnings: list[dict[str, Any]] = []
    ignored_warnings: list[dict[str, Any]] = []
    current_alert_signatures: set[str] = set()

    for issue in issues:
        severity = _issue_severity(issue)
        signature = issue_signature(issue)
        issue_with_signature = {**issue, "signature": signature}
        if severity == "fail":
            alert_issues.append(issue_with_signature)
            current_alert_signatures.add(signature)
            continue
        if severity != "warn":
            continue
        if not warning_is_alertable(issue):
            ignored_warnings.append(issue_with_signature)
            continue
        count = int(previous_warning_counts.get(signature) or 0) + 1
        warning_counts[signature] = count
        if count >= max(1, warn_threshold):
            alert_issues.append(issue_with_signature)
            current_alert_signatures.add(signature)
        else:
            suppressed_warnings.append(issue_with_signature)

    new_alerts = [
        issue
        for issue in alert_issues
        if str(issue.get("signature") or "") not in previous_active
    ]
    next_state = {
        "last_checked_at": str(health.get("checked_at") or ""),
        "last_status": str(health.get("status") or ""),
        "last_summary": health.get("summary")
        if isinstance(health.get("summary"), dict)
        else {},
        "warning_counts": warning_counts,
        "active_alert_signatures": sorted(current_alert_signatures),
    }
    return {
        "new_alerts": new_alerts,
        "alert_issues": alert_issues,
        "suppressed_warnings": suppressed_warnings,
        "ignored_warnings": ignored_warnings,
        "resolved_signatures": sorted(previous_active - current_alert_signatures),
        "next_state": next_state,
        "already_seen": False,
    }


def alert_action_line(decision: dict[str, Any]) -> str:
    new_alerts = [
        issue for issue in decision.get("new_alerts") or [] if isinstance(issue, dict)
    ]
    if any(_issue_severity(issue) == "fail" for issue in new_alerts):
        return "Check the failed host or TUI first; use doctor JSON for exact evidence before restarting anything."
    if new_alerts:
        return "Review repeated warnings; they crossed the debounce threshold and may need cleanup."
    return "No new operator action; this post records current fleet state."


def render_alert_body(health: dict[str, Any], decision: dict[str, Any]) -> str:
    summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    lines = [
        "TUI fleet health alert",
        "",
        f"Action needed: {alert_action_line(decision)}",
        f"Checked: {health.get('checked_at') or 'unknown'}",
        (
            "Summary: "
            f"active={summary.get('active', 0)} "
            f"expected={summary.get('expected', 0)} "
            f"fail={summary.get('fail', 0)} "
            f"warn={summary.get('warn', 0)}"
        ),
        "",
        "New alerts:",
    ]
    for issue in decision["new_alerts"]:
        lines.append(
            "- [{severity}] {location} · {check}: {detail}".format(
                severity=issue.get("severity") or "warn",
                location=issue_location(issue),
                check=issue.get("check") or "check",
                detail=display_issue_detail(issue),
            )
        )
    suppressed = decision.get("suppressed_warnings") or []
    if suppressed:
        lines.extend(
            [
                "",
                f"Suppressed warnings below threshold: {len(suppressed)}",
            ]
        )
    ignored = decision.get("ignored_warnings") or []
    if ignored:
        lines.extend(
            [
                "",
                f"Visible warnings not alerting: {len(ignored)}",
            ]
        )
    lines.extend(
        [
            "",
            "Reports:",
            "- /home/kristopher/.local/state/norman/tui-fleet-doctor.md",
            "- /home/kristopher/.local/state/norman/tui-fleet-doctor.json",
        ]
    )
    return "\n".join(lines)


def ensure_thread(
    *,
    base_url: str,
    token: str,
    actor: str,
    thread_id: str,
    priority: str,
) -> None:
    encoded_thread = urllib.parse.quote(thread_id)
    status, payload = _request(
        "GET", _join_url(base_url, f"/api/v1/threads/{encoded_thread}"), token=token
    )
    if status == 200 and payload.get("ok") is True:
        return
    if status not in {404}:
        raise RuntimeError(f"alert thread lookup failed: status={status} {payload}")
    create_payload = {
        "thread_id": thread_id,
        "title": "TUI fleet health",
        "priority": priority,
        "scope": {
            "site": "norman",
            "system": "tui-fleet",
            "topic": "health",
            "lane": "fleet",
        },
        "summary": "Fleet-wide TUI doctor alerts and follow-up.",
        "created_by": actor,
        "owner": "norman",
        "tags": ["domain:tui", "domain:bbs", "work:reliability"],
        "watchers": ["panelbot", "netops"],
    }
    create_status, create_response = _request(
        "POST",
        _join_url(base_url, "/api/v1/threads"),
        token=token,
        payload=create_payload,
    )
    if create_status not in {200, 201} or create_response.get("ok") is not True:
        raise RuntimeError(
            f"alert thread create failed: status={create_status} {create_response}"
        )


def post_alert(
    *,
    base_url: str,
    token: str,
    actor: str,
    thread_id: str,
    health: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    has_failure = any(
        _issue_severity(issue) == "fail" for issue in decision["new_alerts"]
    )
    priority = "high" if has_failure else "normal"
    ensure_thread(
        base_url=base_url,
        token=token,
        actor=actor,
        thread_id=thread_id,
        priority=priority,
    )
    encoded_thread = urllib.parse.quote(thread_id)
    payload = {
        "posted_by": actor,
        "kind": "alert",
        "body": render_alert_body(health, decision),
        "metadata": {
            "source": "tui_fleet_alerts",
            "status": str(health.get("status") or ""),
            "new_alert_count": len(decision["new_alerts"]),
            "has_failure": has_failure,
        },
    }
    status, response = _request(
        "POST",
        _join_url(base_url, f"/api/v1/threads/{encoded_thread}/messages"),
        token=token,
        payload=payload,
    )
    if status not in {200, 201} or response.get("ok") is not True:
        raise RuntimeError(f"alert post failed: status={status} {response}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post deduped TUI fleet health alerts."
    )
    parser.add_argument("--health-json", type=Path, default=DEFAULT_HEALTH_JSON)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--url", default=DEFAULT_BBS_URL)
    parser.add_argument("--actor", default=DEFAULT_ACTOR)
    parser.add_argument("--actor-env", type=Path, default=DEFAULT_ACTOR_ENV)
    parser.add_argument("--thread-id", default=DEFAULT_THREAD_ID)
    parser.add_argument("--warn-threshold", type=int, default=DEFAULT_WARN_THRESHOLD)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    health = _load_json(args.health_json, {})
    if not isinstance(health, dict) or not health:
        print(f"missing or invalid health JSON: {args.health_json}", file=sys.stderr)
        return 2
    state = _load_json(args.state, {})
    if not isinstance(state, dict):
        state = {}
    decision = evaluate_alerts(
        health, state, warn_threshold=max(1, int(args.warn_threshold or 1))
    )
    if decision["new_alerts"] and not args.dry_run:
        token = _token_from_env(args.actor_env)
        post_alert(
            base_url=str(args.url).rstrip("/"),
            token=token,
            actor=str(args.actor),
            thread_id=str(args.thread_id),
            health=health,
            decision=decision,
        )
    _write_json(args.state, decision["next_state"])
    if args.json:
        print(
            json.dumps(
                {k: v for k, v in decision.items() if k != "next_state"},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(
            (
                "alerts new={new} active={active} suppressed={suppressed} "
                "ignored={ignored} resolved={resolved} seen={seen}"
            ).format(
                new=len(decision["new_alerts"]),
                active=len(decision["alert_issues"]),
                suppressed=len(decision["suppressed_warnings"]),
                ignored=len(decision["ignored_warnings"]),
                resolved=len(decision["resolved_signatures"]),
                seen=str(decision["already_seen"]).lower(),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
