#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPLAY_REPORT = Path("/tmp/norman_tui_context_replay_benchmark.json")
DEFAULT_CASES = REPO_ROOT / "db" / "tui_quality_benchmark_cases.json"
DEFAULT_OUTPUT_DIR = Path("/tmp/norman_tui_shadow_prompt_pack")


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_int(value: Any) -> str:
    return f"{_coerce_int(value):,}"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_replay_report(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("case_replays"), list):
        raise ValueError(f"{path} must contain a context replay report")
    return data


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = _load_json(path)
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError(f"{path} must contain a cases list")
    return [case for case in cases if isinstance(case, dict)]


def safe_name(value: Any) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "")).strip("-")
    return clean or "item"


def _rules(case: dict[str, Any], key: str) -> list[str]:
    rules = case.get(key)
    if not isinstance(rules, list):
        return []
    output: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        label = str(rule.get("description") or rule.get("id") or "").strip()
        terms: list[str] = []
        for term_key in ("all_terms", "any_terms"):
            values = rule.get(term_key)
            if isinstance(values, str):
                terms.append(values)
            elif isinstance(values, list):
                terms.extend(str(item) for item in values if str(item or "").strip())
        suffix = f": {', '.join(terms)}" if terms else ""
        output.append(f"{label}{suffix}")
    return output


def _case_by_id(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(case.get("id") or ""): case for case in cases}


def _row_by_slug(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("row_proofs")
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("slug") or ""): row
        for row in rows
        if isinstance(row, dict) and row.get("slug")
    }


def _format_list(items: list[str], *, empty: str = "none") -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def _aggregate_context(report: dict[str, Any]) -> list[str]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return [
        f"Rows reachable: {summary.get('reachable_rows')}/{summary.get('row_count')}",
        (
            "Context tokens: "
            f"{_compact_int(summary.get('total_current_tokens'))} -> "
            f"{_compact_int(summary.get('total_packed_tokens'))}"
        ),
        (
            "Saved tokens: "
            f"{_compact_int(summary.get('total_saved_tokens'))} "
            f"({summary.get('total_saved_pct')}%)"
        ),
        f"DB-enabled rows: {summary.get('db_enabled_rows')}",
        f"Rows with older-turn reference proof: {summary.get('rows_with_older_reference_proof')}",
        f"Safe to run shadow now: {'yes' if summary.get('shadow_run_ready') else 'no'}",
        f"Activation safe now: {'yes' if summary.get('activation_safe') else 'no'}",
    ]


def _row_context(row: dict[str, Any] | None) -> list[str]:
    if not row:
        return ["No matched TUI row; use aggregate context only."]
    older = (
        row.get("older_turn_reference_proof")
        if isinstance(row.get("older_turn_reference_proof"), dict)
        else {}
    )
    tail = (
        row.get("tail_digest_proof")
        if isinstance(row.get("tail_digest_proof"), dict)
        else {}
    )
    quality_gate = (
        row.get("quality_gate") if isinstance(row.get("quality_gate"), dict) else {}
    )
    lines = [
        f"TUI row: {row.get('slug')}",
        f"State: {row.get('state')}",
        (
            "Tokens: "
            f"{_compact_int(row.get('current_tokens'))} -> "
            f"{_compact_int(row.get('packed_tokens'))}; "
            f"saved {_compact_int(row.get('saved_tokens'))} ({row.get('saved_pct')}%)"
        ),
        f"Approx saved cost: {row.get('saved_cost_label') or 'unknown'}",
        f"State DB enabled: {'yes' if row.get('state_db_enabled') else 'no'}",
        f"History format: {row.get('history_format') or 'unknown'}",
        (
            "Older history proof: "
            f"{_compact_int(older.get('older_body_tokens_replaced'))} body tokens "
            f"-> {_compact_int(older.get('evidence_ref_tokens'))} reference tokens"
        ),
        (
            "Tail proof: "
            f"{_compact_int(tail.get('raw_tail_tokens_replaced'))} raw tail tokens "
            f"-> {_compact_int(tail.get('tail_digest_tokens'))} digest tokens"
        ),
        (
            "Quality gate: "
            f"needs old-detail retrieval={bool(quality_gate.get('needs_retrieval_for_older_details'))}; "
            f"requires shadow before activation={bool(quality_gate.get('requires_shadow_run_before_activation'))}; "
            f"live behavior changed={bool(quality_gate.get('live_prompt_behavior_changed'))}"
        ),
        f"Verdict: {row.get('verdict')} ({', '.join(row.get('reasons') or [])})",
    ]
    included = row.get("included_sources")
    if isinstance(included, list) and included:
        lines.append("Included compact sources:")
        lines.extend(str(item) for item in included)
    replaced = row.get("replaced_sources")
    if isinstance(replaced, list) and replaced:
        lines.append("Replaced sources:")
        lines.extend(str(item) for item in replaced)
    return lines


