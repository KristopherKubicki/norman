#!/usr/bin/env python3
"""Read backend-independent gateway status without tokens or session contents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def get_status(endpoint: str, timeout: float = 3) -> dict:
    url = urllib.parse.urlsplit(endpoint)
    target = urllib.parse.urlunsplit(
        (url.scheme, url.netloc, "/_gateway/status", "", "")
    )
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            state = json.loads(response.read(16384))
        if (
            not isinstance(state, dict)
            or state.get("schema") != "norman.gateway-health.v1"
        ):
            raise ValueError("unknown status contract")
        if not isinstance(state.get("phase"), str) or not isinstance(
            state.get("message"), str
        ):
            raise ValueError("invalid status fields")
        age = time.time() - float(state["checked_at"])
        if not -5 <= age <= 45:
            return {
                "phase": "stale",
                "message": "Gateway watchdog report is stale; backend readiness is unknown.",
            }
        return state
    except urllib.error.HTTPError as error:
        phase = "access_denied" if error.code in (401, 403) else "unreachable"
        return {
            "phase": phase,
            "http_status": error.code,
            "message": f"Status endpoint returned HTTP {error.code}; backend readiness is unknown.",
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "phase": "unreachable",
            "message": "Gateway status is unreachable or invalid; backend readiness is unknown.",
        }


def wait_for_gateway(endpoint: str, wait_seconds: float = 120) -> bool:
    deadline = time.monotonic() + wait_seconds
    host = urllib.parse.urlsplit(endpoint).netloc
    print(f"Codex route: {host} -> Norman model gateway.", file=sys.stderr, flush=True)
    while True:
        remaining = max(0, deadline - time.monotonic())
        state = get_status(endpoint, timeout=min(3, max(0.1, remaining)))
        phase = state["phase"]
        if phase == "ready":
            print(
                "Gateway backend is ready (model availability is checked separately).",
                file=sys.stderr,
                flush=True,
            )
            return True
        remaining = max(0, deadline - time.monotonic())
        print(
            f"Gateway {phase}: {state['message']} Waiting up to {int(remaining)}s more.",
            file=sys.stderr,
            flush=True,
        )
        if remaining <= 0 or phase in {"maintenance", "access_denied"}:
            print(
                "Session was not started; existing history is preserved. Check codex-gateway-status, or use codex-rescue with the appropriate --scope for local diagnosis.",
                file=sys.stderr,
            )
            return False
        time.sleep(min(10, remaining))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="https://keystone.kris.openbrand.com/v1")
    parser.add_argument("--profile-file", type=Path)
    parser.add_argument("--wait", type=float, default=0)
    args = parser.parse_args()
    endpoint = args.endpoint
    if args.profile_file:
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            profile = tomllib.loads(args.profile_file.read_text())
            provider = profile.get("model_provider", "")
            endpoint = (
                profile.get("model_providers", {}).get(provider, {}).get("base_url", "")
            )
        except (OSError, ValueError):
            print(
                "Gateway preflight could not read the selected profile.",
                file=sys.stderr,
            )
            return 1
        # Native/direct providers are outside this gateway's recovery path.
        if not endpoint:
            return 0
    if args.wait:
        return 0 if wait_for_gateway(endpoint, max(0, min(args.wait, 120))) else 1
    state = get_status(endpoint)
    print(json.dumps({"endpoint": endpoint, **state}, indent=2))
    return 0 if state["phase"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
