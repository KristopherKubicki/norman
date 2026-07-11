"""Command policy and approval decisions.

This is the safety boundary between LLM/user text and anything that can mutate
systems (tmux, ssh, kubectl, etc.).

Design goals:
- deny-by-default for execution capable connectors
- small, auditable rules
- deterministic decisions (no LLM involvement)
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import secrets
from typing import Iterable, Optional


@dataclass(frozen=True)
class CommandDecision:
    decision: str  # allow|needs_approval|blocked
    command_class: str  # chat|read|change|destructive
    reason: str
    confirm_token: str = ""  # used for destructive approvals


_SHELL_META = re.compile(r"[;&|`$><]|\n")

_BLOCK_PATTERNS_CHAT = [
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
]

_REQUIRE_APPROVAL_CHAT = [
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bapt(-get)?\b", re.IGNORECASE),
    re.compile(r"\byum\b", re.IGNORECASE),
    re.compile(r"\bdnf\b", re.IGNORECASE),
    re.compile(r"\bpip\s+install\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+install\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\b", re.IGNORECASE),
]

_READ_ALLOWLIST = {
    "ls",
    "cat",
    "tail",
    "head",
    "grep",
    "rg",
    "find",
    "ps",
    "df",
    "du",
    "stat",
    "wc",
    "whoami",
    "id",
    "pwd",
    "date",
    "uname",
    "uptime",
    "free",
    "top",
    "htop",
    "git",
}

_CHANGE_VERBS = {
    "vi",
    "vim",
    "nano",
    "sed",
    "perl",
    "python",
    "python3",
    "pip",
    "npm",
    "apt",
    "apt-get",
    "yum",
    "dnf",
    "systemctl",
    "service",
    "docker",
    "kubectl",
    "terraform",
    "ansible",
}

_DESTRUCTIVE_PATTERNS_SHELL = [
    re.compile(r"\brm\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\b", re.IGNORECASE),
]


def _first_token(text: str) -> str:
    parts = (text or "").strip().split()
    return parts[0] if parts else ""


def _matches_any(text: str, patterns: Iterable[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def evaluate_tmux_payload(
    text: str,
    *,
    mode: str = "chat",
    allow_shell_metachar: bool = False,
    profile: Optional[dict] = None,
) -> CommandDecision:
    """Evaluate whether a tmux payload should be executed.

    Modes:
    - chat: intended for sending natural language to a running agent in a pane
    - shell: intended for sending shell commands to a shell pane
    """

    raw = (text or "").strip()
    if not raw:
        return CommandDecision("blocked", "chat", "empty")

    profile = profile if isinstance(profile, dict) else {}
    # Profile overrides (per-connector policy)
    mode = (profile.get("mode") or mode or "chat").strip().lower()
    if mode not in {"chat", "shell"}:
        mode = "chat"
    allow_shell_metachar = bool(
        profile.get("allow_shell_metachar", allow_shell_metachar)
    )
    max_len = int(profile.get("max_length", 0) or 0)
    if max_len > 0 and len(raw) > max_len:
        return CommandDecision("needs_approval", "change", "command too long")

    blocked_patterns = []
    for pat in profile.get("blocked_patterns") or []:
        try:
            blocked_patterns.append(re.compile(str(pat)))
        except re.error:
            continue
    require_patterns = []
    for pat in profile.get("require_approval_patterns") or []:
        try:
            require_patterns.append(re.compile(str(pat)))
        except re.error:
            continue

    blocked_verbs = {str(v).lower() for v in (profile.get("blocked_verbs") or [])}
    require_verbs = {
        str(v).lower() for v in (profile.get("require_approval_verbs") or [])
    }
    allowed_verbs = {str(v).lower() for v in (profile.get("allowed_verbs") or [])}

    if blocked_patterns and _matches_any(raw, blocked_patterns):
        return CommandDecision(
            "blocked", "change" if mode == "shell" else "chat", "blocked by policy"
        )
    if require_patterns and _matches_any(raw, require_patterns):
        return CommandDecision(
            "needs_approval",
            "change" if mode == "shell" else "chat",
            "requires approval by policy",
        )

    if mode == "chat":
        if _matches_any(raw, _BLOCK_PATTERNS_CHAT):
            token = secrets.token_hex(3)
            return CommandDecision(
                "needs_approval",
                "destructive",
                "high-risk command detected",
                confirm_token=token,
            )
        if _matches_any(raw, _REQUIRE_APPROVAL_CHAT):
            return CommandDecision(
                "needs_approval",
                "change",
                "command requires approval",
            )
        return CommandDecision("allow", "chat", "ok")

    # shell mode
    if not allow_shell_metachar and _SHELL_META.search(raw):
        return CommandDecision(
            "needs_approval",
            "change",
            "shell metacharacters present",
        )

    verb = _first_token(raw).lower()
    if not verb:
        return CommandDecision("blocked", "read", "empty")

    if verb in blocked_verbs:
        return CommandDecision("blocked", "change", "blocked verb")
    if verb in require_verbs:
        return CommandDecision("needs_approval", "change", "requires approval verb")
    if allowed_verbs and verb not in allowed_verbs:
        return CommandDecision("needs_approval", "change", "verb not in allowlist")

    if _matches_any(raw, _DESTRUCTIVE_PATTERNS_SHELL):
        token = secrets.token_hex(3)
        return CommandDecision(
            "needs_approval",
            "destructive",
            "destructive shell command",
            confirm_token=token,
        )

    if verb in _READ_ALLOWLIST:
        # git can be read or write; gate common write subcommands.
        if verb == "git" and re.search(r"\b(push|commit|reset|clean)\b", raw):
            token = secrets.token_hex(3)
            return CommandDecision(
                "needs_approval",
                "change",
                "git write operation",
                confirm_token=token if "reset" in raw or "clean" in raw else "",
            )
        return CommandDecision("allow", "read", "ok")

    if verb in _CHANGE_VERBS:
        return CommandDecision("needs_approval", "change", "mutating command")

    # deny by default
    return CommandDecision("needs_approval", "change", "unknown command")
