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
DEFAULT_OLLAMA_SENSE_JSON = Path("tmp/ollama_sense_live.json")
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


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _best_usable_ollama_endpoint(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    best_endpoint = str(report.get("summary", {}).get("best_endpoint") or "").strip()
    candidates: list[dict[str, Any]] = []
    for endpoint in report.get("endpoints") or []:
        if not isinstance(endpoint, dict):
            continue
        models = endpoint.get("models")
        if not endpoint.get("usable") or not isinstance(models, list) or not models:
            continue
        candidates.append(endpoint)
    if not candidates:
        return {}
    return sorted(
        candidates,
        key=lambda item: (
            0 if str(item.get("endpoint") or "") == best_endpoint else 1,
            0 if item.get("scope") == "local" else 1,
            int(item.get("latency_ms") or 0),
            str(item.get("endpoint") or ""),
        ),
    )[0]


def _apply_ollama_sense_fallback(
    row: dict[str, Any], sense_report: dict[str, Any]
) -> dict[str, Any]:
    if row.get("routeable"):
        row["health_source"] = "direct_probe"
        return row
    endpoint = _best_usable_ollama_endpoint(sense_report)
    if not endpoint:
        row["health_source"] = "direct_probe"
        return row
    endpoint_url = str(endpoint.get("endpoint") or "").strip().rstrip("/")
    models = [str(model) for model in endpoint.get("models") or [] if str(model)]
    return {
        **row,
        "endpoint": endpoint_url,
        "models_url": f"{endpoint_url}/api/tags",
        "status": "healthy",
        "routeable": True,
        "model_count": len(models),
        "reason": "",
        "health_source": "ollama_sense_fallback",
        "source_schema": str(sense_report.get("schema") or ""),
        "endpoint_scope": str(endpoint.get("scope") or ""),
        "latency_ms": int(endpoint.get("latency_ms") or 0),
        "model_names": models,
    }


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
        "health_source": "direct_probe",
    }


def build_report(
    *,
    ollama_endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    vllm_endpoint: str = DEFAULT_VLLM_ENDPOINT,
    ollama_sense_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ollama = ollama_endpoint.rstrip("/")
    vllm = vllm_endpoint.rstrip("/")
    runtimes = [
        _apply_ollama_sense_fallback(
            _runtime_row(
                runtime_class="ollama",
                provider="ollama",
                endpoint=ollama,
                command="ollama",
                models_url=f"{ollama}/api/tags",
            ),
            ollama_sense_report or {},
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
        "| Runtime | Provider | Status | Models | Endpoint | Source | Reason |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for row in report.get("runtimes") or []:
        lines.append(
            "| {runtime} | {provider} | {status} | {count} | {endpoint} | {source} | {reason} |".format(
                runtime=row.get("runtime_class") or "",
                provider=row.get("provider") or "",
                status=row.get("status") or "",
                count=row.get("model_count") or 0,
                endpoint=row.get("endpoint") or "",
                source=row.get("health_source") or "",
                reason=row.get("reason") or "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-endpoint", default=DEFAULT_OLLAMA_ENDPOINT)
    parser.add_argument("--vllm-endpoint", default=DEFAULT_VLLM_ENDPOINT)
    parser.add_argument(
        "--ollama-sense-json", type=Path, default=DEFAULT_OLLAMA_SENSE_JSON
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        ollama_endpoint=args.ollama_endpoint,
        vllm_endpoint=args.vllm_endpoint,
        ollama_sense_report=load_optional_json(args.ollama_sense_json),
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
