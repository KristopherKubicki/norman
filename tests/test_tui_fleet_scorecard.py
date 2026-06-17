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

    assert module.DEFAULT_HEADSCALE_RESOLVER == "100.64.0.5"
    assert module.DEFAULT_TAILSCALE_RESOLVER == "100.100.100.100"
    assert module.DEFAULT_RESOLVER_PROFILE == "tailscale"
    assert module.RESOLVER_PROFILES == {
        "headscale": "100.64.0.5",
        "tailscale": "100.100.100.100",
    }
    assert module.FRONTDOOR_PROFILES == {
        "headscale": "192.168.2.241",
        "tailscale": "100.103.34.17",
    }

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

    assert {item.slug for item in items} == {"active-game", "ops"}


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
        (
            "Console - Publisher",
            "tmux:publisher",
            {
                "collector_url": "http://publisher.local:8788/",
                "session": "publisher",
                "target": "publisher:0.0",
            },
        ),
        (
            "Console - Subprime",
            "tmux:norman-bot-prime",
            {
                "collector_url": "http://subprime.local:8788/",
                "session": "subprime",
                "target": "subprime:0.0",
            },
        ),
        (
            "Console - Switchboard",
            "tmux:switchboard",
            {
                "collector_url": "http://switchboard.local:8788/",
                "session": "switchboard",
                "target": "switchboard:0.0",
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


def test_console_link_token_paths_use_active_home_and_env_override(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_scorecard(monkeypatch)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("NORMAN_CONSOLE_LINK_PATHS", raising=False)

    paths = module.console_link_token_paths()

    assert paths[0] == home / ".codex-work" / "web-bridge" / "console_links.json"
    assert paths[1] == home / ".codex-bot-prime" / "web-bridge" / "console_links.json"
    assert module.DEFAULT_OPERATOR_CONSOLE_LINK_PATHS[0] in paths

    override_a = tmp_path / "a.json"
    override_b = tmp_path / "b.json"
    monkeypatch.setenv(
        "NORMAN_CONSOLE_LINK_PATHS",
        f"{override_a}{module.os.pathsep}{override_b}",
    )

    assert module.console_link_token_paths() == [override_a, override_b]


def test_load_tokens_from_console_links_indexes_all_console_url_shapes(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_scorecard(monkeypatch)
    path = tmp_path / "console_links.json"
    path.write_text(
        json.dumps(
            {
                "links": [
                    {
                        "url": "https://phone.home.arpa/?token=phone-token",
                        "lan_url": "http://192.168.2.146:8790/?token=lan-token",
                        "tailnet_url": "https://phone.tail.ts.net/?token=tail-token",
                    },
                    {
                        "url": "https://missing-token.home.arpa/",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    tokens = module._load_tokens_from_console_links([path])

    assert tokens["phone.home.arpa"] == "phone-token"
    assert tokens["192.168.2.146:8790"] == "lan-token"
    assert tokens["phone.tail.ts.net"] == "tail-token"
    assert "missing-token.home.arpa" not in tokens


def test_check_authenticated_status_uses_visible_status_without_token(
    monkeypatch,
) -> None:
    module = _load_scorecard(monkeypatch)
    item = module.FleetItem(
        slug="studio",
        label="Camera Studio",
        source="registry",
        collector_url="http://studio.local:8795/",
    )
    monkeypatch.setattr(
        module,
        "fetch_console_status",
        lambda *args, **kwargs: {"reachable": True, "state": "ok"},
    )

    result, status = module.check_authenticated_status(item)

    assert result.ok is True
    assert result.score == 12
    assert result.status == "visible-no-token"
    assert status["state"] == "ok"


def test_check_authenticated_status_still_reports_missing_when_no_token_unreachable(
    monkeypatch,
) -> None:
    module = _load_scorecard(monkeypatch)
    item = module.FleetItem(
        slug="studio",
        label="Camera Studio",
        source="registry",
        collector_url="http://studio.local:8795/",
    )
    monkeypatch.setattr(
        module,
        "fetch_console_status",
        lambda *args, **kwargs: {"reachable": False},
    )

    result, status = module.check_authenticated_status(item)

    assert result.ok is False
    assert result.score == 0
    assert result.status == "missing-token"
    assert status == {}


def test_scorecard_surfaces_drift_and_usage_signals(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_scorecard(monkeypatch)
    item = module.FleetItem(
        slug="control-plane",
        label="Control Plane",
        source="registry",
        collector_url="http://control-plane.local:8788/",
        web_url="https://cp.kris.openbrand.com/",
        token="demo-token",
        route_hosts=[],
    )
    status = {
        "reachable": True,
        "state": "ok",
        "pending": False,
        "queue_depth": 0,
        "last_error": "",
        "drift_assessment": {
            "enabled": True,
            "tone": "alert",
            "summary": "Power checkpoint",
            "mission_drift": "cross_lane",
            "context_drift": "possibly_stale",
            "scope_drift": "over_budget",
            "power_drift": ["key", "sword"],
        },
        "usage": {
            "last_24h": {"total_tokens": 250_000, "turns": 4},
            "current_thread": {"total_tokens": 180_000, "turns": 2},
            "billing": {
                "sparkline": [10_000, 40_000, 250_000],
                "tag_health": {"state": "ok"},
                "last_24h_estimate": {"configured": False},
            },
        },
    }

    monkeypatch.setattr(
        module,
        "check_collector",
        lambda item: module.CheckResult(True, 20, 20, "ok", "200"),
    )
    monkeypatch.setattr(
        module,
        "check_authenticated_status",
        lambda item: (
            module.CheckResult(True, 20, 20, "ok", "ok"),
            status,
        ),
    )
    monkeypatch.setattr(
        module,
        "check_frontdoor",
        lambda item: module.CheckResult(True, 15, 15, "ok", "200"),
    )
    monkeypatch.setattr(
        module,
        "check_dns",
        lambda item, expected, resolver: module.CheckResult(True, 15, 15, "ok", "ok"),
    )
    monkeypatch.setattr(
        module,
        "check_persistence",
        lambda item, path: module.CheckResult(True, 10, 10, "ok", "ok"),
    )

    row = module.score_item(item, {}, "100.100.100.100", tmp_path / "hosts.caddy")
    markdown = module.render_markdown([row])

    assert row.drift.status == "alert"
    assert "mission=cross lane" in row.drift.detail
    assert "power=key+sword" in row.drift.detail
    assert row.usage.status == "alert"
    assert "250K tok" in row.usage.detail
    assert "burn=" in row.usage.detail
    assert "| Score | Grade | TUI | Runtime | Drift | Tokens |" in markdown
    assert "drift: Power checkpoint" in markdown
    assert "usage: 250K tok" in markdown
