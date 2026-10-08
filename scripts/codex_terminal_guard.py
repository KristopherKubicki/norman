#!/usr/bin/env python3
"""Restore an interactive terminal after its client exits; never read session data."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import termios

# Disable mouse encodings/reporting, focus events and bracketed paste, leave the
# alternate screen, and restore a visible default cursor. These are idempotent.
RESET = b"\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1005l\x1b[?1006l\x1b[?1015l\x1b[?1004l\x1b[?2004l\x1b[?1049l\x1b[0m\x1b[?25h\x1b[0 q"
MARKER = "NORMAN_CODEX_TERMINAL_GUARD"


def wait_for_child(child: subprocess.Popen, original: list) -> int:
    """Propagate a child-only suspend to the shell's foreground job."""
    while True:
        try:
            _, status = os.waitpid(child.pid, os.WUNTRACED)
        except ChildProcessError:
            return child.returncode if child.returncode is not None else 1
        if os.WIFSTOPPED(status):
            suspended = termios.tcgetattr(0)
            termios.tcsetattr(0, termios.TCSANOW, original)
            os.kill(os.getpid(), signal.SIGSTOP)
            termios.tcsetattr(0, termios.TCSANOW, suspended)
            child.send_signal(signal.SIGCONT)
            continue
        child.returncode = os.waitstatus_to_exitcode(status)
        return child.returncode


def run(command: list[str]) -> int:
    """Keep the child in the foreground job's process group and wait for exit."""
    if not (os.isatty(0) and os.isatty(1)) or os.environ.get(MARKER) == "1":
        os.execvp(command[0], command)
    original = termios.tcgetattr(0)
    environment = {**os.environ, MARKER: "1"}
    child = None
    pending = []

    def handle_signal(number, _frame):
        if child is None:
            pending.append(number)
        elif number not in (signal.SIGINT, signal.SIGQUIT):
            # INT/QUIT from the foreground terminal reach both processes; do
            # not deliver it twice to the TUI. TERM/HUP sent just to this wrapper
            # still need to reach the child.
            try:
                child.send_signal(number)
            except ProcessLookupError:
                pass

    saved = {
        number: signal.signal(number, handle_signal)
        for number in (signal.SIGINT, signal.SIGQUIT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        child = subprocess.Popen(command, env=environment)
        for number in pending:
            child.send_signal(number)
        result = wait_for_child(child, original)
        return result if result >= 0 else 128 - result
    finally:
        # Do not consume or flush queued input: it may contain the user's text.
        try:
            termios.tcsetattr(0, termios.TCSANOW, original)
        except (OSError, termios.error):
            pass
        try:
            os.write(1, RESET)
        except OSError:
            pass
        for number, handler in saved.items():
            signal.signal(number, handler)


def main() -> int:
    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        print("Usage: codex_terminal_guard.py -- COMMAND [ARG ...]", file=sys.stderr)
        return 2
    try:
        return run(command)
    except (OSError, termios.error) as error:
        print(
            f"Unable to launch terminal client ({type(error).__name__}).",
            file=sys.stderr,
        )
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
