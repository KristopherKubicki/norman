from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_shadow_pack(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_shadow_prompt_pack",
        scripts_dir / "tui_shadow_prompt_pack.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_shadow_prompt_pack"] = module
    spec.loader.exec_module(module)
    return module


def _sample_replay_report() -> dict:
    return {
        "schema": "norman.tui.context-replay-benchmark.v1",
        "summary": {
            "row_count": 1,
            "reachable_rows": 1,
            "total_current_tokens": 18000,
            "total_packed_tokens": 4600,
            "total_saved_tokens": 13400,
            "total_saved_pct": 74.4,
            "db_enabled_rows": 1,
            "rows_with_older_reference_proof": 1,
            "shadow_run_ready": True,
            "activation_safe": False,
        },
        "row_proofs": [
            {
                "slug": "control-plane",
                "state": "ok",
                "current_tokens": 18000,
                "packed_tokens": 4600,
                "saved_tokens": 13400,
                "saved_pct": 74.4,
                "saved_cost_label": "$0.007-$0.07",
                "state_db_enabled": True,
                "history_format": "jsonl_write_through_sqlite",
                "quality_gate": {
                    "needs_retrieval_for_older_details": True,
                    "requires_shadow_run_before_activation": True,
                    "live_prompt_behavior_changed": False,
                },
                "older_turn_reference_proof": {
                    "older_body_tokens_replaced": 13000,
                    "evidence_ref_tokens": 728,
                },
                "tail_digest_proof": {
                    "raw_tail_tokens_replaced": 900,
                    "tail_digest_tokens": 400,
                },
                "included_sources": [
                    "state card - included - 240 tok",
                    "evidence refs - included - 728 tok - 18 older turns",
                ],
                "replaced_sources": [
                    "older turn bodies - replaced - 13,000 tok",
                ],
                "verdict": "shadow-ready",
                "reasons": ["needs real shadow answer before activation"],
            }
        ],
        "case_replays": [
            {
                "case_id": "billing-token-caveat",
                "tui": "control-plane",
                "matched_context_slug": "control-plane",
                "baseline_tokens": 18000,
                "candidate_tokens": 4600,
            }
        ],
    }


def _sample_cases() -> list[dict]:
    return [
        {
            "id": "billing-token-caveat",
            "title": "Billing token caveat",
            "tui": "control-plane",
            "prompt": "Can we use the DB token rows for the invoice packet?",
            "answer_contract": {
                "min_response_words": 28,
                "required_sections": ["evidence", "next"],
                "requires_next_step": True,
                "requires_caveat": True,
            },
            "required_facts": [
                {
                    "id": "tags-present",
                    "all_terms": [
                        "billing_owner",
                        "billing_project",
                        "billing_scope",
                    ],
                }
            ],
            "required_evidence": [
                {"id": "usage-events", "all_terms": ["usage_events"]}
            ],
            "wisdom_checks": [
                {"id": "normalizer-before-invoice", "all_terms": ["normalizer"]}
            ],
            "known_traps": [
                {"id": "sum-cumulative", "forbidden_terms": ["exact spend"]}
            ],
        }
    ]


def test_build_pack_writes_prompts_manifest_and_overlay(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_shadow_pack(monkeypatch)

    manifest = module.build_pack(_sample_replay_report(), _sample_cases(), tmp_path)

    manifest_path = tmp_path / "manifest.json"
    overlay_path = tmp_path / "answers.overlay.json"
    commands_path = tmp_path / "run_commands.sh"
    baseline_prompt = tmp_path / "prompts" / "billing-token-caveat__baseline.md"
    candidate_prompt = tmp_path / "prompts" / "billing-token-caveat__candidate.md"

    assert manifest["schema"] == "norman.tui.shadow-prompt-pack.v1"
    assert manifest_path.exists()
    assert overlay_path.exists()
    assert commands_path.exists()
    assert baseline_prompt.exists()
    assert candidate_prompt.exists()

    candidate_text = candidate_prompt.read_text(encoding="utf-8")
    assert "Candidate mode" in candidate_text
    assert "evidence-reference packet" in candidate_text
    assert "13,000 body tokens -> 728 reference tokens" in candidate_text
    assert "## Answer Contract" in candidate_text
    assert "Minimum response words: 28" in candidate_text
    assert "Required sections: evidence, next" in candidate_text
    assert "avoid: exact spend" in candidate_text
    assert "Do not claim exact invoice-grade spend" in candidate_text

    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    assert len(overlay["answers"]) == 2
    assert overlay["answers"][0]["context_tokens"] == 18000
    assert overlay["answers"][1]["context_tokens"] == 4600


def test_ingest_outputs_preserves_answer_context_pairing(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_shadow_pack(monkeypatch)
    manifest = module.build_pack(_sample_replay_report(), _sample_cases(), tmp_path)
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "ingested.json"

    for entry in manifest["entries"]:
        Path(entry["answer_path"]).write_text(
            f"{entry['label']} answer with billing_owner and normalizer.",
            encoding="utf-8",
        )

    overlay = module.ingest_outputs(manifest_path, output_path)

    assert output_path.exists()
    assert overlay["missing_answer_files"] == []
    assert len(overlay["answers"]) == 2
    by_label = {item["label"]: item for item in overlay["answers"]}
    assert by_label["baseline"]["context_tokens"] == 18000
    assert by_label["candidate"]["context_tokens"] == 4600
    assert "baseline answer" in by_label["baseline"]["answer"]
