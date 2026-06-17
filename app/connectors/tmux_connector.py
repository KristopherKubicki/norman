"""Connector that routes messages into tmux panes.

This is the control-plane bridge for local agent fleets. Configure one connector
per worker/session (or one connector with a specific target pane), then route
messages from phone channels (Telegram/Signal/etc.) to this connector.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

from .base_connector import BaseConnector


class TmuxConnector(BaseConnector):
    """Send routed messages to a tmux target pane."""

    id = "tmux"
    name = "tmux"
    CODEX_QUEUE_HINTS = (
        "tab to queue message",
        "? for shortcuts",
        "alt + ↑ edit",
        "alt + up edit",
        "context left",
        "conversation interrupted - tell the model what to do differently",
    )
    SUBMIT_MODE_ENTER = "enter"
    SUBMIT_MODE_TAB_ENTER = "tab_enter"
    SUBMIT_MODE_AUTO = "auto"

    def __init__(
        self,
        session: str,
        target: str = "",
        socket_path: str = "",
        working_dir: str = "",
        send_enter: bool = True,
        send_enter_count: int = 1,
        pane_tty: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(config)
        self.session = session
        self.target = target
        self.socket_path = socket_path
        self.working_dir = working_dir
        self.send_enter = send_enter
        self.send_enter_count = max(0, int(send_enter_count))
        self.pane_tty = pane_tty.strip()

    def _tmux_base_cmd(self) -> list[str]:
        cmd = ["tmux"]
        if self.socket_path:
            cmd.extend(["-S", self.socket_path])
        return cmd

    def _tmux_target(self) -> str:
        if self.target:
            return self.target
        # Default target: first pane in the first window of the configured session.
        return f"{self.session}:0.0"

    def _normalize_tty(self, tty: str) -> str:
        text = str(tty or "").strip()
        if not text:
            return ""
        if text.startswith("/dev/"):
            return text
        return f"/dev/{text}"

    def _tmux(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = [*self._tmux_base_cmd(), *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            stdin=subprocess.DEVNULL,
        )

    def _find_target_by_tty(self) -> str:
        tty = self._normalize_tty(self.pane_tty)
        if not tty:
            return ""

        proc = self._tmux(
            "list-panes",
            "-a",
            "-F",
            "#{pane_tty}\t#{session_name}\t#{window_index}\t#{pane_index}",
            check=False,
        )
        if proc.returncode != 0:
            return ""

        for line in (proc.stdout or "").splitlines():
            pane_tty, session_name, window_index, pane_index = (
                line.split("\t", 3) + ["", "", "", ""]
            )[:4]
            if self._normalize_tty(pane_tty) != tty:
                continue
            if not session_name:
                continue
            resolved = f"{session_name}:{window_index}.{pane_index}"
            self.session = session_name
            self.target = resolved
            if isinstance(self.config, dict):
                self.config["session"] = session_name
                self.config["target"] = resolved
            return resolved
        return ""

    def _resolved_target(self) -> str:
        if self.pane_tty:
            by_tty = self._find_target_by_tty()
            if by_tty:
                return by_tty
        return self._tmux_target()

    def _capture_tail(self, target: str, lines: int = 24) -> str:
        proc = self._tmux(
            "capture-pane",
            "-p",
            "-J",
            "-t",
            target,
            "-S",
            f"-{max(1, int(lines))}",
            check=False,
        )
        if proc.returncode != 0:
            return ""
        return str(proc.stdout or "")

    def _normalize_submit_mode(self, value: str) -> str:
        mode = str(value or "").strip().lower()
        if mode in {
            self.SUBMIT_MODE_ENTER,
            self.SUBMIT_MODE_TAB_ENTER,
            self.SUBMIT_MODE_AUTO,
        }:
            return mode
        return self.SUBMIT_MODE_AUTO

    def _resolve_submit_mode(self, target: str, message: Any) -> str:
        override = ""
        if isinstance(message, dict):
            override = str(message.get("submit_mode") or "")
        if override:
            return self._normalize_submit_mode(override)

        configured = ""
        if isinstance(self.config, dict):
            configured = str(
                self.config.get("submit_mode")
                or self.config.get("send_submit_mode")
                or "",
            )

        mode = self._normalize_submit_mode(configured or self.SUBMIT_MODE_AUTO)
        if mode != self.SUBMIT_MODE_AUTO:
            return mode

        pane_tail = self._capture_tail(target, lines=24).lower()
        if any(hint in pane_tail for hint in self.CODEX_QUEUE_HINTS):
            return self.SUBMIT_MODE_TAB_ENTER
        return self.SUBMIT_MODE_ENTER

    def _prepare_text(self, message: Any) -> str:
        if isinstance(message, dict):
            # Prefer explicit command payloads; fall back to text.
            command = message.get("command")
            if isinstance(command, str) and command.strip():
                return command.strip()
            text = message.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            return ""
        if isinstance(message, str):
            return message.strip()
        return str(message).strip()

    def _resolve_enter_count(self, message: Any) -> int:
        default_count = max(1, int(self.send_enter_count or 1))

        if isinstance(self.config, dict):
            configured = self.config.get("send_enter_count")
            if configured is not None:
                try:
                    default_count = max(1, int(configured))
                except (TypeError, ValueError):
                    pass

        if isinstance(message, dict):
            override = message.get("enter_count")
            if override is not None:
                try:
                    return max(1, int(override))
                except (TypeError, ValueError):
                    return default_count

        return default_count

    def _resolve_submit_delay_seconds(self, message: Any) -> float:
        default_delay = 0.12
        if isinstance(self.config, dict):
            configured = self.config.get("submit_delay_ms")
            if configured is not None:
                try:
                    default_delay = max(0.0, float(configured) / 1000.0)
                except (TypeError, ValueError):
                    pass
        if isinstance(message, dict):
            override = message.get("submit_delay_ms")
            if override is not None:
                try:
                    return max(0.0, float(override) / 1000.0)
                except (TypeError, ValueError):
                    return default_delay
        return default_delay

    def send_message(self, message: Any) -> Dict[str, Any]:
        text = self._prepare_text(message)
        if not text:
            return {"status": "ignored", "reason": "empty_message"}

        target = self._resolved_target()
        submit_mode = self._resolve_submit_mode(target, message)

        if self.working_dir:
            self._tmux("send-keys", "-t", target, "-l", f"cd {self.working_dir}")
            self._tmux("send-keys", "-t", target, "C-m")

        self._tmux("send-keys", "-t", target, "-l", text)
        if self.send_enter:
            if submit_mode == self.SUBMIT_MODE_TAB_ENTER:
                submit_delay = self._resolve_submit_delay_seconds(message)
                if submit_delay:
                    time.sleep(submit_delay)
                self._tmux("send-keys", "-t", target, "Tab")
                if submit_delay:
                    time.sleep(submit_delay)
                self._tmux("send-keys", "-t", target, "C-m")
            else:
                enter_count = self._resolve_enter_count(message)
                for _ in range(enter_count):
                    self._tmux("send-keys", "-t", target, "C-m")

        return {
            "status": "sent",
            "target": target,
            "text": text,
            "submit_mode": submit_mode,
        }

    async def listen_and_process(self) -> None:
        # tmux is command-oriented in this connector; inbound streaming is a
        # follow-up via tmux pipe-pane/log tail bridge.
        while True:  # pragma: no cover - long-running placeholder
            await asyncio.sleep(60)

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        text = self._prepare_text(message)
        return {
            "text": text,
            "text_summary": f"tmux • {text}" if text else "tmux",
            "signal_class": "control",
            "passive_source": "tmux",
            "sensor_type": "tmux",
        }

    def is_connected(self) -> bool:
        if shutil.which("tmux") is None:
            return False

        if self.pane_tty:
            if self._find_target_by_tty():
                return True

        if not self.session:
            return False

        try:
            self._tmux("has-session", "-t", self.session)
            return True
        except Exception:
            return False
