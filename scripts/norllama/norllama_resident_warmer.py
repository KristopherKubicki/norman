#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _split_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]


def _as_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_s: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", errors="replace")
            return int(response.status), json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"error": body[:500]}
        return int(exc.code), parsed


def _free_mib(media_health_url: str, timeout_s: float) -> int | None:
    if not media_health_url:
        return None
    try:
        status, payload = _json_request(media_health_url, timeout_s=timeout_s)
    except Exception:
        return None
    if status >= 400:
        return None
    gpu = payload.get("gpu_memory")
    if not isinstance(gpu, dict):
        return None
    try:
        return int(gpu.get("free_mib") or 0)
    except (TypeError, ValueError):
        return None


def _terminal(status: str) -> bool:
    return status in {
        "cancelled",
        "completed",
        "failed",
        "keep_warm",
        "resident",
        "timeout",
        "warm",
    }


def _poll_prefetch(base_url: str, job_id: str, *, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, timeout_s)
    status_url = f"{base_url.rstrip('/')}/v1/prefetch/status?job_id={job_id}"
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            _, payload = _json_request(status_url, timeout_s=min(10.0, timeout_s))
            items = payload.get("items") if isinstance(payload, dict) else []
            if isinstance(items, list) and items:
                latest = dict(items[0])
                if _terminal(str(latest.get("status") or "")):
                    return latest
        except Exception as exc:
            latest = {"status": "poll_error", "error": str(exc)[:300]}
        time.sleep(3.0)
    if latest:
        latest.setdefault("status", "timeout")
        return latest
    return {"status": "timeout", "job_id": job_id}


def _warm_chat_model(
    *,
    ollama_url: str,
    model: str,
    keep_alive: str,
    timeout_s: float,
    num_ctx: int,
) -> dict[str, Any]:
    options: dict[str, Any] = {"temperature": 0, "num_predict": 4}
    if num_ctx > 0:
        options["num_ctx"] = num_ctx
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
        "keep_alive": keep_alive,
        "options": options,
    }
    if model.lower().startswith(("qwen3.5:", "qwen3.6:")):
        payload["think"] = False
    started = time.perf_counter()
    status, response = _json_request(
        f"{ollama_url.rstrip('/')}/api/chat",
        method="POST",
        payload=payload,
        timeout_s=timeout_s,
    )
    return {
        "model": model,
        "status": "completed"
        if status < 400 and not response.get("error")
        else "failed",
        "ok": status < 400 and not bool(response.get("error")),
        "http_status": status,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "error": str(response.get("error") or "")[:300],
    }


def _warm_embed_model(
    *,
    ollama_url: str,
    model: str,
    keep_alive: str,
    timeout_s: float,
) -> dict[str, Any]:
    status, response = _json_request(
        f"{ollama_url.rstrip('/')}/api/embed",
        method="POST",
        payload={
            "model": model,
            "input": "norllama resident embedding warmup",
            "keep_alive": keep_alive,
        },
        timeout_s=timeout_s,
    )
    return {
        "model": model,
        "status": "completed"
        if status < 400 and not response.get("error")
        else "failed",
        "ok": status < 400 and not bool(response.get("error")),
        "http_status": status,
        "error": str(response.get("error") or "")[:300],
        "duration_ms": int((response.get("total_duration") or 0) / 1_000_000),
    }


def main() -> int:
    base_url = os.getenv("NORLLAMA_WARM_BASE_URL", "http://127.0.0.1:18151")
    ollama_url = os.getenv("NORLLAMA_WARM_OLLAMA_URL", "http://127.0.0.1:11434")
    keep_alive = os.getenv("NORLLAMA_WARM_KEEP_ALIVE", "12h").strip() or "12h"
    timeout_s = _as_float("NORLLAMA_WARM_TIMEOUT_S", 1200.0)
    health_timeout_s = _as_float("NORLLAMA_WARM_HEALTH_TIMEOUT_S", 5.0)
    min_free_mib_chat = _as_int("NORLLAMA_WARM_MIN_FREE_MIB_CHAT", 0)
    num_ctx = _as_int("NORLLAMA_WARM_NUM_CTX", 4096)
    media_health_url = os.getenv(
        "NORLLAMA_WARM_MEDIA_HEALTH_URL", "http://127.0.0.1:8100/health"
    ).strip()
    chat_models = _split_env("NORLLAMA_WARM_CHAT_MODELS")
    embed_models = _split_env("NORLLAMA_WARM_EMBED_MODELS")
    results: list[dict[str, Any]] = []

    for model in chat_models:
        free_mib = _free_mib(media_health_url, health_timeout_s)
        if (
            min_free_mib_chat > 0
            and free_mib is not None
            and free_mib < min_free_mib_chat
        ):
            results.append(
                {
                    "model": model,
                    "status": "skipped_low_gpu_memory",
                    "free_mib": free_mib,
                    "min_free_mib": min_free_mib_chat,
                }
            )
            continue
        try:
            results.append(
                _warm_chat_model(
                    ollama_url=ollama_url,
                    model=model,
                    keep_alive=keep_alive,
                    timeout_s=timeout_s,
                    num_ctx=num_ctx,
                )
            )
        except Exception as exc:
            results.append({"model": model, "status": "error", "error": str(exc)[:300]})

    for model in embed_models:
        try:
            results.append(
                _warm_embed_model(
                    ollama_url=ollama_url,
                    model=model,
                    keep_alive=keep_alive,
                    timeout_s=min(timeout_s, 300.0),
                )
            )
        except Exception as exc:
            results.append({"model": model, "status": "error", "error": str(exc)[:300]})

    payload = {
        "schema": "norllama.resident-warmer.v1",
        "host": os.uname().nodename,
        "base_url": base_url,
        "keep_alive": keep_alive,
        "chat_models": chat_models,
        "embed_models": embed_models,
        "results": results,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
