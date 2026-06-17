import subprocess
from types import SimpleNamespace

import pytest

from app.services import tmux_inspector


def _proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_tmux_falls_back_to_discovered_socket(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(tmux_inspector, "tmux_available", lambda: True)
    monkeypatch.setattr(
        tmux_inspector,
        "_socket_attempts",
        lambda socket_path="": ["", "/tmp/tmux-1000/custom"],
    )

    def fake_run(cmd, capture_output, text, check, stdin=None):
        assert stdin == subprocess.DEVNULL
        calls.append(cmd)
        if cmd[:3] == ["tmux", "-S", "/tmp/tmux-1000/custom"]:
            return _proc(returncode=0, stdout="ok")
        return _proc(returncode=1, stderr="no server running")

    monkeypatch.setattr(subprocess, "run", fake_run)

    proc = tmux_inspector._run_tmux("list-sessions")
    assert proc.returncode == 0
    assert calls[0] == ["tmux", "list-sessions"]
    assert calls[1] == ["tmux", "-S", "/tmp/tmux-1000/custom", "list-sessions"]


def test_run_tmux_raises_called_process_error_when_check_enabled(monkeypatch) -> None:
    monkeypatch.setattr(tmux_inspector, "tmux_available", lambda: True)
    monkeypatch.setattr(tmux_inspector, "_socket_attempts", lambda socket_path="": [""])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, capture_output, text, check, stdin=None: _proc(
            returncode=1, stderr="error connecting to socket"
        ),
    )

    with pytest.raises(subprocess.CalledProcessError):
        tmux_inspector._run_tmux("list-sessions", check=True)


def test_socket_attempts_include_tmux_env_socket(monkeypatch) -> None:
    monkeypatch.setattr(tmux_inspector, "_LAST_WORKING_SOCKET", "")
    monkeypatch.setattr(tmux_inspector, "_discover_socket_paths", lambda: [])
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/custom,123,0")
    monkeypatch.delenv("TMUX_SOCKET_PATH", raising=False)

    attempts = tmux_inspector._socket_attempts("")
    assert "/tmp/tmux-1000/custom" in attempts
