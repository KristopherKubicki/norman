import asyncio
import shutil
import subprocess

from app.connectors.tmux_connector import TmuxConnector


class DummyCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_send_message_uses_target_and_enter(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[1] == "capture-pane":
            return DummyCompleted(stdout="shell prompt")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="ops", target="ops:1.2")
    result = connector.send_message("echo hello")

    assert result["status"] == "sent"
    assert result["target"] == "ops:1.2"
    assert calls == [
        ["tmux", "capture-pane", "-p", "-J", "-t", "ops:1.2", "-S", "-24"],
        ["tmux", "send-keys", "-t", "ops:1.2", "-l", "echo hello"],
        ["tmux", "send-keys", "-t", "ops:1.2", "C-m"],
    ]


def test_send_message_honors_enter_count_payload(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[1] == "capture-pane":
            return DummyCompleted(stdout="shell prompt")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="ops", target="ops:1.2")
    result = connector.send_message({"command": "echo hello", "enter_count": 2})

    assert result["status"] == "sent"
    assert result["target"] == "ops:1.2"
    assert calls == [
        ["tmux", "capture-pane", "-p", "-J", "-t", "ops:1.2", "-S", "-24"],
        ["tmux", "send-keys", "-t", "ops:1.2", "-l", "echo hello"],
        ["tmux", "send-keys", "-t", "ops:1.2", "C-m"],
        ["tmux", "send-keys", "-t", "ops:1.2", "C-m"],
    ]


def test_send_message_applies_working_dir(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[1] == "capture-pane":
            return DummyCompleted(stdout="shell prompt")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="ops", working_dir="/tmp/work")
    connector.send_message({"command": "pwd"})

    assert calls == [
        ["tmux", "capture-pane", "-p", "-J", "-t", "ops:0.0", "-S", "-24"],
        ["tmux", "send-keys", "-t", "ops:0.0", "-l", "cd /tmp/work"],
        ["tmux", "send-keys", "-t", "ops:0.0", "C-m"],
        ["tmux", "send-keys", "-t", "ops:0.0", "-l", "pwd"],
        ["tmux", "send-keys", "-t", "ops:0.0", "C-m"],
    ]


def test_send_message_ignores_empty():
    connector = TmuxConnector(session="ops")
    assert connector.send_message("   ")["status"] == "ignored"


def test_is_connected_true(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        return DummyCompleted()

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="ops")
    assert connector.is_connected() is True
    assert calls == [["tmux", "has-session", "-t", "ops"]]


def test_is_connected_false_when_tmux_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    connector = TmuxConnector(session="ops")
    assert connector.is_connected() is False


def test_is_connected_false_when_session_missing(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="missing")
    assert connector.is_connected() is False


def test_send_message_resolves_target_by_pane_tty(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[1] == "list-panes":
            return DummyCompleted(
                stdout="/dev/pts/31\tplatinum_standard\t0\t0\n",
            )
        if cmd[1] == "capture-pane":
            return DummyCompleted(stdout="shell prompt")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(
        session="7",
        target="7:0.0",
        pane_tty="/dev/pts/31",
    )
    result = connector.send_message("echo hello")

    assert result["status"] == "sent"
    assert result["target"] == "platinum_standard:0.0"
    assert connector.session == "platinum_standard"
    assert connector.target == "platinum_standard:0.0"
    assert calls == [
        [
            "tmux",
            "list-panes",
            "-a",
            "-F",
            "#{pane_tty}\t#{session_name}\t#{window_index}\t#{pane_index}",
        ],
        [
            "tmux",
            "capture-pane",
            "-p",
            "-J",
            "-t",
            "platinum_standard:0.0",
            "-S",
            "-24",
        ],
        ["tmux", "send-keys", "-t", "platinum_standard:0.0", "-l", "echo hello"],
        ["tmux", "send-keys", "-t", "platinum_standard:0.0", "C-m"],
    ]


def test_send_message_auto_uses_tab_enter_for_codex_prompt(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[1] == "capture-pane":
            return DummyCompleted(stdout="... tab to queue message ...")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="ops", target="ops:1.2")
    result = connector.send_message("hello codex")

    assert result["status"] == "sent"
    assert result["submit_mode"] == "tab_enter"
    assert calls == [
        ["tmux", "capture-pane", "-p", "-J", "-t", "ops:1.2", "-S", "-24"],
        ["tmux", "send-keys", "-t", "ops:1.2", "-l", "hello codex"],
        ["tmux", "send-keys", "-t", "ops:1.2", "Tab"],
        ["tmux", "send-keys", "-t", "ops:1.2", "C-m"],
    ]


def test_send_message_auto_uses_tab_enter_for_codex_shortcuts_hint(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[1] == "capture-pane":
            return DummyCompleted(stdout="? for shortcuts")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="ops", target="ops:1.2")
    result = connector.send_message("hello codex")

    assert result["status"] == "sent"
    assert result["submit_mode"] == "tab_enter"
    assert calls == [
        ["tmux", "capture-pane", "-p", "-J", "-t", "ops:1.2", "-S", "-24"],
        ["tmux", "send-keys", "-t", "ops:1.2", "-l", "hello codex"],
        ["tmux", "send-keys", "-t", "ops:1.2", "Tab"],
        ["tmux", "send-keys", "-t", "ops:1.2", "C-m"],
    ]


def test_send_message_auto_uses_tab_enter_for_codex_context_left_hint(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[1] == "capture-pane":
            return DummyCompleted(stdout="24% context left")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="ops", target="ops:1.2")
    result = connector.send_message("hello codex")

    assert result["status"] == "sent"
    assert result["submit_mode"] == "tab_enter"
    assert calls == [
        ["tmux", "capture-pane", "-p", "-J", "-t", "ops:1.2", "-S", "-24"],
        ["tmux", "send-keys", "-t", "ops:1.2", "-l", "hello codex"],
        ["tmux", "send-keys", "-t", "ops:1.2", "Tab"],
        ["tmux", "send-keys", "-t", "ops:1.2", "C-m"],
    ]


def test_send_message_submit_mode_override_forces_enter(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[1] == "capture-pane":
            return DummyCompleted(stdout="... tab to queue message ...")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="ops", target="ops:1.2")
    result = connector.send_message(
        {"command": "echo forced", "submit_mode": "enter", "enter_count": 2}
    )

    assert result["status"] == "sent"
    assert result["submit_mode"] == "enter"
    assert calls == [
        ["tmux", "send-keys", "-t", "ops:1.2", "-l", "echo forced"],
        ["tmux", "send-keys", "-t", "ops:1.2", "C-m"],
        ["tmux", "send-keys", "-t", "ops:1.2", "C-m"],
    ]


def test_is_connected_true_with_pane_tty(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        if cmd[1] == "list-panes":
            return DummyCompleted(stdout="/dev/pts/31\tplatinum_standard\t0\t0\n")
        raise AssertionError("Unexpected tmux call")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = TmuxConnector(session="7", pane_tty="/dev/pts/31")
    assert connector.is_connected() is True


def test_process_incoming_marks_control_signal():
    connector = TmuxConnector(session="ops")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"text": "status"})
    )
    assert result["signal_class"] == "control"
    assert result["sensor_type"] == "tmux"
