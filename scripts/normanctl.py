#!/usr/bin/env python3
"""Norman hypervisor CLI (screen-backed runtime/session management)."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:  # noqa: E402
    from app.services import screen_hypervisor
except ModuleNotFoundError:
    # Fallback import path for shells that do not have full app deps activated.
    app_dir = REPO_ROOT / "app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from services import screen_hypervisor


def _registry(args: argparse.Namespace) -> dict[str, Any]:
    return screen_hypervisor.load_registry(args.registry)


def _targets(args: argparse.Namespace) -> list[str]:
    if args.target == "both":
        return ["app", "agent"]
    return [args.target]


def cmd_init(args: argparse.Namespace) -> int:
    path = screen_hypervisor.init_registry(args.registry, overwrite=args.force)
    print(path)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = screen_hypervisor.status(
        _registry(args),
        app_name=args.app,
        state_dir=args.state_dir,
        log_dir=args.log_dir,
    )
    print(json.dumps(payload, indent=2))
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    registry = _registry(args)
    names = (
        [args.app] if args.app != "all" else sorted((registry.get("apps") or {}).keys())
    )
    for name in names:
        app = registry["apps"].get(name)
        if not isinstance(app, dict):
            print(f"skip {name}: missing app config")
            continue
        for target in _targets(args):
            if target not in app:
                continue
            result = screen_hypervisor.start_target(
                registry,
                name,
                target=target,
                log_dir=args.log_dir,
            )
            print(json.dumps({"app": name, "target": target, **result}))
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    registry = _registry(args)
    names = (
        [args.app] if args.app != "all" else sorted((registry.get("apps") or {}).keys())
    )
    for name in names:
        app = registry["apps"].get(name)
        if not isinstance(app, dict):
            print(f"skip {name}: missing app config")
            continue
        for target in _targets(args):
            if target not in app:
                continue
            result = screen_hypervisor.stop_target(registry, name, target=target)
            print(json.dumps({"app": name, "target": target, **result}))
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    result = screen_hypervisor.send(
        _registry(args),
        args.app,
        text=args.text,
        target=args.target,
        enter_count=args.enter_count,
        state_dir=args.state_dir,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_lock(args: argparse.Namespace) -> int:
    registry = _registry(args)
    for target in _targets(args):
        result = screen_hypervisor.set_lock(
            registry,
            args.app,
            target=target,
            locked=True,
            state_dir=args.state_dir,
        )
        print(json.dumps({"target": target, **result}, indent=2))
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    registry = _registry(args)
    for target in _targets(args):
        result = screen_hypervisor.set_lock(
            registry,
            args.app,
            target=target,
            locked=False,
            state_dir=args.state_dir,
        )
        print(json.dumps({"target": target, **result}, indent=2))
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    registry = _registry(args)
    app = registry.get("apps", {}).get(args.app)
    if not isinstance(app, dict):
        raise SystemExit(f"App not found: {args.app}")
    for target in _targets(args):
        if target not in app:
            continue
        length = screen_hypervisor.queue_length(
            args.app,
            target,
            state_dir=args.state_dir,
        )
        print(json.dumps({"app": args.app, "target": target, "queue_length": length}))
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    result = screen_hypervisor.pull_logs(
        _registry(args),
        args.app,
        target=args.target,
        state_dir=args.state_dir,
        log_dir=args.log_dir,
        max_bytes=args.max_bytes,
        auto_ack=not args.no_auto_ack,
    )
    text = result.pop("text", "")
    print(json.dumps(result, indent=2))
    if text:
        print("\n---")
        print(text.rstrip())
    return 0


def cmd_drain(args: argparse.Namespace) -> int:
    result = screen_hypervisor.drain_queue(
        _registry(args),
        args.app,
        target=args.target,
        state_dir=args.state_dir,
    )
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Norman hypervisor control CLI")
    parser.add_argument(
        "--registry",
        default=str(screen_hypervisor.DEFAULT_REGISTRY_PATH),
        help="Path to apps registry YAML",
    )
    parser.add_argument(
        "--state-dir",
        default=str(screen_hypervisor.DEFAULT_STATE_DIR),
        help="Directory for lock/queue state files",
    )
    parser.add_argument(
        "--log-dir",
        default=str(screen_hypervisor.DEFAULT_LOG_DIR),
        help="Default directory for screen logs when registry target omits log_file",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Create registry from template")
    p.add_argument("--force", action="store_true", help="Overwrite existing registry")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("status", help="Show app/session status")
    p.add_argument("app", nargs="?", help="Optional app name")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("up", help="Start app/agent screen sessions")
    p.add_argument("app", help="App name or 'all'")
    p.add_argument("--target", choices=["app", "agent", "both"], default="both")
    p.set_defaults(func=cmd_up)

    p = sub.add_parser("down", help="Stop app/agent screen sessions")
    p.add_argument("app", help="App name or 'all'")
    p.add_argument("--target", choices=["app", "agent", "both"], default="both")
    p.set_defaults(func=cmd_down)

    p = sub.add_parser("send", help="Send text to an app target")
    p.add_argument("app", help="App name")
    p.add_argument("text", help="Text payload")
    p.add_argument("--target", choices=["app", "agent"], default="agent")
    p.add_argument("--enter-count", type=int, default=2)
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("lock", help="Lock target(s) and queue incoming sends")
    p.add_argument("app", help="App name")
    p.add_argument("--target", choices=["app", "agent", "both"], default="agent")
    p.set_defaults(func=cmd_lock)

    p = sub.add_parser("unlock", help="Unlock target(s) and drain queued send")
    p.add_argument("app", help="App name")
    p.add_argument("--target", choices=["app", "agent", "both"], default="agent")
    p.set_defaults(func=cmd_unlock)

    p = sub.add_parser("queue", help="Show queue depth")
    p.add_argument("app", help="App name")
    p.add_argument("--target", choices=["app", "agent", "both"], default="agent")
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("pull", help="Pull incremental log output")
    p.add_argument("app", help="App name")
    p.add_argument("--target", choices=["app", "agent"], default="agent")
    p.add_argument("--max-bytes", type=int, default=65536)
    p.add_argument("--no-auto-ack", action="store_true")
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("drain", help="Try draining one queued send")
    p.add_argument("app", help="App name")
    p.add_argument("--target", choices=["app", "agent"], default="agent")
    p.set_defaults(func=cmd_drain)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
