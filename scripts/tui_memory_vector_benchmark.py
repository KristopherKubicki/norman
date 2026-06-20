#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CASES_PATH = (
    SCRIPT_DIR.parent / "db" / "tui_memory_retrieval_benchmark_cases.json"
)


DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "id": "panelbot-upload-callback",
        "kind": "vector_helps",
        "query": "panelbot upload handoff callback",
        "expected_terms": ["panelbot", "upload"],
        "notes": "Old session chunk where chunk-level vector ranking should beat broad FTS turn ranking.",
    },
    {
        "id": "work-special-wedged-ssh",
        "kind": "hybrid_should_find",
        "query": "work special wedged ssh banner io pressure",
        "expected_terms": ["work", "ssh"],
        "notes": "Recent operational recovery context; exact terms should be enough.",
    },
    {
        "id": "metadata-only-session-turn-id",
        "kind": "metadata_should_find",
        "query": "019e6d5c-199c-7480-a56e-190ef8f57d3a",
        "expected_terms": ["019e6d5c"],
        "notes": "Session turn IDs live in metadata; the metadata lane should recover them.",
    },
    {
        "id": "semantic-synonym-gap",
        "kind": "known_gap",
        "query": "ssl browser warning blocked file send",
        "expected_terms": ["cert", "upload"],
        "notes": "Sparse local vectors are not neural semantic embeddings; synonym-only queries can miss.",
    },
]


