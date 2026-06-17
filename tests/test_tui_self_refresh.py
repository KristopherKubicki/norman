from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_tui_self_refresh():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "tui_self_refresh.py"
    )
    spec = importlib.util.spec_from_file_location("tui_self_refresh", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_sync_command_targets_web_only_force_when_consented() -> None:
    module = _load_tui_self_refresh()

    command = module.build_sync_command(Path("/repo"), "norman-codex", force=True)

    assert command == [
        "/repo/.venv/bin/python",
        "/repo/scripts/sync_agent_console_template.py",
        "--targets",
        "norman",
        "--restart-web-only",
        "--force-restart",
    ]


def test_forced_refresh_requires_operator_cutoff_consent() -> None:
    module = _load_tui_self_refresh()
    args = module.parse_args(
        [
            "--repo-root",
            "/repo",
            "--target",
            "norman",
            "--force",
            "--dry-run",
        ]
    )

    assert module.run_refresh(args) == 2


def test_guarded_dry_run_does_not_require_cutoff_consent(capsys) -> None:
    module = _load_tui_self_refresh()
    args = module.parse_args(
        [
            "--repo-root",
            "/repo",
            "--target",
            "panel-bot",
            "--dry-run",
        ]
    )

    assert module.run_refresh(args) == 0
    assert "--targets panelbot --restart-web-only" in capsys.readouterr().out
