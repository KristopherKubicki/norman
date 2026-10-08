#!/usr/bin/env python3
"""Read configured routing identities without exporting credentials or account IDs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time


def snapshot(registry: dict, policy: dict) -> dict:
    """Expose configured ownership and model identities, never credential material."""
    if registry.get("schema") != "norman.aws-account-routing.v1":
        raise ValueError("Unknown account routing registry")
    expires = datetime.fromisoformat(policy["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("Routing policy is expired or undated")
    bindings = registry["bindings"]
    routes = {}
    for route, binding_id in registry["gateway_routes"].items():
        binding = bindings[binding_id]
        if binding["owner"] not in {"work", "personal"}:
            raise ValueError("Unknown account owner")
        routes[route] = {
            "binding": binding_id,
            "owner": binding["owner"],
            "allowed_regions": binding["regions"],
        }
    models = {
        alias: {
            field: row[field]
            for field in ("model", "provider", "aws_region")
            if field in row
        }
        for alias, row in policy["cloud_policy"]["explicit_cloud_models"].items()
        if alias.startswith("norman-code-")
    }
    return {
        "schema": "norman.routing-snapshot.v1",
        "checked_at": time.time(),
        "authority": "configured_backend_policy",
        "routes": routes,
        "named_models": models,
        "policy_id": policy.get("policy_id"),
        "policy_expires_at": policy["expires_at"],
        "account_switching": "server binding required; no implicit cross-owner fallback",
        "execution_identity_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("/var/lib/norman-account-routing/registry.json"),
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("/var/lib/norman/norllama/route_policy.json"),
    )
    parser.add_argument("--route", help="Show one registered route")
    args = parser.parse_args()
    try:
        result = snapshot(
            json.loads(args.registry.read_text()), json.loads(args.policy.read_text())
        )
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Routing metadata is unavailable or invalid; no account selection was made.\n",
        )
    if args.route:
        if args.route not in result["routes"]:
            parser.exit(1, "Route is not registered; no account selection was made.\n")
        result["routes"] = {args.route: result["routes"][args.route]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
