from __future__ import annotations

from types import SimpleNamespace
import uuid

from app.models.connectors import Connector
from app.models.user import User
from app.services import tmux_reconciler


def _proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _seed_tmux_connector(db, name: str = "tmux:castle") -> Connector:
    token = uuid.uuid4().hex[:8]
    user = User(
        username=f"{name}-user-{token}",
        email=f"{name}-{token}@example.com",
        password="x",
        is_superuser=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    connector = Connector(
        name=name,
        connector_type="tmux",
        user_id=user.id,
        config={"session": "castle", "target": "castle:0.0"},
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return connector


def test_reconcile_bootstraps_tmux_session_when_command_not_running(
    db, monkeypatch, tmp_path
):
    project_dir = tmp_path / "castle"
    project_dir.mkdir()
    expected = "codex resume 019c63f3-c28f-7072-810c-4b252b2de81f"
    (project_dir / ".session").write_text(expected + "\n", encoding="utf-8")

    connector = _seed_tmux_connector(db)

    monkeypatch.setattr(tmux_reconciler.shutil, "which", lambda name: "/usr/bin/tmux")
    calls = []
    state = {"has_session": False}

    def fake_run(*args: str, check: bool = False):
        calls.append(args)
        if args[0] == "has-session":
            return _proc(returncode=0 if state["has_session"] else 1)
        if args[0] == "new-session":
            state["has_session"] = True
            return _proc(returncode=0)
        if args[0] == "display-message" and args[-1] == "#{pane_id}":
            return _proc(returncode=0, stdout="%1\n")
        if args[0] == "display-message" and args[-1] == "#{pane_pid}":
            return _proc(returncode=0, stdout="123\n")
        if args[0] == "send-keys":
            return _proc(returncode=0)
        raise AssertionError(f"Unexpected tmux args: {args}")

    monkeypatch.setattr(tmux_reconciler, "_run_tmux", fake_run)
    monkeypatch.setattr(tmux_reconciler, "_pane_child_command", lambda target: "")

    summary = tmux_reconciler.reconcile_tmux_connectors(
        db,
        projects_root=tmp_path,
        connector_ids=[connector.id],
    )
    db.refresh(connector)

    assert summary["connectors_seen"] == 1
    assert summary["connectors_updated"] == 1
    assert summary["sessions_started"] == 1
    assert summary["commands_started"] == 1
    assert summary["commands_already_running"] == 0
    assert summary["errors"] == 0
    assert connector.config["working_dir"] == str(project_dir)
    assert connector.config["session_bootstrap"] == expected

    launch_calls = [
        args for args in calls if args[:4] == ("send-keys", "-t", "castle:0.0", "-l")
    ]
    assert any(args[4] == f"cd {project_dir} && {expected}" for args in launch_calls)


def test_reconcile_skips_launch_when_expected_command_already_running(
    db, monkeypatch, tmp_path
):
    project_dir = tmp_path / "castle"
    project_dir.mkdir()
    expected = "codex resume 019c63f3-c28f-7072-810c-4b252b2de81f"
    (project_dir / ".session").write_text(expected + "\n", encoding="utf-8")

    connector = _seed_tmux_connector(db)

    monkeypatch.setattr(tmux_reconciler.shutil, "which", lambda name: "/usr/bin/tmux")
    calls = []

    def fake_run(*args: str, check: bool = False):
        calls.append(args)
        if args[0] == "has-session":
            return _proc(returncode=0)
        if args[0] == "display-message" and args[-1] == "#{pane_id}":
            return _proc(returncode=0, stdout="%1\n")
        if args[0] == "display-message" and args[-1] == "#{pane_pid}":
            return _proc(returncode=0, stdout="123\n")
        if args[0] == "send-keys":
            return _proc(returncode=0)
        raise AssertionError(f"Unexpected tmux args: {args}")

    monkeypatch.setattr(tmux_reconciler, "_run_tmux", fake_run)
    monkeypatch.setattr(
        tmux_reconciler,
        "_pane_child_command",
        lambda target: (
            "node /home/kristopher/.nvm/versions/node/v20.19.6/bin/" f"{expected}"
        ),
    )

    summary = tmux_reconciler.reconcile_tmux_connectors(
        db,
        projects_root=tmp_path,
        connector_ids=[connector.id],
    )
    db.refresh(connector)

    assert summary["connectors_seen"] == 1
    assert summary["connectors_updated"] == 1
    assert summary["sessions_started"] == 0
    assert summary["commands_started"] == 0
    assert summary["commands_already_running"] == 1
    assert summary["errors"] == 0
    assert connector.config["working_dir"] == str(project_dir)
    assert connector.config["session_bootstrap"] == expected

    launch_calls = [args for args in calls if args and args[0] == "send-keys"]
    assert not launch_calls


def test_reconcile_skips_when_tmux_binary_missing(db, monkeypatch):
    connector = _seed_tmux_connector(db)
    monkeypatch.setattr(tmux_reconciler.shutil, "which", lambda name: None)

    summary = tmux_reconciler.reconcile_tmux_connectors(
        db,
        connector_ids=[connector.id],
    )

    assert summary["connectors_seen"] == 0
    assert summary["skipped_tmux_unavailable"] == 1
