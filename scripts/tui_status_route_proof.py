#!/usr/bin/env python3
"""Prove the live status route across every managed TUI without using tools."""

from __future__ import annotations

import argparse
import json
import shlex
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

try:
    import sync_agent_console_template as sync
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sync_agent_console_template as sync  # type: ignore[no-redef]


DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_status_route_proof.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_status_route_proof.md")
STATUS_PROMPT_TEMPLATE = "Status update. No tools or changes. {nonce}"
TERRA_MODEL_MARKER = "gpt-5.6-terra"

REMOTE_COLD_RECOVERY_DRILL = r"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time


config = json.loads(CONFIG_JSON)
result = {
    "ok": False,
    "error": "",
    "inference_attempted": False,
    "fresh_cooldown_seconds": 0,
    "fresh_cooldown_active": False,
    "stale_cooldown_cleared": False,
}
try:
    with tempfile.TemporaryDirectory(prefix="norman-cold-recovery-") as state_dir:
        os.environ["NORMAN_CODEX_WEB_STATE_DIR"] = state_dir
        os.environ["NORMAN_LOCAL_LLM_ROUTE_OUTCOME_PATH"] = (
            state_dir + "/local_llm_route_outcomes.jsonl"
        )
        os.environ["NORMAN_LOCAL_LLM_ROUTE_COOLDOWN_SECONDS"] = "900"
        os.environ["NORMAN_LOCAL_PLANNER_PREFLIGHT_COLD_LOAD_COOLDOWN_SECONDS"] = "60"
        web_path = Path(str(config["web_path"])).resolve()
        for import_root in (web_path.parent, web_path.parent.parent):
            import_root_text = str(import_root)
            if import_root_text not in sys.path:
                sys.path.insert(0, import_root_text)
        spec = importlib.util.spec_from_file_location(
            "norman_cold_recovery_drill", str(web_path)
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load deployed console source")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        model = "routeproof-cold-recovery"
        now = int(time.time())
        short_cooldown = int(
            module.local_llm_outcome_cooldown_seconds(
                {"source": "planner-preflight", "status": "timeout"}
            )
            or 0
        )
        module.append_local_llm_route_outcome(
            source="planner-preflight",
            status="timeout",
            ok=False,
            model=model,
            endpoint="",
            recorded_at=now,
            reason="isolated cold-recovery drill",
        )
        fresh = module.local_llm_route_cooldown(
            model, include_fleet=False
        )
        module.append_local_llm_route_outcome(
            source="planner-preflight",
            status="timeout",
            ok=False,
            model=model,
            endpoint="",
            recorded_at=now - short_cooldown - 1,
            reason="isolated stale cold-recovery drill",
        )
        stale = module.local_llm_route_cooldown(
            model, include_fleet=False
        )
        result.update(
            {
                "fresh_cooldown_seconds": short_cooldown,
                "fresh_cooldown_active": bool(fresh.get("active")),
                "fresh_remaining_seconds": int(fresh.get("remaining_seconds") or 0),
                "stale_cooldown_cleared": not bool(stale.get("active")),
                "state_dir_isolated": bool(
                    str(module.STATE_DIR).startswith(state_dir)
                ),
            }
        )
        result["ok"] = bool(
            short_cooldown > 0
            and short_cooldown <= 60
            and result["fresh_cooldown_active"]
            and result["stale_cooldown_cleared"]
            and result["state_dir_isolated"]
        )
except Exception as exc:
    result["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:360])

print(json.dumps(result, sort_keys=True))
"""


REMOTE_STATUS_ROUTE_PROOF = r"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request


def as_dict(value):
    return dict(value) if isinstance(value, dict) else {}


def as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def as_float(value):
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def trim(value, limit=360):
    return str(value or "").replace("\n", " ").strip()[:limit]


def fetch_json(path, *, data=None, timeout=15.0):
    params = {"token": token} if token else {}
    query = urllib.parse.urlencode(params)
    url = base_url + path + (("&" if "?" in path else "?") + query if query else "")
    headers = {"Accept": "application/json"}
    body = None
    method = "GET"
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        method = "POST"
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return int(response.status), json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"error": raw}
        return int(exc.code), payload


def codex_spark_registry(snapshot):
    for item in snapshot.get("runtime_registry") or []:
        if isinstance(item, dict) and str(item.get("key") or "") == "codexspark":
            return {
                "label": str(item.get("label") or ""),
                "provider": str(item.get("provider") or ""),
                "execution": str(item.get("execution") or ""),
                "can_execute": bool(item.get("can_execute")),
                "default_model": str(item.get("default_model") or ""),
            }
    return {}


def compact_status(snapshot, *, nonce=""):
    source = as_dict(snapshot)
    health = as_dict(source.get("local_llm_health"))
    planner_readiness = as_dict(source.get("local_planner_readiness"))
    return {
        "state": str(source.get("state") or ""),
        "pending": bool(source.get("pending")),
        "queue_depth": as_int(source.get("queue_depth")),
        "status_message": trim(source.get("status_message")),
        "last_error": trim(source.get("last_error"), 600),
        "last_runtime": str(source.get("last_runtime") or ""),
        "last_model": str(source.get("last_model") or ""),
        "last_started_at": as_int(source.get("last_started_at")),
        "last_finished_at": as_int(source.get("last_finished_at")),
        "last_prompt_contains_nonce": bool(
            nonce and nonce in str(source.get("last_prompt") or "")
        ),
        "local_llm_health": {
            "ok": bool(health.get("ok")),
            "model": str(health.get("model") or ""),
            "reason": trim(health.get("reason"), 240),
        },
        "local_planner_readiness": {
            "configured": bool(planner_readiness.get("configured")),
            "ready": bool(planner_readiness.get("ready")),
            "status": str(planner_readiness.get("status") or ""),
            "model": str(planner_readiness.get("model") or ""),
            "reason": trim(planner_readiness.get("reason"), 240),
        },
        "codexspark": codex_spark_registry(source),
    }


def compact_last_turn(payload):
    usage = as_dict(payload).get("usage")
    last_turn = as_dict(usage).get("last_turn")
    turn = as_dict(last_turn)
    return {
        "success": bool(turn.get("success")),
        "runtime": str(turn.get("runtime") or ""),
        "model": str(turn.get("model") or ""),
        "provider_surface": str(turn.get("provider_surface") or ""),
        "route_execution": str(turn.get("route_execution") or ""),
        "route_verifier": str(turn.get("route_verifier") or ""),
        "fallback_reason": str(
            turn.get("fallback_reason") or turn.get("fallback_used") or ""
        ),
        "started_at": as_int(turn.get("started_at")),
        "finished_at": as_int(turn.get("finished_at")),
        "latency_ms": as_int(turn.get("latency_ms")),
        "estimated_cost_usd": as_float(turn.get("estimated_cost_usd")),
        "total_tokens": as_int(turn.get("total_tokens")),
        "local_preflight_used": bool(turn.get("local_preflight_used")),
        "local_preflight_status": str(turn.get("local_preflight_status") or ""),
        "local_preflight_model": str(turn.get("local_preflight_model") or ""),
        "local_preflight_tokens": as_int(turn.get("local_preflight_tokens")),
        "local_preflight_candidate_lane": str(
            turn.get("local_preflight_candidate_lane") or ""
        ),
        "local_preflight_failure_class": str(
            turn.get("local_preflight_failure_class") or ""
        ),
        "provider_error_kind": str(turn.get("provider_error_kind") or ""),
    }


config = json.loads(CONFIG_JSON)
base_url = str(config["base_url"]).rstrip("/")
token = str(config.get("token") or "")
nonce = str(config["nonce"])
form = dict(config["form"])
poll_attempts = max(1, as_int(config.get("poll_attempts")))
poll_interval = max(0.1, float(config.get("poll_interval") or 1.0))
ask_timeout = max(1.0, float(config.get("ask_timeout") or 20.0))
status_timeout = max(1.0, float(config.get("status_timeout") or 10.0))

result = {
    "ok": False,
    "skipped": False,
    "error": "",
    "nonce": nonce,
    "ask_http_status": 0,
    "ask": {},
    "before": {},
    "final": {},
    "last_turn": {},
    "requested_route": {
        "runtime": str(form.get("runtime") or ""),
        "model": str(form.get("model") or ""),
        "service_tier": str(form.get("service_tier") or ""),
        "route_lock": str(form.get("route_lock") or ""),
    },
    "poll_attempts_used": 0,
}
try:
    before_code, before_snapshot = fetch_json("/api/status", timeout=status_timeout)
    result["before_http_status"] = before_code
    result["before"] = compact_status(before_snapshot, nonce=nonce)
except Exception as exc:
    result["error"] = "initial status failed: %s: %s" % (
        type(exc).__name__,
        trim(exc, 240),
    )
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0)

if result["before"].get("pending"):
    result["skipped"] = True
    result["error"] = "TUI was already running a prompt"
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0)

submitted_at = int(time.time())
try:
    ask_code, ask_payload = fetch_json(
        "/api/ask",
        data=form,
        timeout=ask_timeout,
    )
    ask_payload = as_dict(ask_payload)
    visibility_detail = as_dict(ask_payload.get("receipt_visibility_detail"))
    result["ask_http_status"] = ask_code
    result["ask"] = {
        "accepted": bool(ask_payload.get("accepted")),
        "queued": bool(ask_payload.get("queued")),
        "running": bool(ask_payload.get("running")),
        "error": trim(ask_payload.get("error"), 360),
        "receipt_visibility": str(ask_payload.get("receipt_visibility") or ""),
        "receipt_reason": str(visibility_detail.get("reason") or ""),
    }
except Exception as exc:
    result["error"] = "POST /api/ask failed: %s: %s" % (
        type(exc).__name__,
        trim(exc, 240),
    )
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0)

for index in range(poll_attempts):
    result["poll_attempts_used"] = index + 1
    try:
        _status_code, snapshot = fetch_json("/api/status", timeout=status_timeout)
    except Exception as exc:
        result["error"] = "poll failed: %s: %s" % (
            type(exc).__name__,
            trim(exc, 240),
        )
        time.sleep(poll_interval)
        continue
    result["final"] = compact_status(snapshot, nonce=nonce)
    result["last_turn"] = compact_last_turn(
        {"usage": as_dict(snapshot).get("usage")}
    )
    last_turn_started = as_int(result["last_turn"].get("started_at"))
    owns_latest_turn = last_turn_started >= submitted_at - 2
    if (
        result["final"].get("last_prompt_contains_nonce")
        and not result["final"].get("pending")
        and owns_latest_turn
    ):
        result["ok"] = True
        break
    time.sleep(poll_interval)

print(json.dumps(result, sort_keys=True))
"""


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _model_label(runtime: Any, model: Any) -> str:
    runtime_text = _text(runtime) or "unknown"
    model_text = _text(model) or "unknown"
    return f"{runtime_text}/{model_text}"


def is_terra_model(model: Any) -> bool:
    return TERRA_MODEL_MARKER in _text(model).lower()


def proof_prompt(nonce: str) -> str:
    return STATUS_PROMPT_TEMPLATE.format(nonce=nonce)


def proof_form(nonce: str) -> dict[str, str]:
    return {
        "message": proof_prompt(nonce),
        "runtime": "codex",
        "model": "",
        "route_lock": "0",
        "speed": "fast",
        "detail": "1",
        "service_tier": "default",
        "job_budget": "quick",
        "optimization_mode": "auto",
    }


def remote_command(
    host: sync.DiscoveryHost,
    *,
    python_candidate: str = "",
) -> list[str]:
    candidate = _text(python_candidate)
    if candidate:
        command = [
            "/bin/sh",
            "-c",
            (
                f"if [ -x {shlex.quote(candidate)} ]; then "
                f"exec {shlex.quote(candidate)} -; fi; exec python3 -"
            ),
        ]
    else:
        command = ["python3", "-"]
    if host.use_sudo:
        command.insert(0, "sudo")
    if sync.host_runs_local(host):
        return command
    return ["ssh", *sync.SSH_OPTIONS, host.ssh_target, shlex.join(command)]


def run_instance_proof(
    instance: sync.ConsoleInstance,
    *,
    run_id: str,
    poll_attempts: int,
    poll_interval: float,
    ask_timeout: float,
    status_timeout: float,
    ssh_timeout: float,
) -> dict[str, Any]:
    host = sync.HOSTS[instance.host_name]
    nonce = (
        "routeproof"
        + uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"norman-status-route/{run_id}/{instance.host_name}/{instance.name}",
        ).hex
    )
    config = {
        "base_url": f"http://127.0.0.1:{instance.web_port}",
        "token": instance.web_token,
        "nonce": nonce,
        "form": proof_form(nonce),
        "poll_attempts": poll_attempts,
        "poll_interval": poll_interval,
        "ask_timeout": ask_timeout,
        "status_timeout": status_timeout,
    }
    program = f"CONFIG_JSON = {json.dumps(config, sort_keys=True)!r}\n{REMOTE_STATUS_ROUTE_PROOF}"
    base = {
        "target": instance.name,
        "host": instance.host_name,
        "nonce": nonce,
        "transport": (
            "local" if sync.host_runs_local(host) else f"ssh:{host.ssh_target}"
        ),
    }
    try:
        completed = subprocess.run(
            remote_command(host),
            input=program,
            text=True,
            capture_output=True,
            timeout=max(1.0, ssh_timeout),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            **base,
            "ok": False,
            "skipped": False,
            "error": f"proof transport timed out after {ssh_timeout:.0f}s",
        }
    if completed.returncode != 0:
        return {
            **base,
            "ok": False,
            "skipped": False,
            "error": _text(completed.stderr or completed.stdout)[:600]
            or f"proof transport exited {completed.returncode}",
        }
    try:
        payload = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        return {
            **base,
            "ok": False,
            "skipped": False,
            "error": f"invalid probe JSON: {exc}",
        }
    if not isinstance(payload, dict):
        return {
            **base,
            "ok": False,
            "skipped": False,
            "error": "probe did not return an object",
        }
    return {**base, **payload}


def run_instance_cold_recovery_drill(
    instance: sync.ConsoleInstance,
    *,
    ssh_timeout: float,
) -> dict[str, Any]:
    host = sync.HOSTS[instance.host_name]
    base = {
        "target": instance.name,
        "host": instance.host_name,
        "transport": (
            "local" if sync.host_runs_local(host) else f"ssh:{host.ssh_target}"
        ),
    }
    program = (
        "CONFIG_JSON = "
        f"{json.dumps({'web_path': instance.web_path}, sort_keys=True)!r}\n"
        f"{REMOTE_COLD_RECOVERY_DRILL}"
    )
    python_candidate = str(
        Path(instance.web_path).resolve().parent.parent / ".venv" / "bin" / "python"
    )
    try:
        completed = subprocess.run(
            remote_command(host, python_candidate=python_candidate),
            input=program,
            text=True,
            capture_output=True,
            timeout=max(1.0, ssh_timeout),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            **base,
            "ok": False,
            "error": f"cold-recovery transport timed out after {ssh_timeout:.0f}s",
        }
    if completed.returncode != 0:
        return {
            **base,
            "ok": False,
            "error": _text(completed.stderr or completed.stdout)[:600]
            or f"cold-recovery transport exited {completed.returncode}",
        }
    try:
        payload = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        return {**base, "ok": False, "error": f"invalid cold-recovery JSON: {exc}"}
    if not isinstance(payload, dict):
        return {**base, "ok": False, "error": "cold-recovery drill returned no object"}
    return {**base, **payload}


def validate_cold_recovery_drill(result: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if not result.get("ok"):
        failures.append(_text(result.get("error")) or "cold-recovery drill failed")
    if result.get("inference_attempted"):
        failures.append("cold-recovery drill attempted inference")
    if not result.get("state_dir_isolated"):
        failures.append("cold-recovery drill did not use isolated temporary state")
    if not result.get("fresh_cooldown_active"):
        failures.append("simulated planner timeout did not enter cooldown")
    if _int(result.get("fresh_cooldown_seconds")) > 60:
        failures.append("planner cold-load cooldown exceeded 60 seconds")
    if _int(result.get("fresh_cooldown_seconds")) <= 0:
        failures.append("planner cold-load cooldown was not configured")
    if not result.get("stale_cooldown_cleared"):
        failures.append("stale planner timeout still blocked local recovery")
    return {
        **result,
        "passed": not failures,
        "outcome": "cold_recovery_verified"
        if not failures
        else "cold_recovery_proof_failed",
        "failures": failures,
    }


def validate_proof(probe: dict[str, Any]) -> dict[str, Any]:
    before = _dict(probe.get("before"))
    final = _dict(probe.get("final"))
    turn = _dict(probe.get("last_turn"))
    ask = _dict(probe.get("ask"))
    planner_readiness = _dict(before.get("local_planner_readiness"))
    codexspark = _dict(before.get("codexspark"))
    planner_ready = bool(planner_readiness.get("ready"))
    deterministic = _text(ask.get("receipt_reason")) == "deterministic_status"
    final_runtime = _text(turn.get("runtime"))
    final_model = _text(turn.get("model"))
    failures: list[str] = []

    if probe.get("skipped"):
        return {
            **probe,
            "passed": False,
            "outcome": "skipped_busy",
            "local_healthy_before": planner_ready,
            "deterministic_state_read": False,
            "final_authority": "",
            "failures": [_text(probe.get("error")) or "TUI was busy"],
        }

    if not probe.get("ok"):
        failures.append(_text(probe.get("error")) or "proof did not reach completion")
    if _int(probe.get("ask_http_status")) not in {200, 202}:
        failures.append(
            f"POST /api/ask returned HTTP {_int(probe.get('ask_http_status'))}"
        )
    if not bool(ask.get("accepted")):
        failures.append(
            _text(ask.get("error")) or "TUI did not accept the status prompt"
        )
    if not bool(final.get("last_prompt_contains_nonce")):
        failures.append("latest visible prompt did not contain this proof nonce")
    if bool(final.get("pending")):
        failures.append("TUI remained pending after the proof deadline")
    if not bool(turn.get("success")):
        detail = _text(final.get("last_error")) or _text(
            turn.get("provider_error_kind")
        )
        failures.append(f"status turn failed{': ' + detail if detail else ''}")
    if final_runtime == "codexspark":
        failures.append("named codexspark preview was selected as a live final runtime")
    preflight_used = bool(turn.get("local_preflight_used"))
    preflight_ok = _text(turn.get("local_preflight_status")).lower() == "ok"
    preflight_tokens = _int(turn.get("local_preflight_tokens"))
    if deterministic:
        if (
            final_runtime != "localllm"
            or final_model != "deterministic-status"
            or _int(turn.get("total_tokens")) != 0
        ):
            failures.append(
                "deterministic state read did not retain zero-token local semantics"
            )
        if preflight_used or preflight_tokens:
            failures.append(
                "deterministic state read unexpectedly recorded a Norllama preflight"
            )
        outcome = (
            "deterministic_status" if not failures else "deterministic_proof_failed"
        )
        requires_local_preflight = False
    else:
        if not is_terra_model(final_model):
            failures.append("cloud final authority did not use GPT-5.6 Terra")
        requires_local_preflight = planner_ready or preflight_used
        if requires_local_preflight:
            if not (preflight_used and preflight_ok and preflight_tokens > 0):
                failures.append(
                    "ready local planner candidate did not record a successful "
                    "Norllama preflight"
                )
            outcome = (
                "norllama_preflight_cloud_authority"
                if not failures
                else "norllama_preflight_proof_failed"
            )
        else:
            failures.append(
                "local lane was unavailable but the status turn did not record "
                "a deterministic state read"
            )
            outcome = "local_preflight_proof_failed"

    if codexspark and (
        bool(codexspark.get("can_execute"))
        or _text(codexspark.get("execution")) != "access-check"
    ):
        failures.append("named codexspark registry contract changed from access-check")

    started_at = _int(turn.get("started_at"))
    finished_at = _int(turn.get("finished_at"))
    latency_ms = _int(turn.get("latency_ms"))
    if latency_ms <= 0 and finished_at >= started_at > 0:
        latency_ms = (finished_at - started_at) * 1000
    return {
        **probe,
        "passed": not failures,
        "outcome": outcome,
        "local_healthy_before": requires_local_preflight,
        "deterministic_state_read": deterministic,
        "preflight": {
            "used": preflight_used,
            "status": _text(turn.get("local_preflight_status")),
            "model": _text(turn.get("local_preflight_model")),
            "tokens": preflight_tokens,
            "candidate_lane": _text(turn.get("local_preflight_candidate_lane")),
            "failure_class": _text(turn.get("local_preflight_failure_class")),
        },
        "requested_route": _dict(probe.get("requested_route")),
        "final_authority": _model_label(final_runtime, final_model),
        "route_verifier": _text(turn.get("route_verifier")),
        "fallback_reason": _text(turn.get("fallback_reason")),
        "latency_ms": latency_ms,
        "estimated_cost_usd": round(_float(turn.get("estimated_cost_usd")), 6),
        "failures": failures,
    }


def select_instances(
    targets: list[str] | None,
) -> tuple[list[sync.ConsoleInstance], list[dict[str, Any]]]:
    discovered_by_host, discovered_by_name = sync.discover_all_instances(
        host_filter=sync.requested_host_filter(targets)
    )
    failures: list[dict[str, Any]] = []
    try:
        selected = sync.select_instances(
            targets, discovered_by_host, discovered_by_name
        )
    except SystemExit as exc:
        for target in targets or []:
            failures.append(discovery_failure(target, _text(exc)))
        return [], failures

    for target in targets or []:
        if target in sync.HOSTS and not selected.get(target):
            failures.append(
                discovery_failure(
                    target,
                    f"requested host {target} did not yield a managed TUI",
                    host=target,
                )
            )
    instances = [
        instance
        for host_name in sorted(selected)
        for instance in sorted(selected[host_name], key=lambda item: item.name)
    ]
    return instances, failures


def discovery_failure(target: str, reason: str, *, host: str = "") -> dict[str, Any]:
    return {
        "target": target,
        "host": host or "discovery",
        "ok": False,
        "skipped": False,
        "error": reason,
        "passed": False,
        "outcome": "discovery_failed",
        "local_healthy_before": False,
        "deterministic_state_read": False,
        "preflight": {},
        "requested_route": {},
        "final_authority": "",
        "route_verifier": "",
        "fallback_reason": "",
        "latency_ms": 0,
        "estimated_cost_usd": 0.0,
        "failures": [reason],
    }


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    skipped = sum(1 for item in results if item.get("outcome") == "skipped_busy")
    local_healthy = sum(1 for item in results if item.get("local_healthy_before"))
    preflight_success = sum(
        1
        for item in results
        if _dict(item.get("preflight")).get("used")
        and _text(_dict(item.get("preflight")).get("status")).lower() == "ok"
        and _int(_dict(item.get("preflight")).get("tokens")) > 0
    )
    deterministic = sum(1 for item in results if item.get("deterministic_state_read"))
    named_spark_contract_ok = all(
        not _dict(_dict(item.get("before")).get("codexspark")).get("can_execute")
        and _text(_dict(_dict(item.get("before")).get("codexspark")).get("execution"))
        == "access-check"
        for item in results
        if _dict(_dict(item.get("before")).get("codexspark"))
    )
    observed_turns = [
        item
        for item in results
        if _dict(item.get("last_turn"))
        and _text(_dict(item.get("last_turn")).get("runtime"))
    ]
    total_latency_ms = sum(_int(item.get("latency_ms")) for item in observed_turns)
    total_cost_usd = sum(
        _float(item.get("estimated_cost_usd")) for item in observed_turns
    )
    route_scorecard = {
        "observed_turns": len(observed_turns),
        "local_preflight_turns": sum(
            1 for item in observed_turns if _dict(item.get("preflight")).get("used")
        ),
        "cloud_final_authority_turns": sum(
            1
            for item in observed_turns
            if _text(item.get("final_authority"))
            and not item.get("deterministic_state_read")
            and not _text(item.get("final_authority")).startswith("localllm/")
        ),
        "verifier_recorded_turns": sum(
            1 for item in observed_turns if _text(item.get("route_verifier"))
        ),
        "fallback_turns": sum(
            1
            for item in observed_turns
            if not item.get("deterministic_state_read")
            and _text(item.get("fallback_reason"))
        ),
        "total_latency_ms": total_latency_ms,
        "average_latency_ms": round(total_latency_ms / len(observed_turns), 2)
        if observed_turns
        else 0.0,
        "estimated_cost_usd": round(total_cost_usd, 6),
        "estimated_cost_turns": len(observed_turns),
    }
    return {
        "targets": total,
        "passed": passed,
        "failed": total - passed - skipped,
        "skipped_busy": skipped,
        "local_healthy_before": local_healthy,
        "successful_norllama_preflights": preflight_success,
        "deterministic_state_reads": deterministic,
        "named_codexspark_access_check_contract_ok": named_spark_contract_ok,
        "route_scorecard": route_scorecard,
        "passed_rate": round(passed / total, 4) if total else 0.0,
    }


def build_cold_recovery_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    return {
        "targets": total,
        "passed": passed,
        "failed": total - passed,
        "isolated_no_inference": all(
            not item.get("inference_attempted") for item in results
        ),
        "stale_timeout_recovery_verified": all(
            item.get("stale_cooldown_cleared") for item in results
        ),
        "passed_rate": round(passed / total, 4) if total else 0.0,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = _dict(report.get("summary"))
    scorecard = _dict(summary.get("route_scorecard"))
    lines = [
        "# TUI Status Route Proof",
        "",
        f"Run ID: `{_text(report.get('run_id'))}`",
        f"Generated: `{_int(report.get('generated_at'))}`",
        "",
        (
            "Summary: "
            f"{_int(summary.get('passed'))}/{_int(summary.get('targets'))} passed; "
            f"{_int(summary.get('skipped_busy'))} busy; "
            f"{_int(summary.get('successful_norllama_preflights'))} "
            "successful Norllama preflights."
        ),
        (
            "Route scorecard: "
            f"{_int(scorecard.get('cloud_final_authority_turns'))} cloud final "
            "authorities; "
            f"{_int(scorecard.get('verifier_recorded_turns'))} verifier receipts; "
            f"{_int(scorecard.get('fallback_turns'))} fallbacks; "
            f"{_int(scorecard.get('average_latency_ms'))}ms average; "
            f"${_float(scorecard.get('estimated_cost_usd')):.6f} estimated."
        ),
        "",
        "Terminology:",
        "",
        "- `Norllama preflight` is a local planner/worker call before a tool-capable cloud final authority.",
        "- `deterministic state read` is a zero-token TUI state response; it does not require planner readiness or a cloud final authority.",
        "- `codexspark` is the named OpenAI/Cerebras preview runtime. Its required state is `access-check`, not a local worker.",
        "",
        (
            "| Host | TUI | Result | Requested route | Local route | Final authority | "
            "Verifier/fallback | Latency | Est. cost | Outcome |"
        ),
        ("| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |"),
    ]
    for item in report.get("results") or []:
        preflight = _dict(item.get("preflight"))
        local = (
            f"{_text(preflight.get('model'))} ({_int(preflight.get('tokens'))} tok)"
            if preflight.get("used")
            else "deterministic state read"
            if item.get("deterministic_state_read")
            else "not observed"
        )
        detail = _text(item.get("outcome"))
        if item.get("failures"):
            detail += ": " + _text((item.get("failures") or [""])[0])[:180]
        requested = _dict(item.get("requested_route"))
        requested_model = _text(requested.get("model")) or "auto"
        requested_route = "/".join(
            part
            for part in (
                _text(requested.get("runtime")) or "unknown",
                requested_model,
                _text(requested.get("service_tier")) or "default",
            )
            if part
        )
        verifier = _text(item.get("route_verifier")) or "not recorded"
        fallback = _text(item.get("fallback_reason"))
        if fallback:
            verifier = f"{verifier}; fallback={fallback}"
        latency = _int(item.get("latency_ms"))
        cost = _float(item.get("estimated_cost_usd"))
        lines.append(
            (
                "| {host} | {target} | {result} | {requested} | {local} | "
                "{final} | {verifier} | {latency} | ${cost:.6f} | {outcome} |"
            ).format(
                host=_text(item.get("host")).replace("|", "\\|"),
                target=_text(item.get("target")).replace("|", "\\|"),
                result="PASS"
                if item.get("passed")
                else "SKIP"
                if item.get("outcome") == "skipped_busy"
                else "FAIL",
                requested=requested_route.replace("|", "\\|"),
                local=local.replace("|", "\\|"),
                final=_text(item.get("final_authority")).replace("|", "\\|"),
                verifier=verifier.replace("|", "\\|"),
                latency=f"{latency}ms" if latency else "-",
                cost=cost,
                outcome=detail.replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


def render_cold_recovery_markdown(report: dict[str, Any]) -> str:
    summary = _dict(report.get("summary"))
    lines = [
        "# TUI Cold-Recovery Drill",
        "",
        f"Run ID: `{_text(report.get('run_id'))}`",
        f"Generated: `{_int(report.get('generated_at'))}`",
        "",
        (
            "Summary: "
            f"{_int(summary.get('passed'))}/{_int(summary.get('targets'))} passed; "
            f"isolated/no-inference={str(bool(summary.get('isolated_no_inference'))).lower()}; "
            "stale-timeout recovery="
            f"{str(bool(summary.get('stale_timeout_recovery_verified'))).lower()}."
        ),
        "",
        (
            "This drill imports the deployed console in a temporary state directory. "
            "It creates synthetic planner timeout receipts only in that directory and "
            "does not call inference, unload a model, restart a service, or submit a prompt."
        ),
        "",
        "| Host | TUI | Result | Cooldown | Stale timeout |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in report.get("results") or []:
        detail = _text(item.get("outcome"))
        if item.get("failures"):
            detail += ": " + _text((item.get("failures") or [""])[0])[:180]
        lines.append(
            "| {host} | {target} | {result} | {cooldown} | {stale} |".format(
                host=_text(item.get("host")).replace("|", "\\|"),
                target=_text(item.get("target")).replace("|", "\\|"),
                result="PASS" if item.get("passed") else "FAIL",
                cooldown=_int(item.get("fresh_cooldown_seconds")),
                stale=(
                    "cleared"
                    if item.get("stale_cooldown_cleared")
                    else detail.replace("|", "\\|")
                ),
            )
        )
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], *, output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    renderer = (
        render_cold_recovery_markdown
        if _text(report.get("mode")) == "cold-recovery-drill"
        else render_markdown
    )
    output_md.write_text(renderer(report), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one live, non-mutating status route proof per managed TUI. "
            "Use --live to submit prompts."
        )
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--cold-recovery-drill",
        action="store_true",
        help=(
            "Exercise a synthetic stale planner timeout in isolated temporary state "
            "on each deployed console; does not submit a prompt or call inference."
        ),
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        default=None,
        help="Hosts or TUI names. Defaults to every discovered managed TUI.",
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--poll-attempts", type=int, default=75)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--ask-timeout", type=float, default=30.0)
    parser.add_argument("--status-timeout", type=float, default=15.0)
    parser.add_argument("--ssh-timeout", type=float, default=150.0)
    parser.add_argument(
        "--host-workers",
        type=int,
        default=5,
        help="Maximum hosts proved concurrently; each host remains serial.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.live and args.cold_recovery_drill:
        print(
            "--live and --cold-recovery-drill are separate proof modes",
            file=sys.stderr,
        )
        return 2
    instances, discovery_failures = select_instances(args.targets)
    if not instances and not discovery_failures:
        print("No managed TUI instances were discovered.", file=sys.stderr)
        return 2

    run_id = _text(args.run_id) or uuid.uuid4().hex[:10]
    if not args.live and not args.cold_recovery_drill:
        print(
            "Dry run. Add --live for status prompts or --cold-recovery-drill for "
            "the isolated timeout proof."
        )
        for instance in instances:
            print(f"{instance.host_name:16} {instance.name}")
        for failure in discovery_failures:
            print(
                "{host:16} {target} (discovery failed: {reason})".format(
                    host=_text(failure.get("host")),
                    target=_text(failure.get("target")),
                    reason=_text((failure.get("failures") or [""])[0]),
                )
            )
        return 1 if discovery_failures else 0

    grouped: dict[str, list[sync.ConsoleInstance]] = {}
    for instance in instances:
        grouped.setdefault(instance.host_name, []).append(instance)

    def prove_host(
        host_name: str, group: list[sync.ConsoleInstance]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for instance in group:
            if args.cold_recovery_drill:
                print(f"Running cold recovery {host_name}:{instance.name}", flush=True)
                rows.append(
                    validate_cold_recovery_drill(
                        run_instance_cold_recovery_drill(
                            instance,
                            ssh_timeout=max(1.0, float(args.ssh_timeout)),
                        )
                    )
                )
            else:
                print(f"Running {host_name}:{instance.name}", flush=True)
                rows.append(
                    validate_proof(
                        run_instance_proof(
                            instance,
                            run_id=run_id,
                            poll_attempts=max(1, int(args.poll_attempts)),
                            poll_interval=max(0.1, float(args.poll_interval)),
                            ask_timeout=max(1.0, float(args.ask_timeout)),
                            status_timeout=max(1.0, float(args.status_timeout)),
                            ssh_timeout=max(1.0, float(args.ssh_timeout)),
                        )
                    )
                )
        return rows

    results: list[dict[str, Any]] = list(discovery_failures)
    if grouped:
        worker_count = min(max(1, int(args.host_workers)), len(grouped))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(prove_host, host_name, group): host_name
                for host_name, group in sorted(grouped.items())
            }
            for future in as_completed(futures):
                results.extend(future.result())

    results.sort(key=lambda item: (_text(item.get("host")), _text(item.get("target"))))
    drill_mode = bool(args.cold_recovery_drill)
    summary = (
        build_cold_recovery_summary(results) if drill_mode else build_summary(results)
    )
    report = {
        "schema": (
            "norman.tui-cold-recovery-drill.v1"
            if drill_mode
            else "norman.tui-status-route-proof.v1"
        ),
        "run_id": run_id,
        "generated_at": int(time.time()),
        "hostname": socket.gethostname(),
        "live": not drill_mode,
        "mode": "cold-recovery-drill" if drill_mode else "status-route-proof",
        "mutation_scope": (
            "isolated temporary state; no prompt, model inference, model unload, "
            "service restart, or external mutation"
            if drill_mode
            else "status-only prompts; no tool or external mutation requested"
        ),
        "terminology": {
            "norllama_preflight": (
                "Local Norllama/Spark-worker planner evidence before a cloud final authority."
            ),
            "named_codexspark": (
                "OpenAI/Cerebras gpt-5.3-codex-spark preview runtime; access-check only, "
                "not a local worker."
            ),
        },
        "summary": summary,
        "results": results,
    }
    write_report(report, output_json=args.output_json, output_md=args.output_md)
    summary = _dict(report.get("summary"))
    if drill_mode:
        print(
            "Cold-recovery drill: {passed}/{targets} passed, "
            "stale-timeout recovery={recovery}".format(
                passed=_int(summary.get("passed")),
                targets=_int(summary.get("targets")),
                recovery=str(
                    bool(summary.get("stale_timeout_recovery_verified"))
                ).lower(),
            )
        )
    else:
        print(
            "Status route proof: {passed}/{targets} passed, {busy} busy, "
            "{preflights} Norllama preflights".format(
                passed=_int(summary.get("passed")),
                targets=_int(summary.get("targets")),
                busy=_int(summary.get("skipped_busy")),
                preflights=_int(summary.get("successful_norllama_preflights")),
            )
        )
    print(f"wrote {args.output_json}")
    print(f"wrote {args.output_md}")
    return 0 if _int(summary.get("failed")) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