def build_prompt(
    *,
    case: dict[str, Any],
    case_replay: dict[str, Any],
    report: dict[str, Any],
    row: dict[str, Any] | None,
    label: str,
) -> str:
    context_tokens = _coerce_int(
        case_replay.get("baseline_tokens")
        if label == "baseline"
        else case_replay.get("candidate_tokens")
    )
    mode_note = (
        "Baseline mode: answer as if you received the full current TUI context. "
        "The packet below contains the source inventory and benchmark facts needed "
        "for this controlled run, but not the full raw old-history bodies."
        if label == "baseline"
        else "Candidate mode: answer using the compact DB-backed state card, recent "
        "turns, digests, and evidence-reference packet. If older details would need "
        "retrieval, say that instead of inventing them."
    )
    benchmark_facts = (
        _rules(case, "required_facts")
        + _rules(case, "required_evidence")
        + _rules(case, "wisdom_checks")
    )
    traps = _rules(case, "known_traps")
    lines = [
        "# TUI Shadow Answer Prompt",
        "",
        "Answer the operator prompt directly. Be concrete, concise, and careful about uncertainty. Do not mention benchmark internals unless needed to explain a caveat.",
        "",
        "## Mode",
        "",
        f"- Label: {label}",
        f"- Estimated context tokens: {_compact_int(context_tokens)}",
        f"- {mode_note}",
        "",
        "## Operator Prompt",
        "",
        str(case.get("prompt") or "").strip(),
        "",
        "## Replay Context",
        "",
        _format_list(_aggregate_context(report)),
        "",
        "## TUI Context",
        "",
        _format_list(_row_context(row)),
        "",
        "## Relevant Context Facts",
        "",
        _format_list(benchmark_facts),
        "",
        "## Avoid",
        "",
        _format_list(
            traps
            + [
                "Do not claim exact invoice-grade spend unless the usage mode is normalized.",
                "Do not claim live prompt behavior has changed during a dry-run preview.",
                "Do not claim activation is safe while a shadow-before-activation gate remains.",
            ]
        ),
        "",
        "## Answer",
        "",
    ]
    return "\n".join(lines)


