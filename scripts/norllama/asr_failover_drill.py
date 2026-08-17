#!/usr/bin/env python3
"""Verify ASR redundancy without replaying or disrupting an audio upload."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.error import URLError
from urllib.request import urlopen


BACKENDS = (
    ("spark-151", "http://192.168.2.151:8095/health"),
    ("spark-150", "http://192.168.2.150:8097/health"),
)
MAC_GATEWAY = "http://192.168.2.133:18151/asr-readyz"


def get_json(url: str) -> tuple[int, dict[str, Any]]:
    try:
        with urlopen(url, timeout=8) as response:
            value = json.loads(response.read().decode("utf-8"))
            return response.status, value if isinstance(value, dict) else {}
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return 0, {}


def run_drill() -> dict[str, Any]:
    backends: list[dict[str, Any]] = []
    for name, url in BACKENDS:
        status, payload = get_json(url)
        backends.append(
            {
                "name": name,
                "url": url,
                "status_code": status,
                "healthy": status == 200 and payload.get("status") == "ok",
                "engine": payload.get("engine", ""),
                "model": payload.get("model", ""),
            }
        )
    gateway_status, gateway = get_json(MAC_GATEWAY)
    healthy = [backend for backend in backends if backend["healthy"]]
    ready = (
        gateway_status == 200
        and gateway.get("ready") is True
        and int(gateway.get("healthy_backend_count") or 0) >= 2
        and len(healthy) >= 2
    )
    return {
        "schema": "norman.norllama.asr-failover-readiness-drill.v1",
        "checked_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "mode": "readiness_only_no_audio_replay",
        "status": "ok" if ready else "failed",
        "gateway": {
            "url": MAC_GATEWAY,
            "status_code": gateway_status,
            "ready": gateway.get("ready") is True,
            "healthy_backend_count": gateway.get("healthy_backend_count"),
        },
        "backends": backends,
        "automatic_upload_replay": False,
        "note": "The gateway deliberately uses one upload attempt. This drill proves independent alternate capacity without replaying an audio request.",
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_drill()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