def _load_memory_tool() -> Any:
    path = SCRIPT_DIR / "tui_memory_tool.py"
    spec = importlib.util.spec_from_file_location("tui_memory_tool", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_cases(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        if DEFAULT_CASES_PATH.exists():
            return _load_cases(DEFAULT_CASES_PATH)
        return DEFAULT_CASES
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("cases")
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a list or {{'cases': [...]}}")
    return [item for item in raw if isinstance(item, dict)]


def _row_text(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, default=str).lower()


def _clean_terms(terms: list[str]) -> list[str]:
    return [str(term).strip().lower() for term in terms if str(term).strip()]


def _row_identity(row: dict[str, Any]) -> str:
    for key in ("chunk_id", "id", "turn_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    return _row_text(row)


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped


def _hit(rows: list[dict[str, Any]], expected_terms: list[str]) -> bool:
    return _first_hit(rows, expected_terms) is not None


def _first_hit(
    rows: list[dict[str, Any]], expected_terms: list[str]
) -> dict[str, Any] | None:
    if not expected_terms:
        return rows[0] if rows else None
    clean_terms = _clean_terms(expected_terms)
    if not clean_terms:
        return rows[0] if rows else None
    for row in rows:
        if all(term in _row_text(row) for term in clean_terms):
            return row
    return None


def _first_hit_rank(
    rows: list[dict[str, Any]], expected_terms: list[str]
) -> int | None:
    hit = _first_hit(rows, expected_terms)
    if hit is None:
        return None
    target = _row_identity(hit)
    for index, row in enumerate(rows, start=1):
        if _row_identity(row) == target:
            return index
    return None


def _precision_at_k(
    rows: list[dict[str, Any]], expected_terms: list[str], *, k: int
) -> float:
    if k <= 0:
        return 0.0
    clean_terms = _clean_terms(expected_terms)
    if not clean_terms:
        return 1.0 if rows else 0.0
    hits = 0
    for row in rows[:k]:
        text = _row_text(row)
        if all(term in text for term in clean_terms):
            hits += 1
    return hits / k


def _mrr(rank: int | None) -> float:
    return 1.0 / rank if rank else 0.0


def _forbidden_hit_rows(
    rows: list[dict[str, Any]], forbidden_terms: list[str]
) -> list[dict[str, Any]]:
    clean_terms = _clean_terms(forbidden_terms)
    if not clean_terms:
        return []
    return [row for row in rows if any(term in _row_text(row) for term in clean_terms)]


def _outcome_passes(
    kind: str,
    *,
    fts_hit: bool,
    metadata_hit: bool,
    vector_hit: bool,
    forbidden_hit: bool,
) -> bool:
    if forbidden_hit:
        return False
    hybrid_hit = fts_hit or metadata_hit or vector_hit
    if kind == "vector_helps":
        return vector_hit and not fts_hit
    if kind == "metadata_should_find":
        return metadata_hit
    if kind == "hybrid_should_find":
        return hybrid_hit
    if kind == "known_gap":
        return not hybrid_hit
    return hybrid_hit


def benchmark_case(
    memory_tool: Any,
    conn: Any,
    case: dict[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    query = str(case.get("query") or "")
    expected_terms = [str(term) for term in case.get("expected_terms") or []]
    forbidden_terms = [str(term) for term in case.get("forbidden_terms") or []]
    fts = memory_tool.search_turns(conn, query=query, limit=limit)
    metadata = memory_tool.metadata_search(conn, query=query, limit=limit)
    vector = memory_tool.vector_search(conn, query=query, limit=limit)
    fts_rows = [dict(row) for row in fts.get("rows", [])]
    metadata_rows = [dict(row) for row in metadata.get("rows", [])]
    vector_rows = [dict(row) for row in vector.get("rows", [])]
    fts_hit_row = _first_hit(fts_rows, expected_terms)
    metadata_hit_row = _first_hit(metadata_rows, expected_terms)
    vector_hit_row = _first_hit(vector_rows, expected_terms)
    fts_hit = fts_hit_row is not None
    metadata_hit = metadata_hit_row is not None
    vector_hit = vector_hit_row is not None
    hybrid_rows = _dedupe_rows(fts_rows + metadata_rows + vector_rows)
    forbidden_rows = _forbidden_hit_rows(hybrid_rows, forbidden_terms)
    forbidden_hit = bool(forbidden_rows)
    fts_first_hit_rank = _first_hit_rank(fts_rows, expected_terms)
    metadata_first_hit_rank = _first_hit_rank(metadata_rows, expected_terms)
    vector_first_hit_rank = _first_hit_rank(vector_rows, expected_terms)
    rank_candidates = [
        rank
        for rank in (
            fts_first_hit_rank,
            metadata_first_hit_rank,
            vector_first_hit_rank,
        )
        if rank is not None
    ]
    hybrid_first_hit_rank = min(rank_candidates) if rank_candidates else None
    kind = str(case.get("kind") or "hybrid_should_find")
    passed = _outcome_passes(
        kind,
        fts_hit=fts_hit,
        metadata_hit=metadata_hit,
        vector_hit=vector_hit,
        forbidden_hit=forbidden_hit,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "id": str(case.get("id") or query[:40]),
        "kind": kind,
        "query": query,
        "expected_terms": expected_terms,
        "forbidden_terms": forbidden_terms,
        "passed": passed,
        "fts_hit": fts_hit,
        "metadata_hit": metadata_hit,
        "vector_hit": vector_hit,
        "hybrid_hit": fts_hit or metadata_hit or vector_hit,
        "forbidden_hit": forbidden_hit,
        "forbidden_hit_rows": forbidden_rows[:3],
        "elapsed_ms": elapsed_ms,
        "fts_first_hit_rank": fts_first_hit_rank,
        "metadata_first_hit_rank": metadata_first_hit_rank,
        "vector_first_hit_rank": vector_first_hit_rank,
        "hybrid_first_hit_rank": hybrid_first_hit_rank,
        "fts_precision_at_k": _precision_at_k(fts_rows, expected_terms, k=limit),
        "metadata_precision_at_k": _precision_at_k(
            metadata_rows, expected_terms, k=limit
        ),
        "vector_precision_at_k": _precision_at_k(vector_rows, expected_terms, k=limit),
        "hybrid_precision_at_k": _precision_at_k(hybrid_rows, expected_terms, k=limit),
        "fts_mrr": _mrr(fts_first_hit_rank),
        "metadata_mrr": _mrr(metadata_first_hit_rank),
        "vector_mrr": _mrr(vector_first_hit_rank),
        "hybrid_mrr": _mrr(hybrid_first_hit_rank),
        "fts_top": fts_rows[:1],
        "metadata_top": metadata_rows[:1],
        "vector_top": vector_rows[:1],
        "fts_hit_row": fts_hit_row,
        "metadata_hit_row": metadata_hit_row,
        "vector_hit_row": vector_hit_row,
        "notes": str(case.get("notes") or ""),
    }


def run_benchmark(
    db: Path, cases: list[dict[str, Any]], *, limit: int
) -> dict[str, Any]:
    memory_tool = _load_memory_tool()
    with memory_tool.connect(db) as conn:
        stats = memory_tool.stats(conn)
        rows = [benchmark_case(memory_tool, conn, case, limit=limit) for case in cases]
    case_count = len(rows)
    return {
        "schema": "norman.tui.memory-vector-benchmark.v1",
        "db": str(db),
        "limit": limit,
        "memory_vector": stats.get("memory_vector"),
        "summary": {
            "cases": len(rows),
            "passed": sum(1 for row in rows if row["passed"]),
            "failed": sum(1 for row in rows if not row["passed"]),
            "vector_hits": sum(1 for row in rows if row["vector_hit"]),
            "metadata_hits": sum(1 for row in rows if row["metadata_hit"]),
            "fts_hits": sum(1 for row in rows if row["fts_hit"]),
            "hybrid_hits": sum(1 for row in rows if row["hybrid_hit"]),
            "forbidden_hits": sum(1 for row in rows if row["forbidden_hit"]),
            "avg_elapsed_ms": round(
                sum(float(row["elapsed_ms"]) for row in rows) / case_count, 3
            )
            if case_count
            else 0.0,
            "avg_hybrid_mrr": round(
                sum(float(row["hybrid_mrr"]) for row in rows) / case_count, 4
            )
            if case_count
            else 0.0,
        },
        "cases": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# TUI Memory Vector Benchmark",
        "",
        f"DB: `{report.get('db')}`",
        f"Cases: `{summary.get('cases', 0)}`",
        f"Passed: `{summary.get('passed', 0)}`",
        f"Failed: `{summary.get('failed', 0)}`",
        f"FTS hits: `{summary.get('fts_hits', 0)}`",
        f"Metadata hits: `{summary.get('metadata_hits', 0)}`",
        f"Vector hits: `{summary.get('vector_hits', 0)}`",
        f"Hybrid hits: `{summary.get('hybrid_hits', 0)}`",
        f"Forbidden hits: `{summary.get('forbidden_hits', 0)}`",
        f"Avg elapsed ms: `{summary.get('avg_elapsed_ms', 0)}`",
        f"Avg hybrid MRR: `{summary.get('avg_hybrid_mrr', 0)}`",
        "",
        "| Case | Kind | Pass | FTS | Metadata | Vector | Rank | MRR | ms | Notes |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("cases", []):
        lines.append(
            "| {id} | {kind} | {passed} | {fts} | {metadata} | {vector} | {rank} | {mrr} | {elapsed} | {notes} |".format(
                id=str(row.get("id") or "").replace("|", "/"),
                kind=str(row.get("kind") or "").replace("|", "/"),
                passed="yes" if row.get("passed") else "no",
                fts="yes" if row.get("fts_hit") else "no",
                metadata="yes" if row.get("metadata_hit") else "no",
                vector="yes" if row.get("vector_hit") else "no",
                rank=row.get("hybrid_first_hit_rank") or "",
                mrr=row.get("hybrid_mrr") or 0,
                elapsed=row.get("elapsed_ms") or 0,
                notes=str(row.get("notes") or "").replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark local TUI memory FTS/vector/hybrid retrieval."
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_benchmark(args.db, _load_cases(args.cases), limit=args.limit)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(render_markdown(report), encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
