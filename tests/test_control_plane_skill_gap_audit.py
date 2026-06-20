from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_modules(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))

    benchmark_spec = importlib.util.spec_from_file_location(
        "work_domain_skill_benchmark",
        scripts_dir / "work_domain_skill_benchmark.py",
    )
    assert benchmark_spec and benchmark_spec.loader
    benchmark = importlib.util.module_from_spec(benchmark_spec)
    sys.modules["work_domain_skill_benchmark"] = benchmark
    benchmark_spec.loader.exec_module(benchmark)

    audit_spec = importlib.util.spec_from_file_location(
        "control_plane_skill_gap_audit",
        scripts_dir / "control_plane_skill_gap_audit.py",
    )
    assert audit_spec and audit_spec.loader
    audit = importlib.util.module_from_spec(audit_spec)
    sys.modules["control_plane_skill_gap_audit"] = audit
    audit_spec.loader.exec_module(audit)
    return benchmark, audit


def _write_fake_control_plane(root: Path) -> None:
    scripts = root / "scripts"
    runbooks = root / "runbooks"
    docs = root / "docs"
    scripts.mkdir(parents=True)
    runbooks.mkdir()
    docs.mkdir()

    for name in (
        "runbook_runner.py",
        "ticket_turnkey.py",
        "apply_gaphelp_4041_webgoat_cleanup.py",
        "apply_gapi_exact_url_site_id_backfill.py",
        "provider_contract_audit.py",
    ):
        (scripts / name).write_text("# fixture\n")
    for index in range(90):
        (scripts / f"apply_receipt_repair_{index:03}.py").write_text("# fixture\n")

    (runbooks / "MP_missing_price.md").write_text("# MP\n")
    (runbooks / "AAE_agentic_access_enablement.md").write_text("# AAE\n")
    (docs / "runbook_catalog.md").write_text(
        "\n".join(
            [
                "- MP: Missing Price",
                "- AAE: Agentic Access Enablement",
                "- CFS: Category Fill Status",
            ]
        )
    )
    (docs / "script_catalog.md").write_text(
        "- `scripts/runbook_runner.py`\n- `scripts/provider_contract_audit.py`\n"
    )


def test_control_plane_skill_gap_audit_reports_runbook_and_operation_coverage(
    monkeypatch,
    tmp_path,
) -> None:
    benchmark, audit = _load_modules(monkeypatch)
    mirror_root = tmp_path / "control_plane"
    _write_fake_control_plane(mirror_root)

    report = audit.build_gap_report(
        mirror_root=mirror_root,
        benchmark_report=benchmark.build_report(),
    )

    assert report["schema"] == "norman.control-plane-skill-gap-audit.v1"
    assert report["dry_run_only"] is True
    assert report["model_calls_executed"] == 0
    assert report["script_count"] == 95
    assert report["runbook_coverage"]["coverage_rate"] == 1.0
    assert report["runbook_coverage"]["missing_runbook_ids"] == []
    assert report["missing_basic_operations"] == []

    groups = {row["group_id"]: row for row in report["groups"]}
    assert groups["core_runbook_control"]["coverage_status"] == "covered"
    assert groups["instore_panelbot_receipts"]["coverage_status"] == (
        "covered_but_too_coarse"
    )
    assert "instore_panelbot_receipts" in report["high_gap_group_ids"]
    assert groups["instore_panelbot_receipts"]["script_count"] == 90
    assert groups["instore_panelbot_receipts"]["benchmark_skill_count"] > 0


def test_control_plane_skill_gap_audit_writes_json_and_markdown(
    monkeypatch,
    tmp_path,
) -> None:
    benchmark, audit = _load_modules(monkeypatch)
    mirror_root = tmp_path / "control_plane"
    _write_fake_control_plane(mirror_root)
    output_json = tmp_path / "gap.json"
    output_md = tmp_path / "gap.md"

    report = audit.build_gap_report(
        mirror_root=mirror_root,
        benchmark_report=benchmark.build_report(),
    )
    audit.write_report(report, output_json, output_md)

    data = json.loads(output_json.read_text())
    markdown = output_md.read_text()
    assert data["schema"] == "norman.control-plane-skill-gap-audit.v1"
    assert data["summary"]["verdict"] == "not_exhausted"
    assert "Control Plane Skill Gap Audit" in markdown
    assert "Runbook coverage: 3 / 3 (100.0%)" in markdown
    assert "covered_but_too_coarse" in markdown
