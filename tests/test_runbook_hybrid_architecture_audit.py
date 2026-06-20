from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_audit_module(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "runbook_hybrid_architecture_audit",
        scripts_dir / "runbook_hybrid_architecture_audit.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["runbook_hybrid_architecture_audit"] = module
    spec.loader.exec_module(module)
    return module


def test_runbook_audit_classifies_routed_and_guarded_runbooks(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_audit_module(monkeypatch)
    root = tmp_path / "control_plane"
    runbooks = root / "runbooks"
    docs = root / "docs"
    runbooks.mkdir(parents=True)
    docs.mkdir()

    (runbooks / "README.md").write_text(
        """
# Runbooks

Routed runbooks with canonical Jira defaults in-repo:
- `MP_missing_price.md`
- `S8_stage_8_entitlement_offboarding_drift_control.md`

Mirrored Data Science playbooks (not currently routed):
- `IA_impact_analysis.md`
""",
        encoding="utf-8",
    )
    (runbooks / "MP_missing_price.md").write_text(
        """
# MP: Missing Price

Use when price rows are missing. Collect evidence, CSV counts, and public surface proof before close.
""",
        encoding="utf-8",
    )
    (runbooks / "S8_stage_8_entitlement_offboarding_drift_control.md").write_text(
        """
# S8: Stage 8 Entitlement Offboarding / Drift Control

Access, entitlement, Vanta, legal offboarding, approval, reversible deactivation, and hard delete guardrails.
""",
        encoding="utf-8",
    )
    (runbooks / "IA_impact_analysis.md").write_text(
        """
# IA: Impact Analysis

Audit rows and explain blast radius before customer-visible dashboard changes.
""",
        encoding="utf-8",
    )
    (docs / "tmi_dashboard_navigation_and_screenshot_runbook.md").write_text(
        """
# TMI Dashboard Navigation And Screenshot Runbook

Browser screenshot capture and dashboard visible-state proof for closeout evidence.
""",
        encoding="utf-8",
    )

    report = module.build_report(root)
    findings = {item["runbook_id"]: item for item in report["findings"]}

    assert report["summary"]["runbook_count"] == 4
    assert findings["MP"]["tier"] == "canonical-or-routed"
    assert findings["S8"]["complexity"] == "T4 guarded live authority"
    assert findings["S8"]["recommended_architecture"] == (
        "solo-5.5-xhigh-for-decision; hybrid-only-for-evidence"
    )
    assert findings["IA"]["tier"] == "mirrored-playbook"
    assert findings["tmi-dashboard-navigation-and-screenshot-runbook"]["tier"] == (
        "operational-support"
    )

    markdown = module.render_markdown(report)
    assert "Runbook Hybrid Architecture Audit" in markdown
    assert "MP: Missing Price" in markdown
    assert "solo-5.5-xhigh-for-decision" in markdown
