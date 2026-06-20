#!/usr/bin/env python3
"""Sense local offline runtime readiness without executing model calls."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SCHEMA = "norman.local-runtime-health.v1"
DEFAULT_OUTPUT_JSON = Path("tmp/local_runtime_health.json")
DEFAULT_OUTPUT_MD = Path("tmp/local_runtime_health.md")
DEFAULT_OLLAMA_ENDPOINT = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_VLLM_ENDPOINT = os.environ.get(
    "NORMAN_SPARK_VLLM_BASE_URL", "http://127.0.0.1:8000"
)


def _read_json_url(url: str, *, timeout_seconds: float = 1.5) -> tuple[bool, Any, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return False, {}, f"http {exc.code}"
    except OSError as exc:
        return False, {}, str(exc)
    try:
        return True, json.loads(body), ""
    except json.JSONDecodeError:
        return False, {}, "response was not JSON"


def _model_count(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("models", "data", "tags"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _runtime_row(
    *,
    runtime_class: str,
    provider: str,
    endpoint: str,
    command: str,
    models_url: str,
) -> dict[str, Any]:
    command_path = shutil.which(command) or ""
    ok, payload, reason = _read_json_url(models_url)
    count = _model_count(payload)
    healthy = ok and count > 0
    if not command_path and not healthy:
        reason = (
            f"{command} command not found; {reason or 'endpoint did not list models'}"
        )
    elif ok and count <= 0:
        reason = "endpoint returned no models"
    return {
        "runtime_class": runtime_class,
        "provider": provider,
        "endpoint": endpoint,
        "models_url": models_url,
        "command": command,
        "command_path": command_path,
        "status": "healthy" if healthy else "unavailable",
        "routeable": healthy,
        "model_count": count,
        "reason": "" if healthy else reason,
    }


def build_report(
    *,
    ollama_endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    vllm_endpoint: str = DEFAULT_VLLM_ENDPOINT,
) -> dict[str, Any]:
    ollama = ollama_endpoint.rstrip("/")
    vllm = vllm_endpoint.rstrip("/")
    runtimes = [
        _runtime_row(
            runtime_class="ollama",
            provider="ollama",
            endpoint=ollama,
            command="ollama",
            models_url=f"{ollama}/api/tags",
        ),
        _runtime_row(
            runtime_class="spark_vllm",
            provider="vllm",
            endpoint=vllm,
            command="vllm",
            models_url=f"{vllm}/v1/models",
        ),
    ]
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "summary": {
            "runtime_count": len(runtimes),
            "healthy_runtime_count": sum(1 for row in runtimes if row["routeable"]),
            "unavailable_runtime_count": sum(
                1 for row in runtimes if not row["routeable"]
            ),
            "routeable_runtime_classes": [
                row["runtime_class"] for row in runtimes if row["routeable"]
            ],
        },
        "runtimes": runtimes,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Local Runtime Health",
        "",
        f"- Dry run only: `{str(report.get('dry_run_only')).lower()}`",
        f"- Model calls executed: `{report.get('model_calls_executed')}`",
        f"- Healthy runtimes: `{report['summary']['healthy_runtime_count']}`",
        f"- Unavailable runtimes: `{report['summary']['unavailable_runtime_count']}`",
        "",
        "| Runtime | Provider | Status | Models | Endpoint | Reason |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for row in report.get("runtimes") or []:
        lines.append(
            "| {runtime} | {provider} | {status} | {count} | {endpoint} | {reason} |".format(
                runtime=row.get("runtime_class") or "",
                provider=row.get("provider") or "",
                status=row.get("status") or "",
                count=row.get("model_count") or 0,
                endpoint=row.get("endpoint") or "",
                reason=row.get("reason") or "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-endpoint", default=DEFAULT_OLLAMA_ENDPOINT)
    parser.add_argument("--vllm-endpoint", default=DEFAULT_VLLM_ENDPOINT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        ollama_endpoint=args.ollama_endpoint,
        vllm_endpoint=args.vllm_endpoint,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
                "summary": report["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
