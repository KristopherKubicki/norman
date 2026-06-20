#!/usr/bin/env python3
"""Mine mirrored TUI prompt history for operator prompt and response patterns."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "norman.tui-prompt-patterns.v1"
DEFAULT_STATE_DB = Path("/home/kristopher/.codex-work/web-bridge/tui_state.sqlite3")
DEFAULT_OUTPUT_JSON = Path("tmp/tui_prompt_patterns.json")
DEFAULT_OUTPUT_MD = Path("tmp/tui_prompt_patterns.md")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def prompt_template(prompt: str) -> str:
    clean = _norm(prompt)
    if clean.startswith("proceed from your last answer"):
        return "proceed_from_last_answer"
    if clean.startswith("[auto-continuation: promised-work]"):
        return "auto_continuation_promised_work"
    if "make it so" in clean or "do the concrete thing" in clean:
        return "make_it_so"
    if clean in {"next", "proceed", "continue", "keep going", "resume"}:
        return "one_word_continue"
    if clean.startswith("status") or "whats the status" in clean:
        return "status_check"
    if clean.startswith("can you check") or clean.startswith("can you chekc"):
        return "can_you_check"
    if clean.startswith("can you ") or clean.startswith("could you "):
        return "can_you_request"
    if clean.startswith("why ") or "why did" in clean:
        return "why_diagnostic"
    if "whats next" in clean or "what's next" in clean or "what next" in clean:
        return "whats_next"
    if clean.startswith("approved") or clean in {"approved", "its approved"}:
        return "approval_followup"
    if clean.startswith("ok ") or clean.startswith("ok,"):
        return "ok_followup"
    return "other"


def question_style(prompt: str) -> str:
    clean = _norm(prompt)
    if prompt_template(prompt) in {
        "proceed_from_last_answer",
        "make_it_so",
        "one_word_continue",
        "approval_followup",
    }:
        return "imperative_followup"
    if (
        clean.count("?") >= 2
        or len(re.findall(r"\b(can|what|why|how|where)\b", clean)) >= 3
    ):
        return "stacked_question"
    if clean.startswith("why") or "why did" in clean:
        return "diagnostic_why"
    if "how much" in clean or "money" in clean or "save" in clean or "cost" in clean:
        return "cost_or_capacity_question"
    if "i thought" in clean or "didnt we" in clean or "didn't we" in clean:
        return "memory_challenge"
    if clean.startswith("can you") or clean.startswith("could you"):
        return "soft_request"
    if clean.startswith("what") or clean.startswith("how"):
        return "open_design_question"
    return "statement_or_context"


def meta_patterns(prompt: str) -> list[str]:
    clean = _norm(prompt)
    patterns: list[str] = []
    if clean.startswith(("can you", "could you", "would you")):
        patterns.append("softened_request")
    if (
        clean.count("?") >= 2
        or len(re.findall(r"\b(can|what|why|how|where)\b", clean)) >= 3
    ):
        patterns.append("question_stack")
    if any(
        token in clean
        for token in (
            "i thought",
            "didnt we",
            "didn't we",
            "i dont know why",
            "i don't know why",
        )
    ):
        patterns.append("memory_or_expectation_challenge")
    if any(
        token in clean
        for token in ("money", "cost", "save", "spend", "headroom", "budget")
    ):
        patterns.append("cost_pressure")
    if any(
        token in clean
        for token in (
            "why",
            "what happened",
            "wedged",
            "crash",
            "outage",
            "usage limit",
        )
    ):
        patterns.append("failure_pressure")
    if any(
        token in clean
        for token in ("make it so", "do it", "proceed", "next", "keep going")
    ):
        patterns.append("action_after_answer")
    if any(
        token in clean
        for token in ("rather", "instead", "but", "not ", "less ", "more ")
    ):
        patterns.append("correction_or_refinement")
    if any(
        token in clean
        for token in ("maybe", "i think", "probably", "kind of", "i guess")
    ):
        patterns.append("uncertainty_marker")
    return patterns or ["plain_request"]


def response_outcome(response: str, error: str = "") -> str:
    clean = _norm(response)
    tail = "\n".join(str(response or "").strip().splitlines()[-3:]).upper()
    if error:
        return "error"
    if "BLOCKED" in tail:
        return "blocked"
    if "CHECKPOINT" in tail:
        return "checkpoint"
    if "DONE" in tail:
        return "done"
    if any(
        token in clean
        for token in (
            "need explicit approval",
            "missing context",
            "do not ack",
            "cannot ack",
        )
    ):
        return "approval_or_context_block"
    if any(
        token in clean
        for token in (
            "0 online",
            "0 usable",
            "not currently",
            "not routable",
            "timed out",
            "connection refused",
        )
    ):
        return "negative_evidence"
    return "no_terminal"


def likely_next_move(template: str, style: str, patterns: list[str]) -> str:
    if template in {"proceed_from_last_answer", "one_word_continue"}:
        return "load_last_checkpoint_then_continue_or_checkpoint"
    if template == "make_it_so":
        return "extract_prior_recommendation_then_execute_or_gate"
    if template in {"status_check", "can_you_check"}:
        return "one_targeted_check_then_evidence_answer"
    if template == "approval_followup":
        return "validate_approval_scope_before_action"
    if "memory_or_expectation_challenge" in patterns:
        return "verify_against_db_or_source_before_answering"
    if "cost_pressure" in patterns:
        return "run_cost_or_route_policy_before_recommending"
    if style == "stacked_question":
        return "split_question_stack_then_answer_highest_risk_first"
    if style in {"diagnostic_why", "open_design_question"}:
        return "inspect_evidence_then_design_answer"
    return "normal_operator_response"


def route_hint(template: str, style: str, patterns: list[str]) -> str:
    if template == "approval_followup" or "failure_pressure" in patterns:
        return "cheap_preflight_then_cloud_if_evidence_is_ambiguous"
    if template in {
        "proceed_from_last_answer",
        "one_word_continue",
        "status_check",
        "can_you_check",
        "make_it_so",
    }:
        return "local_or_deterministic_preflight_first"
    if "cost_pressure" in patterns or "question_stack" in patterns:
        return "local_summarizer_then_5_4_or_5_5_only_if_authority_pressure"
    return "standard_auto"


def _turns(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT started_at, prompt_preview, response_preview, error_preview, payload_json
        FROM turns
        ORDER BY started_at
        """
    ).fetchall()
    turns: list[dict[str, Any]] = []
    for row in rows:
        payload = _payload(row)
        prompt = str(payload.get("prompt") or row["prompt_preview"] or "")
        response = str(payload.get("response") or row["response_preview"] or "")
        error = str(payload.get("error") or row["error_preview"] or "")
        template = prompt_template(prompt)
        style = question_style(prompt)
        patterns = meta_patterns(prompt)
        turns.append(
            {
                "started_at": row["started_at"],
                "prompt": prompt,
                "template": template,
                "question_style": style,
                "meta_patterns": patterns,
                "response_outcome": response_outcome(response, error),
                "likely_next_move": likely_next_move(template, style, patterns),
                "route_hint": route_hint(template, style, patterns),
            }
        )
    return turns


