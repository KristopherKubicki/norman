#!/usr/bin/env python3
"""Live policy checks for Norman/Switchboard BBS coordination."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = os.environ.get("SWITCHBOARD_URL", "http://127.0.0.1:8765").rstrip("/")
DEFAULT_ACTOR_DIR = Path(
    os.environ.get(
        "SWITCHBOARD_BBS_ACTOR_DIR",
        "/root/.config/networking/switchboard-bbs/actors",
    )
)
DEFAULT_BOT_DIRECTORY = Path(
    os.environ.get(
        "SWITCHBOARD_BBS_BOT_DIRECTORY",
        "/etc/switchboard-bbs/SWITCHBOARD_BOT_DIRECTORY.json",
    )
)
DEFAULT_ACTOR_ENV_FILE = (
    os.environ.get("NORMAN_CODEX_BBS_ENV_FILE")
    or os.environ.get("HOUSEBOT_CODEX_BBS_ENV_FILE")
    or ""
).strip()
DEFAULT_ACTOR_ENV_ACTOR = (
    os.environ.get("NORMAN_CODEX_BBS_ACTOR")
    or os.environ.get("HOUSEBOT_CODEX_BBS_ACTOR")
    or "norman"
).strip()
DEFAULT_POLICY_THREAD_ID = "th_bbs_escalation_contract_20260525"
EXPECTED_ADMIN_ACTORS = {"norman", "subprime"}
EXPECTED_ACTOR_COUNT = 31
PROMOTED_TUI_ACTORS: dict[str, dict[str, str]] = {
    "artmonster": {
        "lane": "family",
        "site": "toy-box",
        "system": "artmonster",
    },
    "castle": {"lane": "family", "site": "toy-box", "system": "castle"},
    "diamond-roc": {
        "lane": "family",
        "site": "toy-box",
        "system": "diamond-roc",
    },
    "dj": {"lane": "family", "site": "toy-box", "system": "dj"},
    "camera-studio": {
        "lane": "family",
        "site": "toy-box",
        "system": "camera-studio",
    },
    "tv": {"lane": "family", "site": "toy-box", "system": "tv"},
    "usbhome": {"lane": "family", "site": "toy-box", "system": "usbhome"},
    "uscache": {"lane": "family", "site": "toy-box", "system": "uscache"},
    "phoneops": {
        "lane": "fleet",
        "site": "phones",
        "system": "phoneops",
    },
    "compere": {"lane": "work", "site": "work-special", "system": "compere"},
    "control-plane": {
        "lane": "work",
        "site": "work-special",
        "system": "control-plane",
    },
    "earlybird": {"lane": "work", "site": "work-special", "system": "earlybird"},
    "gold-book": {"lane": "work", "site": "work-special", "system": "gold-book"},
    "market-sizing": {
        "lane": "work",
        "site": "work-special",
        "system": "market-sizing",
    },
    "leadership-kpis": {
        "lane": "work",
        "site": "work-special",
        "system": "leadership-kpis",
    },
    "mls": {"lane": "work", "site": "work-special", "system": "mls"},
    "panelbot": {"lane": "work", "site": "work-special", "system": "panelbot"},
    "platinum-standard": {
        "lane": "work",
        "site": "work-special",
        "system": "platinum-standard",
    },
    "scout": {"lane": "work", "site": "work-special", "system": "scout"},
    "tmi-dashboards": {
        "lane": "work",
        "site": "work-special",
        "system": "tmi-dashboards",
    },
    "parkergale": {
        "lane": "private",
        "site": "private",
        "system": "parkergale",
    },
    "uplink": {
        "lane": "support",
        "site": "networking",
        "system": "uplink",
    },
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "ok": self.ok,
        }
        if self.detail:
            payload["detail"] = self.detail
        if self.data:
            payload.update(self.data)
        return payload


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _token_from_env(env: dict[str, str]) -> str:
    token = str(env.get("SWITCHBOARD_TOKEN") or "").strip()
    if token:
        return token
    token_file = str(env.get("SWITCHBOARD_TOKEN_FILE") or "").strip()
    if token_file:
        return Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    raise RuntimeError("actor env has no SWITCHBOARD_TOKEN or SWITCHBOARD_TOKEN_FILE")


def _request(
    method: str,
    url: str,
    *,
    token: str = "",
    payload: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else {"ok": True}
            return int(response.status), body if isinstance(body, dict) else {
                "body": body
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {"body": raw}
        if not isinstance(body, dict):
            body = {"body": body}
        body.setdefault("ok", False)
        body.setdefault("status", exc.code)
        return int(exc.code), body


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _parse_actor_filter(values: list[str] | None) -> list[str]:
    actors: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        for raw_actor in str(value).split(","):
            actor = raw_actor.strip()
            if actor and actor not in seen:
                actors.append(actor)
                seen.add(actor)
    return actors


def _actor_id(actor: str) -> str:
    actor = str(actor or "").strip()
    if not actor:
        return ""
    return actor.split("@", 1)[0].strip() or actor


def _parse_actor_env_files(values: list[str] | None) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for value in values or []:
        raw = str(value or "").strip()
        if not raw:
            continue
        if "=" not in raw:
            raise ValueError("--actor-env-file must be ACTOR=PATH")
        actor, path = raw.split("=", 1)
        actor_id = _actor_id(actor)
        if not actor_id or not path.strip():
            raise ValueError("--actor-env-file must be ACTOR=PATH")
        files[actor_id] = Path(path.strip()).expanduser()
    return files


def _select_actors(
    available: list[str] | tuple[str, ...], requested: list[str]
) -> tuple[list[str], list[str]]:
    if not requested:
        return list(available), []
    available_set = set(available)
    selected = [actor for actor in requested if actor in available_set]
    missing = [actor for actor in requested if actor not in available_set]
    return selected, missing


def _policy_bounds(source: str) -> tuple[int, int] | None:
    start = source.find("Fleet coordination policy:")
    end = source.find("\nEOF", start)
    if start < 0 or end < 0:
        return None
    return start, end


def _extract_policy_block(source: str) -> str:
    bounds = _policy_bounds(source)
    if not bounds:
        return ""
    start, end = bounds
    return source[start:end].strip()


def _replace_policy_block(source: str, policy: str) -> str:
    bounds = _policy_bounds(source)
    if not bounds:
        raise ValueError("COMMON_BROKER_POLICY block not found")
    start, end = bounds
    return f"{source[:start]}{policy.strip()}{source[end:]}"


class Doctor:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.url = str(args.url or DEFAULT_URL).rstrip("/")
        self.actor_dir = Path(args.actor_dir).expanduser()
        self.bot_directory = Path(args.bot_directory).expanduser()
        self.policy_thread_id = str(args.policy_thread_id or DEFAULT_POLICY_THREAD_ID)
        self.actor_filter = _parse_actor_filter(args.actors)
        self.probe_actor_filter = _parse_actor_filter(args.probe_actors)
        self.actor_env_files = _parse_actor_env_files(args.actor_env_file)
        self.checks: list[Check] = []
        self.env_cache: dict[str, dict[str, str]] = {}

    def actor_env(self, actor: str) -> dict[str, str]:
        actor_id = _actor_id(actor)
        if actor_id not in self.env_cache:
            override = self.actor_env_files.get(actor_id)
            if override is not None:
                self.env_cache[actor_id] = _load_env_file(override)
                return self.env_cache[actor_id]
            fallback = (
                Path(DEFAULT_ACTOR_ENV_FILE).expanduser()
                if DEFAULT_ACTOR_ENV_FILE
                else None
            )
            if fallback is not None and fallback.exists():
                env = _load_env_file(fallback)
                fallback_actor = _actor_id(
                    env.get("SWITCHBOARD_ACTOR") or DEFAULT_ACTOR_ENV_ACTOR
                )
                if actor_id == fallback_actor:
                    self.env_cache[actor_id] = env
                    return env
            self.env_cache[actor_id] = _load_env_file(
                self.actor_dir / f"{actor_id}.env"
            )
        return self.env_cache[actor_id]

    def token(self, actor: str) -> str:
        return _token_from_env(self.actor_env(actor))

    def actor_request(
        self,
        actor: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return _request(
            method,
            _join_url(self.url, path),
            token=self.token(actor),
            payload=payload,
        )

    def add(self, name: str, ok: bool, detail: str = "", **data: Any) -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail, data=data or None))

    def run_check(self, name: str, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:
            self.add(name, False, f"{type(exc).__name__}: {exc}")

    def live_actors(self) -> list[str]:
        payload = json.loads(self.bot_directory.read_text(encoding="utf-8"))
        actors: list[str] = []
        for row in payload.get("bots", []):
            if not isinstance(row, dict) or row.get("status") != "live":
                continue
            actor = str(row.get("actor") or row.get("id") or "").strip()
            if actor:
                actors.append(actor)
        return actors

    def check_prompt_drift(self) -> None:
        template_path = (
            REPO_ROOT / "scripts" / "agent_console_template" / "agent_console_launch.sh"
        )
        norman_path = REPO_ROOT / "scripts" / "norman_codex_launch.sh"
        try:
            template = template_path.read_text(encoding="utf-8")
            norman = norman_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.add("prompt files readable", False, str(exc))
            return
        template_policy = _extract_policy_block(template)
        norman_policy = _extract_policy_block(norman)
        if (
            self.args.repair_launcher
            and template_policy
            and norman_policy != template_policy
        ):
            try:
                norman_path.write_text(
                    _replace_policy_block(norman, template_policy),
                    encoding="utf-8",
                )
                norman = norman_path.read_text(encoding="utf-8")
                norman_policy = _extract_policy_block(norman)
                self.add(
                    "norman launcher policy auto-repair",
                    True,
                    "copied COMMON_BROKER_POLICY from shared template",
                )
            except Exception as exc:
                self.add("norman launcher policy auto-repair", False, str(exc))
        required = [
            "Switchboard BBS operating rules:",
            "A 403 when reading another actor's inbox, including Norman's, is expected",
            "Norman and Subprime are the admin-level coordination actors",
            "Family/toy-box actors stay isolated from work/private lanes",
            "Treat each actionable BBS handoff as a finite task thread",
            "Do not ACK an empty waiting-pickup shell just to clear it",
            "Post checkpoint updates for long-running work",
            "Fork broad project, policy, incident, or standing-context threads",
            "scripts/bbs_task_lifecycle.py",
            "Close the loop when the task is complete",
            "Do not leave old picked-up or waiting-pickup BBS threads open",
            "scripts/bbs_janitor.py",
            "Apply only deterministic safe fixes",
            "GitHub release flow policy:",
            "GapIntelligence/.github-private",
            "scripts/check_release_gitflow.py",
        ]
        missing = [
            item
            for item in required
            if item not in template_policy or item not in norman_policy
        ]
        self.add(
            "launch prompt BBS policy present",
            not missing,
            ", ".join(missing),
            missing=missing,
        )
        self.add(
            "norman launcher policy matches template",
            bool(template_policy and template_policy == norman_policy),
            "COMMON_BROKER_POLICY drift" if template_policy != norman_policy else "",
        )

    def check_health(self) -> None:
        status, payload = _request("GET", _join_url(self.url, "/healthz"))
        health = (
            payload.get("bot_health")
            if isinstance(payload.get("bot_health"), dict)
            else {}
        )
        ok = (
            status == 200
            and payload.get("ok") is True
            and int(payload.get("actor_count") or 0) == self.args.expected_actor_count
            and int(payload.get("token_count") or 0) == self.args.expected_actor_count
            and int(health.get("ok") or 0) == int(health.get("required") or 0)
            and int(health.get("stale") or 0) == 0
            and int(health.get("missing") or 0) == 0
        )
        self.add(
            "bbs health clean",
            ok,
            "",
            status=status,
            actor_count=payload.get("actor_count"),
            token_count=payload.get("token_count"),
            required=health.get("required"),
            health_ok=health.get("ok"),
            not_required=health.get("not_required"),
            stale=health.get("stale"),
            missing=health.get("missing"),
        )

    def check_capabilities(self) -> None:
        status, payload = self.actor_request("norman", "GET", "/api/v1/capabilities")
        capabilities = (
            payload.get("capabilities")
            if isinstance(payload.get("capabilities"), dict)
            else {}
        )
        auth = (
            capabilities.get("auth")
            if isinstance(capabilities.get("auth"), dict)
            else {}
        )
        admins = {str(item) for item in auth.get("admin_actors") or []}
        grant_text = str(auth.get("access_grants") or "")
        ok = (
            status == 200
            and admins == EXPECTED_ADMIN_ACTORS
            and "Support actors such as NetOps cannot grant upward" in grant_text
        )
        self.add(
            "bbs capabilities authority model",
            ok,
            grant_text,
            status=status,
            admin_actors=sorted(admins),
        )

    def check_policy_thread_readable(self) -> None:
        live_actors = self.live_actors()
        actors, missing = _select_actors(live_actors, self.actor_filter)
        failed = [f"{actor}: not live" for actor in missing]
        for actor in actors:
            try:
                status, payload = self.actor_request(
                    actor,
                    "GET",
                    f"/api/v1/threads/{urllib.parse.quote(self.policy_thread_id)}",
                )
            except Exception as exc:
                failed.append(f"{actor}: {exc}")
                continue
            if status != 200 or payload.get("ok") is not True:
                failed.append(f"{actor}: status={status} error={payload.get('error')}")
        self.add(
            "policy thread readable by live actors",
            not failed,
            "; ".join(failed),
            checked=len(actors),
            requested=self.actor_filter,
            failed=failed,
        )

    def check_grant_denial_hint(self) -> None:
        payload = {
            "posted_by": "netops",
            "actor": "norman",
            "access": ["read"],
            "reason": "bbs doctor expected admin-only grant denial",
        }
        status, response = self.actor_request(
            "netops",
            "POST",
            f"/api/v1/threads/{urllib.parse.quote(self.policy_thread_id)}/grant",
            payload=payload,
        )
        hint = str(response.get("hint") or "")
        ok = (
            status == 403
            and response.get("error") == "actor_not_allowed_for_access_grant"
            and "admin-only" in hint
            and "cannot grant upward" in hint
        )
        self.add("netops upward grant denied with hint", ok, hint, status=status)

    def probe_escalation_create(self) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        requested = self.probe_actor_filter or self.actor_filter
        actors, missing = _select_actors(tuple(PROMOTED_TUI_ACTORS), requested)
        failed = [f"{actor}: not a promoted TUI actor" for actor in missing]
        for actor in actors:
            scope = PROMOTED_TUI_ACTORS[actor]
            thread_id = f"th_escalation_probe_{actor}_{stamp}"
            create_payload = {
                "thread_id": thread_id,
                "title": f"Escalation probe from {actor} to Norman",
                "priority": "low",
                "scope": {
                    "site": scope["site"],
                    "system": scope["system"],
                    "topic": "escalation-probe",
                    "lane": scope["lane"],
                },
                "summary": f"Transient BBS doctor probe: {actor} can escalate to Norman.",
                "created_by": actor,
                "owner": "norman",
                "tags": ["domain:bbs", "work:governance"],
                "watchers": [actor],
            }
            status, response = self.actor_request(
                actor, "POST", "/api/v1/threads", payload=create_payload
            )
            if status not in {200, 201} or response.get("ok") is not True:
                failed.append(
                    f"{actor}: create status={status} error={response.get('error')}"
                )
                continue
            delete_payload = {
                "deleted_by": "norman",
                "reason": "cleanup transient BBS doctor escalation probe",
            }
            delete_status, delete_response = self.actor_request(
                "norman",
                "POST",
                f"/api/v1/threads/{urllib.parse.quote(thread_id)}/delete",
                payload=delete_payload,
            )
            if delete_status != 200 or delete_response.get("ok") is not True:
                failed.append(
                    f"{actor}: cleanup status={delete_status} error={delete_response.get('error')}"
                )
        self.add(
            "promoted TUIs can create Norman escalations",
            not failed,
            "; ".join(failed),
            checked=len(actors),
            requested=requested,
            failed=failed,
        )

    def probe_admin_grant_revoke(self) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        thread_id = f"th_revocation_probe_norman_{stamp}"
        grant_id = f"grant_revocation_probe_{stamp}"
        failed: list[str] = []
        created = False
        create_payload = {
            "thread_id": thread_id,
            "title": "Norman BBS access revocation probe",
            "priority": "low",
            "scope": {
                "site": "norman",
                "system": "switchboard",
                "topic": "revocation-drill",
                "lane": "norman",
            },
            "summary": "Transient probe: create, grant, revoke, verify, delete.",
            "created_by": "norman",
            "owner": "norman",
            "tags": ["domain:bbs", "work:governance"],
            "watchers": ["norman"],
        }
        try:
            status, response = self.actor_request(
                "norman", "POST", "/api/v1/threads", payload=create_payload
            )
            if status not in {200, 201} or response.get("ok") is not True:
                failed.append(f"create status={status} error={response.get('error')}")
            else:
                created = True
                grant_payload = {
                    "posted_by": "norman",
                    "grant_id": grant_id,
                    "actor": "panelbot",
                    "access": ["read", "reply"],
                    "reason": "transient revocation drill grant",
                }
                status, response = self.actor_request(
                    "norman",
                    "POST",
                    f"/api/v1/threads/{urllib.parse.quote(thread_id)}/grant",
                    payload=grant_payload,
                )
                if status != 200 or response.get("ok") is not True:
                    failed.append(
                        f"grant status={status} error={response.get('error')}"
                    )
                else:
                    revoke_payload = {
                        "posted_by": "norman",
                        "grant_id": grant_id,
                        "reason": "transient revocation drill cleanup",
                    }
                    status, response = self.actor_request(
                        "norman",
                        "POST",
                        f"/api/v1/threads/{urllib.parse.quote(thread_id)}/revoke-grant",
                        payload=revoke_payload,
                    )
                    revoked = (
                        response.get("revoked") if isinstance(response, dict) else []
                    )
                    if (
                        status != 200
                        or response.get("ok") is not True
                        or not isinstance(revoked, list)
                        or len(revoked) != 1
                    ):
                        failed.append(
                            f"revoke status={status} revoked={len(revoked) if isinstance(revoked, list) else 'invalid'} error={response.get('error')}"
                        )
                    else:
                        status, response = self.actor_request(
                            "norman",
                            "GET",
                            f"/api/v1/threads/{urllib.parse.quote(thread_id)}",
                        )
                        thread = (
                            response.get("thread") if isinstance(response, dict) else {}
                        )
                        grants = (
                            thread.get("access_grants")
                            if isinstance(thread, dict)
                            else []
                        )
                        if status != 200 or response.get("ok") is not True:
                            failed.append(
                                f"verify status={status} error={response.get('error')}"
                            )
                        if any(
                            isinstance(grant, dict)
                            and grant.get("grant_id") == grant_id
                            for grant in grants or []
                        ):
                            failed.append("verify grant still present after revoke")
        finally:
            if created:
                delete_payload = {
                    "deleted_by": "norman",
                    "reason": "cleanup transient revocation probe",
                }
                status, response = self.actor_request(
                    "norman",
                    "POST",
                    f"/api/v1/threads/{urllib.parse.quote(thread_id)}/delete",
                    payload=delete_payload,
                )
                if status != 200 or response.get("ok") is not True:
                    failed.append(
                        f"cleanup status={status} error={response.get('error')}"
                    )
        self.add(
            "admin grant/revoke access path",
            not failed,
            "; ".join(failed),
            thread_id=thread_id,
            grant_id=grant_id,
        )

    def run(self) -> int:
        self.run_check("launch prompt BBS policy check", self.check_prompt_drift)
        self.run_check("bbs health clean", self.check_health)
        self.run_check("bbs capabilities authority model", self.check_capabilities)
        self.run_check(
            "policy thread readable by live actors",
            self.check_policy_thread_readable,
        )
        if not self.args.skip_grant_denial:
            self.run_check(
                "netops upward grant denied with hint", self.check_grant_denial_hint
            )
        if self.args.probe_escalation:
            self.run_check(
                "promoted TUIs can create Norman escalations",
                self.probe_escalation_create,
            )
        if self.args.probe_grant_revoke:
            self.run_check(
                "admin grant/revoke access path", self.probe_admin_grant_revoke
            )
        return 0 if all(check.ok for check in self.checks) else 1

    def emit(self, exit_code: int) -> None:
        payload = {
            "ok": exit_code == 0,
            "checks": [check.as_dict() for check in self.checks],
        }
        if self.args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return
        for check in self.checks:
            prefix = "ok" if check.ok else "FAIL"
            line = f"{prefix} {check.name}"
            if check.detail:
                line = f"{line}: {check.detail}"
            print(line)
        print(f"summary ok={payload['ok']} checks={len(self.checks)}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--actor-dir", default=str(DEFAULT_ACTOR_DIR))
    parser.add_argument(
        "--actor-env-file",
        action="append",
        default=[],
        metavar="ACTOR=PATH",
        help=(
            "Use a specific actor env file instead of ACTOR_DIR/actor.env. "
            "May be repeated."
        ),
    )
    parser.add_argument("--bot-directory", default=str(DEFAULT_BOT_DIRECTORY))
    parser.add_argument("--policy-thread-id", default=DEFAULT_POLICY_THREAD_ID)
    parser.add_argument(
        "--expected-actor-count", type=int, default=EXPECTED_ACTOR_COUNT
    )
    parser.add_argument(
        "--actor",
        dest="actors",
        action="append",
        default=[],
        help=(
            "Limit actor-scoped read checks to one or more actors. "
            "May be repeated or comma-separated."
        ),
    )
    parser.add_argument(
        "--probe-actor",
        dest="probe_actors",
        action="append",
        default=[],
        help=(
            "Limit --probe-escalation create/delete probes to one or more "
            "promoted TUI actors. May be repeated or comma-separated. "
            "Defaults to --actor when omitted."
        ),
    )
    parser.add_argument("--repair-launcher", action="store_true")
    parser.add_argument("--probe-escalation", action="store_true")
    parser.add_argument("--probe-grant-revoke", action="store_true")
    parser.add_argument("--skip-grant-denial", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    doctor = Doctor(parse_args(list(argv or sys.argv[1:])))
    exit_code = doctor.run()
    doctor.emit(exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
