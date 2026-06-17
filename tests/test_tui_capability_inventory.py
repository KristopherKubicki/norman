from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_inventory(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "tui_capability_inventory", scripts_dir / "tui_capability_inventory.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_capability_inventory"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_inventory_surfaces_actor_skills_and_runbooks(monkeypatch, tmp_path):
    module = _load_inventory(monkeypatch)
    actors_dir = tmp_path / "actors"
    prompts_dir = tmp_path / "prompts"
    docs_dir = tmp_path / "docs"
    actor_dir = actors_dir / "control-plane"
    actor_dir.mkdir(parents=True)
    prompts_dir.mkdir()
    docs_dir.mkdir()
    (actor_dir / "SOUL.md").write_text(
        """# Control Plane

Actor ID: control-plane

## Role

- Maintain control-plane visibility.
- Coordinate runbook cleanup.

## Operating Principles

- Prefer registry-backed facts.

## Memory Policy

- Durable facts belong in runbooks.
""",
        encoding="utf-8",
    )
    (prompts_dir / "control-plane.txt").write_text(
        "Mission: improve workflow skills and runbook evidence.", encoding="utf-8"
    )
    (docs_dir / "control_plane_runbook.md").write_text(
        "Control Plane runbook for workflow repair.", encoding="utf-8"
    )

    report = module.build_inventory(
        actors_dir=actors_dir,
        prompts_dir=prompts_dir,
        docs_dir=docs_dir,
    )

    assert report["summary"]["actors"] == 1
    assert report["summary"]["actors_with_prompt_files"] == 1
    row = report["rows"][0]
    assert row["slug"] == "control-plane"
    assert row["actor_id"] == "control-plane"
    assert row["declared_skill_count"] == 3
    assert row["skill_ref_count"] >= 1
    assert row["runbook_ref_count"] >= 2
    assert "control_plane_runbook.md" in " ".join(row["runbook_refs"])


def test_render_markdown_includes_inventory_counts(monkeypatch):
    module = _load_inventory(monkeypatch)

    markdown = module.render_markdown(
        {
            "summary": {
                "actors": 1,
                "actors_with_prompt_files": 1,
                "actors_with_declared_skills": 1,
                "actors_with_skill_refs": 1,
                "actors_with_runbook_refs": 1,
            },
            "rows": [
                {
                    "slug": "control-plane",
                    "prompt_path": "scripts/agent_console_template/prompts/control-plane.txt",
                    "declared_skill_count": 3,
                    "skill_ref_count": 1,
                    "runbook_ref_count": 2,
                    "declared_skills": ["Maintain control-plane visibility."],
                    "runbook_refs": ["Durable facts belong in runbooks."],
                }
            ],
        }
    )

    assert "# TUI Capability Inventory" in markdown
    assert "Actors with runbook refs: 1" in markdown
    assert "| control-plane | yes | 3 | 1 | 2 |" in markdown
