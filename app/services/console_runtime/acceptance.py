from __future__ import annotations

import glob
import json
import time
from pathlib import Path
from typing import Any

from app.core.config import settings

ACCEPTANCE_REPORT_SCHEMA = "norman.tui-kernel-acceptance.v1"
ACCEPTANCE_GATE_SCHEMA = "norman.tui-kernel-acceptance-gate.v1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean(value).lower() in {"1", "true", "yes", "on", "pass", "passed"}


def _audit_passes(value: Any) -> bool:
    payload = _dict(value)
    return _clean(payload.get("status")).lower() == "pass" or _bool(payload.get("pass"))


def _completion_gate_passes(value: Any) -> bool:
    payload = _dict(value)
    return _clean(payload.get("status")).lower() == "pass" or _bool(
        payload.get("gate_passed")
    )


def _results(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item) for item in report.get("results") or [] if isinstance(item, dict)
    ]


def _result_target(result: dict[str, Any]) -> str:
    return _clean(result.get("target"))


def _result_scenario(result: dict[str, Any]) -> str:
    return _clean(result.get("scenario"))


def _report_paths(pattern: str) -> list[Path]:
    clean = _clean(pattern)
    if not clean:
        return []
    candidates: list[Path] = []
    search_roots = [Path.cwd(), _repo_root()]
    if Path(clean).is_absolute():
        matches = glob.glob(clean)
    else:
        matches = []
        for root in search_roots:
            matches.extend(glob.glob(str(root / clean)))
    seen: set[str] = set()
    for raw in matches:
        path = Path(raw)
        key = str(path.resolve())
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        candidates.append(path)
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def _load_report(path: Path) -> tuple[dict[str, Any], str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as exc:
        return {}, str(exc)


def latest_acceptance_report(
    *,
    pattern: str | None = None,
) -> dict[str, Any]:
    """Return the newest TUI acceptance report, failing closed on read errors."""

    glob_pattern = (
        pattern if pattern is not None else settings.tui_acceptance_report_glob
    )
    paths = _report_paths(glob_pattern)
    if not paths:
        return {
            "available": False,
            "error": "no acceptance report matched %r" % _clean(glob_pattern),
            "path": "",
            "report": {},
        }
    path = paths[0]
    report, error = _load_report(path)
    return {
        "available": not bool(error),
        "error": error,
        "path": str(path),
        "report": report if isinstance(report, dict) else {},
    }


def acceptance_release_gate(
    report: dict[str, Any] | None,
    *,
    path: str = "",
    now: int | None = None,
    required_targets: list[str] | None = None,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Evaluate whether a live TUI acceptance report proves local-first behavior."""

    report = report if isinstance(report, dict) else {}
    now_ts = int(now if now is not None else time.time())
    max_age = int(
        max_age_seconds
        if max_age_seconds is not None
        else settings.tui_acceptance_report_max_age_seconds
    )
    required = [
        _clean(item)
        for item in (
            required_targets
            if required_targets is not None
            else settings.tui_acceptance_required_targets
        )
        if _clean(item)
    ]
    results = _results(report)
    generated_at = _int(report.get("generated_at"))
    age_seconds = max(0, now_ts - generated_at) if generated_at else 0
    target_names = sorted(
        {_result_target(item) for item in results if _result_target(item)}
    )
    scenario_names = sorted(
        {_result_scenario(item) for item in results if _result_scenario(item)}
    )
    missing_targets = [target for target in required if target not in target_names]
    failed_results = [
        {
            "target": _result_target(item),
            "scenario": _result_scenario(item),
            "failures": list(item.get("failures") or []),
        }
        for item in results
        if not bool(item.get("passed"))
    ]
    receipt_failures: list[str] = []
    workerless: list[str] = []
    cloud_token_results: list[str] = []
    cloud_proxy_results: list[str] = []
    nonlocal_kpi: list[str] = []
    missing_model_events: list[str] = []
    missing_live_execution: list[str] = []
    output_shape_failures: list[str] = []
    missing_local_tokens: list[str] = []
    receipt_audit_failures: list[str] = []
    completion_gate_failures: list[str] = []
    observed_workerless: list[str] = []
    invalid_observed_worker_source: list[str] = []
    for item in results:
        label = "%s:%s" % (_result_target(item), _result_scenario(item))
        receipt = _dict(item.get("receipt"))
        if not receipt.get("available"):
            receipt_failures.append(label)
        if receipt.get("job_status") != "done":
            receipt_failures.append(label)
        if receipt.get("kernel_owned_turn") is not True:
            receipt_failures.append(label)
        if not _clean(receipt.get("selected_worker")):
            workerless.append(label)
        if not _clean(receipt.get("observed_worker")):
            observed_workerless.append(label)
        if _clean(receipt.get("observed_worker_source")) != "gateway_response":
            invalid_observed_worker_source.append(label)
        if _clean(receipt.get("execution_mode")).lower() != "live":
            missing_live_execution.append(label)
        if _clean(receipt.get("output_shape")).lower() != "complete":
            output_shape_failures.append(label)
        if _int(receipt.get("local_tokens")) <= 0:
            missing_local_tokens.append(label)
        if not _audit_passes(receipt.get("receipt_audit")):
            receipt_audit_failures.append(label)
        if not _completion_gate_passes(receipt.get("completion_gate")):
            completion_gate_failures.append(label)
        if _bool(receipt.get("cloud_proxy")):
            cloud_proxy_results.append(label)
        if _int(receipt.get("goal_cloud_tokens")) or _int(
            receipt.get("ledger_cloud_tokens")
        ):
            cloud_token_results.append(label)
        if _clean(receipt.get("local_first_status")) != "on_target":
            nonlocal_kpi.append(label)
        if _int(receipt.get("model_completed_count")) < 1:
            missing_model_events.append(label)
    stale = bool(generated_at and max_age > 0 and age_seconds > max_age)
    failures: list[str] = []
    if report.get("schema") != ACCEPTANCE_REPORT_SCHEMA:
        failures.append("report schema is not %s" % ACCEPTANCE_REPORT_SCHEMA)
    if not results:
        failures.append("report has no results")
    if report.get("passed") is not True:
        failures.append("report did not pass")
    if missing_targets:
        failures.append("missing required targets: %s" % ", ".join(missing_targets))
    if stale:
        failures.append("report is stale: %ss old" % age_seconds)
    if failed_results:
        failures.append("one or more target scenarios failed")
    if receipt_failures:
        failures.append(
            "receipt proof incomplete: %s" % ", ".join(sorted(set(receipt_failures)))
        )
    if workerless:
        failures.append("missing worker attribution: %s" % ", ".join(workerless))
    if observed_workerless:
        failures.append(
            "missing observed worker proof: %s"
            % ", ".join(sorted(set(observed_workerless)))
        )
    if invalid_observed_worker_source:
        failures.append(
            "observed worker source is not gateway_response: %s"
            % ", ".join(sorted(set(invalid_observed_worker_source)))
        )
    if missing_live_execution:
        failures.append(
            "missing live execution proof: %s"
            % ", ".join(sorted(set(missing_live_execution)))
        )
    if output_shape_failures:
        failures.append(
            "output shape is not complete: %s"
            % ", ".join(sorted(set(output_shape_failures)))
        )
    if missing_local_tokens:
        failures.append(
            "missing positive local token proof: %s"
            % ", ".join(sorted(set(missing_local_tokens)))
        )
    if receipt_audit_failures:
        failures.append(
            "receipt audit did not pass: %s"
            % ", ".join(sorted(set(receipt_audit_failures)))
        )
    if completion_gate_failures:
        failures.append(
            "completion gate did not pass: %s"
            % ", ".join(sorted(set(completion_gate_failures)))
        )
    if cloud_proxy_results:
        failures.append(
            "cloud proxy used: %s" % ", ".join(sorted(set(cloud_proxy_results)))
        )
    if cloud_token_results:
        failures.append(
            "cloud/proxy tokens present: %s" % ", ".join(cloud_token_results)
        )
    if nonlocal_kpi:
        failures.append("local-first KPI not on_target: %s" % ", ".join(nonlocal_kpi))
    if missing_model_events:
        failures.append(
            "missing model.completed proof: %s" % ", ".join(missing_model_events)
        )
    status = "pass" if not failures else ("stale" if stale else "fail")
    if not report:
        status = "missing"
    return {
        "schema": ACCEPTANCE_GATE_SCHEMA,
        "status": status,
        "passed": status == "pass",
        "report_path": path,
        "report_schema": _clean(report.get("schema")),
        "run_id": _clean(report.get("run_id")),
        "generated_at": generated_at,
        "age_seconds": age_seconds,
        "max_age_seconds": max_age,
        "target_count": len(target_names),
        "scenario_count": len(scenario_names),
        "result_count": len(results),
        "pass_count": _int(report.get("pass_count")),
        "total_count": _int(report.get("total_count")) or len(results),
        "pass_percent": round(
            100.0
            * _int(report.get("pass_count"))
            / max(1, _int(report.get("total_count")) or len(results)),
            2,
        ),
        "targets": target_names,
        "scenarios": scenario_names,
        "required_targets": required,
        "missing_targets": missing_targets,
        "failed_results": failed_results,
        "release_gate": {
            "all_required_targets_present": not missing_targets,
            "all_results_passed": not failed_results and bool(results),
            "receipts_complete": not receipt_failures and bool(results),
            "worker_attribution_complete": not workerless and bool(results),
            "observed_worker_proof": not observed_workerless
            and not invalid_observed_worker_source
            and bool(results),
            "live_execution": not missing_live_execution and bool(results),
            "complete_output_shape": not output_shape_failures and bool(results),
            "positive_local_tokens": not missing_local_tokens and bool(results),
            "receipt_audit_passed": not receipt_audit_failures and bool(results),
            "completion_gate_passed": not completion_gate_failures and bool(results),
            "no_cloud_proxy": not cloud_proxy_results and bool(results),
            "zero_cloud_tokens": not cloud_token_results and bool(results),
            "local_first_on_target": not nonlocal_kpi and bool(results),
            "model_completion_visible": not missing_model_events and bool(results),
            "fresh": not stale and bool(generated_at),
        },
        "failures": failures,
    }


def latest_acceptance_gate(
    *,
    pattern: str | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    loaded = latest_acceptance_report(pattern=pattern)
    if not loaded.get("available"):
        return {
            "schema": ACCEPTANCE_GATE_SCHEMA,
            "status": "missing",
            "passed": False,
            "report_path": loaded.get("path", ""),
            "failures": [loaded.get("error") or "acceptance report unavailable"],
            "release_gate": {
                "all_required_targets_present": False,
                "all_results_passed": False,
                "receipts_complete": False,
                "worker_attribution_complete": False,
                "observed_worker_proof": False,
                "live_execution": False,
                "complete_output_shape": False,
                "positive_local_tokens": False,
                "receipt_audit_passed": False,
                "completion_gate_passed": False,
                "no_cloud_proxy": False,
                "zero_cloud_tokens": False,
                "local_first_on_target": False,
                "model_completion_visible": False,
                "fresh": False,
            },
        }
    return acceptance_release_gate(
        loaded["report"],
        path=str(loaded.get("path") or ""),
        now=now,
    )
