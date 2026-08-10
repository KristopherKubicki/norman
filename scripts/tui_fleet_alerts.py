#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
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
DEFAULT_TOKEN_SECRET = os.environ.get("NORMAN_TUI_FLEET_ALERT_TOKEN_SECRET", "")
DEFAULT_THREAD_ID = os.environ.get(
    "NORMAN_TUI_FLEET_ALERT_THREAD_ID", "th_tui_fleet_health"
)
DEFAULT_WARN_THRESHOLD = 2
DEFAULT_SECRET_TIMEOUT_SECONDS = 5.0
DEFAULT_WATCHERS = ("panelbot", "netops")


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


def _clean(value: object) -> str:
    return str(value or "").strip()


def resolve_watchers(configured: list[str] | None = None) -> list[str]:
    raw_watchers = configured
    if raw_watchers is None:
        configured_watchers = _clean(
            os.environ.get("NORMAN_TUI_FLEET_ALERT_WATCHERS")
        )
        raw_watchers = (
            configured_watchers.split(",")
            if configured_watchers
            else list(DEFAULT_WATCHERS)
        )
    watchers: list[str] = []
    for value in raw_watchers:
        watcher = _clean(value)
        if watcher and watcher not in watchers:
            watchers.append(watcher)
    return watchers


def _first_env(*names: str) -> str:
    for name in names:
        value = _clean(os.environ.get(name))
        if value:
            return value
    return ""


