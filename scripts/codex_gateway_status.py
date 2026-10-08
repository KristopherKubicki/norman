#!/usr/bin/env python3
"""Read backend-independent gateway status without tokens or session contents."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def status_url(endpoint: str) -> str:
    if (
        not isinstance(endpoint, str)
        or not endpoint
        or any(ord(c) <= 32 or ord(c) == 127 for c in endpoint)
    ):
        raise ValueError("Invalid endpoint")
    url = urllib.parse.urlsplit(endpoint)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise ValueError("Invalid endpoint")
    url.port  # Validate malformed or out-of-range ports before opening a socket.
    return urllib.parse.urlunsplit(
        (
            url.scheme,
            url.netloc,
            url.path.removesuffix("/").removesuffix("/v1") + "/_gateway/status",
            "",
            "",
        )
    )


def display_endpoint(endpoint: str) -> str:
    try:
        status_url(endpoint)
        return endpoint
    except (ValueError, TypeError, AttributeError):
        return "<invalid endpoint>"


def open_status(target: str, timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    return opener.open(target, timeout=timeout)


def validate_status(state: object) -> dict:
    phases = {
        "ready",
        "recovering",
        "restarting",
        "restart_requested",
        "recovery_stalled",
        "unavailable",
        "maintenance",
    }
    if not isinstance(state, dict) or state.get("schema") != "norman.gateway-health.v1":
        raise ValueError("Unknown status contract")
    if not isinstance(state.get("phase"), str) or state["phase"] not in phases:
        raise ValueError("Unknown recovery phase")
    message = state.get("message")
    if not isinstance(message, str) or not message.isprintable() or len(message) > 1024:
        raise ValueError("Invalid recovery message")
    stamp = state.get("checked_at")
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0:
        raise ValueError("Invalid observation timestamp")
    code = state.get("backend_http")
    if type(code) is not int or (code != 0 and not 100 <= code <= 599):
        raise ValueError("Invalid backend health code")
    if state["phase"] == "ready" and code != 200:
        raise ValueError("Ready receipt contradicts backend health")
    return state


def get_status(endpoint: str, timeout: float = 3) -> dict:
    try:
        target = status_url(endpoint)
    except (ValueError, TypeError, AttributeError):
        return {
            "phase": "invalid_endpoint",
            "message": "Gateway endpoint is invalid; correct the selected profile before retrying.",
        }
    try:
        with open_status(target, timeout=timeout) as response:
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError("Oversized status receipt")
        state = validate_status(json.loads(raw))
        age = time.time() - state["checked_at"]
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
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return {
            "phase": "unreachable",
            "message": "Gateway status is unreachable or invalid; backend readiness is unknown.",
        }


def wait_for_gateway(endpoint: str, wait_seconds: float = 120) -> bool:
    deadline = time.monotonic() + wait_seconds
    host = display_endpoint(endpoint)
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
        if remaining <= 0 or phase in {
            "maintenance",
            "access_denied",
            "invalid_endpoint",
        }:
            print(
                "Session was not started; existing history is preserved. Check codex-gateway-status, or use codex-rescue with the appropriate --scope for local diagnosis.",
                file=sys.stderr,
            )
            return False
        time.sleep(min(10, remaining))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="https://norman.home.arpa/work/v1")
    parser.add_argument("--profile-file", type=Path)
    parser.add_argument("--wait", type=float, default=0)
    args = parser.parse_args()
    if not math.isfinite(args.wait):
        parser.error("--wait must be a finite number")
    endpoint = args.endpoint
    if args.profile_file:
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            profile = tomllib.loads(args.profile_file.read_text())
            provider = profile.get("model_provider", "")
            if not isinstance(provider, str):
                raise ValueError("Invalid provider name")
            endpoint = (
                profile.get("model_providers", {}).get(provider, {}).get("base_url", "")
            )
            if not isinstance(endpoint, str):
                raise ValueError("Invalid provider endpoint")
        except (OSError, ValueError, TypeError, AttributeError):
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
    print(json.dumps({"endpoint": display_endpoint(endpoint), **state}, indent=2))
    return 0 if state["phase"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
