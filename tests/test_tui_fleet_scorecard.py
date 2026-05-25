from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_scorecard(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_fleet_scorecard", scripts_dir / "tui_fleet_scorecard.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_fleet_scorecard"] = module
    spec.loader.exec_module(module)
    return module


def test_registry_loader_only_includes_tui_service_kinds(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_scorecard(monkeypatch)
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        """
services:
  - slug: app
    display_name: Plain Web App
    kind: web-app
    console_url: http://app.local:8788/
  - slug: worker
    display_name: Plain Daemon
    kind: daemon
    console_url: http://worker.local:8788/
  - slug: ops
    display_name: Ops Console
    kind: ops-console
    console_url: http://ops.local:8788/
  - slug: switchboard
    display_name: Switchboard
    kind: coordination-console
    console_url: http://switchboard.local:8788/
  - slug: active-game
    display_name: Active Game
    kind: game-tui
    console_url: http://game.local:8788/
  - slug: inactive-game
    display_name: Inactive Game
    kind: game-tui
    is_active: false
    console_url: http://inactive-game.local:8788/
""",
        encoding="utf-8",
    )

    items = module.load_registry_items(registry)

    assert {item.slug for item in items} == {"active-game", "ops", "switchboard"}


def test_db_loader_requires_explicit_web_or_collector_console(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_scorecard(monkeypatch)
    db_path = tmp_path / "norman.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        create table connectors (
            id integer primary key,
            name text,
            connector_type text,
            config text
        );
        create table channels (
            id integer primary key,
            name text,
            connector_id integer
        );
        """
    )
    rows = [
        (
            "Console - Raw Pane",
            "tmux:raw-pane",
            {"session": "raw-pane", "target": "raw-pane:0.0"},
        ),
        (
            "Console - Bot Lane",
            "tmux:bot-lane",
            {
                "collector_url": "http://bot-lane.local:8788/",
                "session": "bot-lane",
                "target": "bot-lane:0.0",
            },
        ),
        (
            "Console - Web Lane",
            "tmux:web-lane",
            {
                "session": "web-lane",
                "target": "web-lane:0.0",
                "web_url": "https://web-lane.home.arpa/",
            },
        ),
    ]
    for idx, (channel_name, connector_name, config) in enumerate(rows, start=1):
        con.execute(
            "insert into connectors (id, name, connector_type, config) values (?, ?, 'tmux', ?)",
            (idx, connector_name, json.dumps(config)),
        )
        con.execute(
            "insert into channels (id, name, connector_id) values (?, ?, ?)",
            (idx, channel_name, idx),
        )
    con.commit()
    con.close()

    items = module.load_db_items(db_path)

    assert {item.slug for item in items} == {"bot-lane", "web-lane"}