def build_pack(
    report: dict[str, Any],
    cases: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir = output_dir / "prompts"
    answer_dir = output_dir / "answers"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    answer_dir.mkdir(parents=True, exist_ok=True)

    cases_by_id = _case_by_id(cases)
    rows_by_slug = _row_by_slug(report)
    entries: list[dict[str, Any]] = []
    overlay_answers: list[dict[str, Any]] = []

    for case_replay in report.get("case_replays", []):
        if not isinstance(case_replay, dict):
            continue
        case_id = str(case_replay.get("case_id") or "")
        case = cases_by_id.get(case_id)
        if not case:
            continue
        slug = str(case_replay.get("matched_context_slug") or "")
        row = rows_by_slug.get(slug)
        for label in ("baseline", "candidate"):
            filename = f"{safe_name(case_id)}__{label}.md"
            output_name = f"{safe_name(case_id)}__{label}.out.md"
            prompt_path = prompt_dir / filename
            answer_path = answer_dir / output_name
            prompt_path.write_text(
                build_prompt(
                    case=case,
                    case_replay=case_replay,
                    report=report,
                    row=row,
                    label=label,
                ),
                encoding="utf-8",
            )
            context_tokens = _coerce_int(
                case_replay.get("baseline_tokens")
                if label == "baseline"
                else case_replay.get("candidate_tokens")
            )
            command = (
                "codex exec --ephemeral -C "
                f"{shlex.quote(str(REPO_ROOT))} "
                "-s read-only -a never "
                f"-o {shlex.quote(str(answer_path))} "
                f"< {shlex.quote(str(prompt_path))}"
            )
            entries.append(
                {
                    "case_id": case_id,
                    "label": label,
                    "tui": str(case_replay.get("tui") or ""),
                    "matched_context_slug": slug,
                    "context_tokens": context_tokens,
                    "prompt_path": str(prompt_path),
                    "answer_path": str(answer_path),
                    "command": command,
                }
            )
            overlay_answers.append(
                {
                    "case_id": case_id,
                    "label": label,
                    "context_tokens": context_tokens,
                    "answer": "",
                }
            )

    overlay = {
        "schema": "norman.tui.quality-shadow-answers.v1",
        "run_id": f"shadow-prompt-pack-{int(time.time())}",
        "notes": (
            "Fill answers from the prompt pack outputs, then run "
            "scripts/tui_quality_benchmark.py --answers against this file."
        ),
        "answers": overlay_answers,
    }
    overlay_path = output_dir / "answers.overlay.json"
    overlay_path.write_text(
        json.dumps(overlay, indent=2, sort_keys=True), encoding="utf-8"
    )

    commands_path = output_dir / "run_commands.sh"
    commands_path.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n\n"
        + "\n".join(entry["command"] for entry in entries)
        + "\n",
        encoding="utf-8",
    )

    manifest_data = {
        "schema": "norman.tui.shadow-prompt-pack.v1",
        "generated_at": int(time.time()),
        "output_dir": str(output_dir),
        "limitations": [
            "This pack uses replay evidence and benchmark facts. It does not yet export full raw older-turn bodies from SQLite.",
            "Use this to test answer discipline and scoring workflow. Use a future SQLite retrieval exporter for full end-to-end recall proof.",
            "All commands are read-only and ephemeral by default, but running them can still spend model tokens.",
        ],
        "replay_summary": report.get("summary", {}),
        "answer_overlay_path": str(overlay_path),
        "commands_path": str(commands_path),
        "entries": entries,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_data, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest_data


def ingest_outputs(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("entries"), list):
        raise ValueError(f"{manifest_path} must contain a shadow prompt manifest")
    answers: list[dict[str, Any]] = []
    missing: list[str] = []
    for entry in manifest.get("entries", []):
        if not isinstance(entry, dict):
            continue
        answer_path = Path(str(entry.get("answer_path") or ""))
        answer = ""
        if answer_path.exists():
            answer = answer_path.read_text(encoding="utf-8").strip()
        else:
            missing.append(str(answer_path))
        answers.append(
            {
                "case_id": str(entry.get("case_id") or ""),
                "label": str(entry.get("label") or ""),
                "context_tokens": _coerce_int(entry.get("context_tokens")),
                "answer": answer,
            }
        )
    overlay = {
        "schema": "norman.tui.quality-shadow-answers.v1",
        "run_id": f"shadow-output-ingest-{int(time.time())}",
        "notes": f"Ingested from {manifest_path}",
        "missing_answer_files": missing,
        "answers": answers,
    }
    output_path.write_text(
        json.dumps(overlay, indent=2, sort_keys=True), encoding="utf-8"
    )
    return overlay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or ingest a prompt pack for TUI quality shadow runs."
    )
    parser.add_argument("--replay-report", type=Path, default=DEFAULT_REPLAY_REPORT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--ingest-manifest",
        type=Path,
        help="Read generated answer files from a manifest and write an answer overlay.",
    )
    parser.add_argument(
        "--ingest-output",
        type=Path,
        default=Path("/tmp/norman_tui_shadow_answers.ingested.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.ingest_manifest:
        overlay = ingest_outputs(args.ingest_manifest, args.ingest_output)
        print(f"wrote {args.ingest_output}")
        print(
            json.dumps(
                {
                    "answers": len(overlay.get("answers", [])),
                    "missing": len(overlay.get("missing_answer_files", [])),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    report = load_replay_report(args.replay_report)
    cases = load_cases(args.cases)
    manifest = build_pack(report, cases, args.output_dir)
    print(f"wrote {args.output_dir / 'manifest.json'}")
    print(f"wrote {manifest['answer_overlay_path']}")
    print(f"wrote {manifest['commands_path']}")
    print(
        json.dumps(
            {"entries": len(manifest.get("entries", []))}, indent=2, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
