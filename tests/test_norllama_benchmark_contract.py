import importlib.util
import sys
from pathlib import Path


def _load_module():
    script = Path("scripts/norllama_benchmark_contract.py")
    spec = importlib.util.spec_from_file_location("norllama_benchmark_contract", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["norllama_benchmark_contract"] = module
    spec.loader.exec_module(module)
    return module


def _packet() -> dict:
    return {
        "schema": "norman.planner-llm-benchmark-packet.v1",
        "cases": [
            {
                "case_id": "code-1",
                "title": "Patch",
                "family": "code",
                "prompt": "Write a bounded patch.",
                "required_terms": ["test"],
            }
        ],
        "prompts": [
            {
                "prompt_id": "local::code-1",
                "case_id": "code-1",
                "candidate_id": "local",
                "model": "gpt-oss:120b",
                "provider_surface": "local-dgx-spark",
                "service_tier": "local",
                "input_tokens": 20,
                "expected_output_tokens": 10,
            }
        ],
        "promotion_policy": {},
        "precision_policy": {},
    }


def test_manifest_changes_when_benchmark_semantics_change() -> None:
    module = _load_module()
    first = module.build_suite_manifest(
        packet=_packet(),
        suite_id="packet_188_full",
        profile={"name": "gptoss120_local_board", "model": "gpt-oss:120b"},
        scorer_version="v2",
    )
    changed = _packet()
    changed["cases"][0]["prompt"] = "Write a different bounded patch."
    second = module.build_suite_manifest(
        packet=changed,
        suite_id="packet_188_full",
        profile={"name": "gptoss120_local_board", "model": "gpt-oss:120b"},
        scorer_version="v2",
    )

    assert first["manifest_hash"] != second["manifest_hash"]
    assert first["cases"][0]["case_hash"] != second["cases"][0]["case_hash"]


def test_transport_failure_remains_retryable_and_receipts_are_immutable(
    tmp_path: Path,
) -> None:
    module = _load_module()
    manifest = module.build_suite_manifest(
        packet=_packet(),
        suite_id="packet_188_full",
        profile={"name": "gptoss120_local_board", "model": "gpt-oss:120b"},
        scorer_version="v2",
    )
    row = module.prepare_answer_row(
        {"prompt_id": "local::code-1", "case_id": "code-1"},
        manifest=manifest,
    )
    assert row["execution_state"] == "pending"
    row.update({"error": "Read timed out", "attempt_count": 1})
    row["execution_state"] = module.answer_state(row)
    assert row["execution_state"] == "retryable"
    first = module.write_case_receipt(
        receipts_root=tmp_path,
        manifest=manifest,
        row=row,
        event="transport_failure",
    )
    second = module.write_case_receipt(
        receipts_root=tmp_path,
        manifest=manifest,
        row=row,
        event="transport_failure",
    )
    assert first != second
    assert first.exists() and second.exists()


def test_manifest_mismatch_does_not_reuse_old_answer() -> None:
    module = _load_module()
    manifest = module.build_suite_manifest(
        packet=_packet(),
        suite_id="packet_188_full",
        profile={"name": "gptoss120_local_board", "model": "gpt-oss:120b"},
        scorer_version="v2",
    )
    stale = {
        "prompt_id": "local::code-1",
        "case_id": "code-1",
        "answer": "old answer",
        "case_hash": "wrong",
        "suite_manifest_hash": "wrong",
    }
    prepared = module.prepare_answer_row(stale, manifest=manifest)
    assert prepared["answer"] == ""
    assert prepared["attempt_count"] == 0


def test_legacy_row_is_migrated_without_losing_a_completed_answer() -> None:
    module = _load_module()
    manifest = module.build_suite_manifest(
        packet=_packet(),
        suite_id="packet_188_full",
        profile={"name": "gptoss120_local_board", "model": "gpt-oss:120b"},
        scorer_version="v2",
    )
    prepared = module.prepare_answer_row(
        {
            "prompt_id": "local::code-1",
            "case_id": "code-1",
            "answer": "completed before the receipt contract",
        },
        manifest=manifest,
    )

    assert prepared["answer"]
    assert prepared["contract_migrated_from_legacy"] is True
