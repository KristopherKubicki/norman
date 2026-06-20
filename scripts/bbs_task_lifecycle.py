#!/usr/bin/env python3
"""Task lifecycle helper for Switchboard BBS threads."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ticket_token_cost_ledger import (  # noqa: E402
    DEFAULT_LEDGER_JSONL as DEFAULT_TICKET_COST_LEDGER_JSONL,
)
from ticket_token_cost_ledger import append_record as append_ticket_cost_record  # noqa: E402
from ticket_token_cost_ledger import build_record as build_ticket_cost_record  # noqa: E402
from ticket_token_cost_ledger import (  # noqa: E402
    build_record_from_usage_events as build_ticket_cost_record_from_usage_events,
)
from ticket_token_cost_ledger import load_usage_events  # noqa: E402


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
    quoted = urllib.parse.quote(thread_id)
    return f"{args.url}/api/v1/threads/{quoted}{suffix}"


def _get_thread(args: argparse.Namespace, thread_id: str) -> dict[str, Any]:
    payload = _request_json("GET", _thread_url(args, thread_id), token=args.token)
    if not payload.get("ok"):
        raise SystemExit(json.dumps(payload, indent=2, sort_keys=True))
    thread = payload.get("thread")
    if not isinstance(thread, dict):
        raise SystemExit("BBS response did not include a thread object")
    return thread


def _read_body(value: str | None, file_text: str | None, *, field: str) -> str:
    if value and file_text:
        raise SystemExit(f"use either {field} or --{field}-file, not both")
    if file_text:
        if file_text == "-":
            return sys.stdin.read()
        return Path(file_text).expanduser().read_text(encoding="utf-8")
    return value or ""


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    clean: list[str] = []
    for raw in items:
        item = str(raw or "").strip()
        if item and item not in seen:
            clean.append(item)
            seen.add(item)
    return clean


def _safe_artifact_filename(path: Path, prefix: str = "") -> str:
    name = path.name.strip()
    safe_name = re.sub(r"[^A-Za-z0-9._:-]+", "_", name).strip("._")
    safe_prefix = re.sub(r"[^A-Za-z0-9._:-]+", "_", str(prefix or "")).strip("._")
    if safe_prefix:
        safe_name = f"{safe_prefix}_{safe_name}"
    if not safe_name or safe_name in {".", ".."}:
        raise SystemExit(f"invalid artifact filename for {path}")
    return safe_name[:200]


def _parent_tag(parent_thread_id: str) -> str:
    tag = f"parent:{parent_thread_id}".lower()
    return tag[:128]


def build_fork_payload(
    *,
    parent: dict[str, Any],
    args: argparse.Namespace,
    actor: str,
) -> dict[str, Any]:
    parent_scope = parent.get("scope") if isinstance(parent.get("scope"), dict) else {}
    parent_title = str(parent.get("title") or parent.get("thread_id") or "").strip()
    parent_thread_id = str(parent.get("thread_id") or args.parent_thread_id).strip()
    scope = {
        "site": args.site or str(parent_scope.get("site") or ""),
        "system": args.system or str(parent_scope.get("system") or ""),
        "topic": args.topic or str(parent_scope.get("topic") or ""),
        "lane": args.lane or str(parent_scope.get("lane") or ""),
    }
    missing = [key for key, value in scope.items() if not str(value or "").strip()]
    if missing:
        raise SystemExit(f"missing fork scope fields: {', '.join(missing)}")

    summary = _read_body(args.summary, args.summary_file, field="summary").strip()
    parent_note = f"Parent BBS thread: {parent_thread_id}"
    if parent_title:
        parent_note = f"{parent_note} ({parent_title})"
    if summary:
        summary = f"{summary}\n\n{parent_note}."
    else:
        summary = f"Forked task from {parent_note}."

    tags = _dedupe([*(args.tag or []), "work:task", _parent_tag(parent_thread_id)])
    watchers = _dedupe([*(args.watcher or []), actor])

    return {
        "thread_id": args.thread_id or "",
        "title": args.title,
        "priority": args.priority or str(parent.get("priority") or "normal"),
        "scope": scope,
        "summary": summary,
        "created_by": actor,
        "owner": args.owner,
        "tags": tags,
        "watchers": watchers,
    }


def cmd_ack(args: argparse.Namespace) -> int:
    payload = {
        "posted_by": _actor(args.actor),
        "eta": args.eta or "",
        "eta_at": args.eta_at or "",
        "note": _read_body(args.note, args.note_file, field="note"),
    }
    url = _thread_url(args, args.thread_id, "/ack")
    return _print(_request_json("POST", url, token=args.token, payload=payload))


def _cost_logging_requested(args: argparse.Namespace) -> bool:
    return any(
        bool(getattr(args, name, None))
        for name in (
            "cost_ticket_id",
            "cost_usage_db",
            "cost_input_tokens",
            "cost_cached_input_tokens",
            "cost_output_tokens",
            "cost_reasoning_output_tokens",
            "cost_total_tokens",
        )
    )


def _append_ticket_cost_if_requested(
    args: argparse.Namespace, *, status: str
) -> dict[str, Any] | None:
    if not _cost_logging_requested(args):
        return None
    ticket_id = str(getattr(args, "cost_ticket_id", "") or args.thread_id)
    actor = _actor(args.actor)
    usage_db = getattr(args, "cost_usage_db", None)
    ledger_jsonl = Path(
        getattr(args, "cost_ledger_jsonl", DEFAULT_TICKET_COST_LEDGER_JSONL)
    )
    thread_id = str(getattr(args, "cost_thread_id", "") or args.thread_id)
    architecture_mode = str(getattr(args, "cost_architecture_mode", "") or "unknown")
    price_basis = str(getattr(args, "cost_price_basis", "") or "auto")
    notes = str(getattr(args, "cost_notes", "") or f"BBS thread marked {status}.")
    if usage_db:
        record = build_ticket_cost_record_from_usage_events(
            ticket_id=ticket_id,
            events=load_usage_events(Path(usage_db), thread_id=thread_id),
            actor=actor,
            source_ref=str(usage_db),
            thread_id=thread_id,
            architecture_mode=architecture_mode,
            price_basis=price_basis,
            notes=notes,
        )
    else:
        record = build_ticket_cost_record(
            ticket_id=ticket_id,
            actor=actor,
            thread_id=thread_id,
            source_kind="bbs_task_lifecycle",
            source_ref=args.thread_id,
            architecture_mode=architecture_mode,
            runtime=str(getattr(args, "cost_runtime", "") or ""),
            model=str(getattr(args, "cost_model", "") or ""),
            service_tier=str(getattr(args, "cost_service_tier", "") or ""),
            price_basis=price_basis,
            input_tokens=int(getattr(args, "cost_input_tokens", 0) or 0),
            cached_input_tokens=int(getattr(args, "cost_cached_input_tokens", 0) or 0),
            output_tokens=int(getattr(args, "cost_output_tokens", 0) or 0),
            reasoning_output_tokens=int(
                getattr(args, "cost_reasoning_output_tokens", 0) or 0
            ),
            total_tokens=int(getattr(args, "cost_total_tokens", 0) or 0),
            usage_event_count=0,
            notes=notes,
            metadata={"bbs_status": status},
        )
    append_ticket_cost_record(ledger_jsonl, record)
    return {
        "id": record.get("id"),
        "ledger_jsonl": str(ledger_jsonl),
        "ticket_id": record.get("ticket", {}).get("id"),
        "total_tokens": record.get("usage", {}).get("total_tokens"),
        "estimated_usd": record.get("cost", {}).get("estimated_usd"),
        "charge_status": record.get("billing", {}).get("charge_status"),
    }


def _post_status(args: argparse.Namespace, *, status: str, default_reason: str) -> int:
    payload = {
        "status": status,
        "posted_by": _actor(args.actor),
        "reason": _read_body(args.reason, args.reason_file, field="reason")
        or default_reason,
    }
    url = _thread_url(args, args.thread_id, "/status")
    result = _request_json("POST", url, token=args.token, payload=payload)
    if result.get("ok"):
        try:
            ticket_cost = _append_ticket_cost_if_requested(args, status=status)
        except Exception as exc:
            result["ok"] = False
            result["ticket_cost_error"] = f"{type(exc).__name__}: {exc}"
        else:
            if ticket_cost:
                result["ticket_cost_record"] = ticket_cost
    return _print(result)


def _add_cost_logging_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cost-ticket-id",
        help="Ticket id for internal token/cost logging. Defaults to thread_id.",
    )
    parser.add_argument(
        "--cost-ledger-jsonl",
        type=Path,
        default=DEFAULT_TICKET_COST_LEDGER_JSONL,
        help="Append internal token/cost records to this JSONL ledger.",
    )
    parser.add_argument(
        "--cost-usage-db",
        type=Path,
        help="Aggregate matching usage_events from this TUI SQLite state DB.",
    )
    parser.add_argument(
        "--cost-thread-id",
        help="Thread id to aggregate from usage_events. Defaults to BBS thread_id.",
    )
    parser.add_argument("--cost-architecture-mode", default="unknown")
    parser.add_argument(
        "--cost-price-basis",
        choices=[
            "auto",
            "none",
            "openai-direct-standard",
            "openai-direct-flex",
            "bedrock-us-east-2",
        ],
        default="auto",
    )
    parser.add_argument("--cost-runtime", default="")
    parser.add_argument("--cost-model", default="")
    parser.add_argument("--cost-service-tier", default="")
    parser.add_argument("--cost-input-tokens", type=int, default=0)
    parser.add_argument("--cost-cached-input-tokens", type=int, default=0)
    parser.add_argument("--cost-output-tokens", type=int, default=0)
    parser.add_argument("--cost-reasoning-output-tokens", type=int, default=0)
    parser.add_argument("--cost-total-tokens", type=int, default=0)
    parser.add_argument("--cost-notes", default="")


def cmd_done(args: argparse.Namespace) -> int:
    return _post_status(args, status="done", default_reason="Task complete.")


def cmd_blocked(args: argparse.Namespace) -> int:
    return _post_status(args, status="blocked", default_reason="Task blocked.")


def cmd_fork(args: argparse.Namespace) -> int:
    actor = _actor(args.actor)
    parent = _get_thread(args, args.parent_thread_id)
    payload = build_fork_payload(parent=parent, args=args, actor=actor)
    created = _request_json(
        "POST",
        f"{args.url}/api/v1/threads",
        token=args.token,
        payload=payload,
    )
    if created.get("ok"):
        created.setdefault("parent_thread_id", args.parent_thread_id)
        created.setdefault("fork", payload)
    return _print(created)


def cmd_attach_files(args: argparse.Namespace) -> int:
    actor = _actor(args.actor)
    uploaded: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for raw_path in args.file or []:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            return _print(
                {
                    "ok": False,
                    "error": "artifact_file_not_found",
                    "path": str(path),
                }
            )
        filename = _safe_artifact_filename(path, args.name_prefix)
        if filename in seen_names:
            return _print(
                {
                    "ok": False,
                    "error": "duplicate_artifact_filename",
                    "filename": filename,
                }
            )
        seen_names.add(filename)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        upload = _request_json(
            "POST",
            f"{args.url}/api/v1/artifacts",
            token=args.token,
            timeout=args.upload_timeout,
            payload={
                "uploaded_by": actor,
                "filename": filename,
                "label": path.name,
                "content_base64": base64.b64encode(data).decode("ascii"),
                "sha256": digest,
                "overwrite": bool(args.overwrite),
            },
        )
        if not upload.get("ok"):
            upload.setdefault("attempted_path", str(path))
            upload.setdefault("attempted_filename", filename)
            return _print(upload)
        artifact = upload.get("artifact")
        if not isinstance(artifact, dict):
            return _print(
                {
                    "ok": False,
                    "error": "upload_response_missing_artifact",
                    "path": str(path),
                }
            )
        uploaded.append(
            {
                "label": str(artifact.get("label") or path.name),
                "href": str(artifact.get("href") or ""),
            }
        )

    body = _read_body(args.body, args.body_file, field="body").strip()
    if not body:
        labels = ", ".join(item["label"] for item in uploaded)
        body = f"Attached {len(uploaded)} artifact file(s): {labels}."
    message = _request_json(
        "POST",
        _thread_url(args, args.thread_id, "/messages"),
        token=args.token,
        payload={
            "posted_by": actor,
            "kind": "artifact",
            "body": body,
            "artifacts": uploaded,
        },
    )
    if message.get("ok"):
        message["uploaded_artifacts"] = uploaded
    return _print(message)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--token", default=DEFAULT_TOKEN)
    ap.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    ap.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ack", help="Mark a BBS task thread as picked up.")
    p.add_argument("--actor")
    p.add_argument("thread_id")
    p.add_argument("--eta")
    p.add_argument("--eta-at")
    p.add_argument("--note")
    p.add_argument("--note-file")
    p.set_defaults(func=cmd_ack)

    p = sub.add_parser("done", help="Close a BBS task thread as done.")
    p.add_argument("--actor")
    p.add_argument("thread_id")
    p.add_argument("--reason")
    p.add_argument("--reason-file")
    _add_cost_logging_args(p)
    p.set_defaults(func=cmd_done)

    p = sub.add_parser("blocked", help="Mark a BBS task thread as blocked.")
    p.add_argument("--actor")
    p.add_argument("thread_id")
    p.add_argument("--reason")
    p.add_argument("--reason-file")
    _add_cost_logging_args(p)
    p.set_defaults(func=cmd_blocked)

    p = sub.add_parser(
        "fork",
        help="Create a finite task thread from a broader parent BBS thread.",
    )
    p.add_argument("--actor")
    p.add_argument("parent_thread_id")
    p.add_argument("--thread-id")
    p.add_argument("--title", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--summary")
    p.add_argument("--summary-file")
    p.add_argument("--priority")
    p.add_argument("--site")
    p.add_argument("--system")
    p.add_argument("--topic")
    p.add_argument("--lane")
    p.add_argument("--tag", action="append")
    p.add_argument("--watcher", action="append")
    p.set_defaults(func=cmd_fork)

    p = sub.add_parser(
        "attach-files",
        help="Upload local files to BBS artifact storage and attach them to a thread.",
    )
    p.add_argument("--actor")
    p.add_argument("thread_id")
    p.add_argument("file", nargs="+")
    p.add_argument("--body")
    p.add_argument("--body-file")
    p.add_argument("--name-prefix", default="")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--upload-timeout", type=float, default=60.0)
    p.set_defaults(func=cmd_attach_files)

    return ap


def main(argv: list[str]) -> int:
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
        if env_file.get("SWITCHBOARD_ACTOR") and not os.environ.get(
            "SWITCHBOARD_ACTOR"
        ):
            os.environ["SWITCHBOARD_ACTOR"] = str(env_file["SWITCHBOARD_ACTOR"]).strip()
    if args.token_file:
        args.token = _read_token_file(args.token_file)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
