from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_lint(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "route_policy_drift_lint",
        scripts_dir / "route_policy_drift_lint.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["route_policy_drift_lint"] = module
    spec.loader.exec_module(module)
    return module


def test_route_policy_drift_lint_flags_old_five_five_default(tmp_path, monkeypatch):
    module = _load_lint(monkeypatch)
    sample = tmp_path / "provider_readiness.md"
    sample.write_text(
        "Bedrock Codex 5.5 is the desired default for work-special.\n",
        encoding="utf-8",
    )

    report = module.build_report([sample], root=tmp_path)

    assert report["status"] == "fail"
    assert report["codex_role_policy"]["policy_id"]
    assert report["cloud_default_model"] == "openai.gpt-5.4"
    assert report["final_authority_model"] == "openai.gpt-5.5"
    assert report["error_count"] == 1
    assert report["issues"][0]["rule_id"] == "five_five_desired_default"


def test_route_policy_drift_lint_accepts_five_four_first_policy(tmp_path, monkeypatch):
    module = _load_lint(monkeypatch)
    sample = tmp_path / "route_policy.md"
    sample.write_text(
        "GPT-5.4 planner/verifier by default. "
        "GPT-5.5 final authority only when evidence gates fail.\n",
        encoding="utf-8",
    )

    report = module.build_report([sample], root=tmp_path)

    assert report["status"] == "pass"
    assert report["issues"] == []
