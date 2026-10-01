#!/usr/bin/env python3
"""Refresh one worker-local Norllama route-policy artifact."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

# Allow the repo-owned command to run from cron, systemd, or any working directory.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from app.services.norllama.route_policy_artifact import refresh_route_policy_artifact


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        required=True,
        type=Path,
        help="Absolute path to the worker-local route-policy artifact.",
    )
    return parser.parse_args(argv)


def _summary(result: dict[str, object], *, path: Path) -> dict[str, object]:
    policy = result.get("policy")
    validation = result.get("validation")
    write = result.get("write")
    policy = policy if isinstance(policy, dict) else {}
    validation = validation if isinstance(validation, dict) else {}
    write = write if isinstance(write, dict) else {}
    refreshed = bool(result.get("last_refresh_success"))
    route_allowed = bool(validation.get("default_route_allowed"))
    write_ok = bool(write.get("ok", refreshed))
    status = "ok" if refreshed and write_ok and route_allowed else "blocked"
    return {
        "schema": "norman.norllama.route-policy-refresh-command.v1",
        "status": status,
        "path": str(path),
        "policy_id": str(policy.get("policy_id") or ""),
        "policy_hash": str(policy.get("policy_hash") or ""),
        "refresh_generation": int(result.get("active_generation") or 0),
        "previous_generation": int(result.get("previous_generation") or 0),
        "validation_state": str(validation.get("state") or ""),
        "default_route_allowed": route_allowed,
        "production_route_eligible": bool(validation.get("production_route_eligible")),
        "expires_at": str(
            validation.get("expires_at") or policy.get("expires_at") or ""
        ),
        "error": str(result.get("last_refresh_error") or write.get("error") or ""),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = refresh_route_policy_artifact(args.path)
        summary = _summary(result, path=args.path)
    except Exception as exc:
        summary = {
            "schema": "norman.norllama.route-policy-refresh-command.v1",
            "status": "blocked",
            "path": str(args.path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
