"""Exercise terminal cleanup with isolated PTYs; never launch a real session."""

import errno
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import termios
import time

import pytest

from scripts import codex_terminal_guard as guard

SCRIPT = Path(guard.__file__)


def start_client(code, command=None, overrides=None):
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    environment = dict(os.environ)
    environment.update(overrides or {})
    environment.pop(guard.MARKER, None)
    process = subprocess.Popen(
        command or [sys.executable, str(SCRIPT), "--", sys.executable, "-c", code],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        env=environment,
    )
    return process, master, slave, original


def read_until(master, marker, timeout=5):
    output = b""
    deadline = time.monotonic() + timeout
    while marker not in output and time.monotonic() < deadline:
        if select.select([master], [], [], 0.1)[0]:
            try:
                chunk = os.read(master, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            output += chunk
    assert marker in output, output
    return output


def cleanup(process, master, slave):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    os.close(master)
    os.close(slave)


@pytest.mark.parametrize(
    "ending,expected",
    [("sys.exit(7)", 7), ("os.kill(os.getpid(), signal.SIGKILL)", 137)],
)
def test_terminal_restores_after_client_exit_or_crash(ending, expected):
    code = (
        'import os,sys,tty,signal; tty.setraw(0); os.write(1,b"\\x1b[?1000h\\x1b[?1006h"); '
        + ending
    )
    process, master, slave, original = start_client(code)
    try:
        assert process.wait(timeout=5) == expected
        output = read_until(master, guard.RESET)
        assert b"\x1b[?1000h" in output
        assert termios.tcgetattr(slave) == original
    finally:
        cleanup(process, master, slave)


@pytest.mark.parametrize(
    "target,number,expected",
    [
        ("group", signal.SIGINT, 0),
        ("parent", signal.SIGTERM, 143),
        ("group", signal.SIGQUIT, 131),
    ],
)
def test_terminal_signals_reach_client_and_cleanup(target, number, expected):
    code = """import os,sys,tty,signal,time,resource
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
signal.signal(signal.SIGINT, lambda *args: sys.exit(0))
tty.setraw(0)
os.write(1,b"STARTED")
while True: time.sleep(1)
"""
    process, master, slave, original = start_client(code)
    try:
        read_until(master, b"STARTED")
        (os.killpg if target == "group" else os.kill)(process.pid, number)
        assert process.wait(timeout=5) == expected
        read_until(master, guard.RESET)
        assert termios.tcgetattr(slave) == original
    finally:
        cleanup(process, master, slave)


def test_child_suspend_can_be_resumed_as_one_job():
    code = """import os,tty,signal
tty.setraw(0)
os.kill(os.getpid(), signal.SIGSTOP)
os.write(1,b"RESUMED")
"""
    process, master, slave, original = start_client(code)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid, status = os.waitpid(process.pid, os.WUNTRACED | os.WNOHANG)
            if pid:
                assert os.WIFSTOPPED(status)
                break
            time.sleep(0.02)
        else:
            pytest.fail("supervisor did not propagate the stopped child")
        assert termios.tcgetattr(slave) == original
        os.killpg(process.pid, signal.SIGCONT)
        assert process.wait(timeout=5) == 0
        output = read_until(master, guard.RESET)
        assert b"RESUMED" in output
        assert termios.tcgetattr(slave) == original
    finally:
        cleanup(process, master, slave)


def test_piped_commands_preserve_exact_output_and_status():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--",
            sys.executable,
            "-c",
            'import sys;sys.stdout.buffer.write(b"{\\"ok\\":true}\\n");sys.exit(9)',
        ],
        input=b"",
        capture_output=True,
    )
    assert result.returncode == 9
    assert result.stdout == b'{"ok":true}\n'
    assert result.stderr == b""


@pytest.mark.parametrize("wrapper", ["codex_cli_wrapper.sh", "codex_work_wrapper.sh"])
def test_launcher_wraps_router_reentry_exactly_once(tmp_path, wrapper):
    router = tmp_path / "router.py"
    router.write_text(
        'import os,tty;tty.setraw(0);os.write(1,("GUARDED="+os.environ.get("NORMAN_CODEX_TERMINAL_GUARD", "0")).encode());os._exit(19)'
    )
    process, master, slave, original = start_client(
        "",
        command=["bash", str(SCRIPT.parent / wrapper), "--print-route"],
        overrides={
            "CODEX_ROUTER_SCRIPT": str(router),
            "CODEX_TERMINAL_GUARD_SCRIPT": str(SCRIPT),
        },
    )
    try:
        assert process.wait(timeout=5) == 19
        output = read_until(master, guard.RESET)
        assert b"GUARDED=1" in output
        assert output.count(guard.RESET) == 1
        assert termios.tcgetattr(slave) == original
    finally:
        cleanup(process, master, slave)
