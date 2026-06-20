from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path


def _load_builder(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "build_norman_harness_pro_agent_pack",
        scripts_dir / "build_norman_harness_pro_agent_pack.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_norman_harness_pro_agent_pack"] = module
    spec.loader.exec_module(module)
    return module


def test_pack_builder_includes_replay_dependencies_and_fixture(tmp_path, monkeypatch):
    module = _load_builder(monkeypatch)
    pack_dir = tmp_path / "pack"
    zip_path = tmp_path / "pack.zip"

    result = module.build_pack(
        pack_dir,
        zip_path=zip_path,
        include_reports=False,
        source_prompt=None,
        python=sys.executable,
        evidence_root=tmp_path / "missing-evidence",
    )

    assert result["zip_path"] == str(zip_path)
    assert (pack_dir / "code/scripts/norman_codex_web.py").exists()
    assert (
        pack_dir / "code/scripts/agent_console_template/agent_console_web.py"
    ).exists()
    assert (pack_dir / "code/tests/test_norman_codex_model_settings.py").exists()
    assert (pack_dir / "code/scripts/gaphelp_ticket_loop_shadow.py").exists()
    assert (pack_dir / "code/scripts/ticket_token_cost_ledger.py").exists()
    assert (pack_dir / "code/scripts/route_policy_drift_lint.py").exists()
    assert (pack_dir / "code/scripts/runbook_hybrid_architecture_audit.py").exists()
    assert (pack_dir / "code/scripts/tui_bedrock_shortstop_benchmark.py").exists()
    assert (pack_dir / "code/scripts/local_model_skill_floor.py").exists()
    assert (pack_dir / "code/scripts/bbs_janitor.py").exists()
    assert (pack_dir / "code/tests/test_tui_bedrock_shortstop_benchmark.py").exists()
    assert (pack_dir / "code/tests/test_local_model_skill_floor.py").exists()
    assert (
        pack_dir / "code/scripts/agent_console_template/prompts/control-plane.txt"
    ).exists()
    assert (pack_dir / "code/app/static/js/messages_log.js").exists()
    assert (pack_dir / "code/app/templates/messages_log.html").exists()
    assert (pack_dir / "data/fixtures/paired_hybrid_replay_cases.json").exists()
    assert (pack_dir / "brief/ROUTE_POLICY.json").exists()
    assert (pack_dir / "brief/LIVE_HANDOFF.md").exists()
    assert (pack_dir / "brief/FAILURE_PACKET.md").exists()
    assert (pack_dir / "SHA256SUMS.txt").exists()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "pack/code/scripts/ticket_token_cost_ledger.py" in names
    assert "pack/code/scripts/runbook_hybrid_architecture_audit.py" in names
    assert "pack/code/scripts/tui_bedrock_shortstop_benchmark.py" in names
    assert "pack/code/scripts/local_model_skill_floor.py" in names
    assert "pack/code/scripts/agent_console_template/prompts/control-plane.txt" in names
    assert "pack/code/tests/test_tui_bedrock_shortstop_benchmark.py" in names
    assert "pack/code/tests/test_local_model_skill_floor.py" in names
    assert "pack/code/app/static/js/messages_log.js" in names
    assert "pack/data/fixtures/paired_hybrid_replay_cases.json" in names