def _keys_secret_get_url() -> str:
    base_url = _first_env("NORMAN_KEYS_URL", "NORMAN_KEYS_API_BASE").rstrip("/")
    if not base_url:
        return ""
    if base_url.endswith("/v1/secrets/get"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/secrets/get"
    return f"{base_url}/v1/secrets/get"


def _secret_timeout_seconds() -> float:
    configured = _first_env(
        "NORMAN_TUI_FLEET_ALERT_SECRET_TIMEOUT_SECONDS",
        "NORMAN_KEYS_TIMEOUT_SECONDS",
    )
    try:
        return max(0.1, float(configured or DEFAULT_SECRET_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_SECRET_TIMEOUT_SECONDS


def _secret_command(secret_name: str) -> list[str]:
    configured = _first_env("NORMAN_SECRET_CMD")
    if not configured:
        return []
    command = shlex.split(configured)
    if not command:
        return []
    if "{name}" in configured:
        return [part.replace("{name}", secret_name) for part in command]
    return [*command, "get", secret_name]


def _resolve_from_norman_keys(secret_name: str) -> str:
    url = _keys_secret_get_url()
    if not url:
        return ""
    payload = {
        "name": secret_name,
        "reason": "Post deduplicated Norman TUI health alerts to Switchboard BBS",
        "requester_id": _first_env("NORMAN_KEYS_REQUESTER_ID") or "tui-fleet-alerts",
        "session_id": _first_env("NORMAN_KEYS_SESSION_ID") or "tui-fleet-alerts",
        "lane": _first_env("NORMAN_KEYS_LANE") or "observability",
        "target_host": _first_env("NORMAN_KEYS_TARGET_HOST") or socket.gethostname(),
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    broker_token = _first_env("NORMAN_KEYS_TOKEN", "NORMAN_KEYS_API_TOKEN")
    if broker_token:
        headers["Authorization"] = f"Bearer {broker_token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_secret_timeout_seconds()) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body) if body.strip() else {}
    if not isinstance(parsed, dict):
        raise ValueError("Norman Keys returned an invalid secret response")
    token = _clean(parsed.get("value") or parsed.get("secret"))
    if not token:
        raise ValueError("Norman Keys returned an empty secret response")
    return token


def _resolve_from_secret_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_secret_timeout_seconds(),
    )
    token = _clean(result.stdout)
    if not token:
        raise ValueError("Norman secret broker command returned an empty secret")
    return token


def resolve_brokered_token(secret_name: str) -> tuple[str, list[str]]:
    """Resolve a BBS token without touching actor env files or local plaintext."""

    errors: list[str] = []
    if _keys_secret_get_url():
        try:
            token = _resolve_from_norman_keys(secret_name)
        except (
            json.JSONDecodeError,
            OSError,
            TimeoutError,
            urllib.error.URLError,
            ValueError,
        ):
            errors.append("Norman Keys HTTP broker request failed")
        else:
            if token:
                return token, errors

    command = _secret_command(secret_name)
    if command:
        try:
            token = _resolve_from_secret_command(command)
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError):
            errors.append("Norman secret broker command lookup failed")
        else:
            if token:
                return token, errors

    return "", errors


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


def alert_action_line(decision: dict[str, Any], *, title: str) -> str:
    new_alerts = [
        issue for issue in decision.get("new_alerts") or [] if isinstance(issue, dict)
    ]
    if any(_issue_severity(issue) == "fail" for issue in new_alerts):
        return (
            f"Check the failed {title.lower()} target first; use the report "
            "for exact evidence before restarting anything."
        )
    if new_alerts:
        return "Review repeated warnings; they crossed the debounce threshold and may need cleanup."
    return "No new operator action; this post records current fleet state."


def render_alert_body(
    health: dict[str, Any],
    decision: dict[str, Any],
    *,
    title: str = "TUI fleet health",
    report_paths: list[Path] | None = None,
) -> str:
    summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    paths = report_paths or [
        Path("/home/kristopher/.local/state/norman/tui-fleet-doctor.md"),
        Path("/home/kristopher/.local/state/norman/tui-fleet-doctor.json"),
    ]
    lines = [
        f"{title} alert",
        "",
        f"Action needed: {alert_action_line(decision, title=title)}",
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
            *(f"- {path}" for path in paths),
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
    title: str,
    watchers: list[str],
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
        "title": title,
        "priority": priority,
        "scope": {
            "site": "norman",
            "system": "tui-fleet",
            "topic": "health",
            "lane": "fleet",
        },
        "summary": f"Automated {title.lower()} alerts and follow-up.",
        "created_by": actor,
        "owner": "norman",
        "tags": ["domain:tui", "domain:bbs", "work:reliability"],
        "watchers": watchers,
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
    title: str,
    report_paths: list[Path],
    watchers: list[str] | None = None,
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
        title=title,
        watchers=resolve_watchers(watchers),
    )
    encoded_thread = urllib.parse.quote(thread_id)
    payload = {
        "posted_by": actor,
        "kind": "alert",
        "body": render_alert_body(
            health,
            decision,
            title=title,
            report_paths=report_paths,
        ),
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
    parser.add_argument(
        "--token-secret",
        default=DEFAULT_TOKEN_SECRET,
        help=(
            "Logical Norman Keys secret for the BBS post token. Defaults to "
            "bbs.<actor>.post-token."
        ),
    )
    parser.add_argument("--thread-id", default=DEFAULT_THREAD_ID)
    parser.add_argument("--title", default="TUI fleet health")
    parser.add_argument(
        "--watcher",
        action="append",
        default=None,
        help="BBS actor to watch on a created alert thread. May be repeated.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        action="append",
        default=None,
        help="Health-report path to include in the alert body. May be repeated.",
    )
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
        actor = _clean(args.actor)
        token_secret = _clean(args.token_secret) or f"bbs.{actor}.post-token"
        token, errors = resolve_brokered_token(token_secret)
        if not token:
            detail = "; ".join(errors) if errors else "no approved broker is configured"
            print(
                "unable to resolve Switchboard BBS token "
                f"for logical secret {token_secret}: {detail}.",
                file=sys.stderr,
            )
            return 1
        post_alert(
            base_url=str(args.url).rstrip("/"),
            token=token,
            actor=actor,
            thread_id=str(args.thread_id),
            health=health,
            decision=decision,
            title=str(args.title).strip() or "TUI fleet health",
            report_paths=args.report_path or [],
            watchers=resolve_watchers(args.watcher),
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
