#!/usr/bin/env python3
"""Verify brokered Codex access to every configured TUI Responses gateway."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    from scripts import codex_route
except ModuleNotFoundError:
    import codex_route  # type: ignore[no-redef]


SCHEMA = "norman.codex-route-proof.v1"
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_codex_route_proof.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def route_keys() -> tuple[str, ...]:
    return tuple(route.key for route in codex_route.ROUTES)


def select_routes(keys: Sequence[str]) -> list[codex_route.Route]:
    selected = set(keys)
    routes = [
        route for route in codex_route.ROUTES if not selected or route.key in selected
    ]
    missing = selected.difference(route.key for route in routes)
    if missing:
        raise ValueError(f"Unknown route(s): {', '.join(sorted(missing))}")
    return routes


def _route_result(
    route: codex_route.Route,
    *,
    dry_run: bool,
    attempts: int,
    verifier: Callable[[codex_route.Route], tuple[bool, str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "route": route.key,
        "launcher": route.launcher,
        "endpoint": route.endpoint,
        "token_secret": route.resolved_token_secret,
        "attempts": 0,
        "ok": False,
        "detail": "",
    }
    if dry_run:
        result.update(attempts=0, ok=True, detail="verification planned")
        return result
    for attempt in range(1, attempts + 1):
        result["attempts"] = attempt
        try:
            result["ok"], result["detail"] = verifier(route)
        except Exception as exc:
            result["detail"] = f"verification raised {type(exc).__name__}"
        if result["ok"]:
            break
    return result


def prove_routes(
    routes: Sequence[codex_route.Route],
    *,
    dry_run: bool,
    parallelism: int,
    attempts: int = 1,
    verifier: Callable[[codex_route.Route], tuple[bool, str]] | None = None,
) -> list[dict[str, Any]]:
    verify = verifier or codex_route.verify_route
    if dry_run:
        return [
            _route_result(
                route,
                dry_run=True,
                attempts=attempts,
                verifier=verify,
            )
            for route in routes
        ]

    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(max(1, parallelism), len(routes))
    ) as executor:
        futures = {
            executor.submit(
                _route_result,
                route,
                dry_run=False,
                attempts=attempts,
                verifier=verify,
            ): route.key
            for route in routes
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[str(result["route"])] = result
    return [results[route.key] for route in routes]


def report_payload(
    results: Sequence[dict[str, Any]], *, dry_run: bool
) -> dict[str, Any]:
    successful = sum(1 for result in results if result["ok"])
    return {
        "schema": SCHEMA,
        "checked_at": utc_now(),
        "dry_run": dry_run,
        "ok": successful == len(results),
        "summary": {
            "total": len(results),
            "successful": successful,
            "failed": len(results) - successful,
        },
        "routes": list(results),
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary_path.replace(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify brokered Codex access to configured TUI gateways."
    )
    parser.add_argument(
        "--route",
        action="append",
        choices=route_keys(),
        default=[],
        help="Route key to verify; repeat to verify a subset.",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=4,
        help="Maximum concurrent gateway checks (default: 4).",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="Maximum authenticated checks per route (default: 1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the planned checks without requesting brokered tokens.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help=f"Report destination (default: {DEFAULT_OUTPUT_JSON}).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.parallelism < 1:
        print("codex-route-proof: --parallelism must be at least 1.", file=sys.stderr)
        return 2
    if args.attempts < 1:
        print("codex-route-proof: --attempts must be at least 1.", file=sys.stderr)
        return 2
    routes = select_routes(args.route)
    results = prove_routes(
        routes,
        dry_run=bool(args.dry_run),
        parallelism=args.parallelism,
        attempts=args.attempts,
    )
    payload = report_payload(results, dry_run=bool(args.dry_run))
    write_report(args.output_json, payload)
    action = "planned" if args.dry_run else "verified"
    print(
        f"codex-route-proof: {payload['summary']['successful']}/"
        f"{payload['summary']['total']} routes {action}",
        file=sys.stderr,
    )
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
