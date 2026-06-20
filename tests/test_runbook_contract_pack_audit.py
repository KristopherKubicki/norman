from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_pack_module(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "runbook_contract_pack_audit",
        scripts_dir / "runbook_contract_pack_audit.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["runbook_contract_pack_audit"] = module
    spec.loader.exec_module(module)
    return module


def test_contract_pack_audit_compacts_runbooks_and_keeps_authority_fields(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_pack_module(monkeypatch)
    root = tmp_path / "control_plane"
    runbooks = root / "runbooks"
    runbooks.mkdir(parents=True)
    (runbooks / "README.md").write_text(
        """
# Runbooks

Routed runbooks with canonical Jira defaults in-repo:
- `MP_missing_price.md`
- `S8_stage_8_entitlement_offboarding_drift_control.md`
""",
        encoding="utf-8",
    )
    repeated_detail = "\n".join(
        [
            "Collect evidence rows, CSV counts, public surface proof, status logs, and audit artifacts before close."
            for _ in range(40)
        ]
    )
    (runbooks / "MP_missing_price.md").write_text(
        f"""
# MP: Missing Price

Use when price rows are missing from merchant exports.

Allowed read checks:
- `python scripts/check_missing_price.py --dry-run`
- `sqlite3 control.sqlite 'select count(*) from prices'`

Success criteria: close only after counts, screenshots, and artifact refs are present.

{repeated_detail}
""",
        encoding="utf-8",
    )
    (runbooks / "S8_stage_8_entitlement_offboarding_drift_control.md").write_text(
        """
# S8: Stage 8 Entitlement Offboarding / Drift Control

Use when access or entitlement offboarding needs drift control.
Approval is required before any write, delete, credential, Vanta, or hard delete action.
Required evidence: owner approval, access audit rows, and reversible deactivation proof.
Success criteria: legal/offboarding checklist is complete and no irreversible action is unapproved.
""",
        encoding="utf-8",
    )

    report = module.build_report(root)
    packs = {item["runbook_id"]: item for item in report["packs"]}

    assert report["schema"] == "norman.runbook-contract-pack-audit.v1"
    assert report["summary"]["runbook_count"] == 2
    assert report["summary"]["saved_tokens"] > 0
    assert packs["MP"]["saved_pct"] > 50
    assert (
        "python scripts/check_missing_price.py --dry-run"
        in packs["MP"]["contract_pack"]["suggested_commands"]
    )
    assert packs["S8"]["contract_pack"]["complexity"] == "T4 guarded live authority"
    assert (
        "irreversible action" in packs["S8"]["contract_pack"]["blocked_worker_actions"]
    )
    assert (
        "final closeout remains owned by 5.5"
        in packs["S8"]["contract_pack"]["verifier_focus"]
    )

    markdown = module.render_markdown(report)
    assert "Runbook Contract Pack Audit" in markdown
    assert "Estimated saved tokens" in markdown
    assert "MP: Missing Price" in markdown


def test_contract_pack_cli_writes_json_and_markdown(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_pack_module(monkeypatch)
    root = tmp_path / "control_plane"
    runbooks = root / "runbooks"
    runbooks.mkdir(parents=True)
    (runbooks / "README.md").write_text("# Runbooks\n", encoding="utf-8")
    (runbooks / "OPS_queue_cleanup.md").write_text(
        """
# OPS: Queue Cleanup

Use when queue depth is high. Read status, inspect logs, collect evidence, and close when queue depth is normal.
""",
        encoding="utf-8",
    )
    output_json = tmp_path / "packs.json"
    output_md = tmp_path / "packs.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runbook_contract_pack_audit.py",
            "--mirror-root",
            str(root),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["summary"]["runbook_count"] == 1
    assert data["packs"][0]["contract_pack"]["runbook_id"] == "OPS"
    assert "Runbook Contract Pack Audit" in output_md.read_text(encoding="utf-8")