def test_pack_builder_includes_live_evidence_when_present(tmp_path, monkeypatch):
    module = _load_builder(monkeypatch)
    evidence_root = tmp_path / "evidence"
    receipt_dir = evidence_root / "route_receipts"
    receipt_dir.mkdir(parents=True)
    (evidence_root / "tui_cutover_readiness.json").write_text(
        """
        {
          "readiness": "not_ready_for_cutover",
          "summary": {
            "receipt_count": 1,
            "route_receipt_chain_issue_count": 0,
            "ready_target_count": 0,
            "blocked_target_count": 3,
            "historic_route_benchmark_gate": "pass"
          },
          "targets": [
            {
              "owner_tui": "market-sizing",
              "blockers": ["needs at least 50 route receipts; found 1"],
              "next_actions": ["collect 49 more live shadow route receipts"],
              "metrics": {
                "receipt_count": 1,
                "validator_pass_rate": 1
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    (evidence_root / "tui_cutover_readiness.md").write_text(
        "# Cutover\n",
        encoding="utf-8",
    )
    (evidence_root / "ollama_sense_live.json").write_text(
        '{"schema":"norman.tui.ollama-sense.v1","endpoints":[]}\n',
        encoding="utf-8",
    )
    (evidence_root / "ollama_sense_live.md").write_text(
        "# TUI Ollama Sense\n",
        encoding="utf-8",
    )
    (receipt_dir / "market-sizing.jsonl").write_text(
        (
            '{"owner_tui":"market-sizing","operator_intent_class":"status",'
            '"authority_class":"read_only","mutation_risk":"none",'
            '"requested_model":"gpt-5.4","effective_model":"gpt-5.4",'
            '"requested_service_tier":"default","effective_service_tier":"default",'
            '"validator_gate":"pass","receipt_hash":"abcd1234efgh5678"}\n'
        ),
        encoding="utf-8",
    )

    pack_dir = tmp_path / "pack"
    result = module.build_pack(
        pack_dir,
        zip_path=None,
        include_reports=False,
        source_prompt=None,
        python=sys.executable,
        evidence_root=evidence_root,
    )

    assert result["evidence_root"] == str(evidence_root)
    assert (pack_dir / "live_evidence/tui_cutover_readiness.json").exists()
    assert (pack_dir / "live_evidence/tui_cutover_readiness.md").exists()
    assert (pack_dir / "live_evidence/ollama_sense_live.json").exists()
    assert (pack_dir / "live_evidence/ollama_sense_live.md").exists()
    assert (pack_dir / "live_evidence/route_receipts/market-sizing.jsonl").exists()
    handoff = (pack_dir / "brief/LIVE_HANDOFF.md").read_text(encoding="utf-8")
    assert "Receipt count: 1" in handoff
    assert "Effective model: gpt-5.4" in handoff
    assert "Receipt hash prefix: abcd1234efgh5678" in handoff


def test_pack_builder_includes_old_failure_packet_without_raw_logs(
    tmp_path, monkeypatch
):
    module = _load_builder(monkeypatch)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(parents=True)
    (evidence_root / "bedrock_shortstop_codex_work_168h.json").write_text(
        """
        {
          "schema": "norman.tui.bedrock-shortstop-benchmark.v1",
          "summary": {
            "turns": 628,
            "categories": {
              "low_yield": 214,
              "short_stop": 224,
              "useful_or_unclassified": 145
            },
            "mechanisms": {
              "future_work_promise": 224,
              "thin_output": 214
            },
            "tuis": [
              {
                "tui": "codex-work",
                "turns": 628,
                "output_token_pct": 0.244,
                "categories": {
                  "low_yield": 214,
                  "short_stop": 224
                },
                "mechanisms": {
                  "future_work_promise": 224,
                  "thin_output": 214
                }
              }
            ]
          },
          "examples": [
            {
              "category": "short_stop",
              "model": "gpt-5.5",
              "duration_seconds": 14,
              "prompt_preview": "do not include this raw prompt in the packet",
              "reasons": [
                "final response promises future work",
                "fast return: 14s"
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    (evidence_root / "bedrock_shortstop_codex_work_168h.md").write_text(
        "# TUI Bedrock Short-Stop Benchmark\n",
        encoding="utf-8",
    )

    pack_dir = tmp_path / "pack"
    module.build_pack(
        pack_dir,
        zip_path=None,
        include_reports=False,
        source_prompt=None,
        python=sys.executable,
        evidence_root=evidence_root,
    )

    packet = (pack_dir / "brief/FAILURE_PACKET.md").read_text(encoding="utf-8")
    assert "turns=628" in packet
    assert "low_yield=214" in packet
    assert "short_stop=224" in packet
    assert "future_work_promise=224" in packet
    assert "thin_output=214" in packet
    assert "final response promises future work" in packet
    assert "do not include this raw prompt" not in packet
    assert (
        pack_dir / "live_evidence/old_failures/bedrock_shortstop_codex_work_168h.md"
    ).exists()
    assert not (
        pack_dir / "live_evidence/old_failures/bedrock_shortstop_codex_work_168h.json"
    ).exists()
