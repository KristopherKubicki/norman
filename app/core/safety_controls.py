from __future__ import annotations

from typing import Optional

from app.core.config import Settings, get_settings

_MIN_LEVEL = 0
_MAX_LEVEL = 5

_LEVEL_LABELS = {
    0: "normal",
    1: "action_hold",
    2: "command_hold",
    3: "quarantine",
    4: "read_only",
    5: "hard_kill",
}


def clamp_kill_switch_level(value: object) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = _MIN_LEVEL
    if level < _MIN_LEVEL:
        return _MIN_LEVEL
    if level > _MAX_LEVEL:
        return _MAX_LEVEL
    return level


def current_kill_switch_level(app_settings: Optional[Settings] = None) -> int:
    conf = app_settings or get_settings()
    return clamp_kill_switch_level(getattr(conf, "safety_kill_switch_level", 0))


def kill_switch_label(level: int) -> str:
    return _LEVEL_LABELS.get(clamp_kill_switch_level(level), "normal")


def routing_actions_block_reason(app_settings: Optional[Settings] = None) -> str:
    level = current_kill_switch_level(app_settings)
    if level >= 1:
        return (
            f"kill-switch L{level} ({kill_switch_label(level)}) blocks outbound actions"
        )
    return ""


def tmux_commands_block_reason(app_settings: Optional[Settings] = None) -> str:
    level = current_kill_switch_level(app_settings)
    if level >= 2:
        return f"kill-switch L{level} ({kill_switch_label(level)}) blocks tmux commands"
    return ""


def effective_read_only(app_settings: Optional[Settings] = None) -> bool:
    conf = app_settings or get_settings()
    return bool(getattr(conf, "safety_read_only", False)) or (
        current_kill_switch_level(conf) >= 4
    )


def execution_blocked_reason(app_settings: Optional[Settings] = None) -> str:
    conf = app_settings or get_settings()
    level = current_kill_switch_level(conf)
    if level >= 1:
        return f"kill-switch L{level} ({kill_switch_label(level)}) blocks execution"
    if not getattr(conf, "safety_execution_enabled", True):
        return "execution disabled"
    if effective_read_only(conf):
        return "read-only mode"
    return ""
