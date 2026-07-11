from __future__ import annotations

import subprocess
import os
import shlex
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.command_policy import CommandDecision, evaluate_tmux_payload


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _preview(text: str, limit: int = 4000) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "..."


@dataclass
class ShellRequest:
    command: str
    cwd: str = ""
    timeout_seconds: int = 60
    env: dict[str, str] = field(default_factory=dict)
    allow_shell_metachar: bool = False
    policy_profile: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.command = _clean(self.command)
        self.cwd = _clean(self.cwd)
        self.timeout_seconds = max(1, min(int(self.timeout_seconds or 60), 3600))
        self.env = {
            _clean(key): str(value)
            for key, value in dict(self.env or {}).items()
            if _clean(key)
        }
        self.policy_profile = dict(self.policy_profile or {})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShellResult:
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    policy: dict[str, Any] = field(default_factory=dict)
    timed_out: bool = False

    @property
    def output_preview(self) -> str:
        combined = "\n".join(part for part in (self.stdout, self.stderr) if part)
        return _preview(combined, 4000)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShellPolicyError(RuntimeError):
    """Raised when command policy blocks or holds a shell request."""

    def __init__(self, decision: CommandDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason)


class ShellRuntimeAdapter:
    """Bounded subprocess shell adapter for the Norman kernel.

    This adapter is intentionally small. Session/pty support can be layered on
    later, but even simple subprocess execution must use the same deterministic
    command policy as the tmux control path.
    """

    name = "shell"

    def evaluate(self, request: ShellRequest) -> CommandDecision:
        return evaluate_tmux_payload(
            request.command,
            mode="shell",
            allow_shell_metachar=request.allow_shell_metachar,
            profile=request.policy_profile,
        )

    def run(self, request: ShellRequest) -> ShellResult:
        decision = self.evaluate(request)
        if decision.decision != "allow":
            raise ShellPolicyError(decision)
        try:
            env = None
            if request.env:
                env = dict(os.environ)
                env.update(request.env)
            completed = subprocess.run(
                shlex.split(request.command),
                cwd=request.cwd or None,
                env=env,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ShellResult(
                command=request.command,
                returncode=124,
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or "command timed out"),
                policy=asdict(decision),
                timed_out=True,
            )
        return ShellResult(
            command=request.command,
            returncode=int(completed.returncode),
            stdout=completed.stdout,
            stderr=completed.stderr,
            policy=asdict(decision),
        )