def _count(values: list[str]) -> dict[str, int]:
    return dict(Counter(values).most_common())


def build_report(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        turns = _turns(conn)
    template_counts = Counter(turn["template"] for turn in turns)
    style_counts = Counter(turn["question_style"] for turn in turns)
    outcome_counts = Counter(turn["response_outcome"] for turn in turns)
    pattern_counts = Counter(
        pattern for turn in turns for pattern in turn["meta_patterns"]
    )
    route_counts = Counter(turn["route_hint"] for turn in turns)
    rows: list[dict[str, Any]] = []
    for template, count in template_counts.most_common():
        matching = [turn for turn in turns if turn["template"] == template]
        outcome = Counter(turn["response_outcome"] for turn in matching)
        next_move = Counter(turn["likely_next_move"] for turn in matching).most_common(
            1
        )[0][0]
        route = Counter(turn["route_hint"] for turn in matching).most_common(1)[0][0]
        negative = sum(
            outcome.get(key, 0)
            for key in (
                "blocked",
                "checkpoint",
                "error",
                "approval_or_context_block",
                "negative_evidence",
            )
        )
        rows.append(
            {
                "template": template,
                "count": count,
                "negative_or_checkpoint_count": negative,
                "negative_or_checkpoint_pct": round(
                    negative / count * 100.0 if count else 0.0, 2
                ),
                "dominant_next_move": next_move,
                "dominant_route_hint": route,
                "outcomes": dict(outcome.most_common()),
            }
        )
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "source_db": str(db_path),
        "summary": {
            "turn_count": len(turns),
            "template_counts": _count([turn["template"] for turn in turns]),
            "question_style_counts": dict(style_counts.most_common()),
            "meta_pattern_counts": dict(pattern_counts.most_common()),
            "response_outcome_counts": dict(outcome_counts.most_common()),
            "route_hint_counts": dict(route_counts.most_common()),
        },
        "rows": rows,
        "recent": turns[-25:],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# TUI Prompt Patterns",
        "",
        f"- Source DB: `{report['source_db']}`",
        f"- Turns: `{summary['turn_count']}`",
        "",
        "## Question Styles",
        "",
    ]
    for label, count in summary["question_style_counts"].items():
        lines.append(f"- `{label}`: {count}")
    lines.extend(["", "## Meta Patterns", ""])
    for label, count in summary["meta_pattern_counts"].items():
        lines.append(f"- `{label}`: {count}")
    lines.extend(
        [
            "",
            "## Repeated Templates",
            "",
            "| Template | Count | Negative/checkpoint | Next move | Route hint |",
            "| --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in report["rows"][:20]:
        lines.append(
            "| {template} | {count} | {pct:.2f}% | {move} | {route} |".format(
                template=row["template"],
                count=row["count"],
                pct=row["negative_or_checkpoint_pct"],
                move=row["dominant_next_move"],
                route=row["dominant_route_hint"],
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.state_db)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(report))
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
