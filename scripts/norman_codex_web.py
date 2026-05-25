#!/usr/bin/env python3
from __future__ import annotations

import base64
import binascii
import hashlib
import html
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import zlib
from datetime import datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error, request as urllib_request
from urllib.parse import parse_qs, quote, urlencode, urlparse


SESSION = os.environ.get("HOUSEBOT_CODEX_SESSION", "housebot-codex")
TMUX_SOCKET = os.environ.get("HOUSEBOT_CODEX_TMUX_SOCKET", SESSION).strip() or SESSION
HOST = os.environ.get("HOUSEBOT_CODEX_WEB_BIND", "0.0.0.0")
PORT = int(os.environ.get("HOUSEBOT_CODEX_WEB_PORT", "8787"))
TOKEN = os.environ.get("HOUSEBOT_CODEX_WEB_TOKEN", "").strip()
DEFAULT_AUTH_COOKIE_NAME = (
    f"codex_console_token_{re.sub(r'[^a-z0-9]+', '_', SESSION.lower())}_{PORT}"
)
AUTH_COOKIE_NAME = (
    os.environ.get("HOUSEBOT_CODEX_WEB_COOKIE_NAME", DEFAULT_AUTH_COOKIE_NAME).strip()
    or DEFAULT_AUTH_COOKIE_NAME
)
AUTH_COOKIE_MAX_AGE = int(
    os.environ.get("HOUSEBOT_CODEX_WEB_COOKIE_MAX_AGE", str(14 * 24 * 60 * 60))
)
DEFAULT_UI_VERSION = "2026.04.23.1"
UI_VERSION = (
    os.environ.get("HOUSEBOT_CODEX_UI_VERSION", DEFAULT_UI_VERSION).strip()
    or DEFAULT_UI_VERSION
)
MAX_PANE_LINES = int(os.environ.get("HOUSEBOT_CODEX_WEB_PANE_LINES", "120"))
MAX_LOG_LINES = int(os.environ.get("HOUSEBOT_CODEX_WEB_LOG_LINES", "24"))
MAX_BLOCK_CHARS = int(os.environ.get("HOUSEBOT_CODEX_WEB_BLOCK_CHARS", "12000"))
MAX_HISTORY_ITEMS = int(os.environ.get("HOUSEBOT_CODEX_WEB_HISTORY_ITEMS", "24"))
MAX_USAGE_ITEMS = int(os.environ.get("HOUSEBOT_CODEX_WEB_USAGE_ITEMS", "240"))
MAX_AUDIT_ITEMS = int(os.environ.get("HOUSEBOT_CODEX_WEB_AUDIT_ITEMS", "800"))
USAGE_WINDOW_SECONDS = int(
    os.environ.get("HOUSEBOT_CODEX_WEB_USAGE_WINDOW_SECONDS", str(24 * 60 * 60))
)
USAGE_RECENT_ITEMS = int(os.environ.get("HOUSEBOT_CODEX_WEB_USAGE_RECENT_ITEMS", "5"))
KPI_INTERVAL_SECONDS = int(os.environ.get("HOUSEBOT_CODEX_KPI_INTERVAL_SECONDS", "30"))
KPI_WEDGE_SECONDS = int(os.environ.get("HOUSEBOT_CODEX_KPI_WEDGE_SECONDS", "240"))
STREAM_IDLE_SECONDS = float(
    os.environ.get("HOUSEBOT_CODEX_WEB_STREAM_IDLE_SECONDS", "4")
)
STREAM_PENDING_SECONDS = float(
    os.environ.get("HOUSEBOT_CODEX_WEB_STREAM_PENDING_SECONDS", "0.7")
)
WEB_PROMPT_TIMEOUT_SECONDS = int(
    os.environ.get("HOUSEBOT_CODEX_WEB_PROMPT_TIMEOUT_SECONDS", str(15 * 60))
)
WEB_PROMPT_TIMEOUT_GRACE_SECONDS = float(
    os.environ.get("HOUSEBOT_CODEX_WEB_PROMPT_TIMEOUT_GRACE_SECONDS", "5")
)
DIRECTORY_VIEW_LIMIT = int(os.environ.get("HOUSEBOT_CODEX_DIRECTORY_VIEW_LIMIT", "200"))
FILE_PREVIEW_MAX_BYTES = int(
    os.environ.get("HOUSEBOT_CODEX_FILE_PREVIEW_MAX_BYTES", str(256 * 1024))
)
MAX_ATTACHMENT_BYTES = int(
    os.environ.get("HOUSEBOT_CODEX_MAX_ATTACHMENT_BYTES", str(8 * 1024 * 1024))
)
MAX_ATTACHMENT_TEXT_CHARS = int(
    os.environ.get("HOUSEBOT_CODEX_MAX_ATTACHMENT_TEXT_CHARS", "16000")
)
SCREENSHOT_CAPTURE_TIMEOUT = int(
    os.environ.get("HOUSEBOT_CODEX_SCREENSHOT_TIMEOUT_SECONDS", "20")
)
SCREENSHOT_WINDOW_WIDTH = int(os.environ.get("HOUSEBOT_CODEX_SCREENSHOT_WIDTH", "1440"))
SCREENSHOT_WINDOW_HEIGHT = int(
    os.environ.get("HOUSEBOT_CODEX_SCREENSHOT_HEIGHT", "1024")
)
WORKDIR = os.environ.get("HOUSEBOT_CODEX_WORKDIR", "/opt/housebot")
CODEX_HOME = os.environ.get("HOUSEBOT_CODEX_HOME", "/root/.codex-housebot")
MODEL = os.environ.get("HOUSEBOT_CODEX_MODEL", "gpt-5.5")
LATEST_MODEL = os.environ.get("HOUSEBOT_CODEX_LATEST_MODEL", MODEL).strip() or MODEL
AVAILABLE_MODELS = [
    item.strip()
    for item in os.environ.get("HOUSEBOT_CODEX_AVAILABLE_MODELS", MODEL).split(",")
    if item.strip()
] or [MODEL]
REASONING_EFFORT = os.environ.get("HOUSEBOT_CODEX_REASONING_EFFORT", "xhigh")
AGENT_NAME = os.environ.get("HOUSEBOT_CODEX_AGENT_NAME", "Housebot")
AGENT_GROUP = os.environ.get("HOUSEBOT_CODEX_AGENT_GROUP", "").strip()
CONSOLE_TITLE = os.environ.get("HOUSEBOT_CODEX_CONSOLE_TITLE", f"{AGENT_NAME} Console")
HOST_NAME = (
    os.environ.get("HOUSEBOT_CODEX_HOSTNAME", "").strip()
    or socket.gethostname().split(".", 1)[0].strip()
    or "unknown"
)
PROMPT_PLACEHOLDER = os.environ.get(
    "HOUSEBOT_CODEX_PROMPT_PLACEHOLDER",
    f"Ask {AGENT_NAME} to inspect, explain, or make a targeted change.",
)
DEFAULT_UI_PROFILE = os.environ.get("HOUSEBOT_CODEX_UI_PROFILE", "dusk")
CONFIGURED_UI_PROFILE = (DEFAULT_UI_PROFILE or "").strip().lower()
AGENT_STYLE_HINT = os.environ.get("HOUSEBOT_CODEX_STYLE_HINT", "").strip().lower()
DEFAULT_UI_FINISH = (
    os.environ.get("HOUSEBOT_CODEX_UI_FINISH", "flat").strip().lower() or "flat"
)
STATE_DIR = Path(
    os.environ.get("HOUSEBOT_CODEX_WEB_STATE_DIR", f"{CODEX_HOME}/web-bridge")
)
HOUSEBOT_SERVICE = os.environ.get("HOUSEBOT_SERVICE_NAME", "housebot")
PFSENSE_TIMER = os.environ.get(
    "HOUSEBOT_PFSENSE_TIMER_NAME", "housebot-pfsense-sync.timer"
)
CODEX_SERVICE = os.environ.get("HOUSEBOT_CODEX_SERVICE_NAME", "housebot-codex.service")
WEB_SERVICE = os.environ.get(
    "HOUSEBOT_CODEX_WEB_SERVICE_NAME", "housebot-codex-web.service"
)
TAILSCALE_SERVICE = os.environ.get("TAILSCALE_SERVICE_NAME", "tailscaled")


def resolve_codex_bin() -> str:
    configured = os.environ.get("HOUSEBOT_CODEX_BIN", "").strip()
    candidates = [
        configured,
        "/opt/node-v20.19.6/bin/codex",
        "/home/operator/.nvm/versions/node/v20.19.6/bin/codex",
        "/usr/local/bin/codex",
        "codex",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isabs(candidate):
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                return candidate
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return configured or "codex"


CODEX_BIN = resolve_codex_bin()

THREAD_ID_PATH = STATE_DIR / "thread_id.txt"
LAST_PROMPT_PATH = STATE_DIR / "last_prompt.txt"
LAST_RESPONSE_PATH = STATE_DIR / "last_response.txt"
LAST_ERROR_PATH = STATE_DIR / "last_error.txt"
STATUS_PATH = STATE_DIR / "status.json"
RESOURCE_METER_PATH = Path(
    os.environ.get(
        "HOUSEBOT_CODEX_RESOURCE_METER_PATH", str(STATE_DIR / "resource_meter.json")
    )
)
HISTORY_PATH = STATE_DIR / "history.jsonl"
USAGE_PATH = STATE_DIR / "usage.jsonl"
KPI_PATH = STATE_DIR / "kpis.json"
AUDIT_PATH = STATE_DIR / "audit.jsonl"
DRAFT_ATTACHMENTS_PATH = STATE_DIR / "draft_attachments.json"
RUNTIME_SETTINGS_PATH = STATE_DIR / "runtime_settings.json"
ATTACHMENTS_DIR = STATE_DIR / "attachments"

PROMPT_LOCK = threading.Lock()
STATUS_LOCK = threading.Lock()
KPI_LOCK = threading.RLock()
KPI_COLLECTOR_STARTED = False
ACTIVE_PROMPT_THREAD: threading.Thread | None = None
ACTIVE_CODEX_PROC: subprocess.Popen[str] | None = None
ACTIVE_CODEX_LOCK = threading.Lock()

CANCELLED_WEB_REPLY_MESSAGE = (
    "Cancelled current web reply. The running model process was stopped before it "
    "could return a final answer."
)

TEXT_PREVIEW_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".sh",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".log",
    ".csv",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
}

AUTH_DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4,8}(?:-[A-Z0-9]{4,8})+\b")

PROFILE_MODE_ORDER = ("dark", "light")
FINISH_OPTIONS = ("flat", "engraved", "etched", "glow")

UI_PROFILES: dict[str, dict[str, Any]] = {
    "dusk": {
        "label": "Dusk",
        "mode": "dark",
        "family": "dusk",
        "vars": {
            "bg": "#2a3240",
            "bg-soft": "#313a4a",
            "surface": "rgba(45, 54, 69, 0.88)",
            "surface-2": "#384355",
            "surface-3": "#445266",
            "border": "#4d5a70",
            "border-strong": "#65748d",
            "text": "#e4ebf2",
            "muted": "#a8b3c2",
            "accent": "#b8cedd",
            "accent-2": "#aac9be",
            "warn": "#d8c28d",
            "danger": "#d2aab6",
            "shadow": "0 14px 34px rgba(7, 10, 15, 0.12)",
            "radius": "20px",
            "glow-a": "rgba(184, 206, 221, 0.04)",
            "glow-b": "rgba(170, 201, 190, 0.03)",
            "body-start": "#29313e",
            "body-mid": "#303846",
            "body-end": "#353f4d",
        },
    },
    "dawn": {
        "label": "Dawn",
        "mode": "light",
        "family": "dusk",
        "vars": {
            "bg": "#f0e8dc",
            "bg-soft": "#f5efe6",
            "surface": "rgba(251, 247, 240, 0.88)",
            "surface-2": "#f2e7d7",
            "surface-3": "#eadbc7",
            "border": "#d5c6b3",
            "border-strong": "#c3b09a",
            "text": "#302821",
            "muted": "#766a5f",
            "accent": "#5d7386",
            "accent-2": "#698570",
            "warn": "#9a744d",
            "danger": "#9f6270",
            "shadow": "0 18px 40px rgba(88, 70, 48, 0.10)",
            "radius": "20px",
            "glow-a": "rgba(210, 188, 158, 0.18)",
            "glow-b": "rgba(198, 214, 196, 0.12)",
            "body-start": "#efe5d8",
            "body-mid": "#f5efe7",
            "body-end": "#ece4d7",
        },
    },
    "slate": {
        "label": "Slate",
        "mode": "dark",
        "family": "slate",
        "vars": {
            "bg": "#303642",
            "bg-soft": "#373e4b",
            "surface": "rgba(52, 59, 72, 0.88)",
            "surface-2": "#3f4755",
            "surface-3": "#4a5566",
            "border": "#556174",
            "border-strong": "#6e7e96",
            "text": "#e5ecf4",
            "muted": "#adb8c7",
            "accent": "#c1d0df",
            "accent-2": "#a7c0d1",
            "warn": "#d7c391",
            "danger": "#d0a7bb",
            "shadow": "0 14px 34px rgba(8, 10, 15, 0.12)",
            "radius": "20px",
            "glow-a": "rgba(193, 208, 223, 0.04)",
            "glow-b": "rgba(167, 192, 209, 0.03)",
            "body-start": "#2f3541",
            "body-mid": "#373e4a",
            "body-end": "#3d4552",
        },
    },
    "blueprint": {
        "label": "Blueprint",
        "mode": "dark",
        "family": "blueprint",
        "vars": {
            "bg": "#151b4b",
            "bg-soft": "#182052",
            "surface": "rgba(21, 28, 74, 0.9)",
            "surface-2": "#1b2458",
            "surface-3": "#243067",
            "border": "#2f467a",
            "border-strong": "#3674a4",
            "text": "#e8eeff",
            "muted": "#95a7cf",
            "accent": "#4aa3ff",
            "accent-2": "#3674a4",
            "warn": "#d8c28d",
            "danger": "#d0a0ae",
            "shadow": "0 14px 34px rgba(6, 9, 24, 0.18)",
            "radius": "8px",
            "glow-a": "rgba(74, 163, 255, 0.05)",
            "glow-b": "rgba(54, 116, 164, 0.035)",
            "body-start": "#12173f",
            "body-mid": "#151b4b",
            "body-end": "#182052",
        },
    },
    "draft": {
        "label": "Draft",
        "mode": "light",
        "family": "blueprint",
        "vars": {
            "bg": "#ebf1fb",
            "bg-soft": "#f4f8fd",
            "surface": "rgba(247, 250, 255, 0.92)",
            "surface-2": "#e4ecf8",
            "surface-3": "#d7e3f5",
            "border": "#b7c9e5",
            "border-strong": "#8eb0d5",
            "text": "#1f2b44",
            "muted": "#617393",
            "accent": "#3674a4",
            "accent-2": "#4aa3ff",
            "warn": "#926f48",
            "danger": "#9a6272",
            "shadow": "0 18px 40px rgba(60, 82, 122, 0.12)",
            "radius": "8px",
            "glow-a": "rgba(74, 163, 255, 0.14)",
            "glow-b": "rgba(54, 116, 164, 0.1)",
            "body-start": "#e7eef9",
            "body-mid": "#f2f6fc",
            "body-end": "#e8f0fb",
        },
    },
    "mist": {
        "label": "Mist",
        "mode": "light",
        "family": "slate",
        "vars": {
            "bg": "#edf2f5",
            "bg-soft": "#f5f8fa",
            "surface": "rgba(248, 251, 252, 0.88)",
            "surface-2": "#e9eff3",
            "surface-3": "#dde7ed",
            "border": "#c8d3db",
            "border-strong": "#b0c0cb",
            "text": "#25303a",
            "muted": "#6d7b88",
            "accent": "#496476",
            "accent-2": "#4d7b72",
            "warn": "#8e744d",
            "danger": "#94606f",
            "shadow": "0 18px 40px rgba(85, 103, 118, 0.10)",
            "radius": "20px",
            "glow-a": "rgba(194, 213, 226, 0.18)",
            "glow-b": "rgba(204, 218, 229, 0.14)",
            "body-start": "#e7eef2",
            "body-mid": "#f1f6f8",
            "body-end": "#e8eff3",
        },
    },
    "evergreen": {
        "label": "Evergreen",
        "mode": "dark",
        "family": "evergreen",
        "vars": {
            "bg": "#2a342c",
            "bg-soft": "#323d34",
            "surface": "rgba(47, 57, 49, 0.88)",
            "surface-2": "#3a453d",
            "surface-3": "#455347",
            "border": "#526358",
            "border-strong": "#697e70",
            "text": "#e2ede4",
            "muted": "#a8baaa",
            "accent": "#b8d1be",
            "accent-2": "#a7cec4",
            "warn": "#d5c58e",
            "danger": "#d0a8b2",
            "shadow": "0 14px 34px rgba(6, 10, 7, 0.12)",
            "radius": "20px",
            "glow-a": "rgba(184, 209, 190, 0.04)",
            "glow-b": "rgba(167, 206, 196, 0.03)",
            "body-start": "#2b342d",
            "body-mid": "#344036",
            "body-end": "#3a463c",
        },
    },
    "sage": {
        "label": "Sage",
        "mode": "light",
        "family": "evergreen",
        "vars": {
            "bg": "#edf1e8",
            "bg-soft": "#f4f7f1",
            "surface": "rgba(247, 250, 244, 0.9)",
            "surface-2": "#e8eee1",
            "surface-3": "#dce6d3",
            "border": "#c4d0bf",
            "border-strong": "#aebfa8",
            "text": "#263029",
            "muted": "#69756a",
            "accent": "#4f6f65",
            "accent-2": "#587b72",
            "warn": "#91744d",
            "danger": "#91616f",
            "shadow": "0 18px 40px rgba(73, 92, 72, 0.10)",
            "radius": "20px",
            "glow-a": "rgba(201, 217, 193, 0.18)",
            "glow-b": "rgba(200, 220, 213, 0.14)",
            "body-start": "#e8eee1",
            "body-mid": "#f2f6ee",
            "body-end": "#e6ece0",
        },
    },
    "ember": {
        "label": "Ember",
        "mode": "dark",
        "family": "ember",
        "vars": {
            "bg": "#342b2b",
            "bg-soft": "#3d3232",
            "surface": "rgba(57, 46, 46, 0.9)",
            "surface-2": "#473939",
            "surface-3": "#584646",
            "border": "#6a5350",
            "border-strong": "#876763",
            "text": "#f0e5de",
            "muted": "#b9a69d",
            "accent": "#e2b38a",
            "accent-2": "#d5987e",
            "warn": "#dfbf87",
            "danger": "#d09ca3",
            "shadow": "0 14px 34px rgba(18, 10, 8, 0.14)",
            "radius": "20px",
            "glow-a": "rgba(226, 179, 138, 0.055)",
            "glow-b": "rgba(213, 152, 126, 0.04)",
            "body-start": "#322928",
            "body-mid": "#3a302f",
            "body-end": "#433735",
        },
    },
    "parchment": {
        "label": "Parchment",
        "mode": "light",
        "family": "ember",
        "vars": {
            "bg": "#f5ece1",
            "bg-soft": "#faf5ee",
            "surface": "rgba(253, 249, 243, 0.9)",
            "surface-2": "#f0e2d2",
            "surface-3": "#e7d3bd",
            "border": "#d3bca4",
            "border-strong": "#bea488",
            "text": "#362a22",
            "muted": "#7c695c",
            "accent": "#9f684a",
            "accent-2": "#a77861",
            "warn": "#a17a4b",
            "danger": "#9d6672",
            "shadow": "0 18px 40px rgba(99, 74, 48, 0.11)",
            "radius": "20px",
            "glow-a": "rgba(219, 182, 138, 0.18)",
            "glow-b": "rgba(220, 196, 163, 0.14)",
            "body-start": "#efe4d7",
            "body-mid": "#f8f1e8",
            "body-end": "#ede1d3",
        },
    },
    "tide": {
        "label": "Tide",
        "mode": "dark",
        "family": "tide",
        "vars": {
            "bg": "#23343d",
            "bg-soft": "#2a3e48",
            "surface": "rgba(38, 58, 68, 0.9)",
            "surface-2": "#31505d",
            "surface-3": "#3b6271",
            "border": "#4c7282",
            "border-strong": "#6591a3",
            "text": "#e0edf3",
            "muted": "#a6bcc7",
            "accent": "#8cc7db",
            "accent-2": "#82d7c6",
            "warn": "#d7c08b",
            "danger": "#cf9fb2",
            "shadow": "0 14px 34px rgba(7, 14, 18, 0.14)",
            "radius": "20px",
            "glow-a": "rgba(140, 199, 219, 0.05)",
            "glow-b": "rgba(130, 215, 198, 0.035)",
            "body-start": "#22323a",
            "body-mid": "#29404a",
            "body-end": "#304853",
        },
    },
    "foam": {
        "label": "Foam",
        "mode": "light",
        "family": "tide",
        "vars": {
            "bg": "#e8f1f2",
            "bg-soft": "#f4f9f9",
            "surface": "rgba(248, 252, 252, 0.9)",
            "surface-2": "#dfecee",
            "surface-3": "#d1e3e6",
            "border": "#bad0d6",
            "border-strong": "#9dbac3",
            "text": "#24323a",
            "muted": "#667984",
            "accent": "#427287",
            "accent-2": "#4d8d7f",
            "warn": "#8f774b",
            "danger": "#936172",
            "shadow": "0 18px 40px rgba(76, 110, 126, 0.1)",
            "radius": "20px",
            "glow-a": "rgba(171, 206, 218, 0.17)",
            "glow-b": "rgba(171, 220, 209, 0.13)",
            "body-start": "#e4eef0",
            "body-mid": "#f2f7f8",
            "body-end": "#e7f0f1",
        },
    },
    "orchid": {
        "label": "Orchid",
        "mode": "dark",
        "family": "orchid",
        "vars": {
            "bg": "#322d3e",
            "bg-soft": "#3a3448",
            "surface": "rgba(53, 48, 68, 0.9)",
            "surface-2": "#443d56",
            "surface-3": "#544b69",
            "border": "#655d7e",
            "border-strong": "#8378a1",
            "text": "#ece6f3",
            "muted": "#b7afc5",
            "accent": "#c8b0eb",
            "accent-2": "#9fc6e8",
            "warn": "#d9c28f",
            "danger": "#d4a4bf",
            "shadow": "0 14px 34px rgba(10, 8, 18, 0.14)",
            "radius": "20px",
            "glow-a": "rgba(200, 176, 235, 0.05)",
            "glow-b": "rgba(159, 198, 232, 0.035)",
            "body-start": "#302b3a",
            "body-mid": "#393345",
            "body-end": "#443d50",
        },
    },
    "petal": {
        "label": "Petal",
        "mode": "light",
        "family": "orchid",
        "vars": {
            "bg": "#f4edf4",
            "bg-soft": "#fbf7fb",
            "surface": "rgba(251, 247, 251, 0.9)",
            "surface-2": "#eee4ef",
            "surface-3": "#e4d5e7",
            "border": "#d4c3d8",
            "border-strong": "#bea7c7",
            "text": "#332a35",
            "muted": "#786b7e",
            "accent": "#775f9a",
            "accent-2": "#5f7f9f",
            "warn": "#9a7a52",
            "danger": "#9d667d",
            "shadow": "0 18px 40px rgba(103, 85, 110, 0.1)",
            "radius": "20px",
            "glow-a": "rgba(203, 181, 230, 0.16)",
            "glow-b": "rgba(189, 209, 231, 0.12)",
            "body-start": "#efe7f0",
            "body-mid": "#faf6fa",
            "body-end": "#eee5ef",
        },
    },
}

SEMANTIC_GROUP_PROFILES = {
    "norman": "tide",
    "personal": "dusk",
    "shared": "ember",
    "work": "blueprint",
    "private": "dusk",
    "agents": "dusk",
}

SEMANTIC_GROUP_ACCENTS = {
    "norman": {
        "accent": "#5fd2c4",
        "accent-2": "#72b3e8",
        "glow-a": "rgba(95, 210, 196, 0.07)",
        "glow-b": "rgba(114, 179, 232, 0.045)",
    },
    "personal": {
        "accent": "#d8b25b",
        "accent-2": "#d38b46",
        "glow-a": "rgba(216, 178, 91, 0.075)",
        "glow-b": "rgba(211, 139, 70, 0.045)",
    },
    "shared": {
        "accent": "#d78143",
        "accent-2": "#c76439",
        "glow-a": "rgba(215, 129, 67, 0.076)",
        "glow-b": "rgba(199, 100, 57, 0.045)",
    },
    "work": {
        "accent": "#4aa3ff",
        "accent-2": "#3674a4",
        "glow-a": "rgba(74, 163, 255, 0.075)",
        "glow-b": "rgba(54, 116, 164, 0.045)",
    },
    "private": {
        "accent": "#97afc1",
        "accent-2": "#7ec5bd",
        "glow-a": "rgba(151, 175, 193, 0.072)",
        "glow-b": "rgba(126, 197, 189, 0.043)",
    },
    "agents": {
        "accent": "#9cb6ef",
        "accent-2": "#88d0de",
        "glow-a": "rgba(156, 182, 239, 0.073)",
        "glow-b": "rgba(136, 208, 222, 0.043)",
    },
}

AGENT_GROUP_OVERRIDES = {
    "norman": "norman",
    "autocamera": "personal",
    "housebot": "personal",
    "castle": "personal",
    "glimpser": "personal",
    "phone-ops": "personal",
    "uscache": "personal",
    "earlybird": "personal",
    "infra": "shared",
    "cloudagent": "shared",
    "networking": "shared",
    "uplink": "shared",
    "theseus": "shared",
    "keystone": "work",
    "compere": "work",
    "control-plane": "work",
    "leadership-kpis": "work",
    "market-sizing": "work",
    "gold-book": "work",
    "platinum-standard": "work",
    "panelbot": "work",
    "scout": "work",
    "tmi-dashboards": "work",
    "parkergale": "work",
}

WORK_BOT_THEME_SLUGS = (
    "keystone",
    "compere",
    "earlybird",
    "infra",
    "control-plane",
    "leadership-kpis",
    "market-sizing",
    "gold-book",
    "platinum-standard",
    "panelbot",
    "scout",
    "tmi-dashboards",
    "parkergale",
)

WORK_BOT_ACCENT = {
    "accent": "#4aa3ff",
    "accent-2": "#3674a4",
    "glow-a": "rgba(74, 163, 255, 0.075)",
    "glow-b": "rgba(54, 116, 164, 0.045)",
}

CONSOLE_LANE_DEFS = {
    "make": {
        "label": "Make",
        "description": "Build, write, sketch, and steer the castle.",
        "eyebrow": "Primary",
    },
    "explore": {
        "label": "Explore",
        "description": "Research, scout ideas, and investigate what feels alive.",
        "eyebrow": "Scout",
    },
    "review": {
        "label": "Review",
        "description": "Shared context, Monday-Friday syncs, and handoffs.",
        "eyebrow": "Sync",
    },
    "operate": {
        "label": "Operate",
        "description": "Live systems in reserve when they actually need attention.",
        "eyebrow": "Reserve",
    },
}

CONSOLE_GROUP_NOTES = {
    "norman": "Hub, routing, and strategy surfaces.",
    "personal": "Build, tinker, and castle work.",
    "shared": "Shared context, check-ins, and coordination.",
    "work": "Ops, dashboards, and delegated follow-through.",
    "private": "Fallback tools and admin surfaces.",
    "agents": "Nearby surfaces for this cluster.",
}

CONSOLE_EXPLORE_HINTS = (
    "glimpser",
    "market",
    "gold book",
    "leadership",
    "camera",
    "autocamera",
    "invest",
    "research",
    "theseus",
)

AGENT_PROFILE_OVERRIDES = {
    "autocamera": "dusk",
    "housebot": "dusk",
    "castle": "dusk",
    "glimpser": "dusk",
    "phone-ops": "dusk",
    "uscache": "dusk",
    "keystone": "slate",
    "compere": "slate",
    "earlybird": "dusk",
    "infra": "ember",
    "control-plane": "slate",
    "leadership-kpis": "slate",
    "market-sizing": "slate",
    "gold-book": "slate",
    "platinum-standard": "slate",
    "panelbot": "slate",
    "tmi-dashboards": "slate",
    "theseus": "ember",
    "norman": "tide",
    "cloudagent": "ember",
    "networking": "ember",
    "uplink": "ember",
    "parkergale": "slate",
}

for _slug in WORK_BOT_THEME_SLUGS:
    AGENT_PROFILE_OVERRIDES[_slug] = "blueprint"

AGENT_ACCENT_OVERRIDES = {
    "autocamera": {
        "accent": "#8fd2bf",
        "accent-2": "#78b8de",
        "glow-a": "rgba(143, 210, 191, 0.07)",
        "glow-b": "rgba(120, 184, 222, 0.042)",
    },
    "housebot": {
        "accent": "#8fcfb8",
        "accent-2": "#7bb4dc",
        "glow-a": "rgba(143, 207, 184, 0.07)",
        "glow-b": "rgba(123, 180, 220, 0.045)",
    },
    "castle": {
        "accent": "#d89b88",
        "accent-2": "#c17aa3",
        "glow-a": "rgba(216, 155, 136, 0.075)",
        "glow-b": "rgba(193, 122, 163, 0.045)",
    },
    "glimpser": {
        "accent": "#c3a6f2",
        "accent-2": "#8fc6f2",
        "glow-a": "rgba(195, 166, 242, 0.075)",
        "glow-b": "rgba(143, 198, 242, 0.045)",
    },
    "phone-ops": {
        "accent": "#e7a0c5",
        "accent-2": "#9f9bea",
        "glow-a": "rgba(231, 160, 197, 0.075)",
        "glow-b": "rgba(159, 155, 234, 0.045)",
    },
    "uscache": {
        "accent": "#89cdbb",
        "accent-2": "#7fbadf",
        "glow-a": "rgba(137, 205, 187, 0.072)",
        "glow-b": "rgba(127, 186, 223, 0.044)",
    },
    "keystone": {
        "accent": "#d8ab75",
        "accent-2": "#c58a68",
        "glow-a": "rgba(216, 171, 117, 0.076)",
        "glow-b": "rgba(197, 138, 104, 0.045)",
    },
    "compere": {
        "accent": "#d8ab75",
        "accent-2": "#c58a68",
        "glow-a": "rgba(216, 171, 117, 0.076)",
        "glow-b": "rgba(197, 138, 104, 0.045)",
    },
    "earlybird": {
        "accent": "#e0be73",
        "accent-2": "#d48f66",
        "glow-a": "rgba(224, 190, 115, 0.075)",
        "glow-b": "rgba(212, 143, 102, 0.044)",
    },
    "infra": {
        "accent": "#9fb4c8",
        "accent-2": "#82c8bb",
        "glow-a": "rgba(159, 180, 200, 0.07)",
        "glow-b": "rgba(130, 200, 187, 0.043)",
    },
    "control-plane": {
        "accent": "#97a7e9",
        "accent-2": "#b6a0dd",
        "glow-a": "rgba(151, 167, 233, 0.072)",
        "glow-b": "rgba(182, 160, 221, 0.043)",
    },
    "leadership-kpis": {
        "accent": "#c59de0",
        "accent-2": "#dc9fbf",
        "glow-a": "rgba(197, 157, 224, 0.074)",
        "glow-b": "rgba(220, 159, 191, 0.044)",
    },
    "market-sizing": {
        "accent": "#7bc6d2",
        "accent-2": "#88abf0",
        "glow-a": "rgba(123, 198, 210, 0.072)",
        "glow-b": "rgba(136, 171, 240, 0.043)",
    },
    "gold-book": {
        "accent": "#e2b84e",
        "accent-2": "#f2d36b",
        "glow-a": "rgba(226, 184, 78, 0.078)",
        "glow-b": "rgba(242, 211, 107, 0.05)",
    },
    "platinum-standard": {
        "accent": "#c6d6ee",
        "accent-2": "#8ca5c9",
        "glow-a": "rgba(198, 214, 238, 0.074)",
        "glow-b": "rgba(140, 165, 201, 0.044)",
    },
    "panelbot": {
        "accent": "#76d4c5",
        "accent-2": "#7db6f1",
        "glow-a": "rgba(118, 212, 197, 0.072)",
        "glow-b": "rgba(125, 182, 241, 0.043)",
    },
    "tmi-dashboards": {
        "accent": "#ca9de4",
        "accent-2": "#91b5f4",
        "glow-a": "rgba(202, 157, 228, 0.074)",
        "glow-b": "rgba(145, 181, 244, 0.044)",
    },
    "theseus": {
        "accent": "#8fb9e6",
        "accent-2": "#7fd0bc",
        "glow-a": "rgba(143, 185, 230, 0.072)",
        "glow-b": "rgba(127, 208, 188, 0.042)",
    },
    "norman": {
        "accent": "#9cb6ef",
        "accent-2": "#88d0de",
        "glow-a": "rgba(156, 182, 239, 0.073)",
        "glow-b": "rgba(136, 208, 222, 0.043)",
    },
    "cloudagent": {
        "accent": "#90bbee",
        "accent-2": "#8dd2c5",
        "glow-a": "rgba(144, 187, 238, 0.073)",
        "glow-b": "rgba(141, 210, 197, 0.043)",
    },
    "networking": {
        "accent": "#7fb7ff",
        "accent-2": "#6fd7ef",
        "glow-a": "rgba(127, 183, 255, 0.075)",
        "glow-b": "rgba(111, 215, 239, 0.045)",
    },
    "uplink": {
        "accent": "#75d0c6",
        "accent-2": "#89afe9",
        "glow-a": "rgba(117, 208, 198, 0.074)",
        "glow-b": "rgba(137, 175, 233, 0.044)",
    },
}

for _slug in WORK_BOT_THEME_SLUGS:
    AGENT_ACCENT_OVERRIDES[_slug] = dict(WORK_BOT_ACCENT)

STYLE_VARIANTS: dict[str, dict[str, str]] = {
    "anchor": {
        "brand-radius": "15px",
        "chrome-pill-radius": "999px",
        "body-overlay-opacity": "0.34",
        "body-edge-opacity": "0.62",
        "body-accent-angle": "94deg",
        "topbar-glint-opacity": "0.58",
        "topbar-edge-opacity": "0.76",
        "topbar-saturate": "126%",
        "topbar-blur": "15px",
    },
    "signal": {
        "font-ui-wide": '"IBM Plex Sans Condensed", "Bahnschrift", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
        "brand-radius": "14px",
        "chrome-pill-radius": "13px",
        "body-overlay-opacity": "0.36",
        "body-edge-opacity": "0.70",
        "body-accent-angle": "102deg",
        "topbar-glint-opacity": "0.52",
        "topbar-edge-opacity": "0.80",
        "topbar-saturate": "136%",
        "topbar-blur": "17px",
    },
    "editorial": {
        "font-reading": '"Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif',
        "brand-radius": "17px",
        "chrome-pill-radius": "999px",
        "body-overlay-opacity": "0.31",
        "body-edge-opacity": "0.60",
        "body-accent-angle": "88deg",
        "topbar-glint-opacity": "0.54",
        "topbar-edge-opacity": "0.72",
        "topbar-saturate": "122%",
        "topbar-blur": "15px",
    },
    "grove": {
        "font-ui": '"Segoe UI Variable Text", "IBM Plex Sans", "Segoe UI", Helvetica, Arial, sans-serif',
        "font-body": '"Segoe UI Variable Text", "IBM Plex Sans", "Segoe UI", Helvetica, Arial, sans-serif',
        "brand-radius": "18px",
        "chrome-pill-radius": "16px",
        "body-overlay-opacity": "0.34",
        "body-edge-opacity": "0.64",
        "body-accent-angle": "82deg",
        "topbar-glint-opacity": "0.62",
        "topbar-edge-opacity": "0.78",
        "topbar-saturate": "130%",
        "topbar-blur": "18px",
    },
    "alloy": {
        "font-ui-wide": '"Segoe UI Variable Display", "Bahnschrift", "IBM Plex Sans Condensed", "Segoe UI", Helvetica, Arial, sans-serif',
        "brand-radius": "13px",
        "chrome-pill-radius": "12px",
        "body-overlay-opacity": "0.36",
        "body-edge-opacity": "0.70",
        "body-accent-angle": "108deg",
        "topbar-glint-opacity": "0.48",
        "topbar-edge-opacity": "0.80",
        "topbar-saturate": "138%",
        "topbar-blur": "16px",
    },
    "quiet": {
        "brand-radius": "16px",
        "chrome-pill-radius": "999px",
        "body-overlay-opacity": "0.28",
        "body-edge-opacity": "0.54",
        "body-accent-angle": "96deg",
        "topbar-glint-opacity": "0.42",
        "topbar-edge-opacity": "0.64",
        "topbar-saturate": "120%",
        "topbar-blur": "14px",
    },
}

STYLE_VARIANT_ORDER = tuple(STYLE_VARIANTS)

AGENT_STYLE_VARIANT_OVERRIDES = {
    "norman": "anchor",
    "housebot": "anchor",
    "infra": "anchor",
    "autocamera": "grove",
    "theseus": "alloy",
    "control-plane": "alloy",
    "cloudagent": "grove",
    "networking": "signal",
    "uplink": "signal",
    "earlybird": "grove",
    "scout": "quiet",
    "leadership-kpis": "editorial",
    "gold-book": "editorial",
    "platinum-standard": "alloy",
    "panelbot": "signal",
    "market-sizing": "anchor",
    "parkergale": "editorial",
    "pefb": "editorial",
}

OPENBRAND_FONT_AGENT_SLUGS = {
    "parkergale",
    "pefb",
}

WORK_FONT_VARS = {
    "font-ui": '"Poppins", "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
    "font-ui-wide": '"Poppins", "IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
    "font-body": '"Poppins", "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
    "font-reading": '"Poppins", "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
    "font-brand": '"Poppins", "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
    "font-label": '"Poppins", "IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
    "type-brand-size": "1rem",
    "type-reading-size": "0.94rem",
}

AGENT_FONT_OVERRIDES = {
    "null-agent": {
        "font-brand": '"IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace',
        "font-label": '"IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace',
        "type-brand-size": "0.98rem",
        "type-reading-size": "0.92rem",
    },
    "gold-book": {
        "font-brand": '"Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif',
        "font-label": '"IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
        "type-brand-size": "1.02rem",
        "type-reading-size": "0.96rem",
    },
    "platinum-standard": {
        "font-brand": '"Poppins", "IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
        "type-brand-size": "1.01rem",
        "type-reading-size": "0.94rem",
    },
}

AGENT_TEXTURE_GROUP_OVERRIDES = {
    "earlybird": "work",
    "theseus": "personal",
    "mls": "work",
    "pefb": "private",
}

TEXTURE_GROUP_VARS = {
    "norman": {
        "texture-angle": "112deg",
        "texture-cross-angle": "22deg",
        "texture-spacing": "30px",
        "texture-cross-spacing": "48px",
        "page-texture-opacity": "0.16",
        "page-cross-texture-opacity": "0.06",
        "chrome-detail-opacity": "0.12",
        "brand-wash-opacity": "0.18",
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": "0.14",
        "message-detail-opacity": "0",
        "agent-accent-3": "#b5f4e8",
    },
    "personal": {
        "texture-angle": "74deg",
        "texture-cross-angle": "164deg",
        "texture-spacing": "32px",
        "texture-cross-spacing": "52px",
        "page-texture-opacity": "0.12",
        "page-cross-texture-opacity": "0.05",
        "chrome-detail-opacity": "0.10",
        "brand-wash-opacity": "0.10",
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": "0.10",
        "message-detail-opacity": "0",
        "agent-accent-3": "#f0c879",
    },
    "shared": {
        "texture-angle": "96deg",
        "texture-cross-angle": "6deg",
        "texture-spacing": "36px",
        "texture-cross-spacing": "60px",
        "page-texture-opacity": "0.12",
        "page-cross-texture-opacity": "0.05",
        "chrome-detail-opacity": "0.10",
        "brand-wash-opacity": "0.10",
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": "0.10",
        "message-detail-opacity": "0",
        "agent-accent-3": "#ef9f67",
    },
    "work": {
        "texture-angle": "128deg",
        "texture-cross-angle": "38deg",
        "texture-spacing": "30px",
        "texture-cross-spacing": "48px",
        "page-texture-opacity": "0.13",
        "page-cross-texture-opacity": "0.05",
        "chrome-detail-opacity": "0.11",
        "brand-wash-opacity": "0.11",
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": "0.11",
        "message-detail-opacity": "0",
        "agent-accent-3": "#a8c9ff",
    },
    "private": {
        "texture-angle": "58deg",
        "texture-cross-angle": "148deg",
        "texture-spacing": "38px",
        "texture-cross-spacing": "62px",
        "page-texture-opacity": "0.10",
        "page-cross-texture-opacity": "0.04",
        "chrome-detail-opacity": "0.09",
        "brand-wash-opacity": "0.09",
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": "0.09",
        "message-detail-opacity": "0",
        "agent-accent-3": "#c8d7e3",
    },
    "agents": {
        "texture-angle": "90deg",
        "texture-cross-angle": "0deg",
        "texture-spacing": "34px",
        "texture-cross-spacing": "56px",
        "page-texture-opacity": "0.10",
        "page-cross-texture-opacity": "0.04",
        "chrome-detail-opacity": "0.09",
        "brand-wash-opacity": "0.09",
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": "0.09",
        "message-detail-opacity": "0",
        "agent-accent-3": "#bad1f7",
    },
}

AGENT_TEXTURE_OVERRIDES = {
    "norman": {
        "texture-angle": "118deg",
        "texture-spacing": "28px",
        "texture-cross-spacing": "44px",
        "page-texture-opacity": "0.20",
        "page-cross-texture-opacity": "0.08",
        "chrome-detail-opacity": "0.16",
        "brand-wash-opacity": "0.20",
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": "0.16",
        "message-detail-opacity": "0",
        "agent-accent-3": "#a8f7ea",
    },
    "gold-book": {
        "texture-angle": "42deg",
        "texture-spacing": "28px",
        "brand-wash-opacity": "0.20",
        "composer-detail-opacity": "0",
        "agent-accent-3": "#f1d184",
    },
    "platinum-standard": {
        "texture-angle": "135deg",
        "texture-cross-angle": "45deg",
        "texture-spacing": "26px",
        "composer-cross-detail-opacity": "0",
        "agent-accent-3": "#c7d5e8",
    },
    "null-agent": {
        "texture-angle": "0deg",
        "texture-cross-angle": "90deg",
        "texture-spacing": "24px",
        "texture-cross-spacing": "24px",
        "page-texture-opacity": "0.10",
        "page-cross-texture-opacity": "0.06",
        "chrome-detail-opacity": "0.08",
        "brand-wash-opacity": "0.08",
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": "0.08",
        "message-detail-opacity": "0",
        "agent-accent-3": "#a6b3c1",
    },
}

FALLBACK_PROFILE_ORDER = (
    "dusk",
    "slate",
    "evergreen",
    "ember",
    "tide",
    "orchid",
    "dawn",
    "mist",
    "sage",
    "parchment",
    "foam",
    "petal",
)

FALLBACK_AGENT_ACCENTS = (
    {
        "accent": "#9cb6ef",
        "accent-2": "#88d0de",
        "glow-a": "rgba(156, 182, 239, 0.073)",
        "glow-b": "rgba(136, 208, 222, 0.043)",
    },
    {
        "accent": "#d8ab75",
        "accent-2": "#c58a68",
        "glow-a": "rgba(216, 171, 117, 0.076)",
        "glow-b": "rgba(197, 138, 104, 0.045)",
    },
    {
        "accent": "#8fcfb8",
        "accent-2": "#7bb4dc",
        "glow-a": "rgba(143, 207, 184, 0.07)",
        "glow-b": "rgba(123, 180, 220, 0.045)",
    },
    {
        "accent": "#c3a6f2",
        "accent-2": "#8fc6f2",
        "glow-a": "rgba(195, 166, 242, 0.075)",
        "glow-b": "rgba(143, 198, 242, 0.045)",
    },
    {
        "accent": "#e7a0c5",
        "accent-2": "#9f9bea",
        "glow-a": "rgba(231, 160, 197, 0.075)",
        "glow-b": "rgba(159, 155, 234, 0.045)",
    },
    {
        "accent": "#7bc6d2",
        "accent-2": "#88abf0",
        "glow-a": "rgba(123, 198, 210, 0.072)",
        "glow-b": "rgba(136, 171, 240, 0.043)",
    },
)

RESPONSE_SPEED_TO_REASONING = {
    "fast": "low",
    "balanced": "medium",
    "careful": "xhigh",
}
RESPONSE_DETAIL_LABELS = {
    1: "Simple",
    2: "Lean",
    3: "Balanced",
    4: "Detailed",
    5: "Deep",
}
RESPONSE_DETAIL_INSTRUCTIONS = {
    1: "Use the minimum words needed. Prefer one short paragraph or a very short list. Skip background unless it is essential.",
    2: "Stay concise and practical. Keep explanation lean and avoid extra context unless it clearly helps.",
    3: "Use balanced depth. Cover the main answer, the key rationale, and the next useful detail.",
    4: "Go a layer deeper. Explain the reasoning, tradeoffs, and relevant context while staying organized.",
    5: "Be thorough. Include the important context, tradeoffs, and next steps, but stay concrete and readable.",
}


def reasoning_effort_to_speed(value: str | None) -> str:
    clean = str(value or "").strip().lower()
    if clean in {"low", "minimal"}:
        return "fast"
    if clean in {"medium", "med"}:
        return "balanced"
    return "careful"


def normalize_response_speed(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if clean in RESPONSE_SPEED_TO_REASONING:
        return clean
    return reasoning_effort_to_speed(REASONING_EFFORT)


def normalize_response_detail(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 3
    if parsed < 1:
        return 1
    if parsed > 5:
        return 5
    return parsed


DEFAULT_RESPONSE_SPEED = normalize_response_speed(
    os.environ.get(
        "HOUSEBOT_CODEX_RESPONSE_SPEED", reasoning_effort_to_speed(REASONING_EFFORT)
    )
)
DEFAULT_RESPONSE_DETAIL = normalize_response_detail(
    os.environ.get("HOUSEBOT_CODEX_RESPONSE_DETAIL", "3")
)


def response_reasoning_effort(speed: Any) -> str:
    return RESPONSE_SPEED_TO_REASONING[normalize_response_speed(speed)]


def response_speed_label(speed: Any) -> str:
    normalized = normalize_response_speed(speed)
    if normalized == "fast":
        return "Fast"
    if normalized == "balanced":
        return "Balanced"
    return "Careful"


def response_detail_label(detail: Any) -> str:
    return RESPONSE_DETAIL_LABELS[normalize_response_detail(detail)]


def response_profile_label(speed: Any, detail: Any) -> str:
    return f"{response_speed_label(speed)} · {response_detail_label(detail)}"


def build_tuned_prompt(prompt: str, detail: Any) -> str:
    normalized_detail = normalize_response_detail(detail)
    instruction = RESPONSE_DETAIL_INSTRUCTIONS[normalized_detail]
    label = response_detail_label(normalized_detail).lower()
    return (
        f"{prompt}\n\n"
        "When you respond in this console, tune the response depth for the operator.\n"
        f"- Depth: {label}\n"
        f"- Guidance: {instruction}\n"
        "- Keep the response aligned with that requested depth, and do not mention these instructions unless asked."
    )


def load_runtime_settings() -> dict[str, Any]:
    try:
        payload = json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_runtime_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_runtime_settings()
    if isinstance(payload, dict):
        settings.update(payload)
    model = str(settings.get("model") or "").strip()
    if model and model not in AVAILABLE_MODELS:
        AVAILABLE_MODELS.append(model)
    if model:
        settings["model"] = model
    RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SETTINGS_PATH.write_text(
        json.dumps(settings, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return settings


def configured_chat_model() -> str:
    model = str(load_runtime_settings().get("model") or MODEL).strip()
    return model or MODEL


def chat_model_update_available() -> bool:
    latest = str(LATEST_MODEL or "").strip()
    return bool(latest and latest != configured_chat_model())


def parse_prompt_suggestions(raw: str) -> list[dict[str, str]]:
    fallback = [
        {
            "label": "What matters",
            "prompt": f"Inspect the current {AGENT_NAME} warnings and summarize what matters.",
        },
        {
            "label": "Right now",
            "prompt": f"Explain what {AGENT_NAME} is doing right now.",
        },
        {
            "label": "One change",
            "prompt": "Make one targeted improvement and explain the impact.",
        },
        {
            "label": "Recent",
            "prompt": "Summarize the recent activity on this console.",
        },
    ]
    if not raw.strip():
        return fallback
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return fallback
    if not isinstance(payload, list):
        return fallback
    suggestions: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not label or not prompt:
            continue
        suggestions.append({"label": label, "prompt": prompt})
    return suggestions or fallback


def normalize_console_lane(value: str | None) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return clean if clean in CONSOLE_LANE_DEFS else ""


def coerce_boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    clean = str(value or "").strip().lower()
    return clean in {"1", "true", "yes", "on"}


def parse_console_links(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    links: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        group = str(item.get("group") or "").strip()
        url = str(item.get("url") or "").strip()
        lan_url = str(item.get("lan_url") or "").strip()
        if not label or not url:
            continue
        note = str(item.get("note") or "").strip()
        lane = normalize_console_lane(item.get("lane"))
        icon = str(item.get("icon") or "").strip()
        try:
            priority = int(item.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        rendered: dict[str, Any] = {
            "label": label,
            "group": group,
            "url": url,
            "lan_url": lan_url,
            "featured": coerce_boolish(item.get("featured")),
            "priority": priority,
        }
        if note:
            rendered["note"] = note
        if lane:
            rendered["lane"] = lane
        if icon:
            rendered["icon"] = icon
        links.append(rendered)
    return links


def load_console_links() -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in load_console_links_file():
        key = (
            str(item.get("group") or ""),
            str(item.get("label") or ""),
            str(item.get("url") or ""),
            str(item.get("lan_url") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        links.append(item)
    for raw in (
        os.environ.get("HOUSEBOT_CODEX_LINKS_JSON", "[]"),
        os.environ.get("HOUSEBOT_CODEX_EXTRA_LINKS_JSON", "[]"),
    ):
        for item in parse_console_links(raw):
            key = (
                str(item.get("group") or ""),
                str(item.get("label") or ""),
                str(item.get("url") or ""),
                str(item.get("lan_url") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            links.append(item)
    agent_name = str(os.environ.get("HOUSEBOT_CODEX_AGENT_NAME") or "").strip().lower()
    canonical_host = (
        str(os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST") or "").strip().lower()
    )
    if agent_name == "norman" and canonical_host == "norman.home.arpa":
        for item in (
            {
                "group": "Norman",
                "label": "Switchboard deck",
                "url": "https://norman.home.arpa/dashboard.html?view=switchboard",
                "note": "coordination deck",
                "featured": True,
                "priority": 260,
            },
            {
                "group": "Norman",
                "label": "Directory",
                "url": "https://norman.home.arpa/systems.html",
                "note": "estate directory",
                "featured": True,
                "priority": 250,
            },
            {
                "group": "Norman",
                "label": "Settings",
                "url": "https://norman.home.arpa/settings.html",
                "note": "control plane",
                "priority": 240,
            },
            {
                "group": "Pipeline",
                "label": "Connectors",
                "url": "https://norman.home.arpa/connectors.html",
                "note": "pipeline connectors",
                "priority": 220,
            },
            {
                "group": "Pipeline",
                "label": "Sources",
                "url": "https://norman.home.arpa/channels.html",
                "note": "channel sources",
                "priority": 210,
            },
            {
                "group": "Pipeline",
                "label": "Filters",
                "url": "https://norman.home.arpa/filters.html",
                "note": "routing filters",
                "priority": 200,
            },
            {
                "group": "Pipeline",
                "label": "Actions",
                "url": "https://norman.home.arpa/actions.html",
                "note": "routing actions",
                "priority": 190,
            },
        ):
            key = (
                str(item.get("group") or ""),
                str(item.get("label") or ""),
                str(item.get("url") or ""),
                str(item.get("lan_url") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            links.append(item)
    return links


def load_console_links_file() -> list[dict[str, Any]]:
    path = STATE_DIR / "console_links.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    raw_links = payload.get("links") if isinstance(payload, dict) else payload
    if not isinstance(raw_links, list):
        return []
    return parse_console_links(json.dumps(raw_links))


ICON_FALLBACK = "◦"
ICON_ALIASES: dict[str, str] = {
    "light": "☼",
    "dark": "☾",
    "norman": "◈",
    "toy box": "⌂",
    "housebot": "⌂",
    "work": "◫",
    "work-special": "◫",
    "networking": "⌁",
    "networking-host": "⌁",
    "uplink": "◌",
    "cloudagent": "☁",
    "glimpser": "◉",
    "autocamera": "◎",
    "castle": "⛫",
    "phone ops": "✆",
    "phone-ops": "✆",
    "uscache": "▤",
    "earlybird": "↗",
    "compere": "◇",
    "keystone": "◇",
    "control plane": "⌘",
    "control-plane": "⌘",
    "infra": "▣",
    "leadership kpis": "◍",
    "leadership-kpis": "◍",
    "market sizing": "△",
    "market-sizing": "△",
    "panelbot": "▥",
    "tmi dashboards": "▧",
    "tmi-dashboards": "▧",
    "gold book": "✦",
    "gold-book": "✦",
    "platinum standard": "⬡",
    "platinum-standard": "⬡",
    "theseus": "⌬",
    "hal": "◎",
    "workspace": "↗",
    "bridge state": "◎",
    "route": "⇄",
    "auto": "◌",
    "lan": "⌁",
    "host": "⌁",
    "tui": "▣",
    "mode": "◐",
    "palette": "✶",
    "finish": "◫",
    "phone history": "◴",
    "desktop history": "◷",
    "screen": "▣",
    "density": "⋮",
    "browse": "↗",
    "pace": "▸",
    "depth": "◌",
    "notifications": "✺",
    "system": "⌘",
    "view": "◫",
    "refresh": "↻",
    "theme": "◐",
    "history": "◴",
    "latest": "↓",
    "send": "↗",
}
ENTITY_MARK_ALIASES: dict[str, str] = {
    "norman": "N",
    "toy box": "TB",
    "housebot": "HB",
    "work": "WK",
    "networking": "NW",
    "uplink": "UP",
    "cloudagent": "CA",
    "glimpser": "GL",
    "autocamera": "AC",
    "castle": "CS",
    "phone ops": "PH",
    "phone-ops": "PH",
    "uscache": "US",
    "earlybird": "EB",
    "compere": "CP",
    "keystone": "KS",
    "control plane": "CP",
    "control-plane": "CP",
    "infra": "IF",
    "leadership kpis": "LK",
    "leadership-kpis": "LK",
    "market sizing": "MS",
    "market-sizing": "MS",
    "panelbot": "PB",
    "tmi dashboards": "TD",
    "tmi-dashboards": "TD",
    "gold book": "GB",
    "gold-book": "GB",
    "platinum standard": "PL",
    "platinum-standard": "PL",
    "theseus": "TH",
    "hal": "HL",
    "norman prime": "N1",
    "norman-prime": "N1",
    "norman ops": "NO",
    "norman-ops": "NO",
    "switchboard": "SW",
    "norman subprime": "SU",
    "norman-subprime": "SU",
    "subprime": "SU",
    "scout ranger": "SR",
    "scout-ranger": "SR",
    "diamond roc": "DR",
    "diamond-roc": "DR",
    "eyebat": "EB",
    "personal": "PS",
    "shared": "SH",
    "private": "PV",
    "family": "FM",
    "operator": "ME",
    "agents": "AG",
    "operator": "KR",
    "kris": "KR",
    "me": "KR",
    "lollie": "LO",
    "david": "DV",
    "dave": "DV",
    "paul": "PL",
    "james": "JM",
    "annie": "AN",
    "chicago": "CH",
    "harbor light": "HL",
    "exercise room": "ER",
    "office": "OF",
    "kitchen": "KT",
    "garage": "GR",
    "basement": "BS",
    "living room": "LR",
}

INLINE_HOST_ENTITY_ALIASES: dict[str, dict[str, Any]] = {
    "hal": {
        "label": "Hal",
        "aliases": ("hal", "hal.home.arpa", "hal.tail00000.ts.net", "192.168.0.137"),
    },
    "phobos": {"label": "Phobos", "aliases": ("phobos",)},
    "sun": {"label": "Sun", "aliases": ("Sun",), "strict_case": True},
    "makemake": {"label": "Makemake", "aliases": ("makemake", "Makemake")},
    "io": {"label": "Io", "aliases": ("Io",), "strict_case": True},
    "knox": {"label": "Knox", "aliases": ("Knox", "knox")},
    "toy-box": {
        "label": "Toy Box",
        "aliases": (
            "toy-box",
            "toy box",
            "Toy Box",
            "toy-box.home.arpa",
            "toy-box.tail00000.ts.net",
            "192.168.0.146",
        ),
    },
    "work-special": {
        "label": "Work Special",
        "aliases": (
            "work-special",
            "work special",
            "Work Special",
            "work-special.home.arpa",
            "work-special.tail00000.ts.net",
            "192.168.0.147",
        ),
    },
    "networking-host": {
        "label": "Networking Host",
        "aliases": (
            "networking-host",
            "networking host",
            "Networking Host",
            "networking-host.home.arpa",
            "networking.tail00000.ts.net",
            "192.168.0.242",
        ),
    },
    "private-host": {
        "label": "Private Host",
        "aliases": (
            "private-host",
            "private host",
            "Private Host",
            "private.home.example.test",
            "192.168.0.148",
        ),
    },
    "norman-host": {
        "label": "Norman Host",
        "aliases": (
            "norman-host",
            "norman host",
            "Norman Host",
            "norman.home.arpa",
            "norman.tail00000.ts.net",
            "192.168.0.241",
        ),
    },
    "phobos-host": {
        "label": "Phobos Host",
        "aliases": ("phobos-host", "phobos host", "Phobos Host"),
    },
    "pluto": {"label": "Pluto", "aliases": ("pluto", "Pluto")},
    "quaoar": {"label": "Quaoar", "aliases": ("quaoar", "Quaoar")},
}

INLINE_TUI_ENTITY_DEFS: dict[str, dict[str, Any]] = {
    "norman-prime": {
        "label": "Norman Prime",
        "aliases": ("Norman Prime", "Prime", "Norman console", "Norman session"),
        "group": "norman",
    },
    "switchboard": {
        "label": "Switchboard",
        "aliases": ("Switchboard", "switchboard"),
        "group": "norman",
    },
    "subprime": {
        "label": "Norman Subprime",
        "aliases": ("Norman Subprime", "Subprime", "subprime"),
        "group": "norman",
    },
    "housebot": {
        "label": "Housebot",
        "aliases": ("Housebot", "housebot"),
        "group": "personal",
    },
    "scout-ranger": {
        "label": "Scout Ranger",
        "aliases": ("Scout Ranger", "Scout / Ranger", "Scout", "Ranger"),
        "group": "work",
    },
    "phone-ops": {
        "label": "Phone Ops",
        "aliases": ("Phone Ops", "phone-ops", "phone ops"),
        "group": "personal",
    },
    "norman-ops": {
        "label": "Norman Ops",
        "aliases": ("Norman Ops", "norman-ops", "norman ops"),
        "group": "norman",
    },
    "control-plane": {
        "label": "Control Plane",
        "aliases": ("Control Plane", "control-plane", "control plane"),
        "group": "norman",
    },
    "diamond-roc": {
        "label": "Diamond ROC",
        "aliases": ("Diamond ROC", "Diamond Roc", "diamond roc", "diamond-roc"),
        "group": "work",
    },
    "eyebat": {
        "label": "Eyebat",
        "aliases": (
            "Eyebat",
            "eyebat",
            "Glimpser",
            "glimpser",
            "Glimpser / Eyebat",
            "Glimpse",
            "glimpse",
        ),
        "group": "personal",
    },
}

INLINE_BOT_ENTITY_DEFS: dict[str, dict[str, Any]] = {
    "norman": {"label": "Norman", "aliases": ("Norman", "norman")},
    "housebot": {"label": "Housebot", "aliases": ("Housebot", "housebot")},
    "autocamera": {"label": "Autocamera", "aliases": ("Autocamera", "autocamera")},
    "theseus": {"label": "Theseus", "aliases": ("Theseus", "theseus")},
    "cloudagent": {"label": "CloudAgent", "aliases": ("CloudAgent", "cloudagent")},
    "uplink": {"label": "Uplink", "aliases": ("Uplink", "uplink")},
    "networking": {"label": "Networking", "aliases": ("Networking", "networking")},
    "glimpser": {
        "label": "Eyebat",
        "aliases": (
            "Glimpser",
            "glimpser",
            "Eyebat",
            "eyebat",
            "Glimpse",
            "glimpse",
        ),
    },
    "control-plane": {
        "label": "Control Plane",
        "aliases": ("Control Plane", "control-plane", "control plane"),
    },
    "keystone": {"label": "Keystone", "aliases": ("Keystone", "keystone")},
    "compere": {"label": "Compere", "aliases": ("Compere", "compere")},
    "d-ace": {"label": "d.ace", "aliases": ("d.ace",), "group": "work"},
    "acast": {"label": "Acast", "aliases": ("Acast", "acast"), "group": "work"},
    "earlybird": {"label": "Earlybird", "aliases": ("Earlybird", "earlybird")},
    "scout": {"label": "Scout", "aliases": ("Scout", "scout")},
    "gold-book": {"label": "Gold Book", "aliases": ("Gold Book", "gold book")},
    "platinum-standard": {
        "label": "Platinum",
        "aliases": ("Platinum", "platinum"),
    },
    "leadership-kpis": {
        "label": "Leadership KPIs",
        "aliases": ("Leadership KPIs", "leadership KPIs"),
    },
    "panelbot": {"label": "Panelbot", "aliases": ("Panelbot", "panelbot")},
    "parkergale": {"label": "PEFB", "aliases": ("PEFB", "Pefb", "pefb")},
    "pefb": {"label": "PEFB", "aliases": ("PEFB", "Pefb", "pefb"), "group": "private"},
    "switchboard": {
        "label": "Switchboard",
        "aliases": ("Switchboard", "switchboard"),
        "group": "norman",
    },
    "subprime": {
        "label": "Subprime",
        "aliases": ("Subprime", "subprime", "Norman Subprime"),
        "group": "norman",
    },
    "diamond-roc": {
        "label": "Diamond Roc",
        "aliases": ("Diamond Roc", "diamond roc", "diamond-roc"),
    },
}

INLINE_PERSON_ENTITY_DEFS: dict[str, dict[str, Any]] = {
    "operator": {
        "label": "Operator",
        "aliases": (
            "Operator",
            "operator",
            "Kris",
            "kris",
            "me",
            "Me",
            "myself",
        ),
        "group": "operator",
    },
    "lollie": {"label": "Example", "aliases": ("Example", "lollie"), "group": "family"},
    "david": {"label": "David", "aliases": ("David", "david")},
    "dave": {"label": "Dave", "aliases": ("Dave", "dave")},
    "paul": {"label": "Paul", "aliases": ("Paul", "paul")},
    "james": {"label": "James", "aliases": ("James", "james")},
    "annie": {"label": "Annie", "aliases": ("Annie", "annie")},
}

INLINE_LOCATION_ENTITY_DEFS: dict[str, dict[str, Any]] = {
    "chicago": {"label": "Chicago", "aliases": ("Chicago", "chicago")},
    "harbor-light": {
        "label": "Harbor Light",
        "aliases": ("Harbor Light", "harbor light"),
    },
    "exercise-room": {
        "label": "Exercise Room",
        "aliases": ("Exercise Room", "exercise room"),
    },
    "office": {"label": "Office", "aliases": ("Office",), "strict_case": True},
    "kitchen": {"label": "Kitchen", "aliases": ("Kitchen",), "strict_case": True},
    "garage": {"label": "Garage", "aliases": ("Garage",), "strict_case": True},
    "basement": {"label": "Basement", "aliases": ("Basement",), "strict_case": True},
    "living-room": {
        "label": "Living Room",
        "aliases": ("Living Room", "living room"),
    },
    "crib3": {"label": "Crib3", "aliases": ("Crib3", "crib3")},
}


def icon_for_label(label: str, fallback: str = ICON_FALLBACK) -> str:
    clean = re.sub(r"[^a-z0-9]+", " ", str(label or "").strip().lower()).strip()
    if not clean:
        return fallback
    if clean in ICON_ALIASES:
        return ICON_ALIASES[clean]
    for key, icon in ICON_ALIASES.items():
        if key in clean:
            return icon
    return fallback


def entity_mark_for_label(label: str, fallback: str = "•") -> str:
    clean = re.sub(r"[^a-z0-9]+", " ", str(label or "").strip().lower()).strip()
    if not clean:
        return fallback
    if clean in ENTITY_MARK_ALIASES:
        return ENTITY_MARK_ALIASES[clean]
    for key, mark in ENTITY_MARK_ALIASES.items():
        if key in clean:
            return mark
    tokens = [token for token in re.findall(r"[A-Za-z0-9]+", str(label or "")) if token]
    if not tokens:
        return fallback
    if len(tokens) == 1:
        letters = re.sub(r"[^A-Za-z0-9]+", "", tokens[0]).upper()
        return letters[:2] or fallback
    return f"{tokens[0][0]}{tokens[1][0]}".upper()


def build_inline_entity_defs() -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for key, data in INLINE_HOST_ENTITY_ALIASES.items():
        label = str(data.get("label") or key).strip()
        aliases = tuple(
            str(alias).strip()
            for alias in (data.get("aliases") or ())
            if str(alias).strip()
        ) or (label,)
        entities.append(
            {
                "key": key,
                "label": label,
                "mark": entity_mark_for_label(label, "•"),
                "kind": "host",
                "tone": "host",
                "aliases": aliases,
                "strict_case": bool(data.get("strict_case")),
            }
        )
    for key, data in INLINE_TUI_ENTITY_DEFS.items():
        label = str(data.get("label") or key).strip()
        aliases = tuple(
            str(alias).strip()
            for alias in (data.get("aliases") or ())
            if str(alias).strip()
        ) or (label,)
        group = str(data.get("group") or semantic_agent_group(key, AGENT_GROUP)).strip()
        entities.append(
            {
                "key": key,
                "label": label,
                "mark": entity_mark_for_label(label, "•"),
                "kind": "tui",
                "tone": "tui",
                "group": group or "agents",
                "aliases": aliases,
                "strict_case": bool(data.get("strict_case")),
            }
        )
    for key, data in INLINE_BOT_ENTITY_DEFS.items():
        label = str(data.get("label") or key).strip()
        aliases = tuple(
            str(alias).strip()
            for alias in (data.get("aliases") or ())
            if str(alias).strip()
        ) or (label,)
        group = str(data.get("group") or semantic_agent_group(key, AGENT_GROUP)).strip()
        entities.append(
            {
                "key": key,
                "label": label,
                "mark": entity_mark_for_label(label, "•"),
                "kind": "bot",
                "tone": "bot",
                "group": group or "agents",
                "aliases": aliases,
                "strict_case": bool(data.get("strict_case")),
            }
        )
    for key, data in INLINE_PERSON_ENTITY_DEFS.items():
        label = str(data.get("label") or key).strip()
        aliases = tuple(
            str(alias).strip()
            for alias in (data.get("aliases") or ())
            if str(alias).strip()
        ) or (label,)
        group = str(data.get("group") or "people").strip() or "people"
        entities.append(
            {
                "key": key,
                "label": label,
                "mark": entity_mark_for_label(label, "•"),
                "kind": "person",
                "tone": "person",
                "group": group,
                "aliases": aliases,
                "strict_case": bool(data.get("strict_case")),
            }
        )
    for key, data in INLINE_LOCATION_ENTITY_DEFS.items():
        label = str(data.get("label") or key).strip()
        aliases = tuple(
            str(alias).strip()
            for alias in (data.get("aliases") or ())
            if str(alias).strip()
        ) or (label,)
        entities.append(
            {
                "key": key,
                "label": label,
                "mark": entity_mark_for_label(label, "•"),
                "kind": "location",
                "tone": "location",
                "group": "locations",
                "aliases": aliases,
                "strict_case": bool(data.get("strict_case")),
            }
        )
    return entities


def _normalize_inline_entity_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _inline_entity_for_label(label: str) -> dict[str, Any] | None:
    needle = _normalize_inline_entity_key(label)
    if not needle:
        return None
    for entity in build_inline_entity_defs():
        aliases = entity.get("aliases") or ()
        keys = [entity.get("key"), entity.get("label"), *aliases]
        if needle in {_normalize_inline_entity_key(str(item or "")) for item in keys}:
            return entity
    return None


def _inline_entity_alias_for_visible(entity: dict[str, Any], visible_label: str) -> str:
    label = str(entity.get("label") or "").strip()
    if not label:
        return ""
    return (
        label
        if _normalize_inline_entity_key(label)
        != _normalize_inline_entity_key(visible_label)
        else ""
    )


def _render_entity_cartouche(
    entity: dict[str, Any],
    visible_label: str,
    *,
    compact: bool = False,
    mention: bool = False,
    alias_for: str = "",
) -> str:
    label = str(visible_label or "").strip()
    key = str(entity.get("key") or _normalize_inline_entity_key(label))
    kind = str(entity.get("kind") or "name")
    tone = str(entity.get("tone") or kind)
    group = str(entity.get("group") or "")
    mark = str(entity.get("mark") or entity_mark_for_label(label, "•"))[:2].upper()
    decorator = str(entity.get("decorator") or "")
    if not decorator:
        decorator = {
            "host": "NET",
            "tui": "TUI",
            "bot": "◈",
            "person": "◦",
            "location": "⌂",
        }.get(
            kind,
            "@" if kind == "mention" else "·",
        )
    clean_alias_for = str(alias_for or "").strip()
    group_attr = f' data-group="{html.escape(group)}"' if group else ""
    mention_attr = ' data-mention="true"' if mention else ""
    alias_attr = (
        f' data-alias="true" data-alias-for="{html.escape(clean_alias_for)}"'
        f' title="Alias for {html.escape(clean_alias_for)}"'
        if clean_alias_for
        else ""
    )
    compact_attr = ' data-compact="true"' if compact else ""
    return (
        f'<span class="entity-cartouche" data-kind="{html.escape(kind)}" '
        f'data-tone="{html.escape(tone)}" data-entity-key="{html.escape(key)}" '
        f'data-mark="{html.escape(mark or "•")}" '
        f'data-decorator="{html.escape(decorator)}"'
        f'{group_attr}{mention_attr}{alias_attr}{compact_attr}><span class="entity-cartouche__label">'
        f"{html.escape(label)}</span></span>"
    )


def _render_name_cartouche(
    label: str,
    *,
    compact: bool = True,
    kind: str = "name",
    tone: str | None = None,
    group: str = "",
) -> str:
    clean = str(label or "").strip()
    if not clean:
        return ""
    fallback_kind = str(kind or "name")
    fallback_tone = str(tone or fallback_kind)
    entity = dict(
        _inline_entity_for_label(clean)
        or {
            "key": _normalize_inline_entity_key(clean),
            "label": clean,
            "mark": entity_mark_for_label(clean, "•"),
            "kind": fallback_kind,
            "tone": fallback_tone,
        }
    )
    if group:
        entity["group"] = str(group)
    if not entity.get("kind"):
        entity["kind"] = fallback_kind
    if not entity.get("tone"):
        entity["tone"] = fallback_tone
    return _render_entity_cartouche(
        entity,
        clean,
        compact=compact,
        alias_for=_inline_entity_alias_for_visible(entity, clean),
    )


def console_tab_title(value: str) -> str:
    text = str(value or "").strip() or str(AGENT_NAME or "").strip() or "Console"
    return re.sub(r"\s+Console$", "", text, flags=re.IGNORECASE).strip() or text


CONSOLE_TAB_TITLE = console_tab_title(CONSOLE_TITLE)


def hex_to_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    clean = str(value or "").strip()
    if clean.startswith("#"):
        clean = clean[1:]
        if len(clean) == 3:
            clean = "".join(part * 2 for part in clean)
        if len(clean) == 6:
            try:
                return tuple(int(clean[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                return fallback
    return fallback


def mix_rgb(
    first: tuple[int, int, int], second: tuple[int, int, int], ratio: float
) -> tuple[int, int, int]:
    clamped = max(0.0, min(1.0, ratio))
    return tuple(
        int(round(first[index] * (1.0 - clamped) + second[index] * clamped))
        for index in range(3)
    )


def rgb_css(rgb: tuple[int, int, int]) -> str:
    return f"rgb({rgb[0]} {rgb[1]} {rgb[2]})"


def favicon_palette(agent_key: str) -> dict[str, tuple[int, int, int]]:
    profile = UI_PROFILES[normalize_profile_name(DEFAULT_UI_PROFILE)]["vars"]
    accent_palette = AGENT_ACCENT_OVERRIDES.get(agent_key)
    if accent_palette is None:
        accent_palette = FALLBACK_AGENT_ACCENTS[
            sum(ord(ch) for ch in agent_key) % len(FALLBACK_AGENT_ACCENTS)
        ]
    bg = hex_to_rgb(
        str(profile.get("body-mid") or profile.get("bg") or "#303846"), (48, 56, 70)
    )
    surface = hex_to_rgb(str(profile.get("surface-2") or "#3f4755"), (63, 71, 85))
    border = hex_to_rgb(str(profile.get("border") or "#556174"), (85, 97, 116))
    accent = hex_to_rgb(str(accent_palette.get("accent") or "#9cb6ef"), (156, 182, 239))
    accent_2 = hex_to_rgb(
        str(accent_palette.get("accent-2") or "#88d0de"), (136, 208, 222)
    )
    text = (248, 250, 252) if sum(bg) < 420 else (34, 42, 52)
    return {
        "bg": bg,
        "surface": surface,
        "border": border,
        "accent": accent,
        "accent_2": accent_2,
        "text": text,
    }


def favicon_svg_markup(agent_key: str) -> str:
    palette = favicon_palette(agent_key)
    mark = html.escape(entity_mark_for_label(AGENT_NAME, "•"))
    font_size = "16" if len(mark) > 1 else "22"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="{html.escape(AGENT_NAME)}">
  <defs>
    <linearGradient id="g" x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="{rgb_css(palette["accent"])}"/>
      <stop offset="100%" stop-color="{rgb_css(palette["accent_2"])}"/>
    </linearGradient>
  </defs>
  <rect x="4" y="4" width="56" height="56" rx="16" fill="{rgb_css(palette["bg"])}" stroke="{rgb_css(palette["border"])}" stroke-width="2"/>
  <rect x="10" y="10" width="44" height="44" rx="13" fill="{rgb_css(palette["surface"])}"/>
  <circle cx="32" cy="32" r="14" fill="none" stroke="{rgb_css(mix_rgb(palette["border"], palette["surface"], 0.28))}" stroke-width="4" opacity="0.54"/>
  <path d="M 32 18 A 14 14 0 1 1 18 32" fill="none" stroke="url(#g)" stroke-width="4.5" stroke-linecap="round"/>
  <circle cx="45" cy="24" r="4.5" fill="{rgb_css(palette["accent_2"])}"/>
  <rect x="21" y="21" width="22" height="22" rx="8" fill="{rgb_css(mix_rgb(palette["bg"], palette["surface"], 0.72))}" stroke="{rgb_css(mix_rgb(palette["border"], palette["accent"], 0.24))}" stroke-width="1.4"/>
  <text x="32" y="36.5" text-anchor="middle" font-size="{font_size}" font-weight="700" letter-spacing="0.04em" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" fill="{rgb_css(palette["text"])}">{mark}</text>
</svg>"""


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    payload = chunk_type + data
    return (
        len(data).to_bytes(4, "big")
        + payload
        + (zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big")
    )


def favicon_png_bytes(agent_key: str, size: int = 32) -> bytes:
    palette = favicon_palette(agent_key)
    seed = sum(ord(ch) for ch in agent_key or AGENT_NAME)
    pixels = bytearray()
    inset = max(3, size // 8)
    inner_left = inset
    inner_right = size - inset - 1
    inner_top = inset
    inner_bottom = size - inset - 1
    center = size / 2.0
    ring = size * 0.19
    shape_mode = seed % 5
    for y in range(size):
        row = bytearray()
        for x in range(size):
            color = palette["bg"]
            if x in {0, size - 1} or y in {0, size - 1}:
                color = palette["border"]
            elif inner_left <= x <= inner_right and inner_top <= y <= inner_bottom:
                dx = (x - inner_left) / max(1, inner_right - inner_left)
                dy = (y - inner_top) / max(1, inner_bottom - inner_top)
                color = mix_rgb(
                    mix_rgb(palette["accent"], palette["accent_2"], dx),
                    palette["surface"],
                    max(0.0, (dy - 0.55) * 0.35),
                )
            if (x - (size - inset - 4)) ** 2 + (y - (inset + 3)) ** 2 <= max(
                4, size // 9
            ) ** 2:
                color = palette["surface"]
            distance_x = abs(x + 0.5 - center)
            distance_y = abs(y + 0.5 - center)
            if shape_mode == 0 and distance_x**2 + distance_y**2 <= ring**2:
                color = palette["text"]
            elif shape_mode == 1 and distance_x + distance_y <= ring * 1.36:
                color = palette["text"]
            elif (
                shape_mode == 2
                and distance_x <= ring * 0.48
                and distance_y <= ring * 1.18
            ):
                color = palette["text"]
            elif (
                shape_mode == 3
                and (distance_x <= ring * 0.42 or distance_y <= ring * 0.42)
                and distance_x <= ring * 1.08
                and distance_y <= ring * 1.08
            ):
                color = palette["text"]
            elif shape_mode == 4:
                radius = (distance_x**2 + distance_y**2) ** 0.5
                if ring * 0.62 <= radius <= ring * 1.02:
                    color = palette["text"]
            row.extend((color[0], color[1], color[2], 255))
        pixels.extend(b"\x00" + bytes(row))
    compressed = zlib.compress(bytes(pixels), level=9)
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = size.to_bytes(4, "big") + size.to_bytes(4, "big") + b"\x08\x06\x00\x00\x00"
    return (
        header
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", compressed)
        + png_chunk(b"IEND", b"")
    )


def favicon_ico_bytes(agent_key: str) -> bytes:
    png = favicon_png_bytes(agent_key, 32)
    directory = b"\x00\x00\x01\x00\x01\x00"
    entry = (
        b"\x20"  # width 32
        + b"\x20"  # height 32
        + b"\x00"  # colors
        + b"\x00"  # reserved
        + (1).to_bytes(2, "little")
        + (32).to_bytes(2, "little")
        + len(png).to_bytes(4, "little")
        + (6 + 16).to_bytes(4, "little")
    )
    return directory + entry + png


def normalize_path_prefix(value: str | None) -> str:
    clean = str(value or "").strip()
    if not clean or clean == "/":
        return ""
    if not clean.startswith("/"):
        clean = "/" + clean
    return clean.rstrip("/")


def prefixed_path(path: str, prefix: str = "") -> str:
    clean_path = str(path or "").strip() or "/"
    if not clean_path.startswith("/"):
        clean_path = "/" + clean_path
    clean_prefix = normalize_path_prefix(prefix)
    if not clean_prefix:
        return clean_path
    if clean_path == "/":
        return f"{clean_prefix}/"
    return f"{clean_prefix}{clean_path}"


def cookie_path_for_prefix(prefix: str = "") -> str:
    clean_prefix = normalize_path_prefix(prefix)
    return f"{clean_prefix}/" if clean_prefix else "/"


def favicon_links_html(prefix: str = "") -> str:
    version = quote(UI_VERSION, safe="")
    return (
        f'<link rel="icon" type="image/svg+xml" href="{prefixed_path("/favicon.svg", prefix)}?v={version}">\n'
        f'  <link rel="alternate icon" type="image/x-icon" href="{prefixed_path("/favicon.ico", prefix)}?v={version}">\n'
        f'  <link rel="shortcut icon" href="{prefixed_path("/favicon.ico", prefix)}?v={version}">'
    )


CONSOLE_LINKS = load_console_links()
PROMPT_SUGGESTIONS = parse_prompt_suggestions(
    os.environ.get("HOUSEBOT_CODEX_SUGGESTIONS_JSON", "")
)


def normalize_host_alias(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(f"//{raw}")
    host = (parsed.hostname or raw).strip().lower()
    return host.strip("[]")


def detect_local_host_aliases() -> set[str]:
    aliases: set[str] = set()
    for value in (socket.gethostname(), socket.getfqdn()):
        host = normalize_host_alias(value)
        if host:
            aliases.add(host)
    try:
        output = subprocess.check_output(
            ["hostname", "-A"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        output = ""
    for part in output.split():
        host = normalize_host_alias(part)
        if host:
            aliases.add(host)
    extra = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES", "")
    for part in extra.split(","):
        host = normalize_host_alias(part)
        if host:
            aliases.add(host)
    return aliases


def canonical_host_uses_direct_http(host: str) -> bool:
    candidate = normalize_host_alias(host)
    if not candidate:
        return False
    if candidate == "localhost":
        return True
    if candidate.endswith(".work.example.test"):
        return False
    if CANONICAL_VIA_PROXY:
        return False
    if (
        candidate.endswith(".home.arpa")
        or candidate.endswith(".home.example.test")
        or candidate.endswith(".tail00000.ts.net")
        or candidate.endswith(".ts.net")
        or candidate.endswith(".knox.example.test")
    ):
        return True
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return True
    return parsed.is_loopback or parsed.is_private


def host_access_mode(host: str) -> str:
    candidate = normalize_host_alias(host)
    if not candidate:
        return ""
    if candidate == "localhost":
        return "loopback"
    if candidate.endswith(".home.arpa") or candidate.endswith(".home.example.test"):
        return "lan_dns"
    if candidate.endswith(".tail00000.ts.net") or candidate.endswith(".ts.net"):
        return "tailnet"
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return "public_dns"
    if parsed.is_loopback:
        return "loopback"
    if parsed.is_private:
        return "private_ip"
    return "public_ip"


def parse_client_networks(value: str) -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for raw_part in str(value or "").split(","):
        candidate = raw_part.strip()
        if not candidate:
            continue
        try:
            if "/" in candidate:
                networks.append(ipaddress.ip_network(candidate, strict=False))
            else:
                parsed = ipaddress.ip_address(candidate)
                suffix = "/32" if parsed.version == 4 else "/128"
                networks.append(
                    ipaddress.ip_network(f"{candidate}{suffix}", strict=False)
                )
        except ValueError:
            continue
    return tuple(networks)


def client_ip_matches(
    ip_value: str, networks: tuple[ipaddress._BaseNetwork, ...]
) -> bool:
    if not ip_value or not networks:
        return False
    try:
        parsed = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    return any(parsed in network for network in networks)


LOCAL_HOST_ALIASES = detect_local_host_aliases()
CANONICAL_HOST = normalize_host_alias(
    os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST", "")
)
CANONICAL_VIA_PROXY = coerce_boolish(
    os.environ.get("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY")
)
TRUSTED_CLIENT_NETWORKS = parse_client_networks(
    os.environ.get(
        "HOUSEBOT_CODEX_TRUSTED_CLIENTS",
        "127.0.0.1,::1",
    )
)
TRUSTED_PROXY_NETWORKS = parse_client_networks(
    os.environ.get(
        "HOUSEBOT_CODEX_TRUSTED_PROXIES",
        "127.0.0.1,::1,192.168.0.241",
    )
)
TAILNET_CLIENT_NETWORKS = parse_client_networks(
    os.environ.get(
        "HOUSEBOT_CODEX_TAILNET_CLIENTS",
        "100.64.0.0/10,fd7a:115c:a1e0::/48",
    )
)
AUTH_BRIDGE_CLIENT_NETWORKS = parse_client_networks(
    os.environ.get(
        "HOUSEBOT_CODEX_BROWSER_AUTH_CLIENTS",
        os.environ.get("HOUSEBOT_CODEX_TRUSTED_CLIENTS", "127.0.0.1,::1"),
    )
)


def canonical_origin_components() -> tuple[str, str]:
    if not CANONICAL_HOST:
        return ("http", "")
    if canonical_host_uses_direct_http(CANONICAL_HOST):
        return ("http", f"{CANONICAL_HOST}:{PORT}")
    return ("https", CANONICAL_HOST)


NORMAN_HOME_ALIASES = {
    "192.168.0.241",
    "norman",
    "norman.home.arpa",
    "norman.home.example.test",
    "norman.tail00000.ts.net",
}


def normalize_profile_name(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if candidate in UI_PROFILES:
        return candidate
    return (
        DEFAULT_UI_PROFILE
        if DEFAULT_UI_PROFILE in UI_PROFILES
        else next(iter(UI_PROFILES))
    )


def profile_alias_name_from_path(path: str | None) -> str:
    clean = str(path or "").strip()
    candidate = ""
    if clean.startswith("/profile-"):
        candidate = clean[len("/profile-") :]
    elif clean.startswith("/profile/"):
        candidate = clean[len("/profile/") :]
    candidate = candidate.strip().lower().strip("/")
    return candidate if candidate in UI_PROFILES else ""


def build_profile_alias_href(
    path: str | None, params: dict[str, list[str]], *, prefix: str = ""
) -> str:
    profile = profile_alias_name_from_path(path)
    if not profile:
        return ""
    query_params = {
        key: values for key, values in params.items() if key != "profile" and values
    }
    query_params["profile"] = [profile]
    query = urlencode(query_params, doseq=True)
    base_path = prefixed_path("/", prefix)
    if not query:
        return base_path
    return f"{base_path}?{query}"


def agent_slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


AGENT_SLUG = agent_slug(AGENT_STYLE_HINT or AGENT_NAME)


def normalize_console_group_slug(value: str | None) -> str:
    return agent_slug(value)


def semantic_console_group(value: str | None) -> str:
    slug = normalize_console_group_slug(value)
    if not slug:
        return ""
    for candidate in ("norman", "personal", "shared", "work", "private"):
        if (
            slug == candidate
            or slug.startswith(f"{candidate}-")
            or slug.endswith(f"-{candidate}")
            or f"-{candidate}-" in slug
        ):
            return candidate
    return slug if slug in SEMANTIC_GROUP_PROFILES else "agents"


def semantic_agent_group(agent_key: str, agent_group: str = "") -> str:
    explicit_group = semantic_console_group(agent_group)
    if explicit_group and explicit_group != "agents":
        return explicit_group
    fallback_group = semantic_console_group(AGENT_GROUP_OVERRIDES.get(agent_key, ""))
    return fallback_group or "agents"


def resolve_default_ui_profile(configured: str, agent_key: str) -> str:
    if configured in UI_PROFILES:
        return configured
    if configured == "auto":
        configured = ""
    semantic_group = semantic_agent_group(agent_key, AGENT_GROUP)
    group_profile = SEMANTIC_GROUP_PROFILES.get(semantic_group)
    if group_profile in UI_PROFILES:
        return group_profile
    if agent_key in AGENT_PROFILE_OVERRIDES:
        return AGENT_PROFILE_OVERRIDES[agent_key]
    if not FALLBACK_PROFILE_ORDER:
        return next(iter(UI_PROFILES))
    index = sum(ord(ch) for ch in agent_key) % len(FALLBACK_PROFILE_ORDER)
    return FALLBACK_PROFILE_ORDER[index]


DEFAULT_UI_PROFILE = resolve_default_ui_profile(CONFIGURED_UI_PROFILE, AGENT_SLUG)


def agent_theme_vars_css(agent_key: str) -> str:
    semantic_group = semantic_agent_group(agent_key, AGENT_GROUP)
    palette = SEMANTIC_GROUP_ACCENTS.get(semantic_group)
    if palette is None:
        palette = AGENT_ACCENT_OVERRIDES.get(agent_key)
    if palette is None:
        palette = FALLBACK_AGENT_ACCENTS[
            sum(ord(ch) for ch in agent_key) % len(FALLBACK_AGENT_ACCENTS)
        ]
    values = {
        "accent": palette["accent"],
        "accent-2": palette["accent-2"],
        "agent-accent": palette["accent"],
        "agent-accent-2": palette["accent-2"],
        "glow-a": palette["glow-a"],
        "glow-b": palette["glow-b"],
    }
    return "\n".join(f"      --{key}: {value};" for key, value in values.items())


def resolve_style_variant(agent_key: str) -> str:
    if not STYLE_VARIANT_ORDER:
        return "anchor"
    configured = AGENT_STYLE_VARIANT_OVERRIDES.get(agent_key)
    if configured in STYLE_VARIANTS:
        return str(configured)
    index = sum(ord(ch) for ch in agent_key) % len(STYLE_VARIANT_ORDER)
    return STYLE_VARIANT_ORDER[index]


def style_variant_vars_css(agent_key: str) -> str:
    variant_name = resolve_style_variant(agent_key)
    variant = STYLE_VARIANTS.get(variant_name, {})
    lines = [f"      --style-variant-name: '{variant_name}';"]
    lines.extend(f"      --{key}: {value};" for key, value in variant.items())
    return "\n".join(lines)


def agent_texture_vars_css(agent_key: str) -> str:
    semantic_group = AGENT_TEXTURE_GROUP_OVERRIDES.get(
        agent_key, semantic_agent_group(agent_key, AGENT_GROUP)
    )
    values = dict(
        TEXTURE_GROUP_VARS.get(semantic_group) or TEXTURE_GROUP_VARS["agents"]
    )
    values.update(AGENT_TEXTURE_OVERRIDES.get(agent_key, {}))
    return "\n".join(f"      --{key}: {value};" for key, value in values.items())


def agent_font_vars_css(agent_key: str) -> str:
    semantic_group = semantic_agent_group(agent_key, AGENT_GROUP)
    values = {
        "font-brand": '"IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
        "font-label": '"IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif',
        "type-brand-size": "1rem",
        "type-reading-size": "0.94rem",
    }
    if semantic_group == "work" or agent_key in OPENBRAND_FONT_AGENT_SLUGS:
        values.update(WORK_FONT_VARS)
    values.update(AGENT_FONT_OVERRIDES.get(agent_key, {}))
    return "\n".join(f"      --{key}: {value};" for key, value in values.items())


AGENT_STYLE_VARIANT = resolve_style_variant(AGENT_SLUG)


def profile_mode(profile_name: str) -> str:
    profile = UI_PROFILES[normalize_profile_name(profile_name)]
    mode = str(profile.get("mode") or "dark").strip().lower()
    return mode if mode in PROFILE_MODE_ORDER else PROFILE_MODE_ORDER[0]


def profile_family(profile_name: str) -> str:
    profile = UI_PROFILES[normalize_profile_name(profile_name)]
    return str(profile.get("family") or normalize_profile_name(profile_name))


def profiles_for_mode(mode: str) -> list[tuple[str, dict[str, Any]]]:
    clean_mode = mode if mode in PROFILE_MODE_ORDER else PROFILE_MODE_ORDER[0]
    return [
        (slug, data)
        for slug, data in UI_PROFILES.items()
        if profile_mode(slug) == clean_mode
    ]


def profile_for_mode(profile_name: str, target_mode: str) -> str:
    target = target_mode if target_mode in PROFILE_MODE_ORDER else PROFILE_MODE_ORDER[0]
    normalized = normalize_profile_name(profile_name)
    if profile_mode(normalized) == target:
        return normalized
    family = profile_family(normalized)
    for slug in UI_PROFILES:
        if profile_mode(slug) == target and profile_family(slug) == family:
            return slug
    for slug in UI_PROFILES:
        if profile_mode(slug) == target:
            return slug
    return normalized


def profile_vars_css(profile_name: str) -> str:
    profile = UI_PROFILES[normalize_profile_name(profile_name)]
    return "\n".join(
        f"      --{key}: {value};" for key, value in profile["vars"].items()
    )


ROUTE_MODE_ORDER = ("auto", "lan", "host", "tail")


def normalize_route_mode(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if candidate in ROUTE_MODE_ORDER:
        return candidate
    return ROUTE_MODE_ORDER[0]


def build_console_href(
    *, token: str, profile: str, route: str = "", prefix: str = ""
) -> str:
    query: dict[str, str] = {}
    if token:
        query["token"] = token
    if profile:
        query["profile"] = profile
    route_mode = normalize_route_mode(route)
    if route_mode != "auto":
        query["route"] = route_mode
    root_path = prefixed_path("/", prefix)
    if not query:
        return root_path
    return f"{root_path}?{urlencode(query)}"


def build_file_href(
    *,
    token: str,
    path: str,
    profile: str = "",
    route: str = "",
    prefix: str = "",
    raw: bool = False,
    download: bool = False,
) -> str:
    clean_path, fragment = split_file_target(path)
    query: dict[str, str] = {"path": clean_path or path}
    if token:
        query["token"] = token
    if profile:
        query["profile"] = profile
    route_mode = normalize_route_mode(route)
    if route_mode != "auto":
        query["route"] = route_mode
    if raw:
        query["raw"] = "1"
    if download:
        query["download"] = "1"
    href = f"{prefixed_path('/api/file', prefix)}?{urlencode(query)}"
    return f"{href}{fragment}" if fragment else href


def client_prefers_tailnet(client_ip: str = "") -> bool:
    return client_ip_matches(client_ip, TAILNET_CLIENT_NETWORKS)


def host_prefers_lan(request_host: str = "", client_ip: str = "") -> bool:
    if client_prefers_tailnet(client_ip):
        return False
    return host_access_mode(request_host) in {"loopback", "private_ip", "lan_dns"}


def effective_route_mode(
    request_host: str = "", route_mode: str = "auto", client_ip: str = ""
) -> str:
    normalized = normalize_route_mode(route_mode)
    if normalized == "lan":
        return "lan"
    if normalized == "host":
        return "host"
    if normalized == "tail":
        return "tail"
    if client_prefers_tailnet(client_ip):
        return "tail"
    return "lan" if host_prefers_lan(request_host, client_ip) else "host"


def append_route_preference(url: str, route_mode: str) -> str:
    normalized = normalize_route_mode(route_mode)
    if normalized == "auto":
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["route"] = [normalized]
    encoded = urlencode(query, doseq=True)
    return parsed._replace(query=encoded).geturl()


def build_norman_prime_href(
    request_host: str = "", route_mode: str = "auto", client_ip: str = ""
) -> str:
    current_host = normalize_host_alias(request_host)
    effective_mode = effective_route_mode(request_host, route_mode, client_ip)
    if current_host and current_host in NORMAN_HOME_ALIASES:
        target_host = current_host
    elif host_access_mode(current_host) == "private_ip":
        target_host = "192.168.0.241"
    elif host_access_mode(current_host) == "tailnet":
        target_host = "norman.tail00000.ts.net"
    elif host_access_mode(current_host) == "lan_dns":
        target_host = "norman.home.arpa"
    else:
        target_host = (
            "norman.home.arpa" if effective_mode == "lan" else "norman.tail00000.ts.net"
        )
    if host_access_mode(target_host) in {"loopback", "private_ip"}:
        return f"http://{target_host}:8000/"
    return f"https://{target_host}/"


def build_norman_directory_href(
    request_host: str = "", route_mode: str = "auto", client_ip: str = ""
) -> str:
    return f"{build_norman_prime_href(request_host, route_mode, client_ip)}systems.html"


def render_console_link_url(
    link: dict[str, Any],
    *,
    token: str,
    profile: str,
    request_host: str = "",
    route_mode: str = "auto",
    client_ip: str = "",
) -> str:
    requested_mode = normalize_route_mode(route_mode)
    effective_mode = effective_route_mode(request_host, requested_mode, client_ip)
    request_mode = host_access_mode(request_host)
    has_tail = bool(str(link.get("tail_url") or "").strip())
    remote_from_lan_only = request_mode in {"public_dns", "public_ip"} and has_tail
    if (effective_mode == "tail" or remote_from_lan_only) and has_tail:
        raw_url = str(link.get("tail_url") or "").strip()
    elif effective_mode == "lan" and link.get("lan_url") and not remote_from_lan_only:
        raw_url = str(link.get("lan_url") or "").strip()
    else:
        raw_url = str(link.get("url") or "").strip()
    rendered = (
        raw_url.replace("{token}", quote(token, safe=""))
        .replace("{profile}", quote(profile, safe=""))
        .strip()
    )
    rendered = append_route_preference(rendered, route_mode)
    current_host = normalize_host_alias(request_host)
    if not current_host:
        return rendered
    parsed = urlparse(rendered)
    target_host = normalize_host_alias(parsed.netloc or parsed.hostname or "")
    if not target_host or target_host not in LOCAL_HOST_ALIASES:
        return rendered
    target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if target_port != PORT:
        return rendered
    port = f":{parsed.port}" if parsed.port else ""
    rewritten = parsed._replace(netloc=f"{current_host}{port}")
    return rewritten.geturl()


def console_link_anchor_attrs(url: str) -> str:
    scheme = urlparse(str(url or "").strip()).scheme.lower()
    if scheme in {"", "http", "https"}:
        return ' target="_blank" rel="noreferrer"'
    return ""


def console_lane_for_link(link: dict[str, Any]) -> str:
    explicit_lane = normalize_console_lane(link.get("lane"))
    if explicit_lane:
        return explicit_lane
    label = re.sub(r"[^a-z0-9]+", " ", str(link.get("label") or "").lower()).strip()
    if any(hint in label for hint in CONSOLE_EXPLORE_HINTS):
        return "explore"
    tone_group = semantic_console_group(
        link.get("tone_group") or link.get("group_slug") or link.get("group")
    )
    if tone_group in {"norman", "personal"}:
        return "make"
    if tone_group == "shared":
        return "review"
    if tone_group in {"work", "private"}:
        return "operate"
    return "make"


def console_note_for_link(link: dict[str, Any], lane: str) -> str:
    note = str(link.get("note") or "").strip()
    if note:
        return note
    label_slug = normalize_console_group_slug(link.get("label"))
    if label_slug in {"workspace", "workbench"}:
        return "Repo root, notes, and local files."
    if label_slug == "bridge-state":
        return "Bridge logs, state snapshots, and live status."
    tone_group = semantic_console_group(
        link.get("tone_group") or link.get("group_slug") or link.get("group")
    )
    return CONSOLE_GROUP_NOTES.get(
        tone_group, CONSOLE_LANE_DEFS.get(lane, {}).get("description", "")
    )


def console_focus_score(
    link: dict[str, Any], current_agent_candidates: set[str] | None = None
) -> int:
    candidates = current_agent_candidates or set()
    label_slug = normalize_console_group_slug(link.get("label"))
    tone_group = semantic_console_group(
        link.get("tone_group") or link.get("group_slug") or link.get("group")
    )
    lane = console_lane_for_link(link)
    score = int(link.get("priority") or 0)
    score += {"make": 240, "explore": 220, "review": 140, "operate": 80}.get(lane, 0)
    score += {
        "norman": 80,
        "personal": 60,
        "shared": 32,
        "private": 18,
        "work": 0,
        "agents": 10,
    }.get(tone_group, 0)
    if link.get("featured"):
        score += 280
    if str(link.get("source") or "") == "local":
        score += 120
    if label_slug and label_slug in candidates:
        score += 140
    if lane == "operate" and not link.get("featured"):
        score -= 20
    return score


def build_console_focus_lanes(
    links: list[dict[str, Any]], current_agent_candidates: set[str] | None = None
) -> list[dict[str, Any]]:
    candidates = current_agent_candidates or set()
    grouped: dict[str, dict[str, Any]] = {
        slug: {"slug": slug, **data, "items": []}
        for slug, data in CONSOLE_LANE_DEFS.items()
    }
    for link in links:
        lane = console_lane_for_link(link)
        tone_group = semantic_console_group(
            link.get("tone_group") or link.get("group_slug") or link.get("group")
        )
        item = dict(link)
        item["lane"] = lane
        item["tone_group"] = tone_group or "agents"
        item["note"] = console_note_for_link(item, lane)
        item["icon"] = str(
            item.get("icon") or icon_for_label(str(item.get("label") or ""))
        )
        item["score"] = console_focus_score(item, candidates)
        grouped.setdefault(
            lane,
            {
                "slug": lane,
                "label": lane.title(),
                "description": "",
                "eyebrow": "",
                "items": [],
            },
        )["items"].append(item)
    lane_limits = {"make": 3, "explore": 2, "review": 2, "operate": 2}
    ordered: list[dict[str, Any]] = []
    for lane in CONSOLE_LANE_DEFS:
        bucket = grouped.get(lane)
        if not bucket:
            continue
        items = sorted(
            bucket["items"],
            key=lambda item: (
                -int(item.get("score") or 0),
                str(item.get("label") or ""),
            ),
        )[: lane_limits.get(lane, 2)]
        if not items:
            continue
        ordered.append({**bucket, "items": items})
    return ordered


def build_relay_targets(
    *,
    token: str,
    profile: str,
    request_host: str = "",
    route_mode: str = "auto",
    client_ip: str = "",
) -> list[dict[str, str]]:
    current_host = normalize_host_alias(request_host)
    targets: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for link in CONSOLE_LINKS:
        rendered = render_console_link_url(
            link,
            token=token,
            profile=profile,
            request_host=request_host,
            route_mode=route_mode,
            client_ip=client_ip,
        )
        parsed = urlparse(rendered)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if (parsed.path or "/") not in {"", "/"}:
            continue
        query = parse_qs(parsed.query)
        target_token = (query.get("token") or [""])[0].strip()
        if not target_token:
            continue
        target_host = normalize_host_alias(parsed.hostname or "")
        if (
            current_host
            and target_host == current_host
            and (parsed.port or 80) == PORT
            and target_token == token
        ):
            continue
        api_url = parsed._replace(path="/api/ask", query="", fragment="").geturl()
        key = (link["label"], api_url)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            {
                "label": link["label"],
                "url": rendered,
                "api_url": api_url,
                "token": target_token,
                "host": parsed.netloc,
            }
        )
    return targets


def build_handoff_message(source_prompt: str, source_response: str) -> str:
    prompt = source_prompt.strip() or "[no original prompt recorded]"
    response = source_response.strip() or "[no assistant response recorded]"
    return (
        f"You are receiving a handoff from {AGENT_NAME}.\n\n"
        "Continue this operator task in your own workspace and tools. "
        "Reuse the context below, but re-check anything environment-specific.\n\n"
        "Original operator prompt:\n"
        f"{prompt}\n\n"
        f"Response from {AGENT_NAME} so far:\n"
        f"{response}\n\n"
        "Take the next best action. If anything important is missing, say exactly "
        "what you need."
    )


def relay_eta_label(queue_position: int, pending: bool) -> str:
    if pending and queue_position <= 0:
        return "running now"
    if queue_position <= 0:
        return "ETA unknown"
    minutes = max(5, min(120, queue_position * 10))
    return f"rough ETA {minutes} min"


def build_relay_acknowledgement(
    target_label: str, downstream: dict[str, Any] | None
) -> dict[str, Any]:
    payload = downstream if isinstance(downstream, dict) else {}
    snapshot = (
        payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    )
    queue_depth = _coerce_int(snapshot.get("queue_depth"))
    pending = bool(snapshot.get("pending"))
    queue_position = queue_depth if queue_depth > 0 else 0
    model_alive = bool(
        snapshot.get("model_process_alive") or snapshot.get("web_worker_alive")
    )

    if queue_position > 0:
        state = "queued"
        label = "Queued"
        detail = f"{target_label} picked it up; queued at position {queue_position}."
    elif pending:
        state = "running"
        label = "Picked up"
        detail = f"{target_label} picked it up and is working now."
    else:
        state = "picked-up"
        label = "Picked up"
        detail = f"{target_label} accepted the handoff."

    return {
        "state": state,
        "label": label,
        "target": target_label,
        "picked_up": True,
        "pending": pending,
        "queue_depth": queue_depth,
        "queue_position": queue_position,
        "model_alive": model_alive,
        "eta_label": relay_eta_label(queue_position, pending),
        "detail": detail,
    }


def now_ts() -> int:
    return int(time.time())


def run(
    cmd: list[str], *, input_text: str | None = None, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def tmux_cmd(*args: str) -> list[str]:
    return ["tmux", "-L", TMUX_SOCKET, *args]


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def truncate_block(text: str, limit: int = MAX_BLOCK_CHARS) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    if len(value) <= limit:
        return value
    tail = value[-limit:]
    omitted = len(value) - len(tail)
    return f"[truncated {omitted} earlier characters]\n{tail}"


def summarize_text(text: str, limit: int = 180) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"


def slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip("-._")
    return cleaned or "attachment"


def ensure_attachments_dir() -> None:
    ensure_state_dir()
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)


LINE_FRAGMENT_RE = re.compile(r"^(?P<path>.+?)(?P<fragment>#L\d+(?:C\d+)?)$")


def split_file_target(raw: str) -> tuple[str, str]:
    candidate = (raw or "").strip()
    if not candidate:
        return "", ""
    fragment = ""
    if candidate.startswith("file://"):
        parsed = urlparse(candidate)
        candidate = parsed.path or ""
        if parsed.fragment:
            fragment = f"#{parsed.fragment}"
    match = LINE_FRAGMENT_RE.match(candidate)
    if match:
        candidate = match.group("path")
        fragment = fragment or match.group("fragment")
    return candidate, fragment


def resolve_file_target(raw: str) -> Path | None:
    candidate, _fragment = split_file_target(raw)
    if not candidate:
        return None
    if candidate.startswith("file://"):
        candidate = urlparse(candidate).path
    if candidate.startswith("~/"):
        candidate = str(Path.home() / candidate[2:])
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (Path(WORKDIR) / candidate).resolve()
    else:
        path = path.resolve()
    return path


def guess_file_content_type(path: Path) -> str:
    mime, _encoding = mimetypes.guess_type(path.name)
    if mime:
        if mime.startswith("text/"):
            return f"{mime}; charset=utf-8"
        return mime
    if path.suffix.lower() in TEXT_PREVIEW_SUFFIXES:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def human_size(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def render_file_preview_html(preview_text: str) -> str:
    lines = preview_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines:
        lines = [""]
    rendered_lines = "".join(
        (
            f'<span class="file-line" id="L{index}">'
            f'<a class="line-no" href="#L{index}">{index}</a>'
            f'<span class="line-code">{html.escape(line) or "&nbsp;"}</span>'
            "</span>"
        )
        for index, line in enumerate(lines, start=1)
    )
    return f'<pre class="file-preview">{rendered_lines}</pre>'


def render_file_copy_script() -> str:
    return """<script>
  (function () {
    async function copyText(value, button) {
      const original = button.dataset.copyLabel || button.textContent || "Copy";
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(value);
        } else {
          const helper = document.createElement("textarea");
          helper.value = value;
          helper.setAttribute("readonly", "");
          helper.style.position = "fixed";
          helper.style.opacity = "0";
          document.body.appendChild(helper);
          helper.select();
          document.execCommand("copy");
          helper.remove();
        }
        button.textContent = "Copied";
      } catch (_) {
        button.textContent = "Press Ctrl+C";
      }
      window.setTimeout(() => {
        button.textContent = original;
      }, 1200);
    }

    function resolveCopyValue(button) {
      const direct = button.dataset.copyValue || "";
      if (direct) {
        return direct;
      }
      const targetId = button.dataset.copyTarget || "";
      if (!targetId) {
        return "";
      }
      const target = document.getElementById(targetId);
      if (!target) {
        return "";
      }
      if (typeof target.value === "string") {
        return target.value;
      }
      return target.textContent || "";
    }

    for (const button of document.querySelectorAll("[data-copy-value], [data-copy-target]")) {
      button.dataset.copyLabel = button.textContent || "Copy";
      button.addEventListener("click", () => {
        const value = resolveCopyValue(button);
        if (!value) {
          return;
        }
        copyText(value, button);
      });
    }
  })();
  </script>"""


def is_text_preview_type(path: Path, content_type: str) -> bool:
    if content_type.startswith("text/"):
        return True
    return path.suffix.lower() in TEXT_PREVIEW_SUFFIXES


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return default


def write_text(path: Path, value: str) -> None:
    ensure_state_dir()
    path.write_text(value, encoding="utf-8")


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(default)
    except json.JSONDecodeError:
        return dict(default)
    if not isinstance(payload, dict):
        return dict(default)
    merged = dict(default)
    merged.update(payload)
    return merged


def read_json_list(path: Path) -> list[Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_state_dir()
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def write_json_list(path: Path, payload: list[Any]) -> None:
    ensure_state_dir()
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def normalize_attachment_kind(
    value: Any, *, content_type: str = "", name: str = ""
) -> str:
    clean = str(value or "").strip().lower()
    if clean in {"image", "text", "file"}:
        return clean
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    suffix = Path(name or "").suffix.lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/") or suffix in TEXT_PREVIEW_SUFFIXES:
        return "text"
    return "file"


def normalize_attachments(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return items
    for entry in value:
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("token") or "").strip()
        path = str(entry.get("path") or "").strip()
        if not token or not path:
            continue
        name = str(entry.get("name") or Path(path).name or token).strip() or token
        content_type = str(
            entry.get("content_type") or ""
        ).strip() or guess_file_content_type(Path(path))
        kind = normalize_attachment_kind(
            entry.get("kind"), content_type=content_type, name=name
        )
        try:
            size = int(entry.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        try:
            created_at = int(entry.get("created_at") or 0)
        except (TypeError, ValueError):
            created_at = 0
        try:
            line_count = int(entry.get("line_count") or 0)
        except (TypeError, ValueError):
            line_count = 0
        try:
            char_count = int(entry.get("char_count") or 0)
        except (TypeError, ValueError):
            char_count = 0
        source = str(entry.get("source") or "").strip()
        summary = str(entry.get("summary") or "").strip()
        url = str(entry.get("url") or "").strip()
        items.append(
            {
                "token": token,
                "name": name,
                "path": path,
                "content_type": content_type,
                "kind": kind,
                "size": size,
                "created_at": created_at,
                "line_count": line_count,
                "char_count": char_count,
                "source": source,
                "url": url,
                "summary": summary,
            }
        )
    return items


def load_draft_attachments() -> list[dict[str, Any]]:
    ensure_state_dir()
    return normalize_attachments(read_json_list(DRAFT_ATTACHMENTS_PATH))


def save_draft_attachments(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = normalize_attachments(entries)
    write_json_list(DRAFT_ATTACHMENTS_PATH, payload)
    return payload


def clear_draft_attachments() -> None:
    save_draft_attachments([])


def attachment_token_prefix(kind: str) -> str:
    if kind == "image":
        return "image"
    if kind == "text":
        return "block"
    return "file"


def next_attachment_token(entries: list[dict[str, Any]], kind: str) -> str:
    prefix = attachment_token_prefix(kind)
    existing = {str(item.get("token") or "").strip() for item in entries}
    index = 1
    while f"{prefix}-{index}" in existing:
        index += 1
    return f"{prefix}-{index}"


def build_attachment_summary(
    *,
    token: str,
    name: str,
    content_type: str,
    size: int,
    kind: str,
    source: str = "",
    line_count: int = 0,
    char_count: int = 0,
    url: str = "",
) -> str:
    clean_source = str(source or "").strip().lower()
    parts = [f"[{token}]", name]
    if kind == "image":
        if clean_source == "web-capture":
            parts.append("web snapshot")
        else:
            parts.append("image")
    elif kind == "text":
        if clean_source == "paste-block":
            parts.append("clipboard paste")
        elif clean_source == "history-export":
            parts.append("session history")
        elif clean_source == "log-tail":
            parts.append("log tail")
        elif clean_source == "pane-capture":
            parts.append("live pane")
        else:
            parts.append("text block")
        if line_count > 0:
            parts.append(f"{line_count} line" + ("" if line_count == 1 else "s"))
        if char_count > 0:
            parts.append(f"{char_count:,} chars")
    else:
        parts.append("file")
    clean_url = str(url or "").strip()
    if clean_url:
        parsed = urlparse(clean_url)
        host = parsed.netloc.strip()
        if host:
            parts.append(host)
    if size:
        parts.append(human_size(size))
    mime = str(content_type or "").split(";", 1)[0].strip()
    if mime:
        parts.append(mime)
    return " · ".join(part for part in parts if part)


def build_attachment_origin_label(entry: dict[str, Any]) -> str:
    kind = str(entry.get("kind") or "").strip().lower()
    source = str(entry.get("source") or "").strip().lower()
    name = str(entry.get("name") or "").strip()
    url = str(entry.get("url") or "").strip()
    host = ""
    if url:
        parsed = urlparse(url)
        host = parsed.netloc.strip()

    if source == "web-capture":
        if host:
            return f"web snapshot from {host}"
        return "web snapshot"
    if source == "paste-block":
        return "clipboard image" if kind == "image" else "clipboard paste"
    if source == "history-export":
        return "session history export"
    if source == "log-tail":
        return "log tail"
    if source == "pane-capture":
        return "live pane capture"
    if source == "upload":
        if name:
            return f"uploaded {name}"
        return "uploaded file"
    if kind == "image":
        return f"image {name}" if name else "image"
    if kind == "text":
        return f"text block {name}" if name else "text block"
    if name:
        return f"file {name}"
    return "staged file"


def build_attachment_lead_message(attachments: list[dict[str, Any]]) -> str:
    normalized = normalize_attachments(attachments)
    if not normalized:
        return ""
    labels = [build_attachment_origin_label(entry) for entry in normalized[:3]]
    if len(normalized) == 1:
        return f"{labels[0].capitalize()}."
    if len(normalized) == 2:
        return f"Staged context: {labels[0]}; {labels[1]}."
    return f"Staged context: {labels[0]}; {labels[1]}; {labels[2]}" + (
        f"; plus {len(normalized) - 3} more." if len(normalized) > 3 else "."
    )


def attachment_count_phrase(attachments: list[dict[str, Any]]) -> str:
    counts = {"image": 0, "text": 0, "file": 0}
    for entry in normalize_attachments(attachments):
        kind = str(entry.get("kind") or "file").strip().lower()
        counts[kind if kind in counts else "file"] += 1

    labels = {
        "image": ("image", "images"),
        "text": ("text block", "text blocks"),
        "file": ("file", "files"),
    }
    parts: list[str] = []
    for kind in ("image", "text", "file"):
        count = counts[kind]
        if count <= 0:
            continue
        singular, plural = labels[kind]
        parts.append(f"{count} {singular if count == 1 else plural}")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{parts[0]}, {parts[1]}, and {parts[2]}"


def create_draft_attachment(
    *,
    raw_bytes: bytes,
    name: str,
    content_type: str,
    source: str,
    kind: str | None = None,
    url: str = "",
) -> dict[str, Any]:
    if len(raw_bytes) > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"attachment is too large ({human_size(len(raw_bytes))}; max {human_size(MAX_ATTACHMENT_BYTES)})"
        )
    ensure_attachments_dir()
    existing = load_draft_attachments()
    normalized_kind = normalize_attachment_kind(
        kind, content_type=content_type, name=name
    )
    token = next_attachment_token(existing, normalized_kind)
    suffix = Path(name).suffix.lower()
    if not suffix:
        guessed = mimetypes.guess_extension(
            str(content_type or "").split(";", 1)[0].strip().lower()
        )
        suffix = guessed or (".txt" if normalized_kind == "text" else "")
    safe_name = slugify_filename(Path(name).stem or token)
    target = ATTACHMENTS_DIR / f"{int(time.time() * 1000)}-{token}-{safe_name}{suffix}"
    target.write_bytes(raw_bytes)
    content_type_value = content_type.strip() or guess_file_content_type(target)
    line_count = 0
    char_count = 0
    if normalized_kind == "text":
        body = raw_bytes.decode("utf-8", errors="replace")
        char_count = len(body)
        line_count = len(body.splitlines()) or (1 if body else 0)
    entry = {
        "token": token,
        "name": name.strip() or target.name,
        "path": str(target.resolve()),
        "content_type": content_type_value,
        "kind": normalized_kind,
        "size": len(raw_bytes),
        "created_at": now_ts(),
        "line_count": line_count,
        "char_count": char_count,
        "source": source.strip() or "paste",
        "url": url.strip(),
        "summary": build_attachment_summary(
            token=token,
            name=name.strip() or target.name,
            content_type=content_type_value,
            size=len(raw_bytes),
            kind=normalized_kind,
            source=source.strip() or "paste",
            line_count=line_count,
            char_count=char_count,
            url=url.strip(),
        ),
    }
    existing.append(entry)
    save_draft_attachments(existing)
    return entry


def normalize_capture_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("capture URL is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("capture URL must be a valid http(s) address")
    return value


def screenshot_browser_binary() -> str:
    configured = os.environ.get("HOUSEBOT_CODEX_SCREENSHOT_BROWSER", "").strip()
    candidates = [
        configured,
        "google-chrome",
        "chromium-browser",
        "chromium",
        "/snap/bin/chromium",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        clean = str(candidate or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        if "/" in clean and Path(clean).exists():
            return clean
        resolved = shutil.which(clean)
        if resolved:
            return resolved
    return ""


def capture_web_attachment(*, url: str, label: str = "") -> dict[str, Any]:
    clean_url = normalize_capture_url(url)
    browser = screenshot_browser_binary()
    if not browser:
        raise ValueError("no headless browser is available for screenshots")
    ensure_attachments_dir()
    parsed = urlparse(clean_url)
    display_label = str(label or "").strip() or parsed.netloc or "Web capture"
    file_label = (
        display_label[:-4] if display_label.lower().endswith(".png") else display_label
    )
    file_name = f"{file_label}.png"
    with tempfile.TemporaryDirectory(
        prefix="capture-", dir=str(ATTACHMENTS_DIR)
    ) as temp_dir:
        output_path = Path(temp_dir) / "capture.png"
        base_cmd = [
            browser,
            "--disable-gpu",
            "--hide-scrollbars",
            "--disable-dev-shm-usage",
            "--ignore-certificate-errors",
            f"--window-size={SCREENSHOT_WINDOW_WIDTH},{SCREENSHOT_WINDOW_HEIGHT}",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=2500",
            f"--screenshot={output_path}",
        ]
        if os.geteuid() == 0:
            base_cmd.append("--no-sandbox")
        last_error = ""
        for headless_flag in ("--headless=new", "--headless"):
            cmd = [*base_cmd, headless_flag, clean_url]
            try:
                proc = subprocess.run(
                    cmd,
                    text=True,
                    capture_output=True,
                    timeout=SCREENSHOT_CAPTURE_TIMEOUT,
                )
            except subprocess.TimeoutExpired as exc:
                last_error = str(exc)
                continue
            if (
                proc.returncode == 0
                and output_path.exists()
                and output_path.stat().st_size > 0
            ):
                return create_draft_attachment(
                    raw_bytes=output_path.read_bytes(),
                    name=file_name,
                    content_type="image/png",
                    source="web-capture",
                    kind="image",
                    url=clean_url,
                )
            last_error = (
                proc.stderr or proc.stdout or ""
            ).strip() or f"exit {proc.returncode}"
    raise ValueError(f"screenshot capture failed: {last_error}")


def remove_draft_attachment(token: str) -> list[dict[str, Any]]:
    clean = str(token or "").strip()
    if not clean:
        return load_draft_attachments()
    existing = load_draft_attachments()
    kept: list[dict[str, Any]] = []
    for entry in existing:
        if entry["token"] != clean:
            kept.append(entry)
            continue
        try:
            Path(entry["path"]).unlink(missing_ok=True)
        except OSError:
            pass
    return save_draft_attachments(kept)


def load_history(limit: int = MAX_HISTORY_ITEMS) -> list[dict[str, Any]]:
    ensure_state_dir()
    entries: list[dict[str, Any]] = []
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return entries
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payload["attachments"] = normalize_attachments(payload.get("attachments"))
            payload["usage"] = normalize_usage_entry(payload.get("usage"))
            payload["error"] = strip_codex_empty_last_message_warning(
                str(payload.get("error") or "")
            )
            entries.append(payload)
    if limit and len(entries) > limit:
        return entries[-limit:]
    return entries


def write_history_entries(
    entries: list[dict[str, Any]], *, limit: int = MAX_HISTORY_ITEMS
) -> list[dict[str, Any]]:
    trimmed = list(entries or [])
    if limit and len(trimmed) > limit:
        trimmed = trimmed[-limit:]
    ensure_state_dir()
    payload = "\n".join(json.dumps(item, sort_keys=True) for item in trimmed)
    if payload:
        payload += "\n"
    HISTORY_PATH.write_text(payload, encoding="utf-8")
    return trimmed


def append_history_entry(
    *,
    prompt: str,
    response: str,
    error_text: str,
    started_at: int,
    finished_at: int,
    thread_id: str,
    speed: str,
    detail: int,
    attachments: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    entries = load_history(limit=0)
    clean_error_text = strip_codex_empty_last_message_warning(error_text)
    entries.append(
        {
            "detail": normalize_response_detail(detail),
            "error": clean_error_text,
            "attachments": normalize_attachments(attachments or []),
            "finished_at": finished_at,
            "prompt": prompt,
            "response": response,
            "speed": normalize_response_speed(speed),
            "started_at": started_at,
            "thread_id": thread_id,
            "usage": normalize_usage_entry(usage),
        }
    )
    write_history_entries(entries)


def clear_trailing_reauth_history(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    sanitized = [dict(item) for item in entries or [] if isinstance(item, dict)]
    # Reauth failures are actionable, not cosmetic.  Keep the latest one visible
    # until a later successful turn proves the bot can answer again.
    return sanitized, False


CODEX_ROUTER_WRITE_STDIN_RE = re.compile(
    r"^\S+\s+ERROR\s+codex_core::tools::router:.*\bwrite_stdin failed\b.*$"
)
CODEX_APPLY_PATCH_VERIFY_RE = re.compile(
    r"^\S+\s+ERROR\s+codex_core::tools::router:.*\bapply_patch verification failed\b.*$"
)
CODEX_MODELS_REFRESH_TIMEOUT_RE = re.compile(
    r"^\S+\s+ERROR\s+codex_models_manager::manager: "
    r"failed to refresh available models: "
    r"(?:request timed out|timeout waiting for child process to exit)$"
)
CODEX_ROLLOUT_THREAD_NOT_FOUND_RE = re.compile(
    r"failed to record rollout items: thread\s+([0-9a-fA-F-]{32,40})\s+not found"
)


def codex_rollout_thread_not_found_ids(text: str) -> set[str]:
    return {
        match.group(1).strip()
        for match in CODEX_ROLLOUT_THREAD_NOT_FOUND_RE.finditer(str(text or ""))
        if match.group(1).strip()
    }


def _is_codex_transient_stderr_noise(line: str) -> bool:
    stripped = str(line or "").strip()
    return bool(
        NO_LAST_AGENT_MESSAGE_RE.match(stripped)
        or CODEX_ROUTER_WRITE_STDIN_RE.match(stripped)
        or CODEX_APPLY_PATCH_VERIFY_RE.match(stripped)
        or CODEX_MODELS_REFRESH_TIMEOUT_RE.match(stripped)
        or CODEX_ROLLOUT_THREAD_NOT_FOUND_RE.search(stripped)
    )


def clear_codex_transient_error_history(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    sanitized = [dict(item) for item in entries or [] if isinstance(item, dict)]
    changed = False
    for item in sanitized:
        error_text = str(item.get("error") or "")
        filtered = strip_codex_empty_last_message_warning(error_text)
        if filtered != error_text.strip():
            item["error"] = filtered
            changed = True
    if changed:
        write_history_entries(sanitized, limit=0)
    return sanitized, changed


def _history_entry_is_empty_ghost(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    prompt = str(entry.get("prompt") or "").strip()
    if not prompt:
        return False
    error_text = str(entry.get("error") or "").strip()
    if error_text:
        return False
    response_text = str(entry.get("response") or "").strip().lower()
    if response_text and response_text not in {
        "[no response returned]",
        "[waiting for reply]",
    }:
        return False
    usage = normalize_usage_entry(entry.get("usage"))
    if usage.get("success"):
        return False
    if _coerce_int(usage.get("total_tokens")) > 0:
        return False
    return True


def _history_entry_is_passive_party_line(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    prompt = str(entry.get("prompt") or "").strip()
    if not prompt:
        return False
    lower_prompt = prompt.lower()
    party_markers = (
        "[norman switchboard party line]",
        "[norman subprime party line]",
        "[norman bbs party line]",
    )
    if not any(marker in lower_prompt for marker in party_markers):
        return False
    if "passive fleet context only" not in lower_prompt:
        return False
    response_text = str(entry.get("response") or "").strip().lower()
    if response_text and response_text not in {
        "[no response returned]",
        "[waiting for reply]",
    }:
        return False
    return True


def clear_trailing_empty_ghost_history(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sanitized = [dict(item) for item in entries or [] if isinstance(item, dict)]
    removed: list[dict[str, Any]] = []
    while sanitized and _history_entry_is_empty_ghost(sanitized[-1]):
        removed.insert(0, sanitized.pop())
    if removed:
        write_history_entries(sanitized, limit=0)
    return sanitized, removed


def clear_trailing_passive_party_line_history(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sanitized = [dict(item) for item in entries or [] if isinstance(item, dict)]
    removed: list[dict[str, Any]] = []
    while sanitized and _history_entry_is_passive_party_line(sanitized[-1]):
        removed.insert(0, sanitized.pop())
    if removed:
        write_history_entries(sanitized, limit=0)
    return sanitized, removed


def unwind_latest_history_turn() -> dict[str, Any]:
    with STATUS_LOCK:
        meta = load_status_meta()
        if bool(meta.get("pending")):
            raise RuntimeError(
                "Wait for the running prompt to finish before unwinding."
            )
        if normalize_queue(meta.get("queued_prompts")):
            raise RuntimeError(
                "Clear the queued prompts before unwinding the latest turn."
            )

        history = load_history(limit=0)
        if not history:
            raise ValueError("No completed turn is available to unwind.")

        removed = dict(history.pop())
        write_history_entries(history, limit=0)

        latest_entry = history[-1] if history else {}
        write_text(LAST_PROMPT_PATH, str(latest_entry.get("prompt") or ""))
        write_text(LAST_RESPONSE_PATH, str(latest_entry.get("response") or ""))
        write_text(LAST_ERROR_PATH, str(latest_entry.get("error") or ""))
        write_text(THREAD_ID_PATH, "")

        meta.update(
            {
                "pending": False,
                "state": "ok" if history else "idle",
                "status_message": "Ready." if history else "No conversation yet.",
                "running_prompt": "",
                "running_attachments": [],
                "last_started_at": _coerce_int(latest_entry.get("started_at")),
                "last_finished_at": _coerce_int(latest_entry.get("finished_at")),
                "last_speed": normalize_response_speed(
                    latest_entry.get("speed") or meta.get("last_speed")
                ),
                "last_detail": normalize_response_detail(
                    latest_entry.get("detail") or meta.get("last_detail")
                ),
                "last_attachments": normalize_attachments(
                    latest_entry.get("attachments") or []
                ),
            }
        )
        save_status_meta(meta)

    record_action(
        "history-unwind",
        "Removed the latest turn. The next prompt will start fresh.",
    )
    return removed


def _persist_ready_state_after_history_cleanup(
    meta: dict[str, Any],
    history: list[dict[str, Any]],
    removed_entries: list[dict[str, Any]],
) -> None:
    if not removed_entries:
        return
    latest_entry = history[-1] if history else {}
    latest_prompt = str(latest_entry.get("prompt") or "").strip() or "[no prompt yet]"
    latest_response = (
        str(latest_entry.get("response") or "").strip() or "[no response yet]"
    )
    removed_prompts = {
        str(item.get("prompt") or "").strip() for item in removed_entries if item
    }
    removed_starts = {
        _coerce_int(item.get("started_at")) for item in removed_entries if item
    }
    current_last_prompt = read_text(LAST_PROMPT_PATH, "[no prompt yet]")
    current_last_response = read_text(LAST_RESPONSE_PATH, "[no response yet]")
    stale_state = str(meta.get("state") or "").strip().lower() == "error"
    stale_status = "web prompt failed" in str(meta.get("status_message") or "").lower()
    stale_last_turn = (
        current_last_prompt in removed_prompts
        or current_last_response.strip().lower()
        in {"", "[no response returned]", "[waiting for reply]"}
        or _coerce_int(meta.get("last_started_at")) in removed_starts
    )
    if stale_last_turn:
        try:
            write_text(LAST_PROMPT_PATH, latest_prompt)
            write_text(LAST_RESPONSE_PATH, latest_response)
        except OSError:
            pass
    if stale_state or stale_status or stale_last_turn:
        cleaned_meta = dict(meta)
        cleaned_meta.update(
            {
                "pending": False,
                "state": "ok",
                "status_message": "Ready.",
                "running_prompt": "",
                "running_attachments": [],
                "last_started_at": _coerce_int(latest_entry.get("started_at")),
                "last_finished_at": _coerce_int(latest_entry.get("finished_at")),
                "last_speed": normalize_response_speed(
                    latest_entry.get("speed") or meta.get("last_speed")
                ),
                "last_detail": normalize_response_detail(
                    latest_entry.get("detail") or meta.get("last_detail")
                ),
                "last_attachments": normalize_attachments(
                    latest_entry.get("attachments") or []
                ),
            }
        )
        try:
            save_status_meta(cleaned_meta)
        except OSError:
            pass


def default_audit_event() -> dict[str, Any]:
    return {
        "id": "",
        "event_type": "",
        "severity": "info",
        "summary": "",
        "detail": "",
        "event_at": 0,
        "actor_type": "system",
        "actor_ip": "",
        "thread_id": "",
        "session_name": SESSION,
        "agent_name": AGENT_NAME,
        "host_name": HOST_NAME,
        "payload": {},
    }


def normalize_audit_event(value: Any) -> dict[str, Any]:
    payload = dict(default_audit_event())
    if isinstance(value, dict):
        payload.update(value)
    payload["id"] = str(payload.get("id") or "").strip()
    if not payload["id"]:
        payload["id"] = f"{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    payload["event_type"] = str(payload.get("event_type") or "").strip().lower()
    payload["severity"] = (
        str(payload.get("severity") or "info").strip().lower() or "info"
    )
    if payload["severity"] not in {"info", "warn", "error"}:
        payload["severity"] = "info"
    payload["summary"] = str(payload.get("summary") or "").strip()
    payload["detail"] = str(payload.get("detail") or "").strip()
    payload["event_at"] = _coerce_int(payload.get("event_at")) or now_ts()
    payload["actor_type"] = (
        str(payload.get("actor_type") or "system").strip() or "system"
    )
    payload["actor_ip"] = str(payload.get("actor_ip") or "").strip()
    payload["thread_id"] = str(payload.get("thread_id") or "").strip()
    payload["session_name"] = (
        str(payload.get("session_name") or SESSION).strip() or SESSION
    )
    payload["agent_name"] = (
        str(payload.get("agent_name") or AGENT_NAME).strip() or AGENT_NAME
    )
    payload["host_name"] = (
        str(payload.get("host_name") or HOST_NAME).strip() or HOST_NAME
    )
    metadata = payload.get("payload")
    payload["payload"] = metadata if isinstance(metadata, dict) else {}
    return payload


def load_audit_events(
    *, limit: int = MAX_AUDIT_ITEMS, since_ts: int = 0, event_type: str = ""
) -> list[dict[str, Any]]:
    ensure_state_dir()
    entries: list[dict[str, Any]] = []
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return entries
    wanted_type = str(event_type or "").strip().lower()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        entry = normalize_audit_event(payload)
        if since_ts and int(entry.get("event_at") or 0) < since_ts:
            continue
        if wanted_type and entry["event_type"] != wanted_type:
            continue
        entries.append(entry)
    if limit and len(entries) > limit:
        return entries[-limit:]
    return entries


def append_audit_event(
    *,
    event_type: str,
    summary: str,
    detail: str = "",
    severity: str = "info",
    actor_type: str = "system",
    actor_ip: str = "",
    thread_id: str = "",
    payload: dict[str, Any] | None = None,
    event_at: int = 0,
) -> dict[str, Any]:
    entry = normalize_audit_event(
        {
            "event_type": event_type,
            "summary": summary,
            "detail": detail,
            "severity": severity,
            "actor_type": actor_type,
            "actor_ip": actor_ip,
            "thread_id": thread_id,
            "payload": payload or {},
            "event_at": event_at,
        }
    )
    entries = load_audit_events(limit=0)
    entries.append(entry)
    trimmed = entries[-MAX_AUDIT_ITEMS:]
    ensure_state_dir()
    serialized = "\n".join(json.dumps(item, sort_keys=True) for item in trimmed)
    if serialized:
        serialized += "\n"
    AUDIT_PATH.write_text(serialized, encoding="utf-8")
    return entry


def default_status_meta() -> dict[str, Any]:
    return {
        "pending": False,
        "state": "idle",
        "status_message": "Ready.",
        "running_prompt": "",
        "running_attachments": [],
        "running_speed": DEFAULT_RESPONSE_SPEED,
        "running_detail": DEFAULT_RESPONSE_DETAIL,
        "last_attachments": [],
        "last_speed": DEFAULT_RESPONSE_SPEED,
        "last_detail": DEFAULT_RESPONSE_DETAIL,
        "last_started_at": 0,
        "last_finished_at": 0,
        "last_action": "",
        "last_action_at": 0,
        "last_action_detail": "",
        "active_child_pid": 0,
        "active_child_pgid": 0,
        "active_child_started_at": 0,
        "cancel_requested_at": 0,
        "recovered_after_restart": False,
        "stale_queue": False,
        "updated_at": 0,
        "queued_prompts": [],
        "resource_meter": {},
    }


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _meter_generated_at(snapshot_at: int) -> str:
    try:
        return (
            datetime.utcfromtimestamp(int(snapshot_at or 0)).isoformat(
                timespec="seconds"
            )
            + "Z"
        )
    except (TypeError, ValueError, OSError):
        return datetime.utcfromtimestamp(now_ts()).isoformat(timespec="seconds") + "Z"


def _normalize_meter_tone(value: Any, default: str = "ok") -> str:
    clean = str(value or "").strip().lower()
    if clean in {"ok", "watch", "warn", "danger", "active", "alert"}:
        return clean
    return default


def normalize_kpi_meters(value: Any, *, limit: int = 4) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    meters: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        meter_id = str(raw.get("id") or label).strip()
        meters.append(
            {
                "id": meter_id,
                "label": label,
                "value": raw.get("value", ""),
                "unit": str(raw.get("unit") or "").strip(),
                "tone": _normalize_meter_tone(raw.get("tone")),
                "detail": str(raw.get("detail") or "").strip(),
                "source": str(raw.get("source") or "").strip(),
                "updated_at": raw.get("updated_at", ""),
                "stale_after_seconds": _coerce_int(raw.get("stale_after_seconds")),
                "href": str(raw.get("href") or "").strip(),
            }
        )
        if len(meters) >= limit:
            break
    return meters


def normalize_resource_meter(
    value: Any,
    *,
    snapshot_at: int,
    pending: bool,
    queue_depth: int,
    running_prompt: str,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    source_conversation = source.get("conversation")
    if not isinstance(source_conversation, dict):
        source_conversation = {}
    source_domain = source.get("domain")
    if not isinstance(source_domain, dict):
        source_domain = {}
    source_executor = source.get("executor")
    if not isinstance(source_executor, dict):
        source_executor = {}
    conversation = {
        "running": _coerce_int(source_conversation.get("running"))
        or (1 if pending and running_prompt else 0),
        "queued": _coerce_int(source_conversation.get("queued")) or queue_depth,
        "pending": bool(source_conversation.get("pending", pending)),
        "oldest_age_seconds": _coerce_int(
            source_conversation.get("oldest_age_seconds")
        ),
        "stale": _coerce_int(source_conversation.get("stale")),
    }
    if not source:
        summary = (
            f"Chat running / {queue_depth} queued"
            if pending
            else f"Chat idle / {queue_depth} queued"
            if queue_depth
            else "Chat idle"
        )
        tone = "watch" if pending else "warn" if queue_depth else "ok"
    else:
        summary = str(source.get("summary") or "").strip() or "Queues available"
        tone = _normalize_meter_tone(source.get("tone"))
    return {
        "version": str(source.get("version") or "norman.queue-resource-meter.v1"),
        "generated_at": str(source.get("generated_at") or "")
        or _meter_generated_at(snapshot_at),
        "read_only": True,
        "label": str(source.get("label") or "Queues").strip() or "Queues",
        "tone": tone,
        "summary": summary,
        "conversation": conversation,
        "domain": source_domain,
        "executor": source_executor,
        "kpi_meters": normalize_kpi_meters(source.get("kpi_meters")),
        "warnings": source.get("warnings")
        if isinstance(source.get("warnings"), list)
        else [],
        "sources": source.get("sources")
        if isinstance(source.get("sources"), list)
        else [],
    }


def default_usage_entry() -> dict[str, Any]:
    return {
        "started_at": 0,
        "finished_at": 0,
        "thread_id": "",
        "speed": DEFAULT_RESPONSE_SPEED,
        "detail": DEFAULT_RESPONSE_DETAIL,
        "model": MODEL,
        "success": False,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def normalize_usage_entry(value: Any) -> dict[str, Any]:
    payload = dict(default_usage_entry())
    if isinstance(value, dict):
        payload.update(value)
    payload["started_at"] = _coerce_int(payload.get("started_at"))
    payload["finished_at"] = _coerce_int(payload.get("finished_at"))
    payload["thread_id"] = str(payload.get("thread_id") or "").strip()
    payload["speed"] = normalize_response_speed(payload.get("speed"))
    payload["detail"] = normalize_response_detail(payload.get("detail"))
    payload["model"] = str(payload.get("model") or MODEL).strip() or MODEL
    payload["success"] = bool(payload.get("success"))
    payload["input_tokens"] = _coerce_int(payload.get("input_tokens"))
    payload["cached_input_tokens"] = _coerce_int(payload.get("cached_input_tokens"))
    payload["output_tokens"] = _coerce_int(payload.get("output_tokens"))
    total_tokens = _coerce_int(payload.get("total_tokens"))
    if total_tokens <= 0:
        total_tokens = payload["input_tokens"] + payload["output_tokens"]
    payload["total_tokens"] = total_tokens
    return payload


def default_usage_summary() -> dict[str, int]:
    return {
        "turns": 0,
        "successful_turns": 0,
        "failed_turns": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "last_turn_at": 0,
    }


def summarize_usage_entries(
    entries: list[dict[str, Any]], *, since_ts: int = 0
) -> dict[str, int]:
    summary = dict(default_usage_summary())
    for raw_entry in entries:
        entry = normalize_usage_entry(raw_entry)
        finished_at = int(entry.get("finished_at") or 0)
        if since_ts and finished_at and finished_at < since_ts:
            continue
        summary["turns"] += 1
        if entry["success"]:
            summary["successful_turns"] += 1
        else:
            summary["failed_turns"] += 1
        summary["input_tokens"] += entry["input_tokens"]
        summary["cached_input_tokens"] += entry["cached_input_tokens"]
        summary["output_tokens"] += entry["output_tokens"]
        summary["total_tokens"] += entry["total_tokens"]
        summary["last_turn_at"] = max(summary["last_turn_at"], finished_at)
    return summary


def load_usage_history(limit: int = MAX_USAGE_ITEMS) -> list[dict[str, Any]]:
    ensure_state_dir()
    entries: list[dict[str, Any]] = []
    try:
        lines = USAGE_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return entries
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        entries.append(normalize_usage_entry(payload))
    if limit and len(entries) > limit:
        return entries[-limit:]
    return entries


def append_usage_entry(
    *,
    started_at: int,
    finished_at: int,
    thread_id: str,
    speed: str,
    detail: int,
    success: bool,
    usage: dict[str, Any] | None = None,
) -> None:
    entries = load_usage_history(limit=0)
    entries.append(
        normalize_usage_entry(
            {
                **(usage or {}),
                "started_at": started_at,
                "finished_at": finished_at,
                "thread_id": thread_id,
                "speed": speed,
                "detail": detail,
                "success": success,
                "model": MODEL,
            }
        )
    )
    trimmed = entries[-MAX_USAGE_ITEMS:]
    ensure_state_dir()
    payload = "\n".join(json.dumps(item, sort_keys=True) for item in trimmed)
    if payload:
        payload += "\n"
    USAGE_PATH.write_text(payload, encoding="utf-8")


def usage_snapshot(
    entries: list[dict[str, Any]] | None = None, *, thread_id: str = ""
) -> dict[str, Any]:
    items = load_usage_history() if entries is None else entries
    normalized_items = [normalize_usage_entry(item) for item in items]
    clean_thread_id = str(thread_id or "").strip()
    current_thread_items = (
        [
            item
            for item in normalized_items
            if str(item.get("thread_id") or "").strip() == clean_thread_id
        ]
        if clean_thread_id
        else []
    )
    return {
        "tracked": bool(normalized_items),
        "window_seconds": USAGE_WINDOW_SECONDS,
        "totals": summarize_usage_entries(normalized_items),
        "last_24h": summarize_usage_entries(
            normalized_items, since_ts=max(0, now_ts() - USAGE_WINDOW_SECONDS)
        ),
        "current_thread": summarize_usage_entries(current_thread_items)
        if clean_thread_id
        else dict(default_usage_summary()),
        "last_turn": normalize_usage_entry(normalized_items[-1])
        if normalized_items
        else default_usage_entry(),
        "recent": list(normalized_items[-USAGE_RECENT_ITEMS:]),
    }


def default_kpi_snapshot() -> dict[str, Any]:
    return {
        "schema": "norman.tui.kpis.v1",
        "host_name": HOST_NAME,
        "agent_name": AGENT_NAME,
        "session_name": SESSION,
        "observed_at": 0,
        "state": "unknown",
        "activity_state": "unknown",
        "health_state": "unknown",
        "diagnosis": "No KPI snapshot has been collected yet.",
        "prompt_visible": False,
        "waiting_visible": False,
        "stale_seconds": 0,
        "last_output_changed_at": 0,
        "last_pane_hash": "",
        "state_entered_at": 0,
        "signals": [],
        "metrics": {
            "turns": 0,
            "successful_turns": 0,
            "failed_turns": 0,
            "avg_turn_seconds": 0,
            "last_turn_at": 0,
            "pending_seconds": 0,
            "queue_depth": 0,
            "wedge_count": 0,
            "blocked_count": 0,
            "degraded_count": 0,
            "state_changes": 0,
        },
    }


def load_kpi_snapshot() -> dict[str, Any]:
    ensure_state_dir()
    return read_json(KPI_PATH, default_kpi_snapshot())


def _pane_hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", "replace")).hexdigest()


def _pane_prompt_visible(value: Any) -> bool:
    text = str(value or "")
    if not text:
        return False
    prompt_markers = (
        "\n› ",
        "\n> ",
        "OpenAI Codex (v",
        "Tip: Use /status",
        "% left ·",
        "Use /skills to list available skills",
    )
    return any(marker in text for marker in prompt_markers) or text.lstrip().startswith(
        ("› ", "> ")
    )


def _pane_waiting_visible(value: Any) -> bool:
    text = str(value or "").lower()
    if not text:
        return False
    waiting_markers = (
        "press enter to continue",
        "do you trust the contents of this directory",
        "complete device-code sign-in",
        "choose sign-in",
        "continue sign-in",
        "waiting for operator input",
    )
    return any(marker in text for marker in waiting_markers)


def _contains_usage_limit_error(value: Any) -> bool:
    text = str(value or "").lower()
    if not text:
        return False
    return (
        "you've hit your usage limit" in text
        or "you hit your usage limit" in text
        or ("usage limit" in text and "try again at" in text)
        or ("usage limit" in text and "send a request to your admin" in text)
    )


def _kpi_signal(
    code: str, severity: str, summary: str, detail: str = ""
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "summary": summary,
        "detail": detail,
    }


def detect_kpi_signals(
    snapshot: dict[str, Any],
    pane: str,
    prompt_visible: bool,
    waiting_visible: bool,
    stale_seconds: int,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    auth = snapshot.get("auth") if isinstance(snapshot.get("auth"), dict) else {}
    if bool(auth.get("required")):
        signals.append(
            _kpi_signal(
                "auth_required",
                "blocked",
                str(auth.get("summary") or "The TUI needs a fresh sign-in."),
            )
        )
    combined_error = "\n".join(
        [
            str(snapshot.get("last_error") or ""),
            pane,
            json.dumps(snapshot.get("history") or [])[-4000:],
        ]
    )
    if _contains_usage_limit_error(combined_error):
        signals.append(
            _kpi_signal(
                "usage_limit",
                "blocked",
                "The model provider is reporting a usage limit.",
            )
        )
    lower_pane = pane.lower()
    if (
        "disabled `js_repl`" in lower_pane
        or "node runtime too old" in lower_pane
        or ("node runtime" in lower_pane and "incompatible" in lower_pane)
    ):
        signals.append(
            _kpi_signal(
                "js_repl_node_too_old",
                "degraded",
                "The JavaScript REPL tool is disabled because Node is too old or incompatible.",
            )
        )
    if (
        "model resume mismatch" in lower_pane
        or (
            "resume" in lower_pane
            and "model" in lower_pane
            and "mismatch" in lower_pane
        )
        or (
            "requested model" in lower_pane
            and "session" in lower_pane
            and "model" in lower_pane
        )
    ):
        signals.append(
            _kpi_signal(
                "model_resume_mismatch",
                "degraded",
                "The visible session mentions a model/resume mismatch.",
            )
        )
    for service in snapshot.get("services") or []:
        if not isinstance(service, dict):
            continue
        state = str(service.get("state") or "").strip().lower()
        if state in {"failed", "inactive", "dead"}:
            signals.append(
                _kpi_signal(
                    "service_not_active",
                    "degraded",
                    f"{service.get('name') or 'service'} is {state}.",
                )
            )
    if (
        stale_seconds >= KPI_WEDGE_SECONDS
        and not prompt_visible
        and not waiting_visible
    ):
        signals.append(
            _kpi_signal(
                "no_prompt_stale",
                "wedged",
                "The pane has not changed and no ready prompt is visible.",
            )
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in signals:
        code = str(item.get("code") or "")
        if code in seen:
            continue
        seen.add(code)
        deduped.append(item)
    return deduped


def _usage_duration_metrics(entries: list[dict[str, Any]]) -> dict[str, int]:
    durations: list[int] = []
    for entry in entries:
        started = _coerce_int(entry.get("started_at"))
        finished = _coerce_int(entry.get("finished_at"))
        if started > 0 and finished >= started:
            durations.append(finished - started)
    return {
        "avg_turn_seconds": int(sum(durations) / len(durations)) if durations else 0
    }


def build_kpi_snapshot(
    snapshot: dict[str, Any], previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    previous = previous if isinstance(previous, dict) else {}
    now = now_ts()
    pane = str(snapshot.get("pane") or "")
    pane_hash = _pane_hash(pane)
    previous_hash = str(previous.get("last_pane_hash") or "")
    if previous_hash and previous_hash == pane_hash:
        last_output_changed_at = (
            _coerce_int(previous.get("last_output_changed_at")) or now
        )
    else:
        last_output_changed_at = now
    stale_seconds = max(0, now - last_output_changed_at)
    prompt_is_visible = _pane_prompt_visible(pane)
    waiting_is_visible = _pane_waiting_visible(pane)
    pending = bool(snapshot.get("pending"))
    signals = detect_kpi_signals(
        snapshot,
        pane,
        prompt_is_visible,
        waiting_is_visible,
        stale_seconds,
    )
    severities = {str(signal.get("severity") or "") for signal in signals}
    if "blocked" in severities:
        state, activity_state, health_state = "blocked", "waiting", "blocked"
    elif "wedged" in severities:
        state, activity_state, health_state = "wedged", "stalled", "wedged"
    elif "degraded" in severities:
        state = "degraded"
        activity_state = (
            "working" if pending else "idle" if prompt_is_visible else "unknown"
        )
        health_state = "degraded"
    elif (
        pending
        or bool(snapshot.get("model_process_alive"))
        or bool(snapshot.get("web_worker_alive"))
    ):
        state, activity_state, health_state = "working", "working", "ok"
    elif waiting_is_visible:
        state, activity_state, health_state = "waiting", "waiting", "ok"
    elif prompt_is_visible:
        state, activity_state, health_state = "idle", "idle", "ok"
    elif stale_seconds >= KPI_WEDGE_SECONDS:
        state, activity_state, health_state = "wedged", "stalled", "wedged"
    else:
        state, activity_state, health_state = "working", "working", "unknown"
    previous_state = str(previous.get("state") or "")
    previous_metrics = (
        previous.get("metrics") if isinstance(previous.get("metrics"), dict) else {}
    )
    state_entered_at = _coerce_int(previous.get("state_entered_at")) or now
    state_changes = _coerce_int(previous_metrics.get("state_changes"))
    if previous_state and previous_state != state:
        state_entered_at = now
        state_changes += 1
    elif not previous_state:
        state_entered_at = now
    usage = snapshot.get("usage") if isinstance(snapshot.get("usage"), dict) else {}
    totals = usage.get("totals") if isinstance(usage.get("totals"), dict) else {}
    duration_metrics = _usage_duration_metrics(load_usage_history(limit=0))
    metrics = {
        "turns": _coerce_int(totals.get("turns")),
        "successful_turns": _coerce_int(totals.get("successful_turns")),
        "failed_turns": _coerce_int(totals.get("failed_turns")),
        "avg_turn_seconds": duration_metrics["avg_turn_seconds"],
        "last_turn_at": _coerce_int(totals.get("last_turn_at")),
        "pending_seconds": max(0, now - _coerce_int(snapshot.get("last_started_at")))
        if pending
        else 0,
        "queue_depth": _coerce_int(snapshot.get("queue_depth")),
        "wedge_count": _coerce_int(previous_metrics.get("wedge_count"))
        + int(previous_state != "wedged" and state == "wedged"),
        "blocked_count": _coerce_int(previous_metrics.get("blocked_count"))
        + int(previous_state != "blocked" and state == "blocked"),
        "degraded_count": _coerce_int(previous_metrics.get("degraded_count"))
        + int(previous_state != "degraded" and state == "degraded"),
        "state_changes": state_changes,
    }
    diagnosis = {
        "blocked": signals[0]["summary"] if signals else "The TUI is blocked.",
        "wedged": "The TUI has no prompt and has not produced output recently.",
        "degraded": signals[0]["summary"] if signals else "The TUI is degraded.",
        "working": "The TUI is actively working.",
        "idle": "The TUI is idle and ready.",
        "waiting": "The TUI is waiting for operator input.",
        "dead": "The TUI session is unavailable.",
    }.get(state, "The TUI state is not yet classified.")
    return {
        "schema": "norman.tui.kpis.v1",
        "host_name": HOST_NAME,
        "agent_name": AGENT_NAME,
        "session_name": SESSION,
        "observed_at": now,
        "state": state,
        "activity_state": activity_state,
        "health_state": health_state,
        "diagnosis": diagnosis,
        "prompt_visible": prompt_is_visible,
        "waiting_visible": waiting_is_visible,
        "stale_seconds": stale_seconds,
        "last_output_changed_at": last_output_changed_at,
        "last_pane_hash": pane_hash,
        "state_entered_at": state_entered_at,
        "signals": signals,
        "metrics": metrics,
    }


def update_kpi_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    with KPI_LOCK:
        payload = build_kpi_snapshot(snapshot, load_kpi_snapshot())
        write_json(KPI_PATH, payload)
        return payload


def current_kpis() -> dict[str, Any]:
    snapshot = current_snapshot()
    kpis = snapshot.get("kpis")
    return kpis if isinstance(kpis, dict) else load_kpi_snapshot()


def kpi_collector_loop() -> None:
    while True:
        try:
            current_snapshot()
        except Exception:
            pass
        time.sleep(max(5, KPI_INTERVAL_SECONDS))


def start_kpi_collector() -> None:
    global KPI_COLLECTOR_STARTED
    if KPI_COLLECTOR_STARTED or KPI_INTERVAL_SECONDS <= 0:
        return
    KPI_COLLECTOR_STARTED = True
    threading.Thread(
        target=kpi_collector_loop, name="tui-kpi-collector", daemon=True
    ).start()


def load_status_meta() -> dict[str, Any]:
    ensure_state_dir()
    return read_json(STATUS_PATH, default_status_meta())


def load_resource_meter_file() -> dict[str, Any]:
    try:
        payload = json.loads(RESOURCE_METER_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_queue(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return items
    for entry in value:
        if isinstance(entry, str):
            prompt = entry.strip()
            queued_at = 0
            speed = DEFAULT_RESPONSE_SPEED
            detail = DEFAULT_RESPONSE_DETAIL
        elif isinstance(entry, dict):
            prompt = str(entry.get("prompt") or "").strip()
            try:
                queued_at = int(entry.get("queued_at") or 0)
            except (TypeError, ValueError):
                queued_at = 0
            speed = normalize_response_speed(entry.get("speed"))
            detail = normalize_response_detail(entry.get("detail"))
            attachments = normalize_attachments(entry.get("attachments"))
            relay_callback = normalize_relay_callback(entry.get("relay_callback"))
            source = normalize_queue_source(entry.get("source"), relay_callback, prompt)
            recovered = bool(entry.get("recovered"))
        else:
            continue
        if not isinstance(entry, dict):
            attachments = []
            relay_callback = {}
            source = normalize_queue_source("", relay_callback, prompt)
            recovered = False
        if prompt:
            item = {
                "prompt": prompt,
                "queued_at": queued_at,
                "speed": speed,
                "detail": detail,
                "attachments": attachments,
                "source": source,
                "recovered": recovered,
            }
            if relay_callback:
                item["relay_callback"] = relay_callback
            items.append(item)
    return items


def normalize_queue_source(
    value: Any, relay_callback: dict[str, Any] | None = None, prompt: str = ""
) -> str:
    clean = str(value or "").strip().lower()
    if clean in {"operator", "relay", "passive", "system", "recovered"}:
        return clean
    text = str(prompt or "").lower()
    if relay_callback:
        return "relay"
    if "passive fleet context" in text or "party line" in text or "bbs" in text:
        return "passive"
    return "operator"


def normalize_relay_callback(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "relay_id",
        "callback_url",
        "source_channel_id",
        "source_message_id",
        "target_connector_name",
    }
    return {
        key: value.get(key)
        for key in allowed
        if str(value.get(key) or "").strip() or isinstance(value.get(key), int)
    }


def save_status_meta(meta: dict[str, Any]) -> dict[str, Any]:
    payload = dict(default_status_meta())
    payload.update(meta)
    payload["running_speed"] = normalize_response_speed(payload.get("running_speed"))
    payload["running_detail"] = normalize_response_detail(payload.get("running_detail"))
    payload["running_attachments"] = normalize_attachments(
        payload.get("running_attachments")
    )
    payload["last_speed"] = normalize_response_speed(payload.get("last_speed"))
    payload["last_detail"] = normalize_response_detail(payload.get("last_detail"))
    payload["last_attachments"] = normalize_attachments(payload.get("last_attachments"))
    payload["queued_prompts"] = normalize_queue(payload.get("queued_prompts"))
    if not isinstance(payload.get("resource_meter"), dict):
        payload["resource_meter"] = {}
    else:
        payload["resource_meter"]["kpi_meters"] = normalize_kpi_meters(
            payload["resource_meter"].get("kpi_meters")
        )
    payload["updated_at"] = now_ts()
    write_json(STATUS_PATH, payload)
    return payload


def update_status_meta(**updates: Any) -> dict[str, Any]:
    with STATUS_LOCK:
        meta = load_status_meta()
        meta.update(updates)
        return save_status_meta(meta)


def prompt_thread_alive() -> bool:
    return ACTIVE_PROMPT_THREAD is not None and ACTIVE_PROMPT_THREAD.is_alive()


def codex_exec_child_alive() -> bool:
    parent_pid = str(os.getpid())
    state_dir_marker = str(STATE_DIR)
    proc_root = Path("/proc")
    if not proc_root.exists():
        return False
    for proc_dir in proc_root.iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            stat_fields = (proc_dir / "stat").read_text().split()
            if len(stat_fields) < 4 or stat_fields[3] != parent_pid:
                continue
            cmdline = (proc_dir / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            continue
        command = cmdline.decode("utf-8", errors="replace")
        if "codex exec" in command and state_dir_marker in command:
            return True
    return False


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def active_codex_process_alive() -> bool:
    with ACTIVE_CODEX_LOCK:
        proc = ACTIVE_CODEX_PROC
    if proc is not None and proc.poll() is None:
        return True
    meta = load_status_meta()
    return pid_alive(_coerce_int(meta.get("active_child_pid")))


def prompt_runtime_alive() -> bool:
    return (
        prompt_thread_alive()
        or active_codex_process_alive()
        or codex_exec_child_alive()
    )


def working_response_text(prompt: str) -> str:
    return f"Working on: {summarize_text(prompt, 180)}. New messages will be queued."


def set_active_codex_process(proc: subprocess.Popen[str] | None) -> None:
    global ACTIVE_CODEX_PROC
    with ACTIVE_CODEX_LOCK:
        ACTIVE_CODEX_PROC = proc
    if proc is None:
        update_status_meta(
            active_child_pid=0,
            active_child_pgid=0,
            active_child_started_at=0,
        )
        return
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = proc.pid
    update_status_meta(
        active_child_pid=int(proc.pid),
        active_child_pgid=int(pgid),
        active_child_started_at=now_ts(),
        cancel_requested_at=0,
        status_message="Waiting for model process.",
    )


def terminate_process_group(pid: int, pgid: int) -> bool:
    target_pgid = pgid or pid
    if target_pgid <= 0:
        return False
    try:
        os.killpg(target_pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except OSError:
            return False
    for _ in range(12):
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    try:
        os.killpg(target_pgid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except OSError:
            return False
    return not pid_alive(pid)


def launch_prompt_worker(
    prompt: str,
    started_at: int,
    speed: str,
    detail: int,
    attachments: list[dict[str, Any]],
    relay_callback: dict[str, Any] | None = None,
) -> None:
    global ACTIVE_PROMPT_THREAD
    thread = threading.Thread(
        target=_prompt_worker,
        args=(
            prompt,
            started_at,
            normalize_response_speed(speed),
            normalize_response_detail(detail),
            normalize_attachments(attachments),
            normalize_relay_callback(relay_callback),
        ),
        daemon=True,
    )
    ACTIVE_PROMPT_THREAD = thread
    thread.start()


def queue_prompt(
    prompt: str,
    speed: str,
    detail: int,
    attachments: list[dict[str, Any]],
    relay_callback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with STATUS_LOCK:
        meta = load_status_meta()
        queue = normalize_queue(meta.get("queued_prompts"))
        normalized_relay = normalize_relay_callback(relay_callback)
        source = normalize_queue_source("", normalized_relay, prompt)
        position = len(queue) + 1
        normalized_attachments = normalize_attachments(attachments)
        attachment_phrase = attachment_count_phrase(normalized_attachments)
        attachment_suffix = f" with {attachment_phrase}" if attachment_phrase else ""
        item = {
            "prompt": prompt,
            "queued_at": now_ts(),
            "speed": normalize_response_speed(speed),
            "detail": normalize_response_detail(detail),
            "attachments": normalized_attachments,
            "source": source,
        }
        if normalized_relay:
            item["relay_callback"] = normalized_relay
        queue.append(item)
        meta["queued_prompts"] = queue
        meta["last_action"] = "queue-prompt"
        meta["last_action_at"] = now_ts()
        meta["last_action_detail"] = (
            f"Queued prompt{attachment_suffix} at position {position}. "
            "It will run after the current web reply."
        )
        meta["status_message"] = (
            f"Queued prompt{attachment_suffix} at position {position}. "
            "Current web reply is still running."
        )
        save_status_meta(meta)
    append_audit_event(
        event_type="chat.queued",
        summary="Queued a follow-up prompt in the web TUI.",
        detail=summarize_text(prompt, 180),
        severity="info",
        actor_type="operator",
        thread_id=read_text(THREAD_ID_PATH),
        payload={
            "prompt_preview": summarize_text(prompt, 240),
            "speed": normalize_response_speed(speed),
            "detail": normalize_response_detail(detail),
            "attachment_count": len(attachments),
            "attachment_summary": attachment_phrase,
            "queue_position": position,
            "source": source,
        },
    )
    return current_snapshot()


def recover_stale_prompt_state() -> None:
    if prompt_runtime_alive():
        with STATUS_LOCK:
            meta = load_status_meta()
            last_prompt = read_text(LAST_PROMPT_PATH).strip()
            last_response = read_text(LAST_RESPONSE_PATH).strip()
            if (
                not meta.get("pending")
                and last_prompt
                and last_response == "[waiting for reply]"
            ):
                meta.update(
                    {
                        "pending": True,
                        "state": "running",
                        "status_message": f"{AGENT_NAME} is working.",
                        "running_prompt": last_prompt,
                        "running_attachments": normalize_attachments(
                            meta.get("running_attachments")
                        ),
                        "last_started_at": int(meta.get("last_started_at") or now_ts()),
                    }
                )
                save_status_meta(meta)
        return
    with STATUS_LOCK:
        meta = load_status_meta()
        queue = normalize_queue(meta.get("queued_prompts"))
        running_prompt = str(meta.get("running_prompt") or "").strip()
        if meta.get("pending") and running_prompt:
            queue.insert(
                0,
                {
                    "prompt": running_prompt,
                    "queued_at": int(meta.get("last_started_at") or now_ts()),
                    "speed": normalize_response_speed(meta.get("running_speed")),
                    "detail": normalize_response_detail(meta.get("running_detail")),
                    "attachments": normalize_attachments(
                        meta.get("running_attachments")
                    ),
                    "source": "recovered",
                    "recovered": True,
                },
            )
        if not meta.get("pending") and not queue:
            return
        meta.update(
            {
                "pending": False,
                "state": "recovered",
                "status_message": "Recovered queued work after restart. Review the queue before resuming.",
                "running_prompt": "",
                "running_attachments": [],
                "queued_prompts": queue,
                "recovered_after_restart": True,
                "stale_queue": bool(queue),
                "active_child_pid": 0,
                "active_child_pgid": 0,
                "active_child_started_at": 0,
            }
        )
        save_status_meta(meta)


def start_next_queued_prompt() -> (
    tuple[str, int, str, int, list[dict[str, Any]], dict[str, Any]] | None
):
    with STATUS_LOCK:
        meta = load_status_meta()
        queue = normalize_queue(meta.get("queued_prompts"))
        if not queue:
            meta["queued_prompts"] = []
            save_status_meta(meta)
            return None
        item = queue.pop(0)
        started_at = now_ts()
        prompt = item["prompt"]
        speed = normalize_response_speed(item.get("speed"))
        detail = normalize_response_detail(item.get("detail"))
        attachments = normalize_attachments(item.get("attachments"))
        relay_callback = normalize_relay_callback(item.get("relay_callback"))
        write_text(LAST_PROMPT_PATH, prompt)
        write_text(LAST_RESPONSE_PATH, working_response_text(prompt))
        write_text(LAST_ERROR_PATH, "")
        meta.update(
            {
                "pending": True,
                "state": "running",
                "status_message": f"{AGENT_NAME} is working.",
                "running_prompt": prompt,
                "running_attachments": attachments,
                "running_speed": speed,
                "running_detail": detail,
                "last_started_at": started_at,
                "queued_prompts": queue,
                "recovered_after_restart": False,
                "stale_queue": False,
                "cancel_requested_at": 0,
            }
        )
        save_status_meta(meta)
    return prompt, started_at, speed, detail, attachments, relay_callback


def record_action(action: str, detail: str) -> None:
    update_status_meta(
        last_action=action,
        last_action_at=now_ts(),
        last_action_detail=detail,
        status_message=detail,
    )
    severity = (
        "error"
        if "error" in action
        else "warn"
        if action in {"tmux-interrupt", "tmux-restart"}
        else "info"
    )
    append_audit_event(
        event_type=action,
        summary=detail,
        detail=detail,
        severity=severity,
        actor_type="operator",
        thread_id=read_text(THREAD_ID_PATH),
        payload={"action": action},
    )


def session_exists() -> bool:
    proc = run(tmux_cmd("has-session", "-t", SESSION))
    return proc.returncode == 0


def ensure_session() -> bool:
    if session_exists():
        return True
    proc = run(["systemctl", "start", CODEX_SERVICE])
    if proc.returncode != 0:
        return False
    for _ in range(20):
        if session_exists():
            return True
        time.sleep(0.5)
    return False


def capture_pane() -> str:
    if not session_exists():
        return "[session unavailable]"
    proc = run(
        tmux_cmd(
            "capture-pane",
            "-p",
            "-t",
            f"{SESSION}:0.0",
            "-S",
            f"-{MAX_PANE_LINES}",
        )
    )
    text = proc.stdout or proc.stderr
    return truncate_block(text) or "[pane empty]"


def send_text(text: str) -> None:
    if not ensure_session():
        raise RuntimeError("Codex session could not be started.")
    buffer_name = f"{SESSION}-web-{int(time.time() * 1000)}"
    try:
        run(
            tmux_cmd("load-buffer", "-b", buffer_name, "-"), input_text=text, check=True
        )
        run(
            tmux_cmd("paste-buffer", "-d", "-b", buffer_name, "-t", f"{SESSION}:0.0"),
            check=True,
        )
        run(tmux_cmd("send-keys", "-t", f"{SESSION}:0.0", "Enter"), check=True)
    finally:
        run(tmux_cmd("delete-buffer", "-b", buffer_name))
    record_action("tmux-send", f"Sent raw text to tmux: {summarize_text(text, 140)}")


def send_keys(*keys: str) -> None:
    if not ensure_session():
        raise RuntimeError("Codex session could not be started.")
    run(tmux_cmd("send-keys", "-t", f"{SESSION}:0.0", *keys), check=True)


def _run_post_auth_self_check(*, timeout: float = 10.0) -> tuple[bool, str]:
    if not ensure_session():
        return False, "Sign-in delivered, but the Codex session is unavailable."

    deadline = time.time() + max(timeout, 1.0)
    advanced_steps: list[str] = []
    latest = capture_pane()

    while time.time() < deadline:
        latest = capture_pane()
        if _contains_signed_in_banner(latest):
            send_keys("Enter")
            advanced_steps.append("accepted the signed-in banner")
            time.sleep(0.35)
            continue
        if _contains_trust_directory_prompt(latest):
            send_keys("1", "Enter")
            advanced_steps.append("trusted the working directory")
            time.sleep(0.35)
            continue
        if _contains_active_update_interstitial(latest):
            send_keys("Enter")
            advanced_steps.append("cleared the update interstitial")
            time.sleep(0.35)
            continue
        auth_state = _auth_state_from_console(latest, read_text(LAST_ERROR_PATH))
        if auth_state.get("required"):
            time.sleep(0.35)
            continue
        if _contains_codex_ready_prompt(latest):
            detail = f"{AGENT_NAME} is ready. Self-check passed."
            if advanced_steps:
                detail = f"{detail} Auto-finished: {', '.join(advanced_steps)}."
            return True, detail
        time.sleep(0.35)

    detail = "Sign-in delivered, but readiness is still settling."
    if advanced_steps:
        detail = f"{detail} Auto-finished: {', '.join(advanced_steps)}."
    return False, detail


def send_interrupt() -> None:
    if ensure_session():
        run(tmux_cmd("send-keys", "-t", f"{SESSION}:0.0", "C-c"), check=True)
    record_action("tmux-interrupt", "Sent Ctrl+C to the interactive tmux session.")


def clear_queued_prompts(reason: str = "Cleared queued web prompts.") -> dict[str, Any]:
    with STATUS_LOCK:
        meta = load_status_meta()
        queue = normalize_queue(meta.get("queued_prompts"))
        cleared = len(queue)
        meta["queued_prompts"] = []
        meta["stale_queue"] = False
        meta["last_action"] = "queue-clear"
        meta["last_action_at"] = now_ts()
        meta["last_action_detail"] = reason
        meta["status_message"] = reason
        save_status_meta(meta)
    append_audit_event(
        event_type="queue.cleared",
        summary=reason,
        detail=f"Cleared {cleared} queued prompt{'s' if cleared != 1 else ''}.",
        severity="warn",
        actor_type="operator",
        thread_id=read_text(THREAD_ID_PATH),
        payload={"cleared": cleared},
    )
    return current_snapshot()


def promote_latest_operator_prompt() -> dict[str, Any]:
    item: dict[str, Any] | None = None
    return_snapshot = False
    with STATUS_LOCK:
        meta = load_status_meta()
        queue = normalize_queue(meta.get("queued_prompts"))
        if len(queue) < 2:
            meta["last_action"] = "queue-promote"
            meta["last_action_at"] = now_ts()
            meta["last_action_detail"] = (
                "Queue promotion skipped; fewer than two queued prompts."
            )
            save_status_meta(meta)
            return_snapshot = True
        else:
            selected_index = -1
            for index in range(len(queue) - 1, -1, -1):
                if queue[index].get("source") == "operator":
                    selected_index = index
                    break
            if selected_index <= 0:
                meta["last_action"] = "queue-promote"
                meta["last_action_at"] = now_ts()
                meta["last_action_detail"] = "Latest operator prompt is already next."
                save_status_meta(meta)
                item = None
                return_snapshot = True
            else:
                item = queue.pop(selected_index)
                queue.insert(0, item)
                meta["queued_prompts"] = queue
                meta["last_action"] = "queue-promote"
                meta["last_action_at"] = now_ts()
                meta["last_action_detail"] = (
                    "Promoted the latest operator prompt to the front of the queue."
                )
                meta["status_message"] = (
                    "Latest operator prompt will run next after the current web reply."
                )
                save_status_meta(meta)
    if return_snapshot:
        return current_snapshot()
    append_audit_event(
        event_type="queue.promoted",
        summary="Promoted latest operator prompt.",
        detail=summarize_text((item or {}).get("prompt") or "", 220),
        severity="warn",
        actor_type="operator",
        thread_id=read_text(THREAD_ID_PATH),
        payload={
            "prompt_preview": summarize_text((item or {}).get("prompt") or "", 240)
        },
    )
    return current_snapshot()


def cancel_active_web_prompt(clear_queue: bool = False) -> dict[str, Any]:
    meta = update_status_meta(
        state="cancelling",
        status_message="Cancelling current web reply.",
        cancel_requested_at=now_ts(),
        last_action="web-cancel",
        last_action_at=now_ts(),
        last_action_detail="Cancelling current web reply.",
    )
    pid = _coerce_int(meta.get("active_child_pid"))
    pgid = _coerce_int(meta.get("active_child_pgid"))
    killed = terminate_process_group(pid, pgid) if pid else False
    if not pid or not killed:
        with ACTIVE_CODEX_LOCK:
            proc = ACTIVE_CODEX_PROC
        if proc is not None and proc.poll() is None:
            try:
                pgid = os.getpgid(proc.pid)
            except OSError:
                pgid = proc.pid
            killed = terminate_process_group(proc.pid, pgid)
            pid = proc.pid
    if clear_queue:
        with STATUS_LOCK:
            meta = load_status_meta()
            meta["queued_prompts"] = []
            meta["stale_queue"] = False
            save_status_meta(meta)
    if not killed and not prompt_runtime_alive():
        write_text(LAST_RESPONSE_PATH, CANCELLED_WEB_REPLY_MESSAGE)
        write_text(LAST_ERROR_PATH, CANCELLED_WEB_REPLY_MESSAGE)
        update_status_meta(
            pending=False,
            state="cancelled",
            status_message="Web prompt cancelled.",
            running_prompt="",
            running_attachments=[],
            active_child_pid=0,
            active_child_pgid=0,
            active_child_started_at=0,
            cancel_requested_at=0,
        )
    append_audit_event(
        event_type="chat.cancel-requested",
        summary="Cancel requested for current web reply.",
        detail=(
            "Terminated active codex exec process."
            if killed
            else "No active codex exec process was found."
        ),
        severity="warn",
        actor_type="operator",
        thread_id=read_text(THREAD_ID_PATH),
        payload={
            "pid": pid,
            "pgid": pgid,
            "killed": killed,
            "cleared_queue": clear_queue,
        },
    )
    return current_snapshot()


def restart_session() -> None:
    run(tmux_cmd("kill-session", "-t", SESSION))
    run(["systemctl", "restart", CODEX_SERVICE])
    ensure_session()
    record_action(
        "tmux-restart", f"Restarted the interactive {AGENT_NAME} Codex tmux session."
    )


def service_status(units: list[str]) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for unit in units:
        clean = unit.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        proc = run(["systemctl", "is-active", clean])
        value = (proc.stdout or proc.stderr).strip() or "unknown"
        results.append((clean, value))
    return results


def housebot_log_tail() -> str:
    proc = run(
        [
            "journalctl",
            "-u",
            HOUSEBOT_SERVICE,
            "-n",
            str(MAX_LOG_LINES),
            "--no-pager",
            "-o",
            "cat",
        ]
    )
    text = proc.stdout or proc.stderr
    return truncate_block(text) or "[no housebot journal output]"


def attachment_prompt_context(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return ""
    lines = [
        "",
        "Staged material for this prompt:",
        "Treat these as supporting context. Do not default to summarizing staged material unless the operator asks for that explicitly.",
    ]
    for entry in normalize_attachments(attachments):
        token = entry["token"]
        path = entry["path"]
        summary = entry.get("summary") or build_attachment_summary(
            token=token,
            name=entry["name"],
            content_type=entry["content_type"],
            size=entry["size"],
            kind=entry["kind"],
            source=str(entry.get("source") or ""),
            line_count=int(entry.get("line_count") or 0),
            char_count=int(entry.get("char_count") or 0),
            url=str(entry.get("url") or ""),
        )
        lines.append(f"- {summary} · path: {path}")
        if entry["kind"] == "text":
            body = read_text(Path(path))
            if body:
                truncated = truncate_block(body, MAX_ATTACHMENT_TEXT_CHARS)
                lines.append(f"  [{token}] inline content:")
                for line in truncated.splitlines():
                    lines.append(f"    {line}")
            else:
                lines.append(
                    f"  [{token}] text content could not be read; inspect {path} directly."
                )
        else:
            lines.append(
                f"  [{token}] is available as a local file at {path}. Inspect it directly if useful."
            )
    return "\n".join(lines)


def build_prompt_with_attachments(
    prompt: str, detail: int, attachments: list[dict[str, Any]]
) -> str:
    combined = prompt.strip()
    attachment_context = attachment_prompt_context(attachments)
    if attachment_context:
        combined = f"{combined}\n{attachment_context}".strip()
    return build_tuned_prompt(combined, detail)


NO_LAST_AGENT_MESSAGE_RE = re.compile(
    r"^Warning: no last agent message; wrote empty content to .+$"
)
WEB_PROMPT_TIMED_OUT_PREFIX = "Web prompt timed out after "


def strip_codex_empty_last_message_warning(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        if _is_codex_transient_stderr_noise(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def process_output_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def communicate_with_prompt_timeout(
    popen: subprocess.Popen[str],
) -> tuple[str, str, bool]:
    timeout = max(0, WEB_PROMPT_TIMEOUT_SECONDS)
    if timeout <= 0:
        stdout_text, stderr_text = popen.communicate()
        return process_output_text(stdout_text), process_output_text(stderr_text), False
    try:
        stdout_text, stderr_text = popen.communicate(timeout=timeout)
        return process_output_text(stdout_text), process_output_text(stderr_text), False
    except TypeError:
        # Older test doubles do not accept the timeout kwarg.
        stdout_text, stderr_text = popen.communicate()
        return process_output_text(stdout_text), process_output_text(stderr_text), False
    except subprocess.TimeoutExpired as exc:
        stdout_parts = [process_output_text(exc.stdout)]
        stderr_parts = [process_output_text(exc.stderr)]
        try:
            pgid = os.getpgid(popen.pid)
        except OSError:
            pgid = popen.pid
        terminate_process_group(popen.pid, pgid)
        try:
            tail_stdout, tail_stderr = popen.communicate(
                timeout=max(0.1, WEB_PROMPT_TIMEOUT_GRACE_SECONDS)
            )
            stdout_parts.append(process_output_text(tail_stdout))
            stderr_parts.append(process_output_text(tail_stderr))
        except (subprocess.TimeoutExpired, TypeError):
            terminate_process_group(popen.pid, pgid)
        return (
            "\n".join(part for part in stdout_parts if part).strip(),
            "\n".join(part for part in stderr_parts if part).strip(),
            True,
        )


def notify_relay_callback(
    relay_callback: dict[str, Any],
    *,
    success: bool,
    summary: str,
    thread_id: str,
    started_at: int,
    finished_at: int,
) -> bool:
    callback = normalize_relay_callback(relay_callback)
    callback_url = str(callback.get("callback_url") or "").strip()
    if not callback_url:
        return False
    payload = {
        "relay_id": callback.get("relay_id"),
        "source_channel_id": callback.get("source_channel_id"),
        "source_message_id": callback.get("source_message_id"),
        "status": "closed" if success else "failed",
        "success": bool(success),
        "summary": summarize_text(summary, 1000),
        "thread_id": str(thread_id or ""),
        "target": AGENT_NAME,
        "started_at": int(started_at or 0),
        "finished_at": int(finished_at or 0),
    }
    request = urllib_request.Request(
        callback_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=8) as response:
            response.read()
        return True
    except Exception:
        return False


def _execute_codex_prompt(
    prompt: str, speed: str, detail: int, attachments: list[dict[str, Any]]
) -> tuple[str, str, str, dict[str, Any]]:
    session_id = read_text(THREAD_ID_PATH)
    output_path = STATE_DIR / "last_message.txt"
    if output_path.exists():
        output_path.unlink()

    normalized_speed = normalize_response_speed(speed)
    normalized_detail = normalize_response_detail(detail)
    cmd = [
        CODEX_BIN,
        "exec",
        "--json",
        "--dangerously-bypass-approvals-and-sandbox",
        "-m",
        MODEL,
        "-c",
        f'model_reasoning_effort="{response_reasoning_effort(normalized_speed)}"',
        "-C",
        WORKDIR,
        "-o",
        str(output_path),
    ]
    tuned_prompt = build_prompt_with_attachments(prompt, normalized_detail, attachments)
    if session_id:
        cmd.extend(["resume", session_id, tuned_prompt])
    else:
        cmd.append(tuned_prompt)

    env = dict(os.environ)
    env["CODEX_HOME"] = CODEX_HOME
    popen = subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    set_active_codex_process(popen)
    try:
        stdout_text, stderr_text, timed_out = communicate_with_prompt_timeout(popen)
    finally:
        set_active_codex_process(None)
    proc = subprocess.CompletedProcess(
        cmd,
        popen.returncode,
        stdout_text,
        stderr_text,
    )

    new_session_id = session_id
    messages: list[str] = []
    usage = default_usage_entry()
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            candidate = str(event.get("thread_id") or "").strip()
            if candidate:
                new_session_id = candidate
        elif event.get("type") == "turn.completed":
            usage = normalize_usage_entry(event.get("usage"))
        elif event.get("type") == "turn.failed":
            err = event.get("error") or {}
            msg = str(err.get("message") or "").strip()
            if msg:
                messages.append(msg)

    if timed_out:
        return (
            "",
            f"{WEB_PROMPT_TIMED_OUT_PREFIX}{WEB_PROMPT_TIMEOUT_SECONDS} seconds and was terminated.",
            new_session_id,
            usage,
        )

    cancelled = (
        proc.returncode is not None
        and proc.returncode < 0
        and _coerce_int(load_status_meta().get("cancel_requested_at")) > 0
    )
    if cancelled:
        return "", CANCELLED_WEB_REPLY_MESSAGE, new_session_id, usage

    stderr_rollout_ids = codex_rollout_thread_not_found_ids(proc.stderr)
    message_rollout_ids = codex_rollout_thread_not_found_ids("\n".join(messages))
    if session_id and session_id in (stderr_rollout_ids | message_rollout_ids):
        write_text(THREAD_ID_PATH, "")
        new_session_id = ""
        messages = [
            message
            for message in messages
            if not CODEX_ROLLOUT_THREAD_NOT_FOUND_RE.search(message)
        ]
        resume_reset_note = "Codex resume state was stale and has been reset."
        append_audit_event(
            event_type="chat.resume-reset",
            summary=resume_reset_note,
            detail=resume_reset_note,
            severity="warn",
            actor_type="system",
            thread_id=session_id,
            payload={"thread_id": session_id},
        )

    if new_session_id:
        write_text(THREAD_ID_PATH, new_session_id)

    response = read_text(output_path)
    stderr_text = strip_codex_empty_last_message_warning(proc.stderr)
    error_text = "\n".join(
        part for part in [stderr_text, "\n".join(messages).strip()] if part
    ).strip()
    error_text = strip_codex_empty_last_message_warning(error_text)
    return response, error_text, new_session_id, usage


def _prompt_worker(
    prompt: str,
    started_at: int,
    speed: str,
    detail: int,
    attachments: list[dict[str, Any]],
    relay_callback: dict[str, Any] | None = None,
) -> None:
    global ACTIVE_PROMPT_THREAD
    normalized_relay_callback = normalize_relay_callback(relay_callback)
    next_prompt: (
        tuple[str, int, str, int, list[dict[str, Any]], dict[str, Any]] | None
    ) = None
    try:
        with PROMPT_LOCK:
            normalized_speed = normalize_response_speed(speed)
            normalized_detail = normalize_response_detail(detail)
            attachments = normalize_attachments(attachments)
            # A worker can wait here behind an older run; reassert ownership once
            # it actually has the prompt lock so stale completions cannot leave
            # the UI showing the wrong prompt or attachment state.
            update_status_meta(
                pending=True,
                state="running",
                status_message=f"{AGENT_NAME} is working.",
                running_prompt=prompt,
                running_attachments=attachments,
                running_speed=normalized_speed,
                running_detail=normalized_detail,
                last_started_at=started_at,
                recovered_after_restart=False,
                stale_queue=False,
                cancel_requested_at=0,
            )
            response, error_text, thread_id, usage = _execute_codex_prompt(
                prompt, normalized_speed, normalized_detail, attachments
            )
            cancelled = error_text == CANCELLED_WEB_REPLY_MESSAGE
            timed_out = error_text.startswith(WEB_PROMPT_TIMED_OUT_PREFIX)
            if not response and not error_text:
                error_text = "No final response was returned."
            finished_at = now_ts()
            write_text(LAST_PROMPT_PATH, prompt)
            visible_response = (
                CANCELLED_WEB_REPLY_MESSAGE
                if cancelled
                else error_text
                if timed_out and not response
                else response or "[no response returned]"
            )
            write_text(LAST_RESPONSE_PATH, visible_response)
            visible_error_text = (
                error_text if cancelled or timed_out or not response else ""
            )
            write_text(LAST_ERROR_PATH, visible_error_text)
            append_history_entry(
                prompt=prompt,
                response=visible_response,
                error_text=error_text,
                started_at=started_at,
                finished_at=finished_at,
                thread_id=thread_id,
                speed=normalized_speed,
                detail=normalized_detail,
                attachments=attachments,
                usage=usage,
            )
            append_audit_event(
                event_type="chat.cancelled"
                if cancelled
                else "chat.timed-out"
                if timed_out
                else "chat.completed"
                if response
                else "chat.failed",
                summary="Web prompt cancelled."
                if cancelled
                else "Web prompt timed out."
                if timed_out
                else "Web prompt completed."
                if response
                else "Web prompt failed.",
                detail=summarize_text(
                    visible_response or error_text or "[no response returned]",
                    220,
                ),
                severity="warn"
                if cancelled or timed_out
                else "info"
                if response
                else "error",
                actor_type="bot",
                thread_id=thread_id,
                payload={
                    "prompt_preview": summarize_text(prompt, 240),
                    "response_preview": summarize_text(
                        visible_response or error_text or "[no response returned]",
                        240,
                    ),
                    "speed": normalized_speed,
                    "detail": normalized_detail,
                    "attachment_count": len(attachments),
                    "usage": normalize_usage_entry(usage),
                    "success": bool(response) and not cancelled and not timed_out,
                    "cancelled": cancelled,
                    "timed_out": timed_out,
                },
                event_at=finished_at,
            )
            append_usage_entry(
                started_at=started_at,
                finished_at=finished_at,
                thread_id=thread_id,
                speed=normalized_speed,
                detail=normalized_detail,
                success=bool(response) and not cancelled and not timed_out,
                usage=usage,
            )
            update_status_meta(
                pending=False,
                state="cancelled"
                if cancelled
                else "error"
                if timed_out
                else "ok"
                if response
                else "error",
                status_message="Web prompt cancelled."
                if cancelled
                else "Web prompt timed out."
                if timed_out
                else "Web prompt completed."
                if response
                else "Web prompt failed.",
                running_prompt="",
                running_attachments=[],
                running_speed=normalized_speed,
                running_detail=normalized_detail,
                active_child_pid=0,
                active_child_pgid=0,
                active_child_started_at=0,
                cancel_requested_at=0,
                last_attachments=attachments,
                last_speed=normalized_speed,
                last_detail=normalized_detail,
                last_finished_at=finished_at,
            )
            if normalized_relay_callback:
                notify_relay_callback(
                    normalized_relay_callback,
                    success=bool(response) and not cancelled,
                    summary=visible_response or error_text or "[no response returned]",
                    thread_id=thread_id,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            next_prompt = start_next_queued_prompt()
    except Exception as exc:  # pragma: no cover - defensive bridge hardening
        finished_at = now_ts()
        write_text(LAST_PROMPT_PATH, prompt)
        write_text(LAST_RESPONSE_PATH, "")
        write_text(LAST_ERROR_PATH, str(exc))
        append_history_entry(
            prompt=prompt,
            response="",
            error_text=str(exc),
            started_at=started_at,
            finished_at=finished_at,
            thread_id=read_text(THREAD_ID_PATH),
            speed=speed,
            detail=detail,
            attachments=attachments,
            usage=default_usage_entry(),
        )
        append_audit_event(
            event_type="chat.crashed",
            summary="Web prompt crashed.",
            detail=summarize_text(str(exc), 220),
            severity="error",
            actor_type="bot",
            thread_id=read_text(THREAD_ID_PATH),
            payload={
                "prompt_preview": summarize_text(prompt, 240),
                "speed": normalize_response_speed(speed),
                "detail": normalize_response_detail(detail),
                "attachment_count": len(attachments),
                "error": str(exc),
            },
            event_at=finished_at,
        )
        append_usage_entry(
            started_at=started_at,
            finished_at=finished_at,
            thread_id=read_text(THREAD_ID_PATH),
            speed=speed,
            detail=detail,
            success=False,
            usage=default_usage_entry(),
        )
        update_status_meta(
            pending=False,
            state="error",
            status_message="Web prompt crashed.",
            running_prompt="",
            running_attachments=[],
            running_speed=normalize_response_speed(speed),
            running_detail=normalize_response_detail(detail),
            active_child_pid=0,
            active_child_pgid=0,
            active_child_started_at=0,
            cancel_requested_at=0,
            last_attachments=attachments,
            last_speed=normalize_response_speed(speed),
            last_detail=normalize_response_detail(detail),
            last_finished_at=finished_at,
        )
        if normalized_relay_callback:
            notify_relay_callback(
                normalized_relay_callback,
                success=False,
                summary=str(exc),
                thread_id=read_text(THREAD_ID_PATH),
                started_at=started_at,
                finished_at=finished_at,
            )
        next_prompt = start_next_queued_prompt()
    if next_prompt:
        (
            queued_prompt,
            queued_started_at,
            queued_speed,
            queued_detail,
            queued_attachments,
            queued_relay_callback,
        ) = next_prompt
        launch_prompt_worker(
            queued_prompt,
            queued_started_at,
            queued_speed,
            queued_detail,
            queued_attachments,
            queued_relay_callback,
        )


def start_web_prompt(
    prompt: str,
    speed: str,
    detail: int,
    attachments: list[dict[str, Any]] | None = None,
    relay_callback: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    clean = prompt.strip()
    if not clean:
        return False, current_snapshot()
    normalized_speed = normalize_response_speed(speed)
    normalized_detail = normalize_response_detail(detail)
    normalized_attachments = normalize_attachments(attachments or [])
    normalized_relay_callback = normalize_relay_callback(relay_callback)
    recover_stale_prompt_state()
    should_queue = True
    worker_args: (
        tuple[str, int, str, int, list[dict[str, Any]], dict[str, Any]] | None
    ) = None
    with STATUS_LOCK:
        meta = load_status_meta()
        if meta.get("pending"):
            pass
        else:
            write_text(LAST_PROMPT_PATH, clean)
            write_text(LAST_RESPONSE_PATH, working_response_text(clean))
            write_text(LAST_ERROR_PATH, "")
            meta.update(
                {
                    "pending": True,
                    "state": "running",
                    "status_message": f"{AGENT_NAME} is working.",
                    "running_prompt": clean,
                    "running_attachments": normalized_attachments,
                    "running_speed": normalized_speed,
                    "running_detail": normalized_detail,
                    "last_started_at": now_ts(),
                    "recovered_after_restart": False,
                    "stale_queue": False,
                    "cancel_requested_at": 0,
                }
            )
            save_status_meta(meta)
            started_at = int(meta.get("last_started_at") or now_ts())
            append_audit_event(
                event_type="chat.submitted",
                summary="Submitted a prompt from the web TUI.",
                detail=summarize_text(clean, 180),
                severity="info",
                actor_type="operator",
                thread_id=read_text(THREAD_ID_PATH),
                payload={
                    "prompt_preview": summarize_text(clean, 240),
                    "speed": normalized_speed,
                    "detail": normalized_detail,
                    "attachment_count": len(normalized_attachments),
                },
                event_at=started_at,
            )
            worker_args = (
                clean,
                started_at,
                normalized_speed,
                normalized_detail,
                normalized_attachments,
                normalized_relay_callback,
            )
            should_queue = False
    if not should_queue:
        if worker_args is not None:
            launch_prompt_worker(*worker_args)
        accepted_snapshot = current_snapshot()
        accepted_snapshot.update(
            {
                "pending": True,
                "state": "running",
                "status_message": f"{AGENT_NAME} is working.",
                "running_prompt": clean,
                "running_attachments": normalized_attachments,
                "running_speed": normalized_speed,
                "running_detail": normalized_detail,
            }
        )
        return True, accepted_snapshot
    return True, queue_prompt(
        clean,
        normalized_speed,
        normalized_detail,
        normalized_attachments,
        normalized_relay_callback,
    )


def current_snapshot() -> dict[str, Any]:
    recover_stale_prompt_state()
    meta = load_status_meta()
    history = load_history()
    if history:
        history, _ = clear_codex_transient_error_history(history)
    thread_id = read_text(THREAD_ID_PATH)
    usage = usage_snapshot(thread_id=thread_id)
    queued_prompts = normalize_queue(meta.get("queued_prompts"))
    last_error = read_text(LAST_ERROR_PATH)
    filtered_last_error = strip_codex_empty_last_message_warning(last_error)
    if filtered_last_error != str(last_error or "").strip():
        last_error = filtered_last_error
        write_text(LAST_ERROR_PATH, last_error)
    pane = capture_pane()
    snapshot_state = str(meta.get("state") or "idle")
    snapshot_status = str(meta.get("status_message") or "Ready.")
    session_past_auth_prompt = _session_is_past_auth_prompt(
        pane
    ) or _contains_codex_ready_prompt(pane)
    session_ready_for_cleanup = (
        session_past_auth_prompt or _contains_active_update_interstitial(pane)
    )
    if history and session_ready_for_cleanup and not bool(meta.get("pending")):
        history, cleared_trailing_reauth = clear_trailing_reauth_history(history)
        if cleared_trailing_reauth and _contains_codex_auth_failure(last_error):
            last_error = ""
            write_text(LAST_ERROR_PATH, "")
        removed_trailing_ghosts: list[dict[str, Any]] = []
        removed_trailing_party_line: list[dict[str, Any]] = []
        history, removed_trailing_ghosts = clear_trailing_empty_ghost_history(history)
        if removed_trailing_ghosts and not str(last_error or "").strip():
            snapshot_state = "ok"
            snapshot_status = "Ready."
            _persist_ready_state_after_history_cleanup(
                meta,
                history,
                removed_trailing_ghosts,
            )
        if not removed_trailing_ghosts:
            history, removed_trailing_party_line = (
                clear_trailing_passive_party_line_history(history)
            )
            if removed_trailing_party_line and not str(last_error or "").strip():
                snapshot_state = "ok"
                snapshot_status = "Ready."
                _persist_ready_state_after_history_cleanup(
                    meta,
                    history,
                    removed_trailing_party_line,
                )
    latest_reauth_entry = _latest_history_requires_reauth(history)
    latest_history_requires_reauth = latest_reauth_entry is not None
    if (
        snapshot_state == "ok"
        and _contains_codex_auth_failure(last_error)
        and not latest_history_requires_reauth
    ):
        last_error = ""
        write_text(LAST_ERROR_PATH, "")
    services = [
        {"name": name, "state": state}
        for name, state in service_status(
            [
                HOUSEBOT_SERVICE,
                PFSENSE_TIMER,
                CODEX_SERVICE,
                WEB_SERVICE,
                TAILSCALE_SERVICE,
            ]
        )
    ]
    snapshot_at = now_ts()
    auth = _auth_state_from_console(pane, last_error)
    if not bool(meta.get("pending")) and _contains_codex_cli_upgrade_error(last_error):
        last_error = ""
        write_text(LAST_ERROR_PATH, "")
        snapshot_state = "ok"
        snapshot_status = "Ready."
    if (
        auth.get("required") is False
        and not latest_history_requires_reauth
        and (_auth_prompt_is_stale(pane) or session_past_auth_prompt)
    ):
        last_error = ""
        write_text(LAST_ERROR_PATH, "")
    if (
        auth.get("required") is True
        and str(auth.get("mode") or "").strip().lower()
        in {"signin_choice", "browser_signin", "device_code"}
        and _contains_codex_auth_failure(last_error)
    ):
        last_error = ""
        write_text(LAST_ERROR_PATH, "")
    if (
        auth.get("required") is False
        and _contains_codex_ready_prompt(pane)
        and not prompt_thread_alive()
        and not latest_history_requires_reauth
    ):
        last_error = ""
        write_text(LAST_ERROR_PATH, "")
        snapshot_state = "ok"
        snapshot_status = "Ready."
    if (
        auth.get("required") is False
        and session_past_auth_prompt
        and not bool(meta.get("pending"))
        and not latest_history_requires_reauth
        and not str(last_error or "").strip()
        and str(snapshot_state or "").strip().lower() != "ok"
    ):
        snapshot_state = "ok"
        snapshot_status = "Ready."
        update_status_meta(
            pending=False,
            state="ok",
            status_message="Ready.",
            running_prompt="",
            running_attachments=[],
        )
    auth_mode = str(auth.get("mode") or "").strip().lower()
    if auth.get("required") is True and auth_mode in {
        "signin_choice",
        "browser_signin",
        "device_code",
        "needs_reauth",
    }:
        snapshot_state = "error"
        snapshot_status = {
            "signin_choice": "Choose sign-in.",
            "browser_signin": "Continue sign-in.",
            "device_code": "Complete device-code sign-in.",
            "needs_reauth": "Needs reauth.",
        }.get(
            auth_mode, str(auth.get("summary") or snapshot_status or "Needs sign-in.")
        )
    if latest_history_requires_reauth and (
        not auth.get("required")
        or str(auth.get("mode") or "").strip().lower() == "needs_reauth"
    ):
        last_error = str(latest_reauth_entry.get("error") or last_error).strip()
        auth = {
            "required": True,
            "mode": "needs_reauth",
            "summary": "Recent web prompts are failing because this bot needs a fresh sign-in.",
            "verification_url": "",
            "device_code": "",
        }
        snapshot_state = "error"
        snapshot_status = "Needs reauth."
        write_text(LAST_ERROR_PATH, last_error)
    history = _sanitize_history_entries(
        history,
        pane=pane,
        auth=auth,
        snapshot_state=snapshot_state,
        last_error=last_error,
        latest_history_requires_reauth=latest_history_requires_reauth,
    )
    if (
        not bool(meta.get("pending"))
        and str(snapshot_state or "").strip().lower() == "error"
        and not str(last_error or "").strip()
        and not bool(auth.get("required"))
        and not latest_history_requires_reauth
    ):
        snapshot_state = "ok"
        snapshot_status = "Ready."
        update_status_meta(
            pending=False,
            state="ok",
            status_message="Ready.",
            running_prompt="",
            running_attachments=[],
        )
    pending = bool(meta.get("pending"))
    running_prompt = str(meta.get("running_prompt") or "")
    raw_resource_meter = load_resource_meter_file() or meta.get("resource_meter")
    resource_meter = normalize_resource_meter(
        raw_resource_meter,
        snapshot_at=snapshot_at,
        pending=pending,
        queue_depth=len(queued_prompts),
        running_prompt=running_prompt,
    )
    snapshot = {
        "pending": pending,
        "state": snapshot_state,
        "status_message": snapshot_status,
        "running_prompt": running_prompt,
        "running_attachments": normalize_attachments(meta.get("running_attachments")),
        "running_speed": normalize_response_speed(meta.get("running_speed")),
        "running_detail": normalize_response_detail(meta.get("running_detail")),
        "model_process_alive": active_codex_process_alive(),
        "web_worker_alive": prompt_runtime_alive(),
        "active_child_pid": _coerce_int(meta.get("active_child_pid")),
        "active_child_pgid": _coerce_int(meta.get("active_child_pgid")),
        "active_child_started_at": _coerce_int(meta.get("active_child_started_at")),
        "cancel_requested_at": _coerce_int(meta.get("cancel_requested_at")),
        "recovered_after_restart": bool(meta.get("recovered_after_restart")),
        "stale_queue": bool(meta.get("stale_queue")),
        "last_attachments": normalize_attachments(meta.get("last_attachments")),
        "last_speed": normalize_response_speed(meta.get("last_speed")),
        "last_detail": normalize_response_detail(meta.get("last_detail")),
        "last_started_at": int(meta.get("last_started_at") or 0),
        "last_finished_at": int(meta.get("last_finished_at") or 0),
        "updated_at": snapshot_at,
        "state_updated_at": int(meta.get("updated_at") or 0),
        "last_action": str(meta.get("last_action") or ""),
        "last_action_at": int(meta.get("last_action_at") or 0),
        "last_action_detail": str(meta.get("last_action_detail") or ""),
        "thread_id": thread_id,
        "last_prompt": read_text(LAST_PROMPT_PATH, "[no prompt yet]"),
        "last_response": read_text(LAST_RESPONSE_PATH, "[no response yet]"),
        "last_error": last_error,
        "history": history,
        "usage": usage,
        "draft_attachments": load_draft_attachments(),
        "queued_prompts": queued_prompts,
        "queue_depth": len(queued_prompts),
        "resource_meter": resource_meter,
        "permissions_mode": "danger-full-access",
        "chat_model": MODEL,
        "chat_reasoning_effort": response_reasoning_effort(DEFAULT_RESPONSE_SPEED),
        "default_speed": DEFAULT_RESPONSE_SPEED,
        "default_detail": DEFAULT_RESPONSE_DETAIL,
        "tmux_session": SESSION,
        "services": services,
        "pane": pane,
        "auth": auth,
        "logs": housebot_log_tail(),
    }
    snapshot["kpis"] = update_kpi_snapshot(snapshot)
    return snapshot


def snapshot_marker(snapshot: dict[str, Any]) -> tuple[Any, ...]:
    return (
        snapshot.get("pending"),
        snapshot.get("state"),
        snapshot.get("state_updated_at"),
        snapshot.get("last_action_at"),
        snapshot.get("thread_id"),
        snapshot.get("last_prompt"),
        snapshot.get("last_response"),
        snapshot.get("last_error"),
        tuple(item.get("token") for item in (snapshot.get("draft_attachments") or [])),
        len(snapshot.get("history") or []),
        snapshot.get("queue_depth"),
        tuple(
            item.get("token") for item in (snapshot.get("running_attachments") or [])
        ),
        snapshot.get("running_speed"),
        snapshot.get("running_detail"),
        snapshot.get("model_process_alive"),
        snapshot.get("web_worker_alive"),
        snapshot.get("cancel_requested_at"),
        snapshot.get("stale_queue"),
        tuple(item.get("token") for item in (snapshot.get("last_attachments") or [])),
        snapshot.get("last_speed"),
        snapshot.get("last_detail"),
        json.dumps(snapshot.get("resource_meter") or {}, sort_keys=True),
    )


def token_ok(params: dict[str, list[str]], cookie_token: str = "") -> bool:
    if not TOKEN:
        return True
    values = params.get("token", [])
    return any(value == TOKEN for value in values) or cookie_token == TOKEN


def query_token(params: dict[str, list[str]]) -> str:
    return ((params.get("token") or [""])[0] or "").strip()


def script_json(value: Any) -> str:
    return json.dumps(value).replace("</", "<\\/")


def _format_ui_ts(ts: Any) -> str:
    try:
        numeric = int(ts or 0)
    except (TypeError, ValueError):
        return "n/a"
    if numeric <= 0:
        return "n/a"
    dt = datetime.fromtimestamp(numeric)
    return f"{dt.strftime('%b')} {dt.day}, {dt.strftime('%I:%M:%S %p').lstrip('0')}"


def _response_detail_label(detail: Any) -> str:
    try:
        numeric = int(detail or 0)
    except (TypeError, ValueError):
        numeric = DEFAULT_RESPONSE_DETAIL
    return {
        1: "Simple",
        2: "Lean",
        3: "Balanced",
        4: "Detailed",
        5: "Deep",
    }.get(numeric, "Balanced")


def _response_profile_text(speed: Any, detail: Any) -> str:
    speed_label = {
        "fast": "Fast",
        "balanced": "Balanced",
        "careful": "Careful",
    }.get(normalize_response_speed(speed), "Balanced")
    return f"{speed_label} · {_response_detail_label(detail)}"


def _contains_token_reuse_error(text: str) -> bool:
    clean = str(text or "")
    return "refresh_token_reused" in clean or (
        "already been used to generate a new access token" in clean
    )


def _contains_openai_auth_error(text: str) -> bool:
    clean = str(text or "").lower()
    if not clean:
        return False
    return "missing bearer basic authentication in header" in clean or (
        "401 unauthorized" in clean
        and (
            "api.openai.com/v1/responses" in clean
            or "missing bearer" in clean
            or "basic authentication in header" in clean
        )
    )


def _contains_codex_auth_failure(text: str) -> bool:
    return _contains_token_reuse_error(text) or _contains_openai_auth_error(text)


def _contains_codex_cli_upgrade_error(text: str) -> bool:
    clean = str(text or "").lower()
    return (
        "requires a newer version of codex" in clean
        or "please upgrade to the latest app or cli" in clean
    )


def _contains_openai_transport_error(text: str) -> bool:
    clean = str(text or "").lower()
    if not clean or _contains_openai_auth_error(clean):
        return False
    return (
        "codex_api::endpoint::responses_websocket" in clean
        and "failed to connect to websocket" in clean
    ) or (
        "api.openai.com/v1/responses" in clean and "500 internal server error" in clean
    )


def _contains_cert_workflow_error(text: str) -> bool:
    clean = str(text or "").lower()
    if not clean:
        return False
    cert_terms = (
        "certificate_verify_failed",
        "certbot",
        "acme",
        "x509",
        "make_cert",
        "cert queue",
        "cert-worker",
        "cert_enqueue",
    )
    if any(term in clean for term in cert_terms):
        return True
    has_certish = any(term in clean for term in ("certificate", "ssl", "tls"))
    has_failure = any(
        term in clean
        for term in (
            "error",
            "failed",
            "invalid",
            "expired",
            "mismatch",
            "verify",
            "handshake",
        )
    )
    return has_certish and has_failure


def _contains_update_interstitial(text: str) -> bool:
    clean = str(text or "")
    return "Update available!" in clean and "Press enter to continue" in clean


def _contains_browser_signin_prompt(text: str) -> bool:
    clean = str(text or "")
    return (
        "Finish signing in via your browser" in clean and "Press Esc to cancel" in clean
    )


def _contains_signin_choice_prompt(text: str) -> bool:
    clean = str(text or "")
    return (
        "1. Sign in with ChatGPT" in clean
        and "2. Sign in with Device Code" in clean
        and "Press Enter to continue" in clean
    )


def _contains_browser_auth_port_in_use(text: str) -> bool:
    clean = str(text or "")
    return "Port 127.0.0.1:1455 is already in use" in clean


def _contains_signed_in_banner(text: str) -> bool:
    clean = str(text or "")
    return (
        "Signed in with your ChatGPT account" in clean
        and "Press Enter to continue" in clean
    )


def _contains_trust_directory_prompt(text: str) -> bool:
    clean = str(text or "")
    return (
        "Do you trust the contents of this directory?" in clean
        and "1. Yes, continue" in clean
        and "2. No, quit" in clean
        and "press enter to continue" in clean.lower()
    )


def _contains_codex_ready_prompt(text: str) -> bool:
    clean = str(text or "")
    return ("OpenAI Codex (v" in clean and "directory:" in clean) or (
        "› " in clean and "gpt-" in clean and "% left ·" in clean
    )


def _session_is_past_auth_prompt(text: str) -> bool:
    clean = str(text or "")
    return (
        _contains_signed_in_banner(clean)
        or _contains_trust_directory_prompt(clean)
        or _contains_update_interstitial(clean)
        or _contains_codex_ready_prompt(clean)
    )


def _latest_marker_index(text: str, markers: list[str]) -> int:
    clean = str(text or "")
    latest = -1
    for marker in markers:
        latest = max(latest, clean.rfind(marker))
    return latest


def _update_interstitial_is_stale(text: str) -> bool:
    clean = str(text or "")
    update_index = _latest_marker_index(
        clean,
        [
            "Update available!",
            "Run npm install -g @openai/codex to update.",
        ],
    )
    ready_index = _latest_marker_index(
        clean,
        [
            "OpenAI Codex (v",
            "Tip: Use /status to see the current model, approvals, and token usage.",
            "% left ·",
        ],
    )
    return update_index >= 0 and ready_index > update_index


def _contains_active_update_interstitial(text: str) -> bool:
    return _contains_update_interstitial(text) and not _update_interstitial_is_stale(
        text
    )


def _auth_prompt_is_stale(text: str) -> bool:
    clean = str(text or "")
    auth_prompt_index = _latest_marker_index(
        clean,
        [
            "Finish signing in via your browser",
            "1. Sign in with ChatGPT",
            "Complete device-code sign-in in your browser",
            "open the following link to authenticate:",
        ],
    )
    completed_index = _latest_marker_index(
        clean,
        [
            "Signed in with your ChatGPT account",
            "Do you trust the contents of this directory?",
            "OpenAI Codex (v",
        ],
    )
    return auth_prompt_index >= 0 and completed_index > auth_prompt_index


def _extract_browser_auth_url(text: str) -> str:
    clean = str(text or "")
    lines = clean.splitlines()
    for index, line in enumerate(lines):
        value = line.strip()
        if not value.startswith("https://auth.openai.com/oauth/authorize?"):
            continue
        parts = [value]
        for follow in lines[index + 1 :]:
            follow_value = follow.strip()
            if not follow_value:
                break
            if follow_value.startswith("On a remote") or follow_value.startswith(
                "Press Esc"
            ):
                break
            parts.append(follow_value)
        return "".join(parts)
    return ""


def _extract_device_auth_url(text: str) -> str:
    clean = str(text or "")
    if "https://auth.openai.com/codex/device" in clean:
        return "https://auth.openai.com/codex/device"
    return ""


def _extract_device_code(text: str) -> str:
    clean = str(text or "")
    if "Enter this one-time code" not in clean:
        return ""
    for match in AUTH_DEVICE_CODE_RE.finditer(clean):
        value = str(match.group(0) or "").strip()
        if value:
            return value
    return ""


def _contains_device_code_prompt(text: str) -> bool:
    clean = str(text or "")
    return bool(_extract_device_auth_url(clean) and _extract_device_code(clean))


def _auth_state_from_console(pane: str, last_error: str = "") -> dict[str, Any]:
    combined = f"{last_error}\n{pane}".strip()
    if _auth_prompt_is_stale(pane):
        return {
            "required": False,
            "mode": "",
            "summary": "",
            "verification_url": "",
            "device_code": "",
        }
    browser_auth_url = _extract_browser_auth_url(pane)
    verification_url = _extract_device_auth_url(pane)
    device_code = _extract_device_code(pane)
    if verification_url and device_code:
        return {
            "required": True,
            "mode": "device_code",
            "summary": "Complete device-code sign-in in your browser, then return here.",
            "verification_url": verification_url,
            "device_code": device_code,
        }
    if _contains_signin_choice_prompt(pane):
        return {
            "required": True,
            "mode": "signin_choice",
            "summary": "Codex is waiting at the sign-in method chooser.",
            "verification_url": "",
            "device_code": "",
        }
    if _contains_browser_signin_prompt(pane):
        return {
            "required": True,
            "mode": "browser_signin",
            "summary": "Finish browser sign-in in a real browser tab.",
            "verification_url": browser_auth_url,
            "device_code": "",
        }
    if _session_is_past_auth_prompt(pane):
        return {
            "required": False,
            "mode": "",
            "summary": "",
            "verification_url": "",
            "device_code": "",
        }
    if _contains_codex_auth_failure(combined):
        return {
            "required": True,
            "mode": "needs_reauth",
            "summary": "This bot needs a fresh sign-in. Start browser sign-in from Norman to repair it.",
            "verification_url": "",
            "device_code": "",
        }
    return {
        "required": False,
        "mode": "",
        "summary": "",
        "verification_url": "",
        "device_code": "",
    }


def _history_entry_requires_reauth(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if not _coerce_int(entry.get("started_at")) and not _coerce_int(
        entry.get("finished_at")
    ):
        return False
    error_text = str(entry.get("error") or "").strip()
    if not _contains_codex_auth_failure(error_text):
        return False
    response_text = str(entry.get("response") or "").strip().lower()
    if response_text and response_text not in {
        "[no response returned]",
        "[waiting for reply]",
    }:
        return False
    usage = normalize_usage_entry(entry.get("usage"))
    if usage.get("success"):
        return False
    if _coerce_int(usage.get("total_tokens")) > 0:
        return False
    return bool(str(entry.get("prompt") or "").strip())


def _latest_history_requires_reauth(
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in reversed(entries or []):
        if _history_entry_requires_reauth(item):
            return item
        if isinstance(item, dict) and (
            str(item.get("prompt") or "").strip()
            or str(item.get("response") or "").strip()
            or str(item.get("error") or "").strip()
        ):
            return None
    return None


def _history_error_is_stale(
    error_text: str,
    *,
    pane: str = "",
    auth: dict[str, Any] | None = None,
    snapshot_state: str = "",
    last_error: str = "",
    latest_history_requires_reauth: bool = False,
) -> bool:
    clean_error = str(error_text or "").strip()
    if not clean_error:
        return False
    is_recoverable_error = _contains_codex_auth_failure(
        clean_error
    ) or _contains_codex_cli_upgrade_error(clean_error)
    if not is_recoverable_error:
        return False
    if latest_history_requires_reauth:
        return False
    auth_state = auth or _auth_state_from_console(str(pane or ""))
    if bool(auth_state.get("required")):
        return False
    clean_state = str(snapshot_state or "").strip().lower()
    if not str(last_error or "").strip():
        return True
    clean_pane = str(pane or "")
    return (
        _session_is_past_auth_prompt(clean_pane)
        or _contains_active_update_interstitial(clean_pane)
        or _contains_codex_ready_prompt(clean_pane)
    )


def _sanitize_history_entries(
    entries: list[dict[str, Any]],
    *,
    pane: str = "",
    auth: dict[str, Any] | None = None,
    snapshot_state: str = "",
    last_error: str = "",
    latest_history_requires_reauth: bool = False,
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        error_text = str(item.get("error") or "")
        if _history_error_is_stale(
            error_text,
            pane=pane,
            auth=auth,
            snapshot_state=snapshot_state,
            last_error=last_error,
            latest_history_requires_reauth=latest_history_requires_reauth,
        ):
            sanitized.append({**item, "error": ""})
            continue
        sanitized.append(item)
    return sanitized


def _wait_for_pane(
    predicate: Callable[[str], bool], *, timeout: float = 6.0, interval: float = 0.35
) -> str:
    deadline = time.time() + max(timeout, interval)
    latest = capture_pane()
    while time.time() < deadline:
        latest = capture_pane()
        if predicate(latest):
            return latest
        time.sleep(interval)
    return latest


def start_device_auth() -> dict[str, Any]:
    if not ensure_session():
        raise RuntimeError("Codex session could not be started.")

    pane = capture_pane()
    last_error = read_text(LAST_ERROR_PATH)
    combined = f"{last_error}\n{pane}".strip()
    auth_state = _auth_state_from_console(pane, last_error)

    if not auth_state.get("required") and _contains_codex_ready_prompt(pane):
        return current_snapshot()

    if _contains_codex_auth_failure(combined):
        restart_session()
        pane = _wait_for_pane(
            lambda text: _contains_browser_signin_prompt(text)
            or _contains_signin_choice_prompt(text)
            or _contains_device_code_prompt(text),
            timeout=10.0,
        )

    if _contains_device_code_prompt(pane):
        record_action("auth-device", "Device code sign-in is already ready.")
        return current_snapshot()

    if _contains_browser_signin_prompt(pane):
        run(tmux_cmd("send-keys", "-t", f"{SESSION}:0.0", "Escape"), check=True)
        pane = _wait_for_pane(_contains_signin_choice_prompt, timeout=4.0)

    if not _contains_signin_choice_prompt(pane):
        raise RuntimeError("Codex is not at a web-manageable sign-in prompt yet.")

    run(
        tmux_cmd("send-keys", "-t", f"{SESSION}:0.0", "2", "Enter"),
        check=True,
    )
    pane = _wait_for_pane(_contains_device_code_prompt, timeout=6.0)
    if not _contains_device_code_prompt(pane):
        raise RuntimeError("Device-code sign-in did not appear. Refresh and retry.")

    record_action(
        "auth-device", "Prepared device-code sign-in for the interactive session."
    )
    return current_snapshot()


def start_browser_auth() -> dict[str, Any]:
    if not ensure_session():
        raise RuntimeError("Codex session could not be started.")

    snapshot = current_snapshot()
    snapshot_auth = snapshot.get("auth") if isinstance(snapshot, dict) else {}
    if (
        isinstance(snapshot_auth, dict)
        and snapshot_auth.get("required") is False
        and str(snapshot.get("state") or "").strip().lower() == "ok"
    ):
        return snapshot

    pane = capture_pane()
    last_error = read_text(LAST_ERROR_PATH)
    combined = f"{last_error}\n{pane}".strip()
    auth_state = _auth_state_from_console(pane, last_error)

    if not auth_state.get("required") and _contains_codex_ready_prompt(pane):
        return current_snapshot()

    if _contains_codex_auth_failure(combined):
        restart_session()
        pane = _wait_for_pane(
            lambda text: _contains_browser_signin_prompt(text)
            or _contains_signin_choice_prompt(text)
            or _contains_device_code_prompt(text),
            timeout=10.0,
        )

    if _contains_browser_signin_prompt(pane):
        record_action("auth-browser", "Browser sign-in is already ready.")
        return current_snapshot()

    if _contains_device_code_prompt(pane):
        run(tmux_cmd("send-keys", "-t", f"{SESSION}:0.0", "Escape"), check=True)
        pane = _wait_for_pane(
            lambda text: _contains_browser_signin_prompt(text)
            or _contains_signin_choice_prompt(text),
            timeout=4.0,
        )
        if _contains_browser_signin_prompt(pane):
            record_action(
                "auth-browser",
                "Prepared browser sign-in for the interactive session.",
            )
            return current_snapshot()

    if not _contains_signin_choice_prompt(pane):
        raise RuntimeError("Codex is not at a web-manageable sign-in prompt yet.")

    run(
        tmux_cmd("send-keys", "-t", f"{SESSION}:0.0", "1", "Enter"),
        check=True,
    )
    pane = _wait_for_pane(
        lambda text: _contains_browser_signin_prompt(text)
        or _contains_browser_auth_port_in_use(text),
        timeout=6.0,
    )
    if _contains_browser_auth_port_in_use(pane):
        raise RuntimeError(
            "Another local Codex sign-in is already using the browser callback port. "
            "Finish or cancel that sign-in first, then retry."
        )
    if not _contains_browser_signin_prompt(pane):
        raise RuntimeError("Browser sign-in did not appear. Refresh and retry.")

    record_action(
        "auth-browser", "Prepared browser sign-in for the interactive session."
    )
    return current_snapshot()


def complete_browser_auth_callback(
    *,
    callback_url: str = "",
    query_params: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    params: dict[str, list[str]]
    if callback_url:
        parsed = urlparse(callback_url.strip())
        if parsed.path != "/auth/callback":
            raise RuntimeError("Browser callback path must end with /auth/callback.")
        params = parse_qs(parsed.query)
    else:
        params = dict(query_params or {})

    code = (params.get("code") or [""])[0].strip()
    state = (params.get("state") or [""])[0].strip()
    if not code or not state:
        raise RuntimeError("Browser callback is missing code or state.")

    callback_query = urlencode(params, doseq=True)
    target_url = f"http://127.0.0.1:1455/auth/callback?{callback_query}"
    request = urllib_request.Request(target_url, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=20) as response:
            response.read()
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        reason = body or f"callback returned HTTP {exc.code}"
        raise RuntimeError(f"Private auth callback failed: {reason}") from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise RuntimeError(
            f"Private auth callback could not reach the live sign-in listener: {reason}"
        ) from exc

    write_text(LAST_ERROR_PATH, "")
    record_action("auth-browser-callback", "Completed browser callback handoff.")
    self_check_ok, self_check_detail = _run_post_auth_self_check(timeout=10.0)
    update_status_meta(
        state="ok" if self_check_ok else "idle",
        status_message=self_check_detail,
    )
    if self_check_ok:
        update_status_meta(
            last_action="auth-browser-self-check",
            last_action_at=now_ts(),
            last_action_detail=self_check_detail,
        )
    deadline = time.time() + 8.0
    latest = current_snapshot()
    while time.time() < deadline:
        latest = current_snapshot()
        auth_state = latest.get("auth") or {}
        mode = str(auth_state.get("mode") or "")
        if not auth_state.get("required"):
            return latest
        if mode not in {"browser_signin", "signin_choice"}:
            return latest
        time.sleep(0.35)
    return latest


def _snapshot_tone_label(snapshot: dict[str, Any]) -> tuple[str, str]:
    pane = str(snapshot.get("pane") or "")
    last_error = str(snapshot.get("last_error") or "")
    combined = f"{last_error}\n{pane}".strip()
    if _contains_codex_auth_failure(combined):
        return "error", "Needs reauth"
    if _contains_cert_workflow_error(combined):
        return "error", "Cert issue"
    if _contains_openai_transport_error(combined):
        return "error", "API issue"
    if _contains_active_update_interstitial(pane):
        return "running", "Blocked"
    if snapshot.get("pending"):
        return "running", "Running"
    if last_error:
        return "error", "Attention"
    if str(snapshot.get("state") or "") == "ok":
        return "ok", "Ready"
    if str(snapshot.get("state") or "") == "error":
        return "error", "Error"
    return "idle", "Idle"


def _initial_status_text(snapshot: dict[str, Any]) -> str:
    queue_depth = int(snapshot.get("queue_depth") or 0)
    draft_attachment_count = len(snapshot.get("draft_attachments") or [])
    status_text = str(snapshot.get("status_message") or "Ready.")
    if snapshot.get("pending") and snapshot.get("running_prompt"):
        status_text = (
            f"Working: {summarize_text(str(snapshot.get('running_prompt') or ''), 88)}"
            f" · {_response_profile_text(snapshot.get('running_speed'), snapshot.get('running_detail'))}"
        )
    elif draft_attachment_count > 0:
        status_text = (
            "Ready. 1 attachment staged."
            if draft_attachment_count == 1
            else f"Ready. {draft_attachment_count} attachments staged."
        )
    elif snapshot.get("last_finished_at"):
        status_text = (
            f"Ready. Last reply {_format_ui_ts(snapshot.get('last_finished_at'))}"
            f" · {_response_profile_text(snapshot.get('last_speed'), snapshot.get('last_detail'))}"
        )
    if snapshot.get("pending") and queue_depth > 0:
        status_text += " 1 queued." if queue_depth == 1 else f" {queue_depth} queued."
    return status_text


def _initial_chat_session_text(
    snapshot: dict[str, Any], active_profile_label: str
) -> str:
    thread_id = str(snapshot.get("thread_id") or "")
    if thread_id:
        return f"{MODEL} · {thread_id[:8]}…"
    return f"{MODEL} · {active_profile_label}"


def _initial_chat_activity_text(
    snapshot: dict[str, Any], active_profile_label: str
) -> tuple[str, bool]:
    queue_depth = int(snapshot.get("queue_depth") or 0)
    draft_attachment_count = len(snapshot.get("draft_attachments") or [])
    pane = str(snapshot.get("pane") or "")
    last_error = str(snapshot.get("last_error") or "")
    combined = f"{last_error}\n{pane}".strip()
    if _contains_codex_auth_failure(combined):
        return "Needs reauth", False
    if _contains_cert_workflow_error(combined):
        return "Cert issue", False
    if _contains_openai_transport_error(combined):
        return "API issue", False
    if _contains_active_update_interstitial(pane):
        return "Needs unblock", False
    if snapshot.get("pending"):
        profile = _response_profile_text(
            snapshot.get("running_speed"), snapshot.get("running_detail")
        )
        return (
            f"Working · {profile} · +{queue_depth}"
            if queue_depth > 0
            else f"Working · {profile}",
            False,
        )
    if draft_attachment_count > 0:
        return (
            "Ready · 1 staged"
            if draft_attachment_count == 1
            else f"Ready · {draft_attachment_count} staged",
            False,
        )
    if snapshot.get("last_finished_at"):
        return (
            f"Idle · {_response_profile_text(snapshot.get('last_speed'), snapshot.get('last_detail'))}",
            True,
        )
    return f"Ready · {active_profile_label}", True


def _initial_history_summary(snapshot: dict[str, Any]) -> str:
    total_turns = len(snapshot.get("history") or [])
    queue_depth = int(snapshot.get("queue_depth") or 0)
    visible_turns = 1 if total_turns else 0
    if snapshot.get("pending") and snapshot.get("running_prompt"):
        visible_turns += 1
    if not total_turns and not queue_depth:
        return "No conversation yet."
    if total_turns > visible_turns:
        suffix = f" · {queue_depth} queued" if queue_depth > 0 else ""
        return f"{visible_turns} recent of {total_turns} turns{suffix}"
    if queue_depth > 0:
        return f"{total_turns} turn{'s' if total_turns != 1 else ''} · {queue_depth} queued"
    return f"{total_turns} turn{'s' if total_turns != 1 else ''}"


def _compact_metric(value: Any) -> str:
    amount = max(0, _coerce_int(value))
    if amount >= 1_000_000:
        compact = f"{amount / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{compact}M"
    if amount >= 10_000:
        return f"{round(amount / 1000):.0f}k"
    if amount >= 1000:
        compact = f"{amount / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{compact}k"
    return str(amount)


def _initial_context_meter(snapshot: dict[str, Any]) -> dict[str, Any]:
    usage = snapshot.get("usage") or {}
    current_thread = usage.get("current_thread") or {}
    totals = usage.get("totals") or {}
    recent = usage.get("last_24h") or {}
    thread_scoped = (
        _coerce_int(current_thread.get("turns")) > 0
        or _coerce_int(current_thread.get("total_tokens")) > 0
    )
    primary = current_thread if thread_scoped else totals
    history_turns = len(snapshot.get("history") or [])
    pending_turn = (
        1 if snapshot.get("pending") and snapshot.get("running_prompt") else 0
    )
    tracked_turns = _coerce_int(primary.get("turns"))
    total_turns = max(tracked_turns, history_turns + pending_turn)
    total_tokens = _coerce_int(primary.get("total_tokens"))
    recent_tokens = _coerce_int(recent.get("total_tokens"))
    queue_depth = _coerce_int(snapshot.get("queue_depth"))
    hidden = total_turns <= 0 and total_tokens <= 0 and queue_depth <= 0

    token_load = total_tokens / 90_000 if total_tokens > 0 else 0.0
    turn_load = total_turns / 26 if total_turns > 0 else 0.0
    queue_load = min(1.0, 0.18 + (queue_depth * 0.18)) if queue_depth > 0 else 0.0
    fill = max(token_load, turn_load, queue_load)

    tone = "ok"
    label = "Fresh"
    hint = "Plenty of room before a compact/save is likely useful."
    if fill >= 0.92:
        tone = "danger"
        label = "Save soon"
        hint = "Good point to compact/save before the thread gets unwieldy."
    elif fill >= 0.55:
        tone = "warn"
        label = "Watch"
        hint = (
            "Session is getting heavier; compact soon if the thread starts to sprawl."
        )

    value_parts: list[str] = []
    if total_turns > 0:
        value_parts.append(f"{total_turns}t")
    if total_tokens > 0:
        value_parts.append(f"{_compact_metric(total_tokens)} tok")
    if queue_depth > 0:
        value_parts.append(f"+{queue_depth}")
    value = " · ".join(value_parts) if value_parts else "Fresh"

    title_parts = [f"{label} context load"]
    title_parts.append(
        f"{total_turns} {'current-thread' if thread_scoped else 'tracked'} turn{'s' if total_turns != 1 else ''}"
        if total_turns > 0
        else "No tracked turns yet"
    )
    if total_tokens > 0:
        title_parts.append(
            f"{total_tokens:,} {'current-thread' if thread_scoped else 'tracked'} tokens"
        )
    if recent_tokens > 0 and recent_tokens != total_tokens:
        title_parts.append(f"{recent_tokens:,} tokens in the last 24h")
    if queue_depth > 0:
        title_parts.append(f"{queue_depth} queued")
    title_parts.append(
        "Heuristic only; use it as a save/compact hint, not an exact context ceiling."
    )
    title_parts.append(hint)

    return {
        "hidden": hidden,
        "tone": tone,
        "label": label,
        "value": value,
        "fill_pct": 0 if hidden else max(6, min(100, round(fill * 100))),
        "title": " · ".join(title_parts),
    }


def summarize_services(services: list[dict[str, Any]]) -> str:
    items = services or []
    if not items:
        return "Runtime state unavailable"
    problems = [
        item for item in items if str(item.get("state") or "").lower() != "active"
    ]
    if not problems:
        return "All services healthy"
    if len(problems) == 1:
        item = problems[0]
        return f"{item.get('name', 'service')} {item.get('state', 'unknown')}"
    return f"{len(problems)} runtime issues"


SENSITIVE_LABEL_RE = (
    r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|"
    r"signing[_ -]?secret|webhook[_ -]?secret|app[_ -]?password|"
    r"mcp[_ -]?api[_ -]?key|password|passwd|passphrase|passcode|secret|token|pwd)"
)
SENSITIVE_QUERY_LABEL_RE = (
    r"(?:api(?:[_-]?key)?|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"signing[_-]?secret|webhook[_-]?secret|app[_-]?password|password|passwd|"
    r"passcode|secret|token|pwd)"
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    rf'(?<![?&\w])(?P<prefix>(?:"|\')?{SENSITIVE_LABEL_RE}(?:"|\')?\s*[:=]\s*)'
    r'(?P<value>"[^"\n]*"|\'[^\'\n]*\'|[^\s,;]+)',
    re.IGNORECASE,
)
SENSITIVE_QUERY_RE = re.compile(
    rf"(?P<prefix>(?:[?&]){SENSITIVE_QUERY_LABEL_RE}=)(?P<value>[^&#\s]+)",
    re.IGNORECASE,
)
SENSITIVE_BEARER_RE = re.compile(
    r"(?P<prefix>\bBearer\s+)(?P<value>[A-Za-z0-9._~+/=-]+)",
    re.IGNORECASE,
)


def _secret_token_suffix(index: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    chars: list[str] = []
    current = index
    while True:
        current, remainder = divmod(current, 26)
        chars.append(alphabet[remainder])
        if current == 0:
            break
        current -= 1
    return "".join(reversed(chars))


def _secret_spoiler_html(value: str) -> str:
    return (
        '<button type="button" class="secret-spoiler" aria-pressed="false" '
        'aria-label="Reveal hidden value" title="Reveal hidden value">'
        '<span class="secret-spoiler-mask" aria-hidden="true">'
        "&bull;&bull;&bull;&bull;&bull;&bull;"
        "</span>"
        f'<span class="secret-spoiler-value">{html.escape(str(value or ""))}</span>'
        "</button>"
    )


def _stash_sensitive_segments(
    text: str, *, mask_query_params: bool = True
) -> tuple[str, dict[str, str]]:
    current = str(text or "")
    stash: dict[str, str] = {}
    counter = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal counter
        token = f"__SECRET_SEGMENT_{_secret_token_suffix(counter)}__"
        counter += 1
        stash[token] = _secret_spoiler_html(match.group("value"))
        return f"{match.group('prefix')}{token}"

    patterns: list[re.Pattern[str]] = [SENSITIVE_ASSIGNMENT_RE]
    if mask_query_params:
        patterns.append(SENSITIVE_QUERY_RE)
    patterns.append(SENSITIVE_BEARER_RE)
    for pattern in patterns:
        current = pattern.sub(replace, current)
    return current, stash


def _restore_secret_stash(rendered: str, stash: dict[str, str]) -> str:
    output = rendered
    for token, snippet in stash.items():
        output = output.replace(token, snippet)
    return output


def _mask_sensitive_multiline_html(text: str) -> str:
    masked, stash = _stash_sensitive_segments(text)
    escaped = html.escape(masked).replace("\n", "<br>")
    return _restore_secret_stash(escaped, stash)


def _mask_sensitive_pre_html(text: str) -> str:
    masked, stash = _stash_sensitive_segments(text)
    escaped = html.escape(masked)
    return _restore_secret_stash(escaped, stash)


INITIAL_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\s*\(\s*(&lt;[^>\n]+&gt;|[^\s)]+)\s*\)"
)
INITIAL_FILE_TARGET_RE = re.compile(r"(^|[\s(])((?:/|~/)[^\s<)\"']+)")
INITIAL_URL_RE = re.compile(r"(^|[\s(])(https?://[^\s<]+)")
INITIAL_RAW_HTML_ANCHOR_RE = re.compile(
    r"<a\b(?P<attrs>[^>]*)>(?P<label>.*?)</a>", re.IGNORECASE | re.DOTALL
)
INITIAL_RAW_HTML_HREF_RE = re.compile(
    r'\bhref\s*=\s*(?:"(?P<double>[^"]*)"|\'(?P<single>[^\']*)\'|(?P<bare>[^\s>]+))',
    re.IGNORECASE,
)
INITIAL_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def _mask_sensitive_url_text(url: str) -> str:
    return SENSITIVE_QUERY_RE.sub(
        lambda match: f"{match.group('prefix')}••••••", str(url or "")
    )


def _strip_inline_html_text(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))


def _display_text_for_initial_link(target: str, label: str) -> str:
    plain_label = _strip_inline_html_text(label).strip()
    if not plain_label:
        return (
            _mask_sensitive_url_text(target)
            if target.lower().startswith(("http://", "https://"))
            else target
        )
    if target.lower().startswith(("http://", "https://")):
        normalized_label = _normalize_initial_link_target(plain_label)
        if normalized_label.lower().startswith(("http://", "https://")):
            if _normalize_initial_link_target(
                normalized_label
            ) == _normalize_initial_link_target(target):
                return _mask_sensitive_url_text(target)
    return plain_label


def _normalize_initial_link_target(value: str) -> str:
    clean = html.unescape(str(value or "").strip())
    if clean.startswith("<") and clean.endswith(">"):
        clean = clean[1:-1].strip()
    while re.search(r"[.,!?;:]$", clean):
        clean = clean[:-1]
    return clean


def _normalize_initial_file_target(value: str) -> str:
    clean = html.unescape(str(value or "").strip())
    while re.search(r"[.,!?;:]$", clean):
        clean = clean[:-1]
    return clean


def _render_initial_inline_code_markup(
    code: str, *, token: str, profile: str, route: str, prefix: str = ""
) -> str:
    raw = str(code or "")
    trimmed = raw.strip()
    if not trimmed:
        return "<code></code>"
    if re.match(r"^https?://", trimmed, flags=re.IGNORECASE):
        clean = _normalize_initial_link_target(trimmed)
        return (
            f'<a class="inline-code-link" href="{html.escape(clean)}" target="_blank" rel="noreferrer">'
            f"<code>{html.escape(_mask_sensitive_url_text(trimmed))}</code></a>"
        )
    if trimmed.startswith(("/", "~/", "file://")):
        clean = _normalize_initial_file_target(trimmed)
        href = build_file_href(
            token=token,
            path=clean,
            profile=profile,
            route=route,
            prefix=prefix,
        )
        return (
            f'<a class="inline-code-link" href="{html.escape(href)}" target="_blank" rel="noreferrer">'
            f"<code>{html.escape(clean)}</code></a>"
        )
    return f"<code>{html.escape(raw)}</code>"


INITIAL_HTML_TAG_RE = re.compile(r"(<[^>]+>)")
INITIAL_DYNAMIC_HOST_ENTITY_RE = re.compile(
    r"(^|[\s([{\"'“‘])"
    r"((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:home\.arpa|home\.lollie\.org|kris\.openbrand\.com|tail[0-9]+\.ts\.net)"
    r"|(?:\d{1,3}\.){3}\d{1,3})"
    r"(?=$|[\s).,:;!?\]}\"'”’])",
    re.IGNORECASE,
)


def _initial_inline_entity_pattern(
    alias: str, strict_case: bool = False
) -> re.Pattern[str]:
    escaped = re.escape(str(alias or "").strip()).replace(r"\ ", r"\s+")
    return re.compile(
        r"(^|[\s([{\"'“‘])(" + escaped + r")(?=$|[\s).,:;!?\]}\"'”’])",
        0 if strict_case else re.IGNORECASE,
    )


def _initial_inline_entity_entries() -> (
    list[tuple[str, dict[str, Any], re.Pattern[str]]]
):
    entries: list[tuple[str, dict[str, Any], re.Pattern[str]]] = []
    for entity in build_inline_entity_defs():
        aliases = tuple(
            str(alias).strip()
            for alias in (entity.get("aliases") or (entity.get("label"),))
            if str(alias).strip()
        )
        for alias in aliases:
            entries.append(
                (
                    alias,
                    entity,
                    _initial_inline_entity_pattern(
                        alias, bool(entity.get("strict_case"))
                    ),
                )
            )
    entries.sort(key=lambda item: len(item[0]), reverse=True)
    return entries


def _highlight_initial_inline_entities_in_text(text: str) -> str:
    entity_stash: dict[str, str] = {}
    entity_counter = 0

    def stash_markup(markup: str) -> str:
        nonlocal entity_counter
        token_name = f"__INITIAL_ENTITY_{_secret_token_suffix(entity_counter)}__"
        entity_counter += 1
        entity_stash[token_name] = markup
        return token_name

    def replace_host(match: re.Match[str]) -> str:
        prefix, visible = match.groups()
        entity = _inline_entity_for_label(visible) or {
            "key": _normalize_inline_entity_key(visible),
            "label": visible,
            "mark": entity_mark_for_label(visible, "•"),
            "kind": "host",
            "tone": "host",
            "group": "shared",
        }
        return f"{prefix}{stash_markup(_render_entity_cartouche(entity, visible))}"

    rendered = INITIAL_DYNAMIC_HOST_ENTITY_RE.sub(replace_host, str(text or ""))
    for _alias, entity, pattern in _initial_inline_entity_entries():
        rendered = pattern.sub(
            lambda match: (
                f"{match.group(1)}"
                f"{stash_markup(_render_entity_cartouche(entity, match.group(2), alias_for=_inline_entity_alias_for_visible(entity, match.group(2))))}"
            ),
            rendered,
        )
    return _restore_secret_stash(rendered, entity_stash)


def _highlight_initial_inline_entities(rendered: str) -> str:
    parts = INITIAL_HTML_TAG_RE.split(str(rendered or ""))
    return "".join(
        part
        if not part or part.startswith("<")
        else _highlight_initial_inline_entities_in_text(part)
        for part in parts
    )


def _render_initial_inline_markup(
    text: str, *, token: str, profile: str, route: str, prefix: str = ""
) -> str:
    raw_anchor_stash: dict[str, str] = {}
    raw_anchor_counter = 0
    inline_code_stash: dict[str, str] = {}
    inline_code_counter = 0

    def replace_raw_anchor(match: re.Match[str]) -> str:
        nonlocal raw_anchor_counter
        attrs = str(match.group("attrs") or "")
        label = str(match.group("label") or "")
        href_match = INITIAL_RAW_HTML_HREF_RE.search(attrs)
        if not href_match:
            return _strip_inline_html_text(label)
        target = next(
            (
                item
                for item in (
                    href_match.group("double"),
                    href_match.group("single"),
                    href_match.group("bare"),
                )
                if item
            ),
            "",
        )
        clean = _normalize_initial_link_target(target)
        label_text = _display_text_for_initial_link(clean, label)
        if re.match(r"^https?://", clean, flags=re.IGNORECASE):
            rendered_anchor = (
                f'<a href="{html.escape(clean)}" target="_blank" rel="noreferrer">'
                f"{html.escape(label_text)}</a>"
            )
        elif clean and (
            clean.startswith("/")
            or clean.startswith("~/")
            or clean.startswith("file://")
        ):
            href = build_file_href(
                token=token,
                path=clean,
                profile=profile,
                route=route,
                prefix=prefix,
            )
            rendered_anchor = (
                f'<a class="file-link" href="{html.escape(href)}" target="_blank" '
                f'rel="noreferrer">{html.escape(label_text)}</a>'
            )
        else:
            return label_text or clean
        token_name = (
            f"__INITIAL_RAW_ANCHOR_{_secret_token_suffix(raw_anchor_counter)}__"
        )
        raw_anchor_counter += 1
        raw_anchor_stash[token_name] = rendered_anchor
        return token_name

    source = INITIAL_RAW_HTML_ANCHOR_RE.sub(
        replace_raw_anchor, str(text or "").replace("\r\n", "\n")
    )
    masked, stash = _stash_sensitive_segments(source, mask_query_params=False)

    def replace_inline_code(match: re.Match[str]) -> str:
        nonlocal inline_code_counter
        token_name = (
            f"__INITIAL_INLINE_CODE_{_secret_token_suffix(inline_code_counter)}__"
        )
        inline_code_counter += 1
        inline_code_stash[token_name] = _render_initial_inline_code_markup(
            match.group(1), token=token, profile=profile, route=route, prefix=prefix
        )
        return token_name

    masked = INITIAL_INLINE_CODE_RE.sub(replace_inline_code, masked)
    rendered = html.escape(masked)

    def replace_markdown_link(match: re.Match[str]) -> str:
        label = match.group(1)
        target = _normalize_initial_link_target(match.group(2))
        display_text = _display_text_for_initial_link(target, label)
        if re.match(r"^https?://", target, flags=re.IGNORECASE):
            return (
                f'<a href="{html.escape(target)}" target="_blank" rel="noreferrer">'
                f"{html.escape(display_text)}</a>"
            )
        if target and (
            target.startswith("/")
            or target.startswith("~/")
            or target.startswith("file://")
        ):
            href = build_file_href(
                token=token,
                path=target,
                profile=profile,
                route=route,
                prefix=prefix,
            )
            return (
                f'<a class="file-link" href="{html.escape(href)}" target="_blank" '
                f'rel="noreferrer">{html.escape(display_text)}</a>'
            )
        return match.group(0)

    def replace_file_target(match: re.Match[str]) -> str:
        text_prefix, target = match.groups()
        clean = _normalize_initial_link_target(target)
        if not clean or not (clean.startswith("/") or clean.startswith("~/")):
            return match.group(0)
        href = build_file_href(
            token=token,
            path=clean,
            profile=profile,
            route=route,
            prefix=prefix,
        )
        return (
            f'{text_prefix}<a class="file-link" href="{html.escape(href)}" target="_blank" '
            f'rel="noreferrer">{html.escape(clean)}</a>'
        )

    def replace_url(match: re.Match[str]) -> str:
        prefix, target = match.groups()
        clean = _normalize_initial_link_target(target)
        if not clean.lower().startswith(("http://", "https://")):
            return match.group(0)
        return (
            f'{prefix}<a href="{html.escape(clean)}" target="_blank" rel="noreferrer">'
            f"{html.escape(_mask_sensitive_url_text(clean))}</a>"
        )

    rendered = INITIAL_MARKDOWN_LINK_RE.sub(replace_markdown_link, rendered)
    rendered = INITIAL_FILE_TARGET_RE.sub(replace_file_target, rendered)
    rendered = INITIAL_URL_RE.sub(replace_url, rendered)
    rendered = re.sub(
        r"\*\*([^*\n][\s\S]*?[^*\n])\*\*", r"<strong>\1</strong>", rendered
    )
    rendered = re.sub(
        r"(^|[^\w*])\*([^*\n][\s\S]*?[^*\n])\*(?!\*)", r"\1<em>\2</em>", rendered
    )
    rendered = _highlight_initial_inline_entities(rendered)
    rendered = rendered.replace("\n", "<br>")
    rendered = _restore_secret_stash(rendered, inline_code_stash)
    rendered = _restore_secret_stash(rendered, stash)
    return _restore_secret_stash(rendered, raw_anchor_stash)


def _render_initial_message(
    role: str,
    label: str,
    body: str,
    meta_text: str = "",
    *,
    token: str = "",
    profile: str = "",
    route: str = "",
    prefix: str = "",
) -> str:
    escaped_body = _render_initial_inline_markup(
        str(body or ""), token=token, profile=profile, route=route, prefix=prefix
    )
    meta_html = (
        f'<span class="message-meta">{html.escape(meta_text)}</span>'
        if meta_text
        else ""
    )
    icon = html.escape(entity_mark_for_label(label, "•"))
    label_cartouche = _render_name_cartouche(label, compact=True)
    return (
        f'<article class="message {html.escape(role)}">'
        '<div class="message-head"><div class="meta-block">'
        f'<span class="message-role" data-icon="{icon}" aria-label="{html.escape(label)}">{label_cartouche}</span>'
        f"{meta_html}</div></div>"
        f'<div class="message-body">{escaped_body}</div>'
        "</article>"
    )


def _initial_conversation_html(
    snapshot: dict[str, Any],
    *,
    token: str = "",
    profile: str = "",
    route: str = "",
    prefix: str = "",
) -> str:
    history = snapshot.get("history") or []
    pane = str(snapshot.get("pane") or "")
    auth = snapshot.get("auth") if isinstance(snapshot.get("auth"), dict) else {}
    snapshot_state = str(snapshot.get("state") or "")
    last_error = str(snapshot.get("last_error") or "")
    items: list[str] = []
    if history:
        latest = history[-1]
        prompt = str(latest.get("prompt") or "").strip()
        response = str(latest.get("response") or "").strip()
        error_text = str(latest.get("error") or "").strip()
        if _history_error_is_stale(
            error_text,
            pane=pane,
            auth=auth,
            snapshot_state=snapshot_state,
            last_error=last_error,
        ):
            error_text = ""
        prompt_meta = (
            f"{_format_ui_ts(latest.get('started_at'))} · "
            f"{_response_profile_text(latest.get('speed'), latest.get('detail'))}"
        )
        reply_meta = (
            f"{_format_ui_ts(latest.get('finished_at'))} · "
            f"{_response_profile_text(latest.get('speed'), latest.get('detail'))}"
        )
        if prompt:
            items.append(
                _render_initial_message(
                    "user",
                    "You",
                    prompt,
                    prompt_meta,
                    token=token,
                    profile=profile,
                    route=route,
                    prefix=prefix,
                )
            )
        if response and not (
            response.lower() in {"[no response returned]", "[waiting for reply]"}
            and error_text
        ):
            items.append(
                _render_initial_message(
                    "assistant",
                    AGENT_NAME,
                    response,
                    reply_meta,
                    token=token,
                    profile=profile,
                    route=route,
                    prefix=prefix,
                )
            )
        if error_text:
            items.append(
                _render_initial_message(
                    "error",
                    "Error",
                    error_text,
                    reply_meta,
                    token=token,
                    profile=profile,
                    route=route,
                    prefix=prefix,
                )
            )
    if snapshot.get("pending") and snapshot.get("running_prompt"):
        running_meta = (
            f"{_format_ui_ts(snapshot.get('last_started_at'))} · "
            f"{_response_profile_text(snapshot.get('running_speed'), snapshot.get('running_detail'))}"
        )
        items.append(
            _render_initial_message(
                "user",
                "You",
                str(snapshot.get("running_prompt") or ""),
                running_meta,
                token=token,
                profile=profile,
                route=route,
                prefix=prefix,
            )
        )
        items.append(
            _render_initial_message(
                "assistant pending",
                AGENT_NAME,
                str(snapshot.get("status_message") or "Working…"),
                f"live · {_response_profile_text(snapshot.get('running_speed'), snapshot.get('running_detail'))}",
                token=token,
                profile=profile,
                route=route,
                prefix=prefix,
            )
        )
    if not items:
        return '<div class="message empty">Ready for a new prompt.</div>'
    return "".join(items)


class Handler(BaseHTTPRequestHandler):
    def render_browser_auth_callback_result(
        self,
        *,
        ok: bool,
        title: str,
        detail: str,
        followup_href: str = "/",
        followup_label: str = "Return to console",
        status: HTTPStatus = HTTPStatus.OK,
        show_callback_helper: bool = False,
    ) -> None:
        tone = "ok" if ok else "error"
        accent = "#a7c0d1" if ok else "#d0a7bb"
        helper_block = ""
        if show_callback_helper:
            helper_block = """
    <div class="helper">
      <div class="helper-title">Paste the full callback URL</div>
      <p>When ChatGPT redirects to <code>http://localhost:1455/auth/callback?code=...&amp;state=...</code> and your browser says it refused to connect, copy that entire URL and paste it here.</p>
      <form id="callback-relay-form" class="helper-form">
        <input
          id="callback-relay-input"
          type="text"
          inputmode="url"
          autocomplete="off"
          spellcheck="false"
          placeholder="http://localhost:1455/auth/callback?code=...&state=..."
        >
        <button type="submit">Relay callback</button>
      </form>
      <p class="helper-note">The helper only uses the query parameters and forwards them to this host's live sign-in listener.</p>
    </div>
    <script>
      (() => {
        const form = document.getElementById("callback-relay-form");
        const input = document.getElementById("callback-relay-input");
        if (!form || !input) return;
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          const raw = String(input.value || "").trim();
          if (!raw) {
            input.focus();
            return;
          }
          try {
            const parsed = new URL(raw);
            if (!parsed.pathname.endsWith("/auth/callback")) {
              throw new Error("bad-path");
            }
            const redirect = new URL(window.location.href);
            redirect.search = parsed.search;
            window.location.assign(redirect.toString());
          } catch (err) {
            input.setCustomValidity("Paste the full localhost callback URL from the browser.");
            input.reportValidity();
            setTimeout(() => input.setCustomValidity(""), 1200);
          }
        });
      })();
    </script>
"""
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{html.escape(title)}</title>
  {favicon_links_html(self.request_path_prefix())}
  <style>
    :root {{
      color-scheme: dark;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #2f3541;
      color: #e5ecf4;
      font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", Helvetica, sans-serif;
      padding: 20px;
      box-sizing: border-box;
    }}
    main {{
      width: min(720px, 100%);
      background: rgba(52, 59, 72, 0.92);
      border: 1px solid #556174;
      border-radius: 16px;
      padding: 24px;
      box-sizing: border-box;
      display: grid;
      gap: 14px;
      box-shadow: 0 18px 40px rgba(8, 10, 15, 0.16);
    }}
    h1 {{
      margin: 0;
      font-size: 1.55rem;
      letter-spacing: 0;
    }}
    p {{
      margin: 0;
      line-height: 1.6;
      color: #c7d1dd;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-self: start;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid {accent};
      color: {accent};
      background: rgba(255, 255, 255, 0.02);
      font-size: 0.82rem;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 6px;
    }}
    a {{
      display: inline-flex;
      align-items: center;
      min-height: 36px;
      padding: 0 14px;
      border-radius: 12px;
      border: 1px solid #556174;
      color: #e5ecf4;
      text-decoration: none;
      background: rgba(255, 255, 255, 0.02);
    }}
    code {{
      padding: 1px 5px;
      border-radius: 6px;
      border: 1px solid #556174;
      background: rgba(255, 255, 255, 0.04);
      font-family: "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 0.9em;
    }}
    .helper {{
      display: grid;
      gap: 10px;
      margin-top: 4px;
      padding: 14px;
      border-radius: 14px;
      border: 1px solid #556174;
      background: rgba(255, 255, 255, 0.03);
    }}
    .helper-title {{
      font-weight: 600;
      letter-spacing: 0;
    }}
    .helper-form {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .helper-form input {{
      flex: 1 1 420px;
      min-height: 42px;
      border-radius: 10px;
      border: 1px solid #556174;
      background: rgba(255, 255, 255, 0.03);
      color: #e5ecf4;
      padding: 0 12px;
      font: inherit;
    }}
    .helper-form button {{
      min-height: 42px;
      border-radius: 10px;
      border: 1px solid #556174;
      background: rgba(255, 255, 255, 0.04);
      color: #e5ecf4;
      padding: 0 14px;
      font: inherit;
      cursor: pointer;
    }}
    .helper-note {{
      color: #9eabbc;
      font-size: 0.92rem;
    }}
  </style>
</head>
<body>
  <main class="{tone}">
    <div class="badge">{'Sign-in complete' if ok else 'Sign-in blocked'}</div>
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(detail)}</p>
    {helper_block}
    <div class="actions">
      <a href="{html.escape(followup_href)}">{html.escape(followup_label)}</a>
    </div>
  </main>
</body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def serve_favicon_svg(self) -> None:
        encoded = favicon_svg_markup(AGENT_SLUG).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "public, max-age=604800, immutable")
        self.end_headers()
        self.wfile.write(encoded)

    def serve_favicon_ico(self) -> None:
        encoded = favicon_ico_bytes(AGENT_SLUG)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/x-icon")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "public, max-age=604800, immutable")
        self.end_headers()
        self.wfile.write(encoded)

    def auth_cookie_token(self) -> str:
        raw = self.headers.get("Cookie", "").strip()
        if not raw:
            return ""
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return ""
        morsel = jar.get(AUTH_COOKIE_NAME)
        return morsel.value.strip() if morsel else ""

    def request_client_ip(self) -> str:
        client_address = getattr(self, "client_address", ("",)) or ("",)
        peer_ip = str(client_address[0] or "").strip()
        if client_ip_matches(peer_ip, TRUSTED_PROXY_NETWORKS):
            forwarded = self.headers.get("X-Forwarded-For", "").strip()
            if forwarded:
                forwarded_ip = forwarded.split(",", 1)[0].strip()
                if forwarded_ip:
                    return forwarded_ip
            real_ip = self.headers.get("X-Real-IP", "").strip()
            if real_ip:
                return real_ip
        return peer_ip

    def request_path_prefix(self) -> str:
        client_address = getattr(self, "client_address", ("",)) or ("",)
        peer_ip = str(client_address[0] or "").strip()
        if not client_ip_matches(peer_ip, TRUSTED_PROXY_NETWORKS):
            return ""
        forwarded = self.headers.get("X-Forwarded-Prefix", "").strip()
        if not forwarded:
            return ""
        return normalize_path_prefix(forwarded.split(",", 1)[0].strip())

    def is_trusted_client(self) -> bool:
        return client_ip_matches(self.request_client_ip(), TRUSTED_CLIENT_NETWORKS)

    def browser_auth_supported_for_request(self) -> bool:
        return client_ip_matches(self.request_client_ip(), AUTH_BRIDGE_CLIENT_NETWORKS)

    def should_persist_auth_cookie(self, params: dict[str, list[str]]) -> bool:
        if not TOKEN:
            return False
        return query_token(params) == TOKEN and self.auth_cookie_token() != TOKEN

    def send_auth_cookie(self, prefix: str = "") -> None:
        if not TOKEN:
            return
        cookie = SimpleCookie()
        cookie[AUTH_COOKIE_NAME] = TOKEN
        cookie[AUTH_COOKIE_NAME]["path"] = cookie_path_for_prefix(prefix)
        cookie[AUTH_COOKIE_NAME]["max-age"] = str(AUTH_COOKIE_MAX_AGE)
        cookie[AUTH_COOKIE_NAME]["samesite"] = "Lax"
        self.send_header("Set-Cookie", cookie.output(header="").strip())

    def maybe_send_auth_cookie(self, params: dict[str, list[str]]) -> None:
        if self.should_persist_auth_cookie(params):
            self.send_auth_cookie(self.request_path_prefix())

    def clean_request_url(self, parsed: Any, params: dict[str, list[str]]) -> str:
        cleaned = {
            key: values for key, values in params.items() if key != "token" and values
        }
        query = urlencode(cleaned, doseq=True)
        path = prefixed_path(parsed.path or "/", self.request_path_prefix())
        return parsed._replace(path=path, query=query).geturl() or path

    def canonical_request_url(
        self,
        parsed: Any,
        params: dict[str, list[str]],
        *,
        include_token: bool,
    ) -> str:
        path = prefixed_path(parsed.path or "/", self.request_path_prefix())
        if not CANONICAL_HOST:
            return (
                parsed._replace(path=path, query=urlencode(params, doseq=True)).geturl()
                or path
            )
        cleaned = {
            key: values
            for key, values in params.items()
            if values and (include_token or key != "token")
        }
        query = urlencode(cleaned, doseq=True)
        scheme, netloc = canonical_origin_components()
        return parsed._replace(
            scheme=scheme, netloc=netloc, path=path, query=query
        ).geturl()

    def should_redirect_canonical(
        self, parsed: Any, params: dict[str, list[str]]
    ) -> bool:
        if parsed.path != "/" or not CANONICAL_HOST or self.request_path_prefix():
            return False
        request_host = normalize_host_alias(self.headers.get("Host", ""))
        if not request_host or request_host == CANONICAL_HOST:
            return False
        if request_host not in LOCAL_HOST_ALIASES:
            return False
        request_mode = host_access_mode(request_host)
        canonical_mode = host_access_mode(CANONICAL_HOST)
        if request_mode in {"loopback", "private_ip"}:
            return False
        if (
            request_mode
            and canonical_mode
            and request_mode != canonical_mode
            and canonical_mode not in {"public_dns", "public_ip"}
        ):
            return False
        return True

    def redirect_canonical_request_url(
        self,
        parsed: Any,
        params: dict[str, list[str]],
        *,
        include_token: bool,
    ) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header(
            "Location",
            self.canonical_request_url(parsed, params, include_token=include_token),
        )
        self.end_headers()

    def redirect_clean_request_url(
        self, parsed: Any, params: dict[str, list[str]]
    ) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.maybe_send_auth_cookie(params)
        self.send_header("Location", self.clean_request_url(parsed, params))
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        api_path = parsed.path.startswith("/api/")
        cookie_token = self.auth_cookie_token()

        if parsed.path == "/favicon.svg":
            self.serve_favicon_svg()
            return

        if parsed.path == "/favicon.ico":
            self.serve_favicon_ico()
            return

        profile_alias_href = build_profile_alias_href(
            parsed.path,
            params,
            prefix=self.request_path_prefix(),
        )
        if profile_alias_href:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.maybe_send_auth_cookie(params)
            self.send_header("Location", profile_alias_href)
            self.end_headers()
            return

        if parsed.path in {"/auth/browser/callback", "/api/auth/browser/callback"}:
            followup_href = build_console_href(
                token=TOKEN,
                profile=normalize_profile_name((params.get("profile") or [""])[0]),
                route=normalize_route_mode((params.get("route") or [""])[0]),
                prefix=self.request_path_prefix(),
            )
            try:
                snapshot = complete_browser_auth_callback(query_params=params)
            except RuntimeError as exc:
                if api_path:
                    self.json_response(
                        {"error": str(exc), "snapshot": current_snapshot()},
                        status=HTTPStatus.CONFLICT,
                    )
                    return
                self.render_browser_auth_callback_result(
                    ok=False,
                    title=f"{AGENT_NAME} sign-in needs attention",
                    detail=str(exc),
                    followup_href=followup_href,
                    status=HTTPStatus.CONFLICT,
                    show_callback_helper="missing code or state" in str(exc).lower(),
                )
                return
            if api_path:
                self.json_response(
                    {
                        "ok": True,
                        "detail": "Browser callback delivered to the live sign-in listener.",
                        "snapshot": snapshot,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
                return
            self.render_browser_auth_callback_result(
                ok=True,
                title=f"{AGENT_NAME} sign-in delivered",
                detail=(
                    "The browser callback was handed to the live sign-in listener on this host. "
                    "You can close this tab and return to the console."
                ),
                followup_href=followup_href,
            )
            return

        if not (self.is_trusted_client() or token_ok(params, cookie_token)):
            if parsed.path == "/":
                self.render_token_gate(params)
                return
            if api_path:
                self.json_response(
                    {"error": "missing or invalid token"}, status=HTTPStatus.FORBIDDEN
                )
                return
            self.send_error(HTTPStatus.FORBIDDEN, "missing or invalid token")
            return

        if parsed.path == "/healthz":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.maybe_send_auth_cookie(params)
            self.end_headers()
            self.wfile.write(b"ok\n")
            return

        if self.should_redirect_canonical(parsed, params):
            self.redirect_canonical_request_url(
                parsed, params, include_token=bool(TOKEN)
            )
            return

        if parsed.path == "/" and query_token(params) == TOKEN:
            self.redirect_root(params)
            return

        if parsed.path == "/api/status":
            self.json_response(current_snapshot())
            return

        if parsed.path == "/api/kpis":
            self.json_response(current_kpis())
            return

        if parsed.path == "/api/audit":
            try:
                limit = max(
                    1,
                    min(
                        int((params.get("limit") or [str(MAX_AUDIT_ITEMS)])[0] or 0),
                        MAX_AUDIT_ITEMS,
                    ),
                )
            except (TypeError, ValueError):
                limit = MAX_AUDIT_ITEMS
            try:
                since_ts = int((params.get("since") or ["0"])[0] or 0)
            except (TypeError, ValueError):
                since_ts = 0
            event_type = str((params.get("event_type") or [""])[0] or "").strip()
            items = load_audit_events(
                limit=limit,
                since_ts=max(0, since_ts),
                event_type=event_type,
            )
            self.json_response(
                {
                    "count": len(items),
                    "items": items,
                    "session_name": SESSION,
                    "agent_name": AGENT_NAME,
                    "host_name": HOST_NAME,
                    "ui_version": UI_VERSION,
                }
            )
            return

        if parsed.path == "/api/stream":
            self.stream_status()
            return

        if parsed.path in {"/auth/browser", "/api/auth/browser"}:
            followup_href = build_console_href(
                token=TOKEN,
                profile=normalize_profile_name((params.get("profile") or [""])[0]),
                route=normalize_route_mode((params.get("route") or [""])[0]),
                prefix=self.request_path_prefix(),
            )
            try:
                snapshot = start_browser_auth()
            except RuntimeError as exc:
                if api_path:
                    self.json_response(
                        {"error": str(exc), "snapshot": current_snapshot()},
                        status=HTTPStatus.CONFLICT,
                    )
                    return
                self.render_browser_auth_callback_result(
                    ok=False,
                    title=f"{AGENT_NAME} sign-in needs attention",
                    detail=str(exc),
                    followup_href=followup_href,
                    status=HTTPStatus.CONFLICT,
                )
                return
            if api_path:
                self.json_response(
                    {
                        "ok": True,
                        "detail": "Browser sign-in is ready.",
                        "snapshot": snapshot,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
                return
            auth = snapshot.get("auth") if isinstance(snapshot, dict) else None
            verification_url = (
                str(auth.get("verification_url") or "").strip()
                if isinstance(auth, dict)
                else ""
            )
            if verification_url:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.maybe_send_auth_cookie(params)
                self.send_header("Location", verification_url)
                self.end_headers()
                return
            self.redirect_root(params)
            return

        if parsed.path == "/api/file":
            self.serve_file_target(params)
            return

        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        self.render_index(params)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        api_path = parsed.path.startswith("/api/")
        raw_body = self._read_request_body()
        query_params = parse_qs(parsed.query)
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        json_payload: dict[str, Any] | None = None
        cookie_token = self.auth_cookie_token()
        if content_type == "application/json":
            json_payload = self._read_json_body(raw_body)
            params = self._merge_params(query_params, self._json_params(json_payload))
        else:
            params = self._merge_params(
                query_params, self._read_post_params(raw_body=raw_body)
            )

        if not (self.is_trusted_client() or token_ok(params, cookie_token)):
            if api_path:
                self.json_response(
                    {"error": "missing or invalid token"}, status=HTTPStatus.FORBIDDEN
                )
                return
            self.send_error(HTTPStatus.FORBIDDEN, "missing or invalid token")
            return

        if parsed.path in {"/api/attachment", "/attachment"}:
            payload = json_payload or {}
            if not isinstance(payload, dict):
                self.json_response(
                    {"error": "invalid attachment payload"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            text_value = payload.get("text")
            raw_bytes = b""
            if isinstance(text_value, str):
                raw_bytes = text_value.encode("utf-8")
            else:
                encoded = str(payload.get("data_b64") or "").strip()
                if not encoded:
                    self.json_response(
                        {"error": "attachment data is required"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                try:
                    raw_bytes = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    self.json_response(
                        {"error": "attachment data is not valid base64"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
            name = str(payload.get("name") or "attachment").strip() or "attachment"
            attachment_type = str(payload.get("content_type") or "").strip()
            source = str(payload.get("source") or "paste").strip() or "paste"
            kind = str(payload.get("kind") or "").strip() or None
            try:
                attachment = create_draft_attachment(
                    raw_bytes=raw_bytes,
                    name=name,
                    content_type=attachment_type,
                    source=source,
                    kind=kind,
                )
            except ValueError as exc:
                self.json_response(
                    {"error": str(exc), "snapshot": current_snapshot()},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self.json_response(
                {
                    "ok": True,
                    "attachment": attachment,
                    "snapshot": current_snapshot(),
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if parsed.path in {"/api/attachment/capture", "/attachment/capture"}:
            payload = json_payload or {}
            if not isinstance(payload, dict):
                self.json_response(
                    {"error": "invalid capture payload"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            capture_url = str(payload.get("url") or "").strip()
            capture_label = str(payload.get("label") or "").strip()
            try:
                attachment = capture_web_attachment(
                    url=capture_url,
                    label=capture_label,
                )
            except ValueError as exc:
                self.json_response(
                    {"error": str(exc), "snapshot": current_snapshot()},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self.json_response(
                {
                    "ok": True,
                    "attachment": attachment,
                    "snapshot": current_snapshot(),
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if parsed.path in {"/api/attachment/remove", "/attachment/remove"}:
            attachment_token = (params.get("attachment_token") or [""])[0].strip()
            remove_draft_attachment(attachment_token)
            self.json_response(
                {"ok": True, "snapshot": current_snapshot()},
                status=HTTPStatus.ACCEPTED,
            )
            return

        if parsed.path in {"/api/history/unwind", "/history/unwind"}:
            try:
                removed = unwind_latest_history_turn()
            except ValueError as exc:
                self.json_response(
                    {"error": str(exc), "snapshot": current_snapshot()},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            except RuntimeError as exc:
                self.json_response(
                    {"error": str(exc), "snapshot": current_snapshot()},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self.json_response(
                {
                    "ok": True,
                    "removed": removed,
                    "snapshot": current_snapshot(),
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if parsed.path in {"/relay", "/api/relay"}:
            actor_ip = self.request_client_ip()
            request_host = self.headers.get("Host", "")
            target_label = (params.get("target_label") or [""])[0].strip() or (
                params.get("target") or [""]
            )[0].strip()
            source_prompt = (params.get("source_prompt") or [""])[0].strip()
            source_response = (params.get("source_response") or [""])[0].strip()
            speed = normalize_response_speed((params.get("speed") or [""])[0])
            detail = normalize_response_detail((params.get("detail") or [""])[0])
            relay_targets = {
                item["label"]: item
                for item in build_relay_targets(
                    token=TOKEN or ((params.get("token") or [""])[0]),
                    profile=normalize_profile_name((params.get("profile") or [""])[0]),
                    request_host=request_host,
                    route_mode=(params.get("route") or [""])[0],
                    client_ip=actor_ip,
                )
            }
            target = relay_targets.get(target_label)
            if not target:
                self.json_response(
                    {
                        "error": "relay target unavailable",
                        "snapshot": current_snapshot(),
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            handoff_message = build_handoff_message(source_prompt, source_response)
            payload = urlencode(
                {
                    "token": target["token"],
                    "message": handoff_message,
                    "speed": speed,
                    "detail": str(detail),
                }
            ).encode("utf-8")
            request = urllib_request.Request(
                target["api_url"],
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
                },
                method="POST",
            )
            try:
                with urllib_request.urlopen(request, timeout=25) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    try:
                        downstream = json.loads(body) if body else {}
                    except json.JSONDecodeError:
                        downstream = {}
            except urllib_error.HTTPError as exc:
                error_text = exc.read().decode("utf-8", errors="replace")
                error_payload: dict[str, Any] = {}
                try:
                    error_payload = json.loads(error_text) if error_text else {}
                except json.JSONDecodeError:
                    error_payload = {}
                self.json_response(
                    {
                        "error": error_payload.get("error")
                        or f"{target_label} rejected the handoff.",
                        "target": target_label,
                        "snapshot": current_snapshot(),
                    },
                    status=HTTPStatus.CONFLICT
                    if exc.code == HTTPStatus.CONFLICT
                    else HTTPStatus.BAD_GATEWAY,
                )
                return
            except (urllib_error.URLError, TimeoutError, OSError) as exc:
                reason = getattr(exc, "reason", None) or str(exc)
                self.json_response(
                    {
                        "error": f"relay to {target_label} failed: {reason}",
                        "target": target_label,
                        "snapshot": current_snapshot(),
                    },
                    status=HTTPStatus.BAD_GATEWAY,
                )
                return
            record_action(
                "relay-send",
                f"Handed off the current thread to {target_label} · {response_profile_label(speed, detail)}",
            )
            append_audit_event(
                event_type="relay.send",
                summary=f"Relayed the current thread to {target_label}.",
                detail=f"{target_label} · {response_profile_label(speed, detail)}",
                severity="info",
                actor_type="operator",
                actor_ip=actor_ip,
                thread_id=read_text(THREAD_ID_PATH),
                payload={
                    "target_label": target_label,
                    "speed": speed,
                    "detail": detail,
                },
            )
            self.json_response(
                {
                    "ok": True,
                    "target": target_label,
                    "target_url": target["url"],
                    "relay_ack": build_relay_acknowledgement(target_label, downstream),
                    "downstream": downstream,
                    "snapshot": current_snapshot(),
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if parsed.path in {"/ask", "/api/ask"}:
            actor_ip = self.request_client_ip()
            attachments = load_draft_attachments()
            message = (params.get("message", [""])[0]).strip()
            speed = normalize_response_speed((params.get("speed") or [""])[0])
            detail = normalize_response_detail((params.get("detail") or [""])[0])
            if not message and not attachments:
                if api_path:
                    self.json_response(
                        {
                            "error": "message or attachment is required",
                            "snapshot": current_snapshot(),
                        },
                        status=HTTPStatus.BAD_REQUEST,
                    )
                else:
                    self.redirect_root(params)
                return
            if not message:
                message = build_attachment_lead_message(attachments)
            accepted, snapshot = start_web_prompt(message, speed, detail, attachments)
            if accepted:
                clear_draft_attachments()
                snapshot = current_snapshot()
                append_audit_event(
                    event_type="chat.requested",
                    summary="Prompt requested from the web TUI.",
                    detail=summarize_text(message, 180),
                    severity="info",
                    actor_type="operator",
                    actor_ip=actor_ip,
                    thread_id=read_text(THREAD_ID_PATH),
                    payload={
                        "prompt_preview": summarize_text(message, 240),
                        "speed": speed,
                        "detail": detail,
                        "attachment_count": len(attachments),
                    },
                )
            if api_path:
                self.json_response(
                    {
                        "accepted": accepted,
                        "error": "" if accepted else "a web prompt is already running",
                        "snapshot": snapshot,
                    },
                    status=HTTPStatus.ACCEPTED if accepted else HTTPStatus.CONFLICT,
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/send", "/api/send"}:
            message = (params.get("message", [""])[0]).strip()
            if message:
                send_text(message)
                append_audit_event(
                    event_type="tmux.send",
                    summary="Sent raw text to the live tmux session.",
                    detail=summarize_text(message, 180),
                    severity="warn",
                    actor_type="operator",
                    actor_ip=self.request_client_ip(),
                    thread_id=read_text(THREAD_ID_PATH),
                    payload={"message_preview": summarize_text(message, 240)},
                )
            snapshot = current_snapshot()
            if api_path:
                self.json_response(
                    {"ok": True, "snapshot": snapshot}, status=HTTPStatus.ACCEPTED
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/cancel-web", "/api/cancel-web"}:
            snapshot = cancel_active_web_prompt(clear_queue=False)
            if api_path:
                self.json_response(
                    {"ok": True, "snapshot": snapshot}, status=HTTPStatus.ACCEPTED
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/cancel-all", "/api/cancel-all"}:
            snapshot = cancel_active_web_prompt(clear_queue=True)
            if api_path:
                self.json_response(
                    {"ok": True, "snapshot": snapshot}, status=HTTPStatus.ACCEPTED
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/queue/clear", "/api/queue/clear"}:
            snapshot = clear_queued_prompts()
            if api_path:
                self.json_response(
                    {"ok": True, "snapshot": snapshot}, status=HTTPStatus.ACCEPTED
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/queue/promote-latest", "/api/queue/promote-latest"}:
            snapshot = promote_latest_operator_prompt()
            if api_path:
                self.json_response(
                    {"ok": True, "snapshot": snapshot}, status=HTTPStatus.ACCEPTED
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/interrupt", "/api/interrupt"}:
            send_interrupt()
            append_audit_event(
                event_type="tmux.interrupt",
                summary="Interrupted the live tmux session.",
                detail="Sent Ctrl+C to the interactive tmux session.",
                severity="warn",
                actor_type="operator",
                actor_ip=self.request_client_ip(),
                thread_id=read_text(THREAD_ID_PATH),
            )
            snapshot = current_snapshot()
            if api_path:
                self.json_response(
                    {"ok": True, "snapshot": snapshot}, status=HTTPStatus.ACCEPTED
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/restart", "/api/restart"}:
            restart_session()
            append_audit_event(
                event_type="tmux.restart",
                summary="Restarted the live tmux session.",
                detail=f"Restarted the interactive {AGENT_NAME} Codex tmux session.",
                severity="warn",
                actor_type="operator",
                actor_ip=self.request_client_ip(),
                thread_id=read_text(THREAD_ID_PATH),
            )
            snapshot = current_snapshot()
            if api_path:
                self.json_response(
                    {"ok": True, "snapshot": snapshot}, status=HTTPStatus.ACCEPTED
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/auth/device", "/api/auth/device"}:
            try:
                snapshot = start_device_auth()
            except RuntimeError as exc:
                self.json_response(
                    {
                        "error": str(exc),
                        "snapshot": current_snapshot(),
                    },
                    status=HTTPStatus.CONFLICT,
                )
                return
            if api_path:
                self.json_response(
                    {
                        "ok": True,
                        "detail": "Device-code sign-in is ready.",
                        "snapshot": snapshot,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/auth/browser", "/api/auth/browser"}:
            try:
                snapshot = start_browser_auth()
            except RuntimeError as exc:
                self.json_response(
                    {
                        "error": str(exc),
                        "snapshot": current_snapshot(),
                    },
                    status=HTTPStatus.CONFLICT,
                )
                return
            if api_path:
                self.json_response(
                    {
                        "ok": True,
                        "detail": "Browser sign-in is ready.",
                        "snapshot": snapshot,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
            else:
                self.redirect_root(params)
            return

        if parsed.path in {"/auth/browser/callback", "/api/auth/browser/callback"}:
            payload = json_payload or {}
            callback_url = str(payload.get("callback_url") or "").strip()
            try:
                snapshot = complete_browser_auth_callback(callback_url=callback_url)
            except RuntimeError as exc:
                self.json_response(
                    {"error": str(exc), "snapshot": current_snapshot()},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self.json_response(
                {
                    "ok": True,
                    "detail": "Browser callback delivered to the live sign-in listener.",
                    "snapshot": snapshot,
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if api_path:
            self.json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _read_request_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _read_post_params(
        self, *, raw_body: bytes | None = None
    ) -> dict[str, list[str]]:
        if raw_body is None:
            raw_body = self._read_request_body()
        raw = raw_body.decode("utf-8", errors="replace")
        return parse_qs(raw)

    def _read_json_body(self, raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _json_params(self, payload: dict[str, Any]) -> dict[str, list[str]]:
        params: dict[str, list[str]] = {}
        for key in (
            "token",
            "profile",
            "message",
            "speed",
            "detail",
            "attachment_token",
        ):
            value = payload.get(key)
            if value is None:
                continue
            params[key] = [str(value)]
        return params

    def _merge_params(self, *param_sets: dict[str, list[str]]) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        for param_set in param_sets:
            for key, values in param_set.items():
                merged.setdefault(key, []).extend(values)
        return merged

    def json_response(
        self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        query_params = parse_qs(urlparse(self.path).query)
        self.maybe_send_auth_cookie(query_params)
        self.end_headers()
        self.wfile.write(encoded)

    def render_directory_view(self, path: Path, params: dict[str, list[str]]) -> None:
        profile = normalize_profile_name((params.get("profile") or [""])[0])
        route_mode = normalize_route_mode((params.get("route") or [""])[0])
        local_token = "" if self.auth_cookie_token() == TOKEN else TOKEN
        path_prefix = self.request_path_prefix()
        entries = sorted(
            path.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )[:DIRECTORY_VIEW_LIMIT]
        entry_items = "".join(
            (
                f'<li><a href="{html.escape(build_file_href(token=local_token, path=str(entry.resolve()), profile=profile, route=route_mode, prefix=path_prefix))}">'
                f'{html.escape(entry.name)}{"/" if entry.is_dir() else ""}</a></li>'
            )
            for entry in entries
        )
        back_href = build_console_href(
            token=local_token, profile=profile, route=route_mode, prefix=path_prefix
        )
        copy_script = render_file_copy_script()
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{html.escape(path.name or str(path))}</title>
  {favicon_links_html(path_prefix)}
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      background: #2f3541;
      color: #e5ecf4;
      font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", Helvetica, sans-serif;
      padding: 20px;
      box-sizing: border-box;
    }}
    main {{
      max-width: 900px;
      margin: 0 auto;
      background: rgba(52, 59, 72, 0.9);
      border: 1px solid #556174;
      border-radius: 20px;
      padding: 18px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 1.25rem;
    }}
    p, li {{
      line-height: 1.5;
    }}
    code {{
      display: block;
      padding: 10px 12px;
      border-radius: 14px;
      background: #373e4b;
      border: 1px solid #556174;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    a {{
      color: #c1d0df;
    }}
    button.chip {{
      appearance: none;
      font: inherit;
      cursor: pointer;
    }}
    .row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 9px;
      border-radius: 0;
      border: 1px solid #556174;
      background: #373e4b;
      color: #e5ecf4;
      text-decoration: none;
      font-size: 0.78rem;
    }}
    ul {{
      margin: 14px 0 0;
      padding-left: 18px;
    }}
  </style>
</head>
<body>
    <main>
    <div class="row">
    <a class="chip" href="{html.escape(back_href)}">Back to console</a>
    <button class="chip" type="button" data-copy-value="{html.escape(str(path), quote=True)}">Copy path</button>
    </div>
    <h1>{html.escape(path.name or str(path))}</h1>
    <p>{len(entries)} entries shown.</p>
    <code>{html.escape(str(path))}</code>
    <ul>{entry_items or "<li>[empty]</li>"}</ul>
  </main>
  {copy_script}
</body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.maybe_send_auth_cookie(params)
        self.end_headers()
        self.wfile.write(encoded)

    def render_file_view(
        self,
        path: Path,
        content_type: str,
        stat: os.stat_result,
        params: dict[str, list[str]],
    ) -> None:
        profile = normalize_profile_name((params.get("profile") or [""])[0])
        route_mode = normalize_route_mode((params.get("route") or [""])[0])
        local_token = "" if self.auth_cookie_token() == TOKEN else TOKEN
        path_prefix = self.request_path_prefix()
        back_href = build_console_href(
            token=local_token, profile=profile, route=route_mode, prefix=path_prefix
        )
        raw_href = build_file_href(
            token=local_token,
            path=str(path),
            profile=profile,
            route=route_mode,
            prefix=path_prefix,
            raw=True,
        )
        download_href = build_file_href(
            token=local_token,
            path=str(path),
            profile=profile,
            route=route_mode,
            prefix=path_prefix,
            download=True,
        )
        preview_text = ""
        preview_note = ""
        preview_available = is_text_preview_type(path, content_type)
        image_preview = content_type.split(";", 1)[0].lower().startswith("image/")
        copy_preview_button = ""
        copy_preview_source = ""
        if preview_available:
            with path.open("rb") as handle:
                data = handle.read(FILE_PREVIEW_MAX_BYTES + 1)
            preview_available = True
            if len(data) > FILE_PREVIEW_MAX_BYTES:
                preview_note = (
                    f"Preview truncated at {human_size(FILE_PREVIEW_MAX_BYTES)}."
                )
                data = data[:FILE_PREVIEW_MAX_BYTES]
            preview_text = data.decode("utf-8", errors="replace")
        if preview_available and not image_preview:
            copy_preview_button = (
                '<button class="chip" id="copy-preview-button" type="button" '
                'data-copy-target="file-copy-source">Copy text</button>'
            )
            copy_preview_source = f'<textarea id="file-copy-source" hidden>{html.escape(preview_text)}</textarea>'
        preview_html = (
            f'<div class="image-frame"><img src="{html.escape(raw_href)}" alt="{html.escape(path.name)}"></div>'
            if image_preview
            else render_file_preview_html(preview_text)
            if preview_available
            else "<p>Preview is not available for this file type. Use Raw or Download.</p>"
        )
        copy_script = render_file_copy_script()
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{html.escape(path.name)}</title>
  {favicon_links_html(path_prefix)}
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        linear-gradient(180deg, #14191f 0%, #171d24 54%, #11161c 100%);
      color: #e5ecf4;
      font-family: "IBM Plex Sans", "Segoe UI", Helvetica, Arial, sans-serif;
      padding: 20px;
      box-sizing: border-box;
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      background: rgba(22, 29, 36, 0.94);
      border: 1px solid #4f6176;
      border-radius: 0;
      padding: 18px;
      display: grid;
      gap: 14px;
    }}
    h1 {{
      margin: 0;
      font-size: 1.25rem;
    }}
    p {{
      margin: 0;
      line-height: 1.5;
      color: #adb8c7;
    }}
    code, pre {{
      margin: 0;
      padding: 12px;
      border-radius: 0;
      background: #1d2630;
      border: 1px solid #4f6176;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "JetBrains Mono", "IBM Plex Mono", Menlo, Consolas, monospace;
      font-size: 0.9rem;
      line-height: 1.5;
    }}
    .file-preview {{
      padding: 0;
      overflow: auto;
    }}
    .file-line {{
      display: grid;
      grid-template-columns: minmax(3.8rem, auto) 1fr;
      gap: 0;
      min-width: max-content;
      scroll-margin-top: 18px;
    }}
    .file-line:target {{
      background: rgba(122, 162, 247, 0.22);
    }}
    .line-no {{
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      padding: 0 12px;
      border-right: 1px solid #556174;
      color: #7f8da3;
      text-decoration: none;
      user-select: none;
    }}
    .line-no:hover {{
      color: #c1d0df;
    }}
    .line-code {{
      display: block;
      padding: 0 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 9px;
      border-radius: 0;
      border: 1px solid #4f6176;
      background: #1b232d;
      color: #e5ecf4;
      text-decoration: none;
      font-size: 0.78rem;
    }}
    button.chip {{
      appearance: none;
      font: inherit;
      cursor: pointer;
    }}
    a {{
      color: #c1d0df;
    }}
    .image-frame {{
      display: grid;
      place-items: center;
      padding: 12px;
      border-radius: 0;
      border: 1px solid #4f6176;
      background: #1d2630;
      overflow: hidden;
    }}
    .image-frame img {{
      max-width: 100%;
      max-height: min(72vh, 880px);
      border-radius: 0;
      display: block;
    }}
  </style>
</head>
<body>
  <main>
    <div class="row">
      <a class="chip" href="{html.escape(back_href)}">Back to console</a>
      <a class="chip" href="{html.escape(raw_href)}">Raw</a>
      <a class="chip" href="{html.escape(download_href)}">Download</a>
      <button class="chip" id="copy-path-button" type="button" data-copy-value="{html.escape(str(path), quote=True)}">Copy path</button>
      {copy_preview_button}
    </div>
    <h1>{html.escape(path.name)}</h1>
    <p>{html.escape(str(path))}</p>
    <div class="row">
      <span class="chip">{html.escape(content_type)}</span>
      <span class="chip">{html.escape(human_size(stat.st_size))}</span>
    </div>
    {"<p>" + html.escape(preview_note) + "</p>" if preview_note else ""}
    {copy_preview_source}
    {preview_html}
  </main>
  {copy_script}
</body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.maybe_send_auth_cookie(params)
        self.end_headers()
        self.wfile.write(encoded)

    def send_file_bytes(
        self, path: Path, content_type: str, stat: os.stat_result, *, download: bool
    ) -> None:
        disposition = "attachment" if download else "inline"
        file_size = int(stat.st_size)
        start = 0
        end = max(0, file_size - 1)
        status = HTTPStatus.OK
        range_header = self.headers.get("Range", "").strip()
        if range_header and file_size > 0:
            range_match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if range_match:
                raw_start, raw_end = range_match.groups()
                if raw_start == "" and raw_end:
                    suffix_length = min(file_size, int(raw_end))
                    start = file_size - suffix_length
                else:
                    start = int(raw_start or "0")
                    end = min(file_size - 1, int(raw_end)) if raw_end else file_size - 1
                if start > end or start >= file_size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                status = HTTPStatus.PARTIAL_CONTENT
        content_length = (end - start + 1) if file_size else 0
        with path.open("rb") as handle:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Accept-Ranges", "bytes")
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header(
                "Content-Disposition", f'{disposition}; filename="{path.name}"'
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if start:
                handle.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                self.wfile.write(chunk)

    def serve_file_target(self, params: dict[str, list[str]]) -> None:
        raw_path = (params.get("path") or [""])[0]
        target = resolve_file_target(raw_path)
        if target is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "missing path")
            return
        if not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "file not found")
            return
        if target.is_dir():
            self.render_directory_view(target, params)
            return
        try:
            stat = target.stat()
        except PermissionError:
            self.send_error(HTTPStatus.FORBIDDEN, "file is not readable")
            return
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "file not found")
            return
        content_type = guess_file_content_type(target)
        wants_raw = (params.get("raw") or [""])[0] == "1"
        wants_download = (params.get("download") or [""])[0] == "1"
        if wants_raw or wants_download:
            self.send_file_bytes(target, content_type, stat, download=wants_download)
            return
        self.render_file_view(target, content_type, stat, params)

    def stream_status(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_marker: tuple[Any, ...] | None = None
        last_sent = 0.0
        try:
            while True:
                snapshot = current_snapshot()
                marker = snapshot_marker(snapshot)
                now = time.time()
                if marker != last_marker:
                    payload = json.dumps(snapshot).encode("utf-8")
                    self.wfile.write(b"event: snapshot\n")
                    self.wfile.write(b"data: ")
                    self.wfile.write(payload)
                    self.wfile.write(b"\n\n")
                    self.wfile.flush()
                    last_marker = marker
                    last_sent = now
                elif (now - last_sent) >= STREAM_IDLE_SECONDS:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    last_sent = now
                time.sleep(
                    STREAM_PENDING_SECONDS
                    if snapshot.get("pending")
                    else STREAM_IDLE_SECONDS
                )
        except (BrokenPipeError, ConnectionResetError):
            return

    def redirect_root(self, params: dict[str, list[str]]) -> None:
        cookie_token = self.auth_cookie_token()
        trusted_request = self.is_trusted_client()
        token_value = (
            ""
            if trusted_request
            or TOKEN
            and (cookie_token == TOKEN or query_token(params) == TOKEN)
            else TOKEN or ((params.get("token") or [""])[0])
        )
        profile_value = normalize_profile_name((params.get("profile") or [""])[0])
        route_value = normalize_route_mode((params.get("route") or [""])[0])
        target = build_console_href(
            token=token_value,
            profile=profile_value,
            route=route_value,
            prefix=self.request_path_prefix(),
        )
        self.send_response(HTTPStatus.SEE_OTHER)
        self.maybe_send_auth_cookie(params)
        self.send_header("Location", target)
        self.end_headers()

    def render_index(self, params: dict[str, list[str]]) -> None:
        ensure_session()
        active_profile = normalize_profile_name((params.get("profile") or [""])[0])
        active_profile_label = UI_PROFILES[active_profile]["label"]
        active_mode = profile_mode(active_profile)
        opposite_mode = "light" if active_mode == "dark" else "dark"
        trusted_request = self.is_trusted_client()
        browser_auth_supported = self.browser_auth_supported_for_request()
        token_value_raw = (
            "" if trusted_request else TOKEN or ((params.get("token") or [""])[0])
        )
        local_token_value = (
            ""
            if trusted_request or TOKEN and self.auth_cookie_token() == TOKEN
            else token_value_raw
        )
        request_host = self.headers.get("Host", "")
        request_client_ip = self.request_client_ip()
        path_prefix = self.request_path_prefix()
        route_preference = normalize_route_mode((params.get("route") or [""])[0])
        active_route_mode = effective_route_mode(
            request_host, route_preference, request_client_ip
        )
        norman_prime_href = build_norman_prime_href(
            request_host=request_host,
            route_mode=route_preference,
            client_ip=request_client_ip,
        )
        norman_directory_href = build_norman_directory_href(
            request_host=request_host,
            route_mode=route_preference,
            client_ip=request_client_ip,
        )
        relay_targets_json = script_json(
            build_relay_targets(
                token=token_value_raw,
                profile=active_profile,
                request_host=request_host,
                route_mode=route_preference,
                client_ip=request_client_ip,
            )
        )
        theme_toggle_target = profile_for_mode(active_profile, opposite_mode)
        theme_toggle_label = opposite_mode.title()
        settings_mode_links_html = "".join(
            f'<a class="profile-chip setting-pill{" active" if mode == active_mode else ""}" data-icon="{html.escape(icon_for_label(mode))}" href="{html.escape(build_console_href(token=local_token_value, profile=profile_for_mode(active_profile, mode), route=route_preference, prefix=path_prefix))}">{html.escape(mode.title())}</a>'
            for mode in PROFILE_MODE_ORDER
        )
        settings_profile_links_html = "".join(
            f'<a class="profile-chip setting-pill{" active" if slug == active_profile else ""}" data-icon="{html.escape(entity_mark_for_label(data["label"], "•"))}" href="{html.escape(build_console_href(token=local_token_value, profile=slug, route=route_preference, prefix=path_prefix))}">{html.escape(data["label"])}</a>'
            for slug, data in profiles_for_mode(active_mode)
        )
        settings_route_links_html = "".join(
            f'<a class="profile-chip setting-pill{" active" if mode == route_preference else ""}" data-icon="{html.escape(icon_for_label(mode, "⇄"))}" href="{html.escape(build_console_href(token=local_token_value, profile=active_profile, route=mode, prefix=path_prefix))}">{html.escape("Auto" if mode == "auto" else "LAN" if mode == "lan" else "Tail" if mode == "tail" else "Host")}</a>'
            for mode in ROUTE_MODE_ORDER
        )
        console_groups_by_slug: dict[str, dict[str, Any]] = {}
        console_groups: list[dict[str, Any]] = []
        active_console_group = ""
        current_agent_candidates = {
            AGENT_SLUG,
            re.sub(r"[^a-z0-9]+", "-", AGENT_NAME.lower()).strip("-"),
            re.sub(r"[^a-z0-9]+", "-", AGENT_GROUP.lower()).strip("-"),
        }
        for link in CONSOLE_LINKS:
            group = str(link.get("group") or "").strip() or "Agents"
            group_slug = normalize_console_group_slug(group) or "agents"
            tone_group = semantic_console_group(group_slug) or "agents"
            if group_slug not in console_groups_by_slug:
                group_record: dict[str, Any] = {
                    "label": group,
                    "slug": group_slug,
                    "tone_group": tone_group,
                    "links": [],
                }
                console_groups_by_slug[group_slug] = group_record
                console_groups.append(group_record)
            rendered_url = render_console_link_url(
                link,
                token=token_value_raw,
                profile=active_profile,
                request_host=request_host,
                route_mode=route_preference,
                client_ip=request_client_ip,
            )
            console_groups_by_slug[group_slug]["links"].append(
                {
                    "label": link["label"],
                    "url": rendered_url,
                    "group": group,
                    "group_slug": group_slug,
                    "tone_group": tone_group,
                    "note": str(link.get("note") or "").strip(),
                    "lane": str(link.get("lane") or "").strip(),
                    "featured": bool(link.get("featured")),
                    "priority": int(link.get("priority") or 0),
                    "icon": str(
                        link.get("icon")
                        or entity_mark_for_label(str(link["label"]), "•")
                    ),
                }
            )
            link_slug = re.sub(r"[^a-z0-9]+", "-", link["label"].lower()).strip("-")
            if (
                link_slug
                and link_slug in current_agent_candidates
                and not active_console_group
            ):
                active_console_group = group_slug
        if not active_console_group and console_groups:
            active_console_group = str(console_groups[0]["slug"])
        show_console_panels = any(len(group["links"]) > 1 for group in console_groups)
        console_group_buttons_html = "".join(
            (
                f'<button type="button" class="console-group-pill{" active" if group["slug"] == active_console_group else ""}" '
                f'data-group="{html.escape(str(group["slug"]))}" '
                f'data-tone="{html.escape(str(group["tone_group"]))}" '
                f'data-icon="{html.escape(entity_mark_for_label(str(group["label"]), "•"))}" '
                f'role="tab" aria-selected="{"true" if group["slug"] == active_console_group else "false"}">'
                f'<span class="console-group-name">{html.escape(str(group["label"]))}</span>'
                + (
                    f'<span class="console-group-count">{len(group["links"])}</span>'
                    if len(group["links"]) > 1
                    else ""
                )
                + "</button>"
            )
            for group in console_groups
        )
        console_group_panels_html = "".join(
            (
                f'<div class="console-nav-panel{" active" if group["slug"] == active_console_group else ""}{" solo" if len(group["links"]) <= 1 else ""}" data-group="{html.escape(str(group["slug"]))}" role="tabpanel"{" hidden" if group["slug"] != active_console_group else ""}>'
                + "".join(
                    f'<a class="quick-link" data-group="{html.escape(str(group["slug"]))}" data-tone="{html.escape(str(item["tone_group"]))}" data-icon="{html.escape(str(item["icon"]))}" data-label="{html.escape(str(item["label"]))}" href="{html.escape(str(item["url"]))}"{console_link_anchor_attrs(str(item["url"]))}>'
                    f'{_render_name_cartouche(str(item["label"]), kind="bot", tone="bot", group=str(item["tone_group"]))}</a>'
                    for item in group["links"]
                )
                + "</div>"
            )
            for group in console_groups
        )
        console_nav_html = (
            f'<nav class="console-nav" aria-label="Console links" data-active-group="{html.escape(active_console_group)}">'
            f'<div class="console-nav-shell"><div class="console-nav-groups" role="tablist" aria-label="Agent groups">{console_group_buttons_html}</div>'
            + (
                f'<div class="console-nav-panels">{console_group_panels_html}</div>'
                if show_console_panels
                else ""
            )
            + "</div></nav>"
            if console_groups
            else ""
        )
        topbar_context_links_html = "".join(
            f'<a class="ghost utility-button button-link" data-icon="{html.escape(str(item["icon"]))}" data-label="{html.escape(str(item["label"]))}" href="{html.escape(str(item["url"]))}"{console_link_anchor_attrs(str(item["url"]))} title="{html.escape(str(item.get("note") or item["label"]))}">'
            f'{_render_name_cartouche(str(item["label"]), kind="bot", tone="bot", group=str(item["tone_group"]))}</a>'
            for group in console_groups
            if str(group.get("slug") or "") in {"norman", "pipeline"}
            for item in group["links"]
        )
        prompt_suggestions_html = "".join(
            f'<button type="button" class="ghost suggestion-chip" data-icon="{html.escape(icon_for_label(item["label"], "·"))}" data-suggestion="{html.escape(item["prompt"], quote=True)}">{html.escape(item["label"])}</button>'
            for item in PROMPT_SUGGESTIONS
        )
        browse_targets: list[dict[str, Any]] = []
        if Path(WORKDIR).exists():
            browse_targets.append(
                {
                    "label": "Workspace",
                    "focus_label": "Workbench",
                    "group": "Norman",
                    "group_slug": "norman",
                    "tone_group": "norman",
                    "icon": icon_for_label("Workspace"),
                    "url": build_file_href(
                        token=local_token_value,
                        path=WORKDIR,
                        profile=active_profile,
                        route=route_preference,
                        prefix=path_prefix,
                    ),
                    "note": "Repo root, notes, and local files.",
                    "lane": "make",
                    "priority": 320,
                    "featured": True,
                    "source": "local",
                }
            )
        if STATE_DIR.exists():
            browse_targets.append(
                {
                    "label": "Bridge State",
                    "group": "Shared",
                    "group_slug": "shared",
                    "tone_group": "shared",
                    "icon": icon_for_label("Bridge State"),
                    "url": build_file_href(
                        token=local_token_value,
                        path=str(STATE_DIR),
                        profile=active_profile,
                        route=route_preference,
                        prefix=path_prefix,
                    ),
                    "note": "Bridge logs, state snapshots, and live status.",
                    "lane": "operate",
                    "priority": 40,
                    "featured": False,
                    "source": "local",
                }
            )
        settings_browse_links_html = "".join(
            f'<a class="quick-link" data-icon="{html.escape(str(item["icon"]))}" data-label="{html.escape(str(item["label"]))}" href="{html.escape(str(item["url"]))}"{console_link_anchor_attrs(str(item["url"]))}>'
            f'{_render_name_cartouche(str(item["label"]), kind="name", tone=str(item["tone_group"]), group=str(item["tone_group"]))}</a>'
            for item in browse_targets
        )
        console_focus_sources = [
            {
                **item,
                "label": str(item.get("focus_label") or item["label"]),
            }
            for item in browse_targets
        ]
        for group in console_groups:
            console_focus_sources.extend(group["links"])
        console_focus_lanes = build_console_focus_lanes(
            console_focus_sources, current_agent_candidates
        )
        console_focus_item_count = sum(
            len(lane["items"]) for lane in console_focus_lanes
        )
        console_focus_summary = (
            f"{len(console_focus_lanes)} lanes · {console_focus_item_count} surfaces"
        )
        console_focus_html = (
            '<section id="console-focus-shell" class="console-focus-shell surface" aria-label="Priority surfaces">'
            f'<button id="console-focus-toggle" type="button" class="ghost console-focus-toggle" aria-expanded="false" title="{html.escape(console_focus_summary)}"><span class="console-focus-toggle-copy"><span class="console-focus-toggle-label">Switchboard</span><span class="console-focus-toggle-summary">{html.escape(console_focus_summary)}</span></span><span id="console-focus-caret" class="console-focus-caret">+</span></button>'
            '<div id="console-focus-panel" class="console-focus-panel" hidden><section class="console-focus" aria-label="Priority surfaces">'
            + "".join(
                (
                    f'<section class="focus-lane surface" data-lane="{html.escape(str(lane["slug"]))}">'
                    f'<header class="focus-lane-head"><span class="focus-lane-eyebrow">{html.escape(str(lane["eyebrow"]))}</span>'
                    f'<h2>{html.escape(str(lane["label"]))}</h2>'
                    f'<p>{html.escape(str(lane["description"]))}</p></header>'
                    '<div class="focus-lane-grid">'
                    + "".join(
                        f'<a class="focus-card" data-group="{html.escape(str(item["group_slug"]))}" data-tone="{html.escape(str(item["tone_group"]))}" data-lane="{html.escape(str(item["lane"]))}" href="{html.escape(str(item["url"]))}"{console_link_anchor_attrs(str(item["url"]))}>'
                        f'<span class="focus-card-top"><span class="focus-card-group">{html.escape(str(item.get("group") or lane["label"]))}</span><span class="focus-card-icon">{html.escape(str(item["icon"]))}</span></span>'
                        f'<span class="focus-card-title">{_render_name_cartouche(str(item["label"]), kind="bot", tone=str(item["tone_group"]), group=str(item["tone_group"]))}</span>'
                        f'<span class="focus-card-note">{html.escape(str(item["note"]))}</span>'
                        '<span class="focus-card-tail">Open</span></a>'
                        for item in lane["items"]
                    )
                    + "</div></section>"
                )
                for lane in console_focus_lanes
            )
            + "</section></div></section>"
            if console_focus_lanes
            else ""
        )
        token_suffix = (
            "?"
            + urlencode(
                {
                    key: value
                    for key, value in {
                        "token": local_token_value,
                        "route": route_preference if route_preference != "auto" else "",
                    }.items()
                    if value
                }
            )
            if TOKEN or route_preference != "auto"
            else ""
        )
        initial_snapshot_data = current_snapshot()
        initial_snapshot = script_json(initial_snapshot_data)
        initial_tone, initial_run_label = _snapshot_tone_label(initial_snapshot_data)
        initial_status_message = _initial_status_text(initial_snapshot_data)
        initial_chat_activity_text, initial_chat_activity_hidden = (
            _initial_chat_activity_text(initial_snapshot_data, active_profile_label)
        )
        initial_chat_session_text = _initial_chat_session_text(
            initial_snapshot_data, active_profile_label
        )
        initial_history_summary = _initial_history_summary(initial_snapshot_data)
        initial_context_meter = _initial_context_meter(initial_snapshot_data)
        initial_chat_summary_hidden = (
            initial_chat_activity_hidden and initial_context_meter["hidden"]
        )
        initial_last_updated = (
            f"updated {_format_ui_ts(initial_snapshot_data.get('updated_at'))}"
            if initial_snapshot_data.get("updated_at")
            else "waiting for first update"
        )
        initial_conversation_html = _initial_conversation_html(
            initial_snapshot_data,
            token=local_token_value,
            profile=active_profile,
            route=route_preference,
            prefix=path_prefix,
        )
        token_value = script_json(TOKEN)
        active_profile_name_json = script_json(active_profile)
        active_profile_label_json = script_json(active_profile_label)
        default_response_speed_json = script_json(DEFAULT_RESPONSE_SPEED)
        default_response_detail_json = script_json(DEFAULT_RESPONSE_DETAIL)
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{html.escape(CONSOLE_TAB_TITLE)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Poppins:wght@400;500;600;700&display=swap">
  {favicon_links_html(self.request_path_prefix())}
  <style>
    :root {{
{profile_vars_css(active_profile)}
{agent_theme_vars_css(AGENT_SLUG)}
{agent_texture_vars_css(AGENT_SLUG)}
      --font-ui: "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-ui-wide: "Bahnschrift", "IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-body: "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-reading: "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-brand: "IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-label: "IBM Plex Sans Condensed", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-mono: "SFMono-Regular", "JetBrains Mono", "IBM Plex Mono", Menlo, Consolas, "Liberation Mono", monospace;
      --type-brand-size: 1rem;
      --type-reading-size: 0.94rem;
      --brand-radius: 16px;
      --chrome-pill-radius: 999px;
      --body-overlay-opacity: 0.68;
      --body-edge-opacity: 0.82;
      --body-accent-angle: 90deg;
      --topbar-glint-opacity: 0.9;
      --topbar-edge-opacity: 1;
      --topbar-saturate: 128%;
      --topbar-blur: 16px;
{style_variant_vars_css(AGENT_SLUG)}
{agent_font_vars_css(AGENT_SLUG)}
      --group-norman: #5fd2c4;
      --group-personal: #d8b25b;
      --group-shared: #d78143;
      --group-work: #76a8ff;
      --group-private: #97afc1;
      --group-agents: #8eaed0;
      --flat-0: 0px;
      --flat-1: 1px;
    }}
    * {{
      box-sizing: border-box;
    }}
    html,
    body {{
      min-height: 100%;
    }}
    body {{
      margin: 0;
      min-height: 100dvh;
      background:
        linear-gradient(
          180deg,
          color-mix(in srgb, var(--body-start) 76%, black 24%) 0%,
          color-mix(in srgb, var(--body-mid) 84%, black 16%) 54%,
          color-mix(in srgb, var(--body-end) 74%, black 26%) 100%
        );
      color: var(--text);
      font-family: var(--font-ui);
      text-rendering: optimizeLegibility;
      font-feature-settings: "kern" 1, "liga" 1, "calt" 1;
      overscroll-behavior-y: auto;
      overflow: hidden;
    }}
    body::before,
    body::after {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 0;
    }}
    body::before {{
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent 14%, transparent 86%, rgba(0, 0, 0, 0.12)),
        linear-gradient(var(--body-accent-angle), color-mix(in srgb, var(--agent-accent) 16%, transparent), transparent 30%),
        repeating-linear-gradient(
          var(--texture-angle),
          color-mix(in srgb, var(--agent-accent-3) calc(var(--page-texture-opacity) * 100%), transparent) 0 1px,
          transparent 1px var(--texture-spacing)
        ),
        repeating-linear-gradient(
          var(--texture-cross-angle),
          color-mix(in srgb, var(--agent-accent-2) calc(var(--page-cross-texture-opacity) * 100%), transparent) 0 1px,
          transparent 1px var(--texture-cross-spacing)
        ),
        repeating-linear-gradient(
          180deg,
          color-mix(in srgb, var(--border) 28%, transparent) 0 1px,
          transparent 1px 26px
        );
      opacity: var(--body-overlay-opacity);
    }}
    body::after {{
      inset: 0;
      border-radius: 0;
      border: 0;
      border-top: 1px solid color-mix(in srgb, var(--border) 34%, transparent);
      border-bottom: 1px solid color-mix(in srgb, rgba(0, 0, 0, 0.44) 44%, transparent);
      opacity: var(--body-edge-opacity);
    }}
    body.system-open,
    body.settings-open,
    body.notices-open {{
      overflow: hidden;
    }}
    body.mobile-keyboard-open {{
      overscroll-behavior-y: contain;
    }}
    ::selection {{
      background: rgba(125, 211, 252, 0.26);
      color: #f8fbff;
    }}
    a {{
      color: var(--accent);
    }}
    button,
    a,
    textarea {{
      touch-action: manipulation;
      -webkit-tap-highlight-color: rgba(178, 92, 52, 0.12);
    }}
    .app-shell {{
      --composer-reserve: 0px;
      --viewport-height: 100dvh;
      --keyboard-inset: 0px;
      position: relative;
      z-index: 1;
      width: 100%;
      max-width: none;
      margin: 0;
      min-height: var(--viewport-height);
      height: var(--viewport-height);
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 0;
      overflow: hidden;
    }}
    .surface {{
      background: color-mix(in srgb, var(--surface) 96%, rgba(0, 0, 0, 0.1));
      border: 1px solid color-mix(in srgb, var(--border) 78%, transparent);
      border-radius: 0;
      box-shadow: none;
    }}
    body[data-finish="engraved"] .surface {{
      box-shadow:
        0 6px 16px rgba(12, 16, 22, 0.036),
        inset 0 1px 0 rgba(255, 255, 255, 0.028),
        inset 0 0 0 1px color-mix(in srgb, var(--agent-accent) 5%, transparent);
      background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.016), rgba(0, 0, 0, 0)),
        repeating-linear-gradient(
          135deg,
          transparent 0 10px,
          color-mix(in srgb, var(--agent-accent) 3%, transparent) 10px 11px
        );
    }}
    body[data-finish="etched"] .surface {{
      box-shadow:
        0 6px 16px rgba(12, 16, 22, 0.034),
        inset 0 1px 0 rgba(255, 255, 255, 0.022),
        inset 0 0 0 1px color-mix(in srgb, var(--agent-accent) 6%, transparent);
      background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.014), rgba(0, 0, 0, 0)),
        repeating-linear-gradient(
          180deg,
          transparent 0 14px,
          color-mix(in srgb, var(--border) 16%, transparent) 14px 15px
        );
    }}
    body[data-finish="glow"] .surface {{
      box-shadow:
        0 8px 22px rgba(12, 16, 22, 0.04),
        0 0 0 1px color-mix(in srgb, var(--agent-accent) 8%, transparent),
        0 0 18px color-mix(in srgb, var(--agent-accent) 6%, transparent),
        inset 0 1px 0 rgba(255, 255, 255, 0.024);
    }}
    .brand {{
      min-width: 0;
      position: relative;
      overflow: hidden;
      display: grid;
      gap: 3px;
      min-height: 42px;
      padding: 6px 10px 7px 8px;
      border-radius: var(--brand-radius);
      border: 1px solid color-mix(in srgb, var(--border) 34%, transparent);
      background:
        radial-gradient(circle at 0% 50%, color-mix(in srgb, var(--agent-accent) calc(var(--brand-wash-opacity) * 78%), transparent), transparent 46%),
        repeating-linear-gradient(
          var(--texture-angle),
          color-mix(in srgb, var(--agent-accent-3) calc(var(--chrome-detail-opacity) * 100%), transparent) 0 1px,
          transparent 1px var(--texture-spacing)
        ),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 88%, transparent), color-mix(in srgb, var(--surface-2) 72%, transparent));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 48%, transparent),
        inset 0 -1px 0 color-mix(in srgb, rgba(0, 0, 0, 0.16) 36%, transparent),
        0 7px 18px rgba(8, 12, 18, 0.07);
    }}
    .brand::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 8px;
      bottom: 8px;
      width: 3px;
      border-radius: 999px;
      background: linear-gradient(
        180deg,
        transparent,
        color-mix(in srgb, var(--agent-accent-3) 64%, transparent),
        transparent
      );
      opacity: 0.68;
      pointer-events: none;
    }}
    .brand::after {{
      content: "";
      position: absolute;
      inset: auto 10px 0;
      height: 1px;
      background: linear-gradient(
        90deg,
        transparent,
        color-mix(in srgb, var(--agent-accent) 32%, transparent),
        transparent
      );
      opacity: 0.58;
      pointer-events: none;
    }}
    .brand-line {{
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      min-width: 0;
    }}
    .brand h1 {{
      margin: 0;
      font-size: var(--type-brand-size);
      line-height: 1.04;
      letter-spacing: 0;
      font-weight: 720;
      font-family: var(--font-brand);
      color: color-mix(in srgb, var(--text) 92%, var(--agent-accent) 8%);
    }}
    body[data-finish="engraved"] .brand h1 {{
      text-shadow:
        0 1px 0 rgba(255, 255, 255, 0.04),
        0 -1px 0 rgba(0, 0, 0, 0.12);
    }}
    body[data-finish="etched"] .brand h1 {{
      letter-spacing: 0;
      text-shadow: 0 1px 0 rgba(255, 255, 255, 0.03);
    }}
    body[data-finish="glow"] .brand h1 {{
      text-shadow:
        0 0 18px color-mix(in srgb, var(--agent-accent) 24%, transparent),
        0 1px 0 rgba(255, 255, 255, 0.04);
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      position: sticky;
      top: 0;
      z-index: 20;
      isolation: isolate;
      transition: padding 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease, background 0.16s ease;
    }}
    body.topbar-menu-open .topbar {{
      z-index: 32;
    }}
    .topbar.surface {{
      background:
        repeating-linear-gradient(
          var(--texture-cross-angle),
          color-mix(in srgb, var(--agent-accent-3) calc(var(--chrome-detail-opacity) * 100%), transparent) 0 1px,
          transparent 1px var(--texture-cross-spacing)
        ),
        linear-gradient(90deg, color-mix(in srgb, var(--agent-accent) 7%, transparent), transparent 26%, transparent 74%, color-mix(in srgb, var(--agent-accent-2) 5%, transparent)),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 99%, rgba(255, 255, 255, 0.035)), color-mix(in srgb, var(--surface) 95%, rgba(0, 0, 0, 0.12)));
      border-left: 0;
      border-right: 0;
      border-top: 0;
      border-bottom-color: color-mix(in srgb, var(--border) 58%, transparent);
      box-shadow:
        0 9px 24px rgba(8, 12, 18, 0.065),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 34%, transparent),
        inset 0 -1px 0 color-mix(in srgb, rgba(0, 0, 0, 0.2) 36%, transparent);
      backdrop-filter: saturate(var(--topbar-saturate)) blur(var(--topbar-blur));
    }}
    .topbar.surface::before {{
      content: "";
      position: absolute;
      inset: 0 14px auto;
      height: 2px;
      background:
        linear-gradient(90deg, transparent, color-mix(in srgb, var(--agent-accent-3) 28%, transparent), transparent),
        linear-gradient(90deg, transparent, color-mix(in srgb, rgba(255, 255, 255, 0.12) 74%, transparent), transparent);
      pointer-events: none;
      opacity: var(--topbar-glint-opacity);
    }}
    .topbar.surface::after {{
      content: "";
      position: absolute;
      inset: auto 18px 0;
      height: 1px;
      background:
        linear-gradient(90deg, transparent, color-mix(in srgb, var(--agent-accent) 26%, transparent), transparent),
        linear-gradient(90deg, transparent, color-mix(in srgb, var(--border-strong) 56%, transparent), transparent);
      pointer-events: none;
      opacity: var(--topbar-edge-opacity);
    }}
    body.quiet-status .topbar.surface {{
      background: color-mix(in srgb, var(--surface) 92%, rgba(0, 0, 0, 0.08));
      border-bottom-color: color-mix(in srgb, var(--border) 34%, transparent);
      box-shadow: inset 0 -1px 0 color-mix(in srgb, rgba(0, 0, 0, 0.16) 26%, transparent);
    }}
    .topbar-actions {{
      position: relative;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 5px;
      flex: 0 0 auto;
      min-width: 0;
      align-self: center;
      margin-top: 0;
      transition: opacity 0.14s ease;
    }}
    .topbar-actions .utility-button,
    .topbar-actions .button-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 30px;
      padding: 4px 10px;
      box-sizing: border-box;
      line-height: 1;
      border-radius: var(--chrome-pill-radius);
      border-color: color-mix(in srgb, var(--border) 70%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 86%, transparent), color-mix(in srgb, var(--surface-2) 76%, transparent));
      color: color-mix(in srgb, var(--text) 88%, var(--muted));
      font-size: 0.66rem;
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 46%, transparent),
        0 1px 0 rgba(8, 12, 18, 0.08);
      transition:
        background 0.12s ease,
        border-color 0.12s ease,
        color 0.12s ease,
        box-shadow 0.12s ease,
        transform 0.12s ease;
    }}
    .topbar-actions .utility-button:hover,
    .topbar-actions .button-link:hover,
    .topbar-actions .utility-button:focus-visible,
    .topbar-actions .button-link:focus-visible {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 24%, var(--border-strong));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, transparent), color-mix(in srgb, var(--surface-3) 78%, transparent));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 56%, transparent),
        0 6px 16px rgba(8, 12, 18, 0.10);
      transform: translateY(-1px);
    }}
    body.quiet-status .topbar-actions {{
      opacity: 0.92;
    }}
    .topbar-version {{
      color: color-mix(in srgb, var(--muted) 72%, var(--text));
      font: 600 0.56rem/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      letter-spacing: 0;
      opacity: 0.74;
      padding-top: 0.12rem;
      white-space: nowrap;
    }}
    .status-action-button {{
      min-height: 20px;
      padding: 2px 7px;
      border-radius: var(--chrome-pill-radius);
      border: 1px solid color-mix(in srgb, var(--border) 64%, transparent);
      background: color-mix(in srgb, var(--surface-2) 78%, transparent);
      color: color-mix(in srgb, var(--text) 76%, var(--muted));
      font-size: 0.56rem;
      line-height: 1;
    }}
    .status-action-button[data-tone="error"],
    .status-action-button[data-tone="blocked"],
    .status-action-button[data-tone="wedged"] {{
      border-color: color-mix(in srgb, var(--danger) 44%, var(--border));
      color: color-mix(in srgb, var(--danger) 68%, var(--text));
      background: color-mix(in srgb, var(--danger) 10%, var(--surface));
    }}
    .status-action-button[data-tone="degraded"] {{
      border-color: color-mix(in srgb, var(--warning) 44%, var(--border));
      color: color-mix(in srgb, var(--warning) 72%, var(--text));
      background: color-mix(in srgb, var(--warning) 10%, var(--surface));
    }}
    .status-action-button[data-tone="working"] {{
      border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
      color: color-mix(in srgb, var(--accent) 72%, var(--text));
    }}
    .status-action-panel {{
      position: absolute;
      left: 0;
      top: calc(100% + 8px);
      width: min(30rem, calc(100vw - 24px));
      z-index: 38;
      display: grid;
      gap: 8px;
      padding: 10px;
      border-radius: 10px;
      border-color: color-mix(in srgb, var(--border) 74%, transparent);
      box-shadow: 0 18px 44px rgba(8, 12, 18, 0.22);
    }}
    .status-action-panel[hidden] {{
      display: none;
    }}
    .status-action-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-width: 0;
    }}
    .status-action-title {{
      min-width: 0;
      color: var(--text);
      font-size: 0.74rem;
      line-height: 1.16;
    }}
    .status-action-state {{
      flex: 0 0 auto;
      border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
      border-radius: var(--chrome-pill-radius);
      padding: 2px 7px;
      color: var(--muted);
      font: 650 0.57rem/1 var(--font-mono);
      text-transform: uppercase;
    }}
    .status-action-summary {{
      margin: 0;
      color: color-mix(in srgb, var(--text) 78%, var(--muted));
      font-size: 0.68rem;
      line-height: 1.38;
    }}
    .status-action-meta {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 5px;
    }}
    .status-action-meta span {{
      min-width: 0;
      border: 1px solid color-mix(in srgb, var(--border) 46%, transparent);
      border-radius: 7px;
      padding: 5px 7px;
      color: var(--muted);
      background: color-mix(in srgb, var(--surface-2) 58%, transparent);
      font-size: 0.58rem;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }}
    .status-action-controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .status-action-controls .utility-button {{
      min-height: 26px;
      padding: 3px 8px;
      font-size: 0.63rem;
    }}
    .topbar-menu-button {{
      position: relative;
      min-width: 32px;
      min-height: 26px;
      padding: 2px 8px;
      display: inline-flex;
      align-items: center;
      gap: 0.42rem;
      font-size: 0.68rem;
    }}
    .switcher-toggle-button {{
      min-width: 32px;
      min-height: 26px;
      padding: 2px 8px;
      display: inline-flex;
      align-items: center;
      gap: 0.42rem;
      font-size: 0.68rem;
    }}
    .switcher-toggle-label {{
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      line-height: 1;
      white-space: nowrap;
    }}
    .topbar-menu-button.has-unread {{
      border-color: color-mix(in srgb, var(--accent) 26%, var(--border));
      background: color-mix(in srgb, var(--accent) 7%, var(--surface));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 10%, transparent);
    }}
    .topbar-menu-button-label {{
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      line-height: 1;
      white-space: nowrap;
    }}
    .topbar-menu-count,
    .notice-count {{
      position: absolute;
      top: -4px;
      right: -2px;
      min-width: 15px;
      height: 15px;
      padding: 0 4px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--danger) 88%, var(--surface-3));
      color: #fff;
      font-size: 0.58rem;
      line-height: 15px;
      text-align: center;
      box-shadow: 0 3px 8px rgba(0, 0, 0, 0.18);
    }}
    .topbar-menu-backdrop {{
      position: fixed;
      inset: 0;
      background: transparent;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease;
      z-index: 24;
    }}
    body.topbar-menu-open .topbar-menu-backdrop {{
      opacity: 1;
      pointer-events: auto;
    }}
    .topbar-menu {{
      position: fixed;
      top: var(--topbar-menu-top, 54px);
      right: var(--topbar-menu-right, 12px);
      width: min(320px, calc(100vw - 18px));
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      opacity: 0;
      pointer-events: none;
      transform: translateY(-6px) scale(0.985);
      transform-origin: top right;
      transition: opacity 0.18s ease, transform 0.18s ease;
      z-index: 33;
    }}
    body.topbar-menu-open .topbar-menu {{
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0) scale(1);
    }}
    .topbar-menu-meta {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .topbar-menu-status {{
      color: var(--muted);
      font-size: 0.64rem;
      white-space: nowrap;
    }}
    .topbar-menu-links {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
    }}
    .topbar-menu-links .utility-button,
    .topbar-menu-links .button-link {{
      min-height: 31px;
      justify-content: flex-start;
      padding: 5px 10px;
      font-size: 0.72rem;
    }}
    .topbar-menu-links .utility-button {{
      min-width: 0;
      display: inline-flex;
      align-items: center;
      gap: 0.38rem;
    }}
    .topbar-menu-links .button-link {{
      text-decoration: none;
    }}
    .topbar-menu-links .utility-button:hover,
    .topbar-menu-links .button-link:hover,
    .topbar-menu-links .utility-button:focus-visible,
    .topbar-menu-links .button-link:focus-visible {{
      background: color-mix(in srgb, var(--agent-accent) 14%, var(--surface-2));
      border-color: color-mix(in srgb, var(--agent-accent) 42%, var(--border-strong));
      color: color-mix(in srgb, var(--text) 88%, var(--agent-accent) 12%);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--agent-accent) 18%, transparent);
      transform: translateY(-1px);
      outline: none;
    }}
    .topbar-menu-links .utility-button:active,
    .topbar-menu-links .button-link:active {{
      transform: translateY(0);
      background: color-mix(in srgb, var(--agent-accent) 20%, var(--surface-3));
      border-color: color-mix(in srgb, var(--agent-accent) 52%, var(--border-strong));
    }}
    .topbar-menu-links .utility-button:disabled,
    .topbar-menu-links .button-link[aria-disabled="true"] {{
      opacity: 0.46;
      cursor: not-allowed;
      pointer-events: none;
      box-shadow: none;
      transform: none;
    }}
    .topbar-menu-shortcuts {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding-top: 2px;
    }}
    .shortcut-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 54%, transparent);
      background: color-mix(in srgb, var(--surface-2) 42%, transparent);
      color: var(--muted);
      font-size: 0.62rem;
      letter-spacing: 0.03em;
      white-space: nowrap;
    }}
    .shortcut-chip kbd {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 16px;
      padding: 0 5px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border-strong) 62%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, transparent), color-mix(in srgb, var(--surface-2) 84%, transparent));
      color: var(--text);
      font-family: var(--font-mono);
      font-size: 0.58rem;
      font-weight: 600;
      line-height: 1;
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 42%, transparent),
        0 1px 0 rgba(8, 12, 18, 0.08);
    }}
    .shortcut-chip span:last-child {{
      color: var(--text);
      opacity: 0.88;
    }}
    .topbar-actions .utility-button[data-icon]::before,
    .button-link[data-icon]::before,
    .console-group-pill[data-icon]::before,
    .quick-link[data-icon]::before,
    .profile-chip[data-icon]::before,
    .suggestion-chip[data-icon]::before,
    .history-toggle[data-icon]::before,
    .jump-latest[data-icon]::before,
    .composer-send[data-icon]::before,
    .composer-inline-action[data-icon]::before,
    .copy-button[data-icon]::before,
    .relay-target[data-icon]::before,
    .link-copy-button[data-icon]::before,
    .code-copy-button[data-icon]::before,
    .attachment-remove[data-icon]::before,
    .settings-label[data-icon]::before,
    .response-rail-name[data-icon]::before,
    .meta-chip[data-icon]::before {{
      content: attr(data-icon);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 0.82rem;
      width: auto;
      height: 0.82rem;
      padding: 0 0.08rem;
      border-radius: 999px;
      background: transparent;
      color: currentColor;
      font-size: 0.6rem;
      line-height: 1;
      flex: 0 0 auto;
      opacity: 0.72;
      font-variant-numeric: tabular-nums;
    }}
    .console-group-pill[data-icon]::before,
    .quick-link[data-icon]::before,
    .profile-chip[data-icon]::before,
    .message-role::before {{
      min-width: 1rem;
      padding: 0 0.18rem;
      background: color-mix(in srgb, currentColor 11%, transparent);
      border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.54rem;
      font-weight: 700;
      letter-spacing: 0.03em;
      opacity: 0.92;
    }}
    .notice-toggle {{
      position: relative;
      min-width: 0;
    }}
    .notice-toggle.has-unread {{
      border-color: color-mix(in srgb, var(--accent) 28%, var(--border));
      background: color-mix(in srgb, var(--accent) 7%, var(--surface));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 12%, transparent);
    }}
    .notice-toggle-label {{
      display: inline-flex;
      align-items: center;
      gap: 0.24rem;
      line-height: 1;
    }}
    .notice-toggle-label span:first-child {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1rem;
      height: 1rem;
      border-radius: 999px;
      background: transparent;
      font-size: 0.6rem;
    }}
    .status-copy {{
      display: none;
      color: var(--muted);
      margin: 1px 0 0 1px;
      font-size: 0.61rem;
      line-height: 1.17;
      max-width: 28rem;
      display: -webkit-box;
      -webkit-line-clamp: 1;
      -webkit-box-orient: vertical;
      overflow: hidden;
      opacity: 0.92;
      transition: opacity 0.16s ease, max-height 0.16s ease, margin 0.16s ease;
      max-height: 2.2em;
    }}
    body.quiet-status .status-copy {{
      opacity: 0;
      max-height: 0;
      margin-top: 0;
    }}
    body.chat-scrolled .status-copy {{
      opacity: 0;
      max-height: 0;
      margin-top: 0;
    }}
    .version-chip {{
      display: inline-flex;
      align-items: center;
      min-height: 17px;
      padding: 1px 4px;
      border-radius: 0;
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      background: transparent;
      color: var(--muted);
      font-size: 0.54rem;
      letter-spacing: 0.02em;
      white-space: nowrap;
    }}
    .console-focus {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 7px;
      padding: 1px 0;
      min-width: 0;
    }}
    .console-focus-shell {{
      position: relative;
      display: flex;
      flex-direction: column;
      gap: 0;
      align-self: flex-end;
      width: fit-content;
      max-width: 100%;
      min-width: 0;
      overflow: visible;
      border: 0;
      background: transparent;
      box-shadow: none;
    }}
    .console-focus-toggle {{
      width: auto;
      min-height: 22px;
      padding: 2px 6px;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 6px;
      background: transparent;
      border: 0;
      text-align: left;
    }}
    .console-focus-toggle-copy {{
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }}
    .console-focus-toggle-label {{
      color: var(--text);
      font-size: 0.61rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .console-focus-toggle-summary {{
      display: none;
    }}
    .console-focus-caret {{
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1;
      flex: 0 0 auto;
    }}
    .console-focus-shell.expanded .console-focus-caret {{
      color: var(--text);
    }}
    .console-focus-panel {{
      position: absolute;
      top: calc(100% + 4px);
      right: 0;
      left: auto;
      width: min(920px, calc(100vw - 16px));
      z-index: 26;
      padding: 7px;
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      background: color-mix(in srgb, var(--surface) 98%, rgba(0, 0, 0, 0.16));
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22);
    }}
    .focus-lane {{
      display: flex;
      flex-direction: column;
      gap: 7px;
      min-width: 0;
      padding: 8px 9px 9px;
      border-color: color-mix(in srgb, var(--lane-tone, var(--agent-accent)) 36%, var(--border));
      background:
        repeating-linear-gradient(
          var(--texture-angle),
          color-mix(in srgb, var(--agent-accent-3) calc(var(--focus-detail-opacity) * 100%), transparent) 0 1px,
          transparent 1px var(--texture-spacing)
        ),
        linear-gradient(180deg, color-mix(in srgb, var(--lane-tone, var(--agent-accent)) 6%, transparent), transparent 34%),
        color-mix(in srgb, var(--surface) 98%, rgba(0, 0, 0, 0.12));
    }}
    .focus-lane[data-lane="make"] {{
      --lane-tone: var(--group-norman);
    }}
    .focus-lane[data-lane="explore"] {{
      --lane-tone: var(--group-personal);
    }}
    .focus-lane[data-lane="review"] {{
      --lane-tone: var(--group-shared);
    }}
    .focus-lane[data-lane="operate"] {{
      --lane-tone: var(--group-work);
    }}
    .focus-lane-head {{
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }}
    .focus-lane-eyebrow {{
      color: color-mix(in srgb, var(--lane-tone, var(--agent-accent)) 76%, var(--text));
      font-size: 0.56rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .focus-lane h2 {{
      margin: 0;
      font-size: 0.82rem;
      line-height: 1.08;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }}
    .focus-lane p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.66rem;
      line-height: 1.36;
    }}
    .focus-lane-grid {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }}
    .focus-card {{
      --surface-group-tone: var(--group-agents);
      display: flex;
      flex-direction: column;
      gap: 5px;
      min-height: 84px;
      padding: 10px;
      border: 1px solid color-mix(in srgb, var(--surface-group-tone) 34%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface-group-tone) 8%, transparent), transparent 44%),
        color-mix(in srgb, var(--surface-2) 58%, rgba(0, 0, 0, 0.18));
      color: var(--text);
      text-decoration: none;
      transition: transform 0.12s ease, border-color 0.12s ease, background 0.12s ease;
    }}
    .focus-card-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
      color: color-mix(in srgb, var(--surface-group-tone) 74%, var(--text));
      font-size: 0.57rem;
      font-weight: 700;
      letter-spacing: 0.11em;
      text-transform: uppercase;
    }}
    .focus-card-group {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .focus-card-icon {{
      color: var(--muted);
      font-size: 0.72rem;
      line-height: 1;
      flex: 0 0 auto;
    }}
    .focus-card-title {{
      font-size: 0.92rem;
      line-height: 1.1;
      font-weight: 650;
      letter-spacing: 0;
    }}
    .focus-card-note {{
      color: var(--muted);
      font-size: 0.69rem;
      line-height: 1.36;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .focus-card-tail {{
      margin-top: auto;
      color: color-mix(in srgb, var(--surface-group-tone) 68%, var(--text));
      font-size: 0.58rem;
      font-weight: 700;
      letter-spacing: 0.11em;
      text-transform: uppercase;
    }}
    .focus-card:hover,
    .focus-card:focus-visible {{
      transform: translate(-1px, -1px);
      border-color: color-mix(in srgb, var(--surface-group-tone) 54%, var(--border-strong));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface-group-tone) 12%, transparent), transparent 44%),
        color-mix(in srgb, var(--surface-3) 68%, rgba(0, 0, 0, 0.18));
      outline: none;
    }}
    .console-nav {{
      display: flex;
      flex-direction: column;
      gap: 3px;
      align-items: stretch;
      padding: 0;
      border-radius: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
      max-width: 100%;
      transition: opacity 0.16s ease, background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease, padding 0.16s ease;
    }}
    .console-nav-shell {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 6px;
      min-width: 0;
      padding: 1px 0 2px;
    }}
    .console-nav-groups,
    .console-nav-panel {{
      display: flex;
      align-items: center;
      gap: 5px;
      overflow-x: auto;
      scroll-snap-type: x proximity;
      scrollbar-width: none;
      -webkit-overflow-scrolling: touch;
      min-width: 0;
      flex-wrap: wrap;
    }}
    .console-nav-groups::-webkit-scrollbar,
    .console-nav-panel::-webkit-scrollbar {{
      display: none;
    }}
    .console-nav-panels {{
      min-width: 0;
    }}
    .console-nav-panels:not(:empty) {{
      padding-top: 2px;
      border-top: 1px solid color-mix(in srgb, var(--border) 38%, transparent);
    }}
    .console-nav-panel[hidden] {{
      display: none;
    }}
    .console-group-pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.44rem;
      scroll-snap-align: start;
      min-height: 28px;
      padding: 3px 11px;
      border-radius: 8px;
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      background: color-mix(in srgb, var(--surface-2) 62%, transparent);
      color: color-mix(in srgb, var(--muted) 72%, var(--text));
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.01em;
      white-space: nowrap;
      opacity: 0.94;
      cursor: pointer;
      transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease, transform 0.14s ease;
    }}
    .console-group-name {{
      line-height: 1;
    }}
    .console-group-pill:hover,
    .console-group-pill:focus-visible {{
      border-color: color-mix(in srgb, var(--agent-accent) 24%, var(--border-strong));
      color: var(--text);
    }}
    .console-group-pill.active {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 30%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 10%, var(--surface-3));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--agent-accent) 8%, transparent);
    }}
    .console-group-count {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 1rem;
      height: 1rem;
      padding: 0 0.26rem;
      border-radius: 999px;
      background: color-mix(in srgb, currentColor 12%, transparent);
      color: color-mix(in srgb, currentColor 86%, var(--text));
      font-size: 0.58rem;
      font-weight: 600;
      line-height: 1;
      opacity: 0.74;
      font-variant-numeric: tabular-nums;
    }}
    .console-group-pill[data-group="norman"] {{
      color: color-mix(in srgb, var(--agent-accent) 64%, var(--text));
      border-color: color-mix(in srgb, var(--agent-accent) 32%, var(--border));
      background: color-mix(in srgb, var(--agent-accent) 10%, var(--surface-2));
    }}
    .console-group-pill[data-group="personal"] {{
      color: color-mix(in srgb, var(--agent-accent-2) 62%, var(--text));
      border-color: color-mix(in srgb, var(--agent-accent-2) 32%, var(--border));
      background: color-mix(in srgb, var(--agent-accent-2) 10%, var(--surface-2));
    }}
    .console-group-pill[data-group="work"] {{
      color: color-mix(in srgb, var(--warn) 70%, var(--text));
      border-color: color-mix(in srgb, var(--warn) 34%, var(--border));
      background: color-mix(in srgb, var(--warn) 10%, var(--surface-2));
    }}
    .console-group-pill[data-group="shared"] {{
      color: color-mix(in srgb, var(--text) 74%, var(--accent));
      border-color: color-mix(in srgb, var(--accent) 24%, var(--border));
      background: color-mix(in srgb, var(--accent) 9%, var(--surface-2));
    }}
    body.quiet-status .console-nav {{
      opacity: 0.78;
    }}
    body.quiet-status .console-group-pill {{
      background: transparent;
      border-color: transparent;
      color: color-mix(in srgb, var(--muted) 76%, var(--text));
      box-shadow: none;
    }}
    body.quiet-status .console-group-pill.active {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 18%, transparent);
      background: color-mix(in srgb, var(--agent-accent) 6%, transparent);
    }}
    body.quiet-status .console-nav .quick-link {{
      background: transparent;
      border-color: transparent;
      color: color-mix(in srgb, var(--muted) 76%, var(--text));
    }}
    body.quiet-status .console-nav .quick-link:hover,
    body.quiet-status .console-nav .quick-link:focus-visible {{
      background: color-mix(in srgb, var(--agent-accent) 8%, var(--surface-3));
      border-color: color-mix(in srgb, var(--agent-accent) 20%, var(--border-strong));
      color: var(--text);
    }}
    .console-nav-panel {{
      padding: 1px 0 0;
    }}
    .console-nav-panel.solo {{
      display: none !important;
    }}
    body.chat-scrolled .topbar {{
      padding-top: 6px;
      padding-bottom: 5px;
    }}
    body.chat-scrolled .brand {{
      padding: 2px 5px 3px 1px;
      border-color: transparent;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 38%, transparent), color-mix(in srgb, var(--surface-2) 18%, transparent));
      box-shadow: none;
    }}
    body.chat-scrolled .brand h1 {{
      font-size: 0.95rem;
      letter-spacing: 0;
    }}
    body.chat-scrolled .pill {{
      padding: 2px 6px;
      font-size: 0.64rem;
    }}
    body.chat-scrolled .pill::before {{
      width: 0.58rem;
      height: 0.58rem;
    }}
    body.chat-scrolled .console-nav {{
      opacity: 0.7;
    }}
    body.chat-scrolled .prime-home-button,
    body.chat-scrolled .directory-home-button {{
      opacity: 0;
      max-width: 0;
      min-width: 0;
      margin: 0;
      padding-left: 0;
      padding-right: 0;
      border-color: transparent;
      pointer-events: none;
      overflow: hidden;
    }}
    body.chat-scrolled .topbar-actions {{
      gap: 2px;
    }}
    body.chat-scrolled .switcher-toggle-button,
    body.chat-scrolled .topbar-menu-button {{
      min-height: 26px;
      padding: 2px 8px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      border-radius: 999px;
      padding: 3px 7px;
      font-size: 0.71rem;
      font-weight: 700;
      border: 1px solid transparent;
      white-space: nowrap;
    }}
    .pill::before {{
      content: "";
      width: 0.7rem;
      height: 0.7rem;
      border-radius: 999px;
      flex: 0 0 auto;
      background: currentColor;
      opacity: 0.9;
    }}
    .pill.idle {{
      background: var(--surface-2);
      color: var(--muted);
      border-color: var(--border);
    }}
    .pill.running {{
      background: var(--surface-2);
      color: var(--warn);
      border-color: var(--border);
    }}
    .pill.ok {{
      background: var(--surface-2);
      color: var(--agent-accent-2);
      border-color: var(--border);
    }}
    .pill.error {{
      background: var(--surface-2);
      color: var(--danger);
      border-color: var(--border);
    }}
    .pill.running::before,
    button.primary.pending::before {{
      content: "";
      width: 0.72rem;
      height: 0.72rem;
      border-radius: 999px;
      border: 2px solid currentColor;
      border-right-color: transparent;
      background: transparent;
      display: inline-block;
      vertical-align: -0.1rem;
      animation: spin 0.8s linear infinite;
    }}
    .pill.running::before {{
      margin-right: 2px;
    }}
    button,
    .button-link {{
      appearance: none;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface-2) 58%, transparent);
      color: var(--text);
      border-radius: 6px;
      padding: 5px 9px;
      font: inherit;
      font-weight: 560;
      cursor: pointer;
      min-height: 30px;
      transition:
        background 0.12s ease,
        border-color 0.12s ease,
        color 0.12s ease,
        box-shadow 0.12s ease;
    }}
    .button-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-decoration: none;
      white-space: nowrap;
    }}
    button.primary {{
      background: color-mix(in srgb, var(--agent-accent) 9%, var(--surface-2));
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 18%, var(--border-strong));
    }}
    button:hover,
    .button-link:hover {{
      background: color-mix(in srgb, var(--surface-3) 68%, transparent);
      border-color: var(--border-strong);
      box-shadow: none;
    }}
    button.primary.pending {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .ghost {{
      background: transparent;
    }}
    .visually-hidden {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    button.warn {{
      color: var(--warn);
    }}
    button.danger {{
      color: var(--danger);
    }}
    button:disabled {{
      opacity: 0.6;
      cursor: wait;
    }}
    .hint {{
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .workspace {{
      flex: 1;
      min-height: 0;
      display: grid;
      gap: 1px;
      position: relative;
      padding: 0 10px 10px;
      background:
        linear-gradient(
          180deg,
          color-mix(in srgb, var(--surface) 16%, transparent) 0%,
          transparent 18%,
          transparent 100%
        );
      box-shadow: inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.03) 22%, transparent);
      overflow-x: hidden;
      overflow-y: auto;
      scrollbar-gutter: auto;
      scrollbar-width: thin;
      scrollbar-color: color-mix(in srgb, var(--agent-accent) 24%, var(--border-strong)) transparent;
      -webkit-overflow-scrolling: touch;
      overscroll-behavior-y: contain;
      scroll-padding-bottom: calc(var(--composer-reserve) + 92px + env(safe-area-inset-bottom));
    }}
    .workspace::-webkit-scrollbar {{
      width: 8px;
    }}
    .workspace::-webkit-scrollbar-track {{
      background: transparent;
    }}
    .workspace::-webkit-scrollbar-thumb {{
      border-radius: 999px;
      border: 2px solid transparent;
      background-clip: padding-box;
      background: color-mix(in srgb, var(--agent-accent) 22%, var(--border-strong));
      min-height: 28px;
    }}
    .workspace::-webkit-scrollbar-thumb:hover {{
      background: color-mix(in srgb, var(--agent-accent) 34%, var(--border-strong));
    }}
    .workspace::-webkit-scrollbar-corner {{
      background: transparent;
    }}
    .chat-shell {{
      --reading-lane: 760px;
      --conversation-lane: 860px;
      min-height: 0;
      min-height: 100%;
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 8px clamp(6px, 1vw, 14px) 10px;
      position: relative;
      overflow: visible;
      isolation: isolate;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 32%, transparent), transparent 14%),
        transparent;
      border: 0;
      box-shadow: none;
      backdrop-filter: none;
    }}
    .chat-shell::before {{
      content: none;
    }}
    .chat-main {{
      flex: 0 0 auto;
      min-height: 0;
      overflow: visible;
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding-right: 0;
      touch-action: pan-y;
      padding-bottom: calc(28px + var(--composer-reserve));
    }}
    .chat-main:focus {{
      outline: none;
    }}
    .chat-summary-bar {{
      position: relative;
      display: flex;
      gap: 4px 5px;
      flex-wrap: wrap;
      align-items: center;
      min-height: 30px;
      padding: 5px 7px 6px;
      border-radius: 16px;
      border: 1px solid color-mix(in srgb, var(--border) 24%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 72%, transparent), color-mix(in srgb, var(--surface-2) 54%, transparent));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 42%, transparent),
        0 4px 14px rgba(8, 12, 18, 0.04);
      overflow: hidden;
      transition: padding 0.16s ease, opacity 0.14s ease, max-height 0.16s ease, margin 0.14s ease, border-color 0.14s ease, background 0.14s ease;
    }}
    .chat-summary-bar::before {{
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 48%;
      border-radius: inherit;
      background: linear-gradient(180deg, color-mix(in srgb, rgba(255, 255, 255, 0.05) 54%, transparent), transparent 82%);
      pointer-events: none;
      opacity: 0.86;
    }}
    #chat-session-chip,
    #route-chip {{
      display: none;
    }}
    body.quiet-status .chat-summary-bar {{
      opacity: 0.94;
      padding-bottom: 6px;
      border-color: color-mix(in srgb, var(--border) 16%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 52%, transparent), color-mix(in srgb, var(--surface-2) 32%, transparent));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.03) 36%, transparent),
        0 4px 14px rgba(8, 12, 18, 0.03);
    }}
    body.chat-scrolled .chat-summary-bar {{
      gap: 3px 4px;
      min-height: 24px;
      padding: 2px 4px 3px;
      border-color: transparent;
      background: transparent;
      box-shadow: none;
    }}
    body.chat-scrolled .chat-summary-bar::before {{
      opacity: 0;
    }}
    body.quiet-status #route-chip {{
      display: none;
    }}
    body.chat-scrolled .meta-chip {{
      min-height: 16px;
      padding: 0 2px;
      border-color: transparent;
      background: transparent;
      box-shadow: none;
    }}
    body.chat-scrolled #context-meter-value,
    body.chat-scrolled #history-summary,
    body.chat-scrolled #last-updated-head {{
      display: none;
    }}
    body.chat-scrolled .context-meter-track {{
      width: 22px;
      flex-basis: 22px;
    }}
    .notice-rail {{
      display: none;
      flex-wrap: wrap;
      gap: 5px;
      overflow-x: auto;
      padding: 0 0 3px;
      scrollbar-width: none;
      transition: padding 0.16s ease, opacity 0.14s ease, max-height 0.16s ease, margin 0.14s ease;
    }}
    .notice-rail::-webkit-scrollbar {{
      display: none;
    }}
    .notice-rail.visible {{
      display: flex;
    }}
    .notice-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      scroll-snap-align: start;
      min-height: 24px;
      max-width: 100%;
      padding: 4px 10px 4px 8px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, currentColor 6%, transparent), transparent 58%),
        color-mix(in srgb, var(--surface-2) 58%, transparent);
      color: var(--muted);
      font-size: 0.68rem;
      line-height: 1.2;
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 36%, transparent),
        0 1px 0 rgba(8, 12, 18, 0.05);
      backdrop-filter: blur(10px);
    }}
    .notice-chip-body {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      flex: 1 1 auto;
    }}
    .notice-chip.has-actions {{
      padding-right: 6px;
    }}
    .notice-chip-actions {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-left: 2px;
      flex: 0 0 auto;
    }}
    .notice-chip-action {{
      min-height: 21px;
      padding: 1px 7px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, currentColor 26%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 92%, transparent), color-mix(in srgb, var(--surface-2) 78%, transparent));
      color: inherit;
      font-size: 0.6rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .notice-chip-action:hover {{
      color: var(--text);
      border-color: color-mix(in srgb, currentColor 42%, var(--border-strong));
      background: color-mix(in srgb, var(--surface) 92%, transparent);
    }}
    .notice-chip::before {{
      content: attr(data-icon);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1.05rem;
      height: 1.05rem;
      border-radius: 999px;
      background: color-mix(in srgb, currentColor 14%, transparent);
      color: currentColor;
      font-size: 0.62rem;
      font-weight: 800;
      flex: 0 0 auto;
      box-shadow: inset 0 0 0 1px color-mix(in srgb, currentColor 16%, transparent);
    }}
    .notice-label {{
      color: var(--text);
      font-weight: 640;
      white-space: nowrap;
    }}
    .notice-copy {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .notice-copy:empty {{
      display: none;
    }}
    .notice-chip.alert {{
      color: var(--danger);
      border-color: color-mix(in srgb, var(--danger) 52%, var(--border));
      background: color-mix(in srgb, var(--danger) 10%, var(--surface-2));
    }}
    .notice-chip.queue {{
      color: var(--warn);
      border-color: color-mix(in srgb, var(--warn) 46%, var(--border));
      background: color-mix(in srgb, var(--warn) 10%, var(--surface-2));
    }}
    .notice-chip.console {{
      color: var(--accent-2);
      border-color: color-mix(in srgb, var(--accent-2) 46%, var(--border));
      background: color-mix(in srgb, var(--accent-2) 10%, var(--surface-2));
    }}
    .notice-chip.info {{
      color: var(--accent);
      border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
      background: color-mix(in srgb, var(--accent) 8%, var(--surface-2));
    }}
    .notice-chip[role="button"] {{
      cursor: pointer;
    }}
    .notice-chip-body[role="button"] {{
      cursor: pointer;
      border-radius: 999px;
    }}
    .notice-chip[role="button"]:hover,
    .notice-chip[role="button"]:focus-visible,
    .notice-chip:focus-within .notice-chip-body[role="button"] {{
      color: var(--text);
      border-color: color-mix(in srgb, currentColor 62%, var(--border-strong));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.08) 42%, transparent),
        0 8px 20px rgba(8, 12, 18, 0.12);
      outline: none;
    }}
    .notice-chip-body[role="button"]:focus-visible {{
      outline: none;
    }}
    .meta-block {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      min-width: 0;
    }}
    .meta-chip {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-height: 18px;
      padding: 1px 6px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-2) 42%, transparent);
      border: 1px solid color-mix(in srgb, var(--border) 34%, transparent);
      color: color-mix(in srgb, var(--muted) 82%, var(--text));
      font-size: 0.58rem;
      line-height: 1.1;
      box-shadow: inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.03) 34%, transparent);
    }}
    .meta-chip.strong {{
      background: color-mix(in srgb, var(--agent-accent) 6%, var(--surface-3));
      border-color: color-mix(in srgb, var(--agent-accent) 12%, transparent);
      color: var(--text);
    }}
    .meta-chip.subtle {{
      background: color-mix(in srgb, var(--surface-2) 26%, transparent);
      border-color: color-mix(in srgb, var(--border) 24%, transparent);
    }}
    .context-meter-chip {{
      --context-tone: color-mix(in srgb, var(--agent-accent) 72%, var(--text));
      gap: 5px;
      padding-right: 7px;
      color: color-mix(in srgb, var(--muted) 82%, var(--text));
      border-color: color-mix(in srgb, var(--border) 28%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 84%, transparent), color-mix(in srgb, var(--surface-2) 78%, transparent));
    }}
    .context-meter-chip[data-load-tone="ok"] {{
      --context-tone: color-mix(in srgb, var(--agent-accent) 76%, var(--text));
      border-color: color-mix(in srgb, var(--agent-accent) 16%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--agent-accent) 5%, var(--surface)), color-mix(in srgb, var(--surface-2) 82%, transparent));
    }}
    .context-meter-chip[data-load-tone="warn"] {{
      --context-tone: color-mix(in srgb, var(--warn) 88%, var(--text));
      border-color: color-mix(in srgb, var(--warn) 22%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--warn) 8%, var(--surface)), color-mix(in srgb, var(--surface-2) 84%, transparent));
    }}
    .context-meter-chip[data-load-tone="danger"] {{
      --context-tone: color-mix(in srgb, var(--danger) 88%, var(--text));
      border-color: color-mix(in srgb, var(--danger) 26%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--danger) 9%, var(--surface)), color-mix(in srgb, var(--surface-2) 84%, transparent));
    }}
    #context-meter-status {{
      color: var(--text);
      font-weight: 620;
    }}
    #context-meter-value {{
      color: inherit;
      opacity: 0.94;
      white-space: nowrap;
    }}
    .context-meter-track {{
      position: relative;
      flex: 0 0 30px;
      width: 30px;
      height: 4px;
      border-radius: 999px;
      overflow: hidden;
      background: color-mix(in srgb, var(--border) 34%, transparent);
      box-shadow: inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 40%, transparent);
    }}
    .context-meter-fill {{
      display: block;
      width: var(--context-load, 0%);
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, color-mix(in srgb, var(--context-tone) 68%, transparent), var(--context-tone));
    }}
    .context-save-button {{
      min-height: 18px;
      padding: 1px 7px;
      border-radius: 999px;
      font-size: 0.58rem;
      line-height: 1.1;
      border-color: color-mix(in srgb, var(--border) 34%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 88%, transparent), color-mix(in srgb, var(--surface-2) 78%, transparent));
      color: color-mix(in srgb, var(--text) 80%, var(--muted));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 40%, transparent),
        0 1px 0 rgba(8, 12, 18, 0.06);
    }}
    .context-save-button[data-save-tone="warn"] {{
      border-color: color-mix(in srgb, var(--warn) 22%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--warn) 10%, var(--surface)), color-mix(in srgb, var(--surface-2) 84%, transparent));
      color: color-mix(in srgb, var(--warn) 78%, var(--text));
    }}
    .context-save-button[data-save-tone="danger"] {{
      border-color: color-mix(in srgb, var(--danger) 24%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--danger) 12%, var(--surface)), color-mix(in srgb, var(--surface-2) 84%, transparent));
      color: color-mix(in srgb, var(--danger) 82%, var(--text));
    }}
    .kpi-strip {{
      display: flex;
      flex-wrap: nowrap;
      align-items: center;
      gap: 4px;
      overflow-x: auto;
      padding: 0 1px 0;
      scrollbar-width: none;
      -webkit-overflow-scrolling: touch;
    }}
    body.chat-scrolled .kpi-strip {{
      gap: 3px;
      padding-top: 0;
    }}
    .kpi-strip::-webkit-scrollbar {{
      display: none;
    }}
    .kpi-capsule {{
      min-width: max-content;
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 9px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 16%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 74%, transparent), color-mix(in srgb, var(--surface-2) 62%, transparent));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 42%, transparent),
        0 1px 0 rgba(8, 12, 18, 0.05);
      text-align: left;
      position: relative;
      overflow: hidden;
      transition: transform 0.14s ease, border-color 0.14s ease, box-shadow 0.14s ease, background 0.14s ease;
    }}
    .kpi-capsule::before {{
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 52%;
      border-radius: inherit;
      background: linear-gradient(180deg, color-mix(in srgb, rgba(255, 255, 255, 0.05) 54%, transparent), transparent 82%);
      pointer-events: none;
      opacity: 0.78;
    }}
    .kpi-capsule:hover,
    .kpi-capsule:focus-visible {{
      border-color: color-mix(in srgb, var(--agent-accent) 22%, var(--border-strong));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 44%, transparent),
        0 6px 18px rgba(8, 12, 18, 0.06);
      transform: translateY(-1px);
    }}
    body.chat-scrolled .kpi-capsule {{
      gap: 5px;
      padding: 3px 8px;
      border-color: color-mix(in srgb, var(--border) 10%, transparent);
      background: transparent;
      box-shadow: none;
    }}
    body.chat-scrolled .kpi-capsule::before {{
      opacity: 0;
    }}
    body.chat-scrolled .kpi-capsule:hover,
    body.chat-scrolled .kpi-capsule:focus-visible {{
      border-color: color-mix(in srgb, var(--agent-accent) 18%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 6%, transparent);
      box-shadow: none;
    }}
    .kpi-capsule[data-tone="ok"] {{
      border-color: color-mix(in srgb, var(--accent-2) 22%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--accent-2) 8%, var(--surface)), color-mix(in srgb, var(--surface-2) 84%, transparent));
    }}
    .kpi-capsule[data-tone="warn"] {{
      border-color: color-mix(in srgb, var(--warn) 24%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--warn) 10%, var(--surface)), color-mix(in srgb, var(--surface-2) 84%, transparent));
    }}
    .kpi-capsule[data-tone="alert"] {{
      border-color: color-mix(in srgb, var(--danger) 24%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--danger) 11%, var(--surface)), color-mix(in srgb, var(--surface-2) 84%, transparent));
    }}
    .kpi-capsule[data-tone="active"] {{
      border-color: color-mix(in srgb, var(--agent-accent) 24%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--agent-accent) 10%, var(--surface)), color-mix(in srgb, var(--surface-2) 84%, transparent));
    }}
    .kpi-capsule-label {{
      font-size: 0.48rem;
      line-height: 1.1;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      white-space: nowrap;
    }}
    .kpi-capsule-value {{
      font-size: 0.68rem;
      line-height: 1.1;
      font-weight: 680;
      color: var(--text);
      white-space: nowrap;
    }}
    .kpi-capsule-meta {{
      display: none;
    }}
    .system-runtime-metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .system-runtime-metric {{
      display: grid;
      gap: 3px;
      padding: 8px 10px;
      border-radius: 14px;
      border: 1px solid color-mix(in srgb, var(--border) 28%, transparent);
      background: color-mix(in srgb, var(--surface-2) 42%, transparent);
    }}
    .system-runtime-metric-label {{
      font-size: 0.6rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .system-runtime-metric-value {{
      font-size: 0.84rem;
      line-height: 1.2;
      font-weight: 650;
      color: var(--text);
    }}
    .system-runtime-metric-meta {{
      font-size: 0.68rem;
      line-height: 1.3;
      color: color-mix(in srgb, var(--muted) 84%, var(--text));
    }}
    #history-summary,
    #last-updated-head {{
      display: none;
    }}
    .conversation {{
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      flex: 0 0 auto;
      gap: 2px;
      padding: 2px 2px calc(88px + var(--composer-reserve));
      border-radius: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
      overflow: clip;
      min-height: clamp(180px, 40vh, 460px);
      touch-action: pan-y;
    }}
    .conversation::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(
          90deg,
          transparent 0%,
          transparent 8%,
          color-mix(in srgb, var(--surface) 22%, transparent) 18%,
          color-mix(in srgb, var(--surface) 18%, transparent) 52%,
          transparent 76%,
          transparent 100%
        );
      opacity: 0.82;
    }}
    .conversation::after {{
      content: none;
    }}
    .conversation > * {{
      position: relative;
      z-index: 1;
    }}
    body[data-finish="engraved"] .conversation {{
      box-shadow: none;
    }}
    body[data-finish="glow"] .conversation {{
      box-shadow: none;
    }}
    body[data-view-mode="stage"] .app-shell {{
      max-width: 1480px;
      gap: 4px;
      padding: 8px;
    }}
    body[data-view-mode="stage"] .console-nav {{
      display: none;
    }}
    body[data-view-mode="stage"] .topbar {{
      padding: 8px 10px;
      justify-content: center;
    }}
    body[data-view-mode="stage"] .topbar-actions,
    body[data-view-mode="stage"] .topbar-menu,
    body[data-view-mode="stage"] .topbar-menu-backdrop {{
      display: none;
    }}
    body[data-view-mode="stage"] .brand h1 {{
      font-size: 1.5rem;
    }}
    body[data-view-mode="stage"] .status-copy {{
      font-size: 0.78rem;
      -webkit-line-clamp: 2;
      max-width: 48rem;
    }}
    body[data-view-mode="stage"] .chat-shell {{
      padding: 10px;
    }}
    body[data-view-mode="stage"] .chat-summary-bar {{
      gap: 5px;
      padding-bottom: 4px;
      justify-content: center;
    }}
    body[data-view-mode="stage"] .meta-chip {{
      font-size: 0.76rem;
      min-height: 24px;
      padding: 4px 9px;
    }}
    body[data-view-mode="stage"] #route-chip,
    body[data-view-mode="stage"] #history-summary,
    body[data-view-mode="stage"] #last-updated-head,
    body[data-view-mode="stage"] .notice-rail,
    body[data-view-mode="stage"] .activity-strip,
    body[data-view-mode="stage"] .composer-tools-toggle,
    body[data-view-mode="stage"] .composer-toolbar-panels {{
      display: none !important;
    }}
    .history-toolbar {{
      display: none;
      justify-content: flex-end;
      align-items: center;
      gap: 5px;
      flex-wrap: wrap;
      padding: 0;
      transition: padding 0.16s ease, opacity 0.14s ease, max-height 0.16s ease, margin 0.14s ease;
    }}
    .history-inline-teaser {{
      align-self: center;
      min-height: 27px;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 48%, transparent);
      background: color-mix(in srgb, var(--surface-2) 54%, transparent);
      font-size: 0.71rem;
      color: var(--muted);
    }}
    .history-toolbar.visible {{
      display: flex;
    }}
    .history-note {{
      color: var(--muted);
      font-size: 0.58rem;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }}
    .history-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 0.32rem;
      min-height: 22px;
      padding: 2px 7px;
      font-size: 0.61rem;
    }}
    .profile-chip,
    .quick-link {{
      display: inline-flex;
      align-items: center;
      gap: 0.34rem;
      scroll-snap-align: start;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 7px;
      border: 1px solid color-mix(in srgb, var(--border) 48%, transparent);
      background: color-mix(in srgb, var(--surface-2) 32%, transparent);
      color: color-mix(in srgb, var(--muted) 72%, var(--text));
      text-decoration: none;
      font-size: 0.67rem;
      white-space: nowrap;
    }}
    .console-nav .quick-link {{
      background: color-mix(in srgb, var(--surface-2) 34%, transparent);
      border-color: color-mix(in srgb, var(--border) 32%, transparent);
      color: color-mix(in srgb, var(--muted) 78%, var(--text));
    }}
    .console-nav .quick-link[data-group="norman"] {{
      border-color: color-mix(in srgb, var(--agent-accent) 16%, transparent);
      background: color-mix(in srgb, var(--agent-accent) 5%, transparent);
    }}
    .console-nav .quick-link[data-group="personal"] {{
      border-color: color-mix(in srgb, var(--agent-accent-2) 16%, transparent);
      background: color-mix(in srgb, var(--agent-accent-2) 5%, transparent);
    }}
    .console-nav .quick-link[data-group="work"] {{
      border-color: color-mix(in srgb, var(--warn) 18%, transparent);
      background: color-mix(in srgb, var(--warn) 5%, transparent);
    }}
    .console-nav .quick-link[data-group="shared"] {{
      border-color: color-mix(in srgb, var(--accent) 16%, transparent);
      background: color-mix(in srgb, var(--accent) 5%, transparent);
    }}
    .console-nav .quick-link:hover {{
      background: color-mix(in srgb, var(--agent-accent) 8%, var(--surface-3));
      border-color: color-mix(in srgb, var(--agent-accent) 22%, transparent);
      color: var(--text);
    }}
    .console-group-pill[data-tone],
    .console-nav .quick-link[data-tone],
    .focus-card[data-tone] {{
      --surface-group-tone: var(--group-agents);
    }}
    .console-group-pill[data-tone="norman"],
    .console-nav .quick-link[data-tone="norman"],
    .focus-card[data-tone="norman"] {{
      --surface-group-tone: var(--group-norman);
    }}
    .console-group-pill[data-tone="personal"],
    .console-nav .quick-link[data-tone="personal"],
    .focus-card[data-tone="personal"] {{
      --surface-group-tone: var(--group-personal);
    }}
    .console-group-pill[data-tone="shared"],
    .console-nav .quick-link[data-tone="shared"],
    .focus-card[data-tone="shared"] {{
      --surface-group-tone: var(--group-shared);
    }}
    .console-group-pill[data-tone="work"],
    .console-nav .quick-link[data-tone="work"],
    .focus-card[data-tone="work"] {{
      --surface-group-tone: var(--group-work);
    }}
    .console-group-pill[data-tone="private"],
    .console-nav .quick-link[data-tone="private"],
    .focus-card[data-tone="private"] {{
      --surface-group-tone: var(--group-private);
    }}
    .console-group-pill[data-tone] {{
      color: color-mix(in srgb, var(--surface-group-tone) 72%, var(--text));
      border-color: color-mix(in srgb, var(--surface-group-tone) 30%, var(--border));
      background: color-mix(in srgb, var(--surface-group-tone) 10%, var(--surface-2));
    }}
    .console-group-pill[data-tone]:hover,
    .console-group-pill[data-tone]:focus-visible {{
      border-color: color-mix(in srgb, var(--surface-group-tone) 54%, var(--border-strong));
      color: var(--text);
    }}
    .console-group-pill.active[data-tone] {{
      border-color: color-mix(in srgb, var(--surface-group-tone) 56%, var(--border-strong));
      background: color-mix(in srgb, var(--surface-group-tone) 14%, var(--surface-3));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--surface-group-tone) 12%, transparent);
    }}
    .console-nav .quick-link[data-tone] {{
      border-color: color-mix(in srgb, var(--surface-group-tone) 18%, transparent);
      background: color-mix(in srgb, var(--surface-group-tone) 6%, transparent);
      color: color-mix(in srgb, var(--surface-group-tone) 64%, var(--text));
    }}
    .console-nav .quick-link[data-tone]:hover,
    .console-nav .quick-link[data-tone]:focus-visible {{
      background: color-mix(in srgb, var(--surface-group-tone) 9%, var(--surface-3));
      border-color: color-mix(in srgb, var(--surface-group-tone) 28%, transparent);
      color: var(--text);
      outline: none;
    }}
    .profile-chip.active {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 18%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 7%, var(--surface-3));
    }}
    .timeline-divider {{
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 0.62rem;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      padding: 6px 0 4px;
      opacity: 0.86;
    }}
    .timeline-divider::before,
    .timeline-divider::after {{
      content: "";
      height: 1px;
      flex: 1;
      background: color-mix(in srgb, var(--border) 78%, transparent);
    }}
    .message {{
      align-self: flex-start;
      max-width: min(92%, 760px);
      border-radius: 12px;
      border: 1px solid color-mix(in srgb, var(--border) 24%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 20%, transparent), color-mix(in srgb, var(--surface-2) 10%, transparent));
      padding: 6px 8px 7px;
      box-shadow:
        0 8px 18px rgba(6, 10, 16, 0.05),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.03) 46%, transparent);
      transition: border-color 0.12s ease, background 0.12s ease, box-shadow 0.12s ease, transform 0.12s ease;
    }}
    .message.user {{
      align-self: flex-end;
      max-width: min(80%, 600px);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface-3) 72%, var(--accent) 6%), color-mix(in srgb, var(--surface-2) 82%, var(--accent) 4%));
      border-color: color-mix(in srgb, var(--accent) 22%, transparent);
      box-shadow:
        0 10px 22px rgba(6, 10, 16, 0.06),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 42%, transparent);
    }}
    .message.assistant {{
      position: relative;
      max-width: min(100%, 940px);
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--agent-accent) 7%, transparent), transparent 22%),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 14%, transparent), transparent 58%);
      border-top-color: transparent;
      border-right-color: transparent;
      border-bottom-color: transparent;
      border-left: 2px solid color-mix(in srgb, var(--agent-accent) 18%, transparent);
      border-radius: 0 12px 12px 0;
      padding-left: 10px;
      box-shadow: none;
    }}
    .message.continuation {{
      margin-top: -1px;
      border-top-left-radius: 9px;
      border-top-right-radius: 9px;
    }}
    .message.user.continuation {{
      border-top-left-radius: 11px;
      border-top-right-radius: 7px;
    }}
    .message.assistant.continuation {{
      border-top-left-radius: 7px;
      border-top-right-radius: 11px;
    }}
    .message.continuation .meta-block {{
      display: none;
    }}
    .message.continuation .message-head {{
      justify-content: flex-end;
      min-height: 0;
      margin-bottom: 2px;
    }}
    .message.continuation .message-body {{
      margin-top: 0;
    }}
    .message.group-start {{
      border-bottom-left-radius: 11px;
      border-bottom-right-radius: 11px;
    }}
    .message.group-start.user {{
      border-bottom-right-radius: 9px;
    }}
    .message.group-start.assistant {{
      border-bottom-left-radius: 4px;
    }}
    .message.group-end {{
      box-shadow: none;
    }}
    body[data-finish="engraved"] .message.assistant {{
      box-shadow: none;
      background-image: none;
    }}
    body[data-finish="etched"] .message.assistant {{
      background-image: none;
    }}
    body[data-finish="glow"] .message.assistant {{
      box-shadow: none;
    }}
    .message:hover,
    .message:focus-within {{
      border-color: color-mix(in srgb, var(--border-strong) 52%, transparent);
      box-shadow:
        0 12px 26px rgba(6, 10, 16, 0.07),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 44%, transparent);
    }}
    .message.latest-message {{
      position: relative;
    }}
    .message.latest-message::after {{
      content: none;
    }}
    .message.assistant.latest-message::after {{
      inset: -1px -2px;
      border-radius: 10px;
    }}
    .message.error {{
      border-color: color-mix(in srgb, var(--danger) 30%, var(--border));
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--danger) 6%, transparent), transparent 48%),
        color-mix(in srgb, var(--surface-2) 68%, transparent);
      box-shadow:
        0 7px 18px rgba(6, 10, 16, 0.045),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.035) 36%, transparent);
    }}
    .message.pending {{
      border-style: dashed;
      background: var(--surface-2);
      border-color: var(--warn);
    }}
    .message.pending.live-status {{
      max-width: min(58%, 340px);
      padding: 5px 10px 6px;
      border-style: solid;
      border-left: 0;
      border-color: color-mix(in srgb, var(--warn) 12%, var(--border));
      border-radius: 14px 14px 14px 6px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 26%, transparent), transparent 72%),
        linear-gradient(90deg, color-mix(in srgb, var(--warn) 4%, transparent), transparent 42%),
        color-mix(in srgb, var(--surface-2) 46%, transparent);
      box-shadow:
        0 8px 18px rgba(6, 10, 16, 0.04),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.03) 40%, transparent);
    }}
    .message.queued {{
      border-style: dashed;
      background: var(--surface-2);
    }}
    .message.queued.relay-queued {{
      border-color: color-mix(in srgb, var(--agent-accent) 34%, var(--border));
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--agent-accent) 8%, transparent), transparent 38%),
        var(--surface-2);
    }}
    .message.empty {{
      align-self: stretch;
      max-width: none;
      color: var(--muted);
      text-align: center;
      font-style: italic;
      padding: 12px 8px;
      background: transparent;
      border-style: dashed;
      border-color: color-mix(in srgb, var(--border) 18%, transparent);
    }}
    .message-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 3px;
      color: var(--muted);
      font-size: 0.54rem;
      font-weight: 620;
      letter-spacing: 0.008em;
      text-transform: none;
      font-family: var(--font-label);
    }}
    .message.assistant .message-head {{
      margin-bottom: 4px;
    }}
    .message-tools {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-left: auto;
    }}
    .message-tools-toggle {{
      min-width: 24px;
      min-height: 22px;
      padding: 2px 6px;
      font-size: 0;
      color: var(--muted);
      background: transparent;
      border-color: transparent;
    }}
    .message-tools-toggle.active,
    .message-tools-toggle:hover {{
      color: var(--text);
      background: color-mix(in srgb, var(--surface-2) 28%, transparent);
      border-color: color-mix(in srgb, var(--border) 36%, transparent);
      box-shadow: none;
    }}
    @media (hover: hover) and (pointer: fine) {{
      .message.assistant .message-tools,
      .message.error .message-tools {{
        opacity: 0;
        transition: opacity 0.12s ease;
      }}
      .message.assistant:hover .message-tools,
      .message.assistant:focus-within .message-tools,
      .message.error:hover .message-tools,
      .message.error:focus-within .message-tools {{
        opacity: 1;
      }}
    }}
    .message-role {{
      display: inline-flex;
      align-items: center;
      min-height: 0;
      padding: 0;
      border: 0;
      background: transparent;
      color: color-mix(in srgb, var(--muted) 52%, var(--text));
      font-size: 0.56rem;
      letter-spacing: 0;
      text-transform: none;
    }}
    .message-role::before {{
      content: none;
      display: none;
    }}
    .message-meta {{
      color: var(--muted);
      font-size: 0.6rem;
      letter-spacing: 0.01em;
      opacity: 0.8;
    }}
    .message-state-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 17px;
      padding: 1px 6px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 52%, transparent);
      color: var(--muted);
      background: color-mix(in srgb, var(--surface-2) 64%, transparent);
      font-size: 0.54rem;
      line-height: 1;
    }}
    .message-state-badge.relay {{
      min-height: 0;
      padding: 0;
      border: 0;
      color: inherit;
      background: transparent;
    }}
    .message.user .message-head {{
      display: none;
    }}
    .message.assistant .message-head,
    .message.error .message-head,
    .message.pending .message-head,
    .message.queued .message-head {{
      margin-bottom: 4px;
    }}
    .message.pending.live-status .message-head {{
      display: none;
    }}
    .message-body {{
      white-space: normal;
      word-break: break-word;
      line-height: 1.58;
      font-size: var(--type-reading-size);
      letter-spacing: 0;
      user-select: text;
      -webkit-user-select: text;
      text-wrap: pretty;
    }}
    .message.assistant .message-body,
    .raw-view {{
      font-family: var(--font-reading);
      font-size: 0.96rem;
      line-height: 1.58;
      letter-spacing: 0;
      font-kerning: normal;
      hanging-punctuation: first last;
      font-variant-numeric: lining-nums proportional-nums;
    }}
    .message.assistant .message-body > p,
    .message.assistant .message-body > ul,
    .message.assistant .message-body > ol,
    .message.assistant .message-body > blockquote,
    .message.assistant .message-body > .callout,
    .message.assistant .message-body > .kv-list,
    .message.assistant .message-body > .task-list,
    .message.assistant .message-body > hr {{
      max-width: min(68ch, 100%);
    }}
    .message.assistant .message-body > h1,
    .message.assistant .message-body > h2,
    .message.assistant .message-body > h3,
    .message.assistant .message-body > h4,
    .message.assistant .message-body > .section-label {{
      max-width: min(30ch, 100%);
    }}
    .message.user .message-body,
    .message.pending .message-body,
    .message.queued .message-body,
    .message.error .message-body {{
      font-family: var(--font-body);
      font-size: 0.84rem;
      line-height: 1.44;
    }}
    .collapsed-prompt-toggle {{
      width: 100%;
      display: flex;
      align-items: center;
      gap: 0.54rem;
      min-width: 0;
      padding: 0.48rem 0.62rem;
      border-radius: 12px;
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      background: color-mix(in srgb, var(--surface-2) 42%, transparent);
      color: inherit;
      text-align: left;
      cursor: pointer;
      box-shadow: none;
    }}
    .collapsed-prompt-toggle:hover,
    .collapsed-prompt-toggle:focus-visible {{
      border-color: color-mix(in srgb, var(--agent-accent) 38%, var(--border));
      background: color-mix(in srgb, var(--surface-3) 42%, transparent);
    }}
    .collapsed-prompt-toggle[aria-expanded="true"] {{
      border-color: color-mix(in srgb, var(--agent-accent) 44%, var(--border-strong));
      background: color-mix(in srgb, var(--surface-3) 50%, transparent);
    }}
    .collapsed-prompt-badge {{
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      padding: 0.14rem 0.42rem;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 62%, transparent);
      background: color-mix(in srgb, var(--surface) 52%, transparent);
      color: color-mix(in srgb, var(--muted) 58%, var(--text));
      font-family: var(--font-ui-wide);
      font-size: 0.58rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .collapsed-prompt-title {{
      flex: 0 0 auto;
      font-weight: 620;
      color: color-mix(in srgb, var(--text) 86%, var(--agent-accent));
      white-space: nowrap;
    }}
    .collapsed-prompt-meta {{
      flex: 0 0 auto;
      color: var(--muted);
      font-size: 0.78rem;
      white-space: nowrap;
    }}
    .collapsed-prompt-preview {{
      flex: 1 1 auto;
      min-width: 0;
      color: color-mix(in srgb, var(--muted) 56%, var(--text));
      font-size: 0.82rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .collapsed-prompt-body {{
      margin-top: 0.5rem;
    }}
    .error-inline-summary {{
      max-width: min(100%, 84ch);
      font-weight: 620;
      line-height: 1.34;
      overflow-wrap: anywhere;
      color: color-mix(in srgb, var(--danger) 50%, var(--text));
    }}
    .error-details {{
      margin-top: 5px;
      border: 0;
      background: transparent;
      overflow: visible;
    }}
    .error-details summary {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-height: 20px;
      cursor: pointer;
      list-style: none;
      padding: 1px 7px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--danger) 20%, var(--border));
      background: color-mix(in srgb, var(--surface-2) 36%, transparent);
      font-size: 0.58rem;
      letter-spacing: 0.045em;
      text-transform: uppercase;
      color: color-mix(in srgb, var(--muted) 82%, var(--danger));
      font-family: var(--font-ui-wide);
      user-select: none;
    }}
    .error-details summary::before {{
      content: "!";
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 0.86rem;
      height: 0.86rem;
      border-radius: 999px;
      background: color-mix(in srgb, var(--danger) 11%, transparent);
      color: color-mix(in srgb, var(--danger) 68%, var(--text));
      font-size: 0.54rem;
      line-height: 1;
    }}
    .error-details summary::-webkit-details-marker {{
      display: none;
    }}
    .error-details[open] {{
      border: 1px solid color-mix(in srgb, var(--danger) 18%, var(--border));
      border-radius: 10px;
      background: color-mix(in srgb, var(--surface-2) 48%, transparent);
      padding: 5px;
      overflow: hidden;
    }}
    .error-details[open] summary {{
      margin-bottom: 5px;
      border-color: color-mix(in srgb, var(--danger) 28%, var(--border));
      background: color-mix(in srgb, var(--surface-3) 38%, transparent);
    }}
    .error-details pre {{
      margin: 0;
      padding: 8px 9px;
      overflow: auto;
      max-height: min(34vh, 260px);
      border-radius: 8px;
      background: color-mix(in srgb, var(--bg-soft) 72%, transparent);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.7rem;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
      color: color-mix(in srgb, var(--text) 90%, var(--danger));
    }}
    .message.pending.live-status .message-body {{
      font-size: 0.76rem;
      line-height: 1.34;
      font-weight: 540;
      color: color-mix(in srgb, var(--muted) 44%, var(--text));
    }}
    .message.pending.live-status .message-body::before {{
      content: "";
      width: 0.4rem;
      height: 0.4rem;
      border-radius: 999px;
      background: color-mix(in srgb, var(--warn) 76%, white 10%);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 8%, transparent);
      flex: 0 0 auto;
    }}
    .message.pending.live-status .message-body::after {{
      content: "···";
      color: color-mix(in srgb, var(--muted) 56%, var(--text));
      letter-spacing: 0.18em;
      font-size: 0.72rem;
      line-height: 1;
    }}
    .message-body > :first-child,
    .raw-view > :first-child {{
      margin-top: 0;
    }}
    .message-body > :last-child,
    .raw-view > :last-child {{
      margin-bottom: 0;
    }}
    .message-body p,
    .raw-view p {{
      margin: 0.54rem 0 0;
    }}
    .message.assistant .message-body p + p,
    .raw-view p + p {{
      margin-top: 0.68rem;
    }}
    .message-body h1,
    .message-body h2,
    .message-body h3,
    .message-body h4,
    .raw-view h1,
    .raw-view h2,
    .raw-view h3,
    .raw-view h4 {{
      margin: 0.82rem 0 0.24rem;
      line-height: 1.12;
      letter-spacing: 0;
      color: var(--text);
      font-family: var(--font-ui-wide);
      font-weight: 720;
    }}
    .message-body h1,
    .raw-view h1 {{
      font-size: 1.22rem;
    }}
    .message-body h2,
    .raw-view h2 {{
      font-size: 1.1rem;
    }}
    .message-body h3,
    .raw-view h3 {{
      font-size: 1rem;
    }}
    .message-body h4,
    .raw-view h4 {{
      font-size: 0.84rem;
      color: color-mix(in srgb, var(--muted) 64%, var(--text));
      letter-spacing: 0.03em;
      text-transform: none;
    }}
    .message-body .section-label,
    .raw-view .section-label {{
      margin: 0.86rem 0 0.28rem;
      line-height: 1.18;
      font-family: var(--font-ui-wide);
      font-size: 0.84rem;
      font-weight: 720;
      letter-spacing: 0.018em;
      color: color-mix(in srgb, var(--text) 86%, var(--agent-accent));
    }}
    .message-body ul,
    .message-body ol,
    .raw-view ul,
    .raw-view ol {{
      margin: 0.76rem 0 0;
      padding-left: 1.34rem;
      display: grid;
      gap: 0.46rem;
    }}
    .message-body li,
    .raw-view li {{
      padding-left: 0.05rem;
    }}
    .message-body li::marker,
    .raw-view li::marker {{
      color: color-mix(in srgb, var(--text) 38%, var(--agent-accent));
    }}
    .message-body blockquote,
    .raw-view blockquote {{
      margin: 0.76rem 0 0;
      padding: 0.1rem 0 0.1rem 0.95rem;
      border-left: 3px solid color-mix(in srgb, var(--agent-accent) 32%, var(--border));
      color: color-mix(in srgb, var(--muted) 44%, var(--text));
      font-style: italic;
    }}
    .message-body hr,
    .raw-view hr {{
      border: 0;
      border-top: 1px solid color-mix(in srgb, var(--border) 82%, transparent);
      margin: 0.9rem 0 0.1rem;
    }}
    .message-body strong,
    .raw-view strong {{
      font-weight: 700;
      color: color-mix(in srgb, var(--text) 92%, var(--agent-accent));
    }}
    .message-body em,
    .raw-view em {{
      font-style: italic;
      color: color-mix(in srgb, var(--text) 82%, var(--agent-accent-2));
    }}
    .message-body table,
    .raw-view table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
      line-height: 1.45;
      min-width: max-content;
    }}
    .table-wrap {{
      margin-top: 0.76rem;
      overflow-x: auto;
      border-radius: 15px;
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      background: color-mix(in srgb, var(--surface) 78%, transparent);
      box-shadow:
        0 10px 24px rgba(8, 12, 18, 0.08),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.03) 42%, transparent);
      -webkit-overflow-scrolling: touch;
      scrollbar-gutter: stable both-edges;
    }}
    .rich-table th,
    .rich-table td {{
      padding: 0.56rem 0.7rem;
      border-bottom: 1px solid color-mix(in srgb, var(--border) 66%, transparent);
      vertical-align: top;
      text-align: left;
      min-width: 8.5ch;
      overflow-wrap: anywhere;
    }}
    .rich-table th + th,
    .rich-table td + td {{
      border-left: 1px solid color-mix(in srgb, var(--border) 42%, transparent);
    }}
    .rich-table thead th {{
      color: var(--text);
      font-size: 0.74rem;
      font-weight: 680;
      letter-spacing: 0.015em;
      font-family: var(--font-ui-wide);
      background: color-mix(in srgb, var(--surface-2) 54%, transparent);
      white-space: nowrap;
    }}
    .rich-table tbody tr:nth-child(even) td {{
      background: color-mix(in srgb, var(--surface-2) 22%, transparent);
    }}
    .rich-table tbody tr:hover td {{
      background: color-mix(in srgb, var(--surface-3) 32%, transparent);
    }}
    .rich-table tbody tr:last-child td {{
      border-bottom: 0;
    }}
    .task-list {{
      list-style: none;
      padding-left: 0;
      margin-left: 0;
      gap: 0.34rem;
    }}
    .task-item {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 0.5rem;
      align-items: flex-start;
      padding-left: 0;
    }}
    .task-check {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1rem;
      height: 1rem;
      margin-top: 0.12rem;
      border-radius: 0.3rem;
      border: 1px solid color-mix(in srgb, var(--border-strong) 72%, transparent);
      background: color-mix(in srgb, var(--surface-2) 64%, transparent);
      color: var(--agent-accent-2);
      font-size: 0.68rem;
      line-height: 1;
      font-weight: 700;
    }}
    .task-item.checked .task-check {{
      background: color-mix(in srgb, var(--agent-accent-2) 16%, var(--surface-2));
      border-color: color-mix(in srgb, var(--agent-accent-2) 52%, var(--border));
    }}
    .task-copy {{
      min-width: 0;
    }}
    .kv-list {{
      margin-top: 0.76rem;
      display: grid;
      gap: 0.5rem;
      padding: 0.1rem 0;
    }}
    .kv-row {{
      display: grid;
      grid-template-columns: minmax(120px, 0.34fr) minmax(0, 1fr);
      gap: 0.8rem;
      align-items: start;
      padding: 0.52rem 0.72rem;
      border-radius: 14px;
      border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
      background: color-mix(in srgb, var(--surface-2) 40%, transparent);
    }}
    .kv-key {{
      color: var(--muted);
      font-size: 0.66rem;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      line-height: 1.35;
      font-family: var(--font-ui-wide);
    }}
    .kv-value {{
      min-width: 0;
      color: var(--text);
      font-size: 0.92rem;
      line-height: 1.55;
      font-family: var(--font-reading);
    }}
    .callout {{
      margin-top: 0.8rem;
      padding: 0.76rem 0.9rem 0.8rem;
      border-radius: 16px;
      border: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
      background: color-mix(in srgb, var(--surface-2) 42%, transparent);
      display: grid;
      gap: 0.32rem;
    }}
    .callout-head {{
      display: inline-flex;
      align-items: center;
      gap: 0.42rem;
      font-size: 0.72rem;
      font-weight: 720;
      letter-spacing: 0.02em;
      color: var(--text);
      font-family: var(--font-ui-wide);
    }}
    .callout-head::before {{
      content: attr(data-icon);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1.08rem;
      height: 1.08rem;
      border-radius: 999px;
      background: color-mix(in srgb, currentColor 14%, transparent);
      font-size: 0.66rem;
      line-height: 1;
    }}
    .callout-copy {{
      color: color-mix(in srgb, var(--muted) 58%, var(--text));
    }}
    .callout-alert {{
      color: var(--danger);
      border-color: color-mix(in srgb, var(--danger) 44%, var(--border));
      background: color-mix(in srgb, var(--danger) 8%, var(--surface-2));
    }}
    .callout-note {{
      color: var(--agent-accent);
      border-color: color-mix(in srgb, var(--agent-accent) 42%, var(--border));
      background: color-mix(in srgb, var(--agent-accent) 8%, var(--surface-2));
    }}
    .callout-decision,
    .callout-next {{
      color: var(--agent-accent-2);
      border-color: color-mix(in srgb, var(--agent-accent-2) 44%, var(--border));
      background: color-mix(in srgb, var(--agent-accent-2) 8%, var(--surface-2));
    }}
    .callout-watch {{
      color: var(--warn);
      border-color: color-mix(in srgb, var(--warn) 48%, var(--border));
      background: color-mix(in srgb, var(--warn) 9%, var(--surface-2));
    }}
    .entity-cartouche,
    .message-body .entity-cartouche,
    .raw-view .entity-cartouche {{
      --cartouche-tone: color-mix(in srgb, var(--text) 82%, var(--agent-accent));
      --cartouche-border: color-mix(in srgb, var(--border) 66%, transparent);
      --cartouche-fill: color-mix(in srgb, var(--surface-2) 62%, transparent);
      --cartouche-rail: color-mix(in srgb, currentColor 28%, transparent);
      position: relative;
      isolation: isolate;
      display: inline-grid;
      grid-template-columns: auto minmax(0, auto) auto;
      align-items: center;
      gap: 0.34rem;
      min-height: 1.42rem;
      max-width: min(100%, 24rem);
      padding: 0.1rem 0.48rem 0.1rem 0.2rem;
      margin: 0 0.08rem;
      border-radius: 7px 11px 7px 11px;
      border: 1px solid var(--cartouche-border);
      background:
        linear-gradient(90deg, var(--cartouche-rail) 0 0.16rem, transparent 0.16rem),
        linear-gradient(180deg, color-mix(in srgb, rgba(255, 255, 255, 0.075) 62%, transparent), transparent 70%),
        linear-gradient(120deg, color-mix(in srgb, currentColor 13%, transparent), transparent 38%),
        var(--cartouche-fill);
      color: var(--cartouche-tone);
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.045) 54%, transparent),
        inset 0 -1px 0 color-mix(in srgb, rgba(0, 0, 0, 0.16) 36%, transparent),
        inset 0 0 0 1px color-mix(in srgb, currentColor 5%, transparent),
        0 1px 0 rgba(8, 12, 18, 0.08);
      font-family: var(--font-ui-wide);
      font-size: 0.8em;
      font-weight: 650;
      letter-spacing: 0.01em;
      line-height: 1.1;
      white-space: nowrap;
      vertical-align: -0.14em;
      text-decoration: none;
      text-shadow: 0 1px 0 rgba(0, 0, 0, 0.12);
    }}
    .entity-cartouche__label {{
      position: relative;
      z-index: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      background-image: linear-gradient(90deg, transparent, color-mix(in srgb, currentColor 26%, transparent), transparent);
      background-repeat: no-repeat;
      background-size: 100% 1px;
      background-position: 0 100%;
    }}
    .entity-cartouche[href] {{
      cursor: pointer;
    }}
    .entity-cartouche[href]:hover,
    .entity-cartouche[href]:focus-visible {{
      --cartouche-border: color-mix(in srgb, currentColor 42%, var(--border-strong));
      --cartouche-fill: color-mix(in srgb, currentColor 7%, var(--surface));
      color: color-mix(in srgb, var(--text) 86%, currentColor);
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.06) 54%, transparent),
        inset 0 0 0 1px color-mix(in srgb, currentColor 8%, transparent),
        0 5px 16px color-mix(in srgb, currentColor 12%, transparent);
    }}
    .entity-cartouche[href]:focus-visible {{
      outline: 2px solid color-mix(in srgb, currentColor 44%, transparent);
      outline-offset: 2px;
    }}
    .entity-cartouche::before,
    .message-body .entity-cartouche::before,
    .raw-view .entity-cartouche::before {{
      content: attr(data-mark);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 1.12rem;
      height: 1.06rem;
      padding: 0 0.12rem;
      border-radius: 4px 7px 4px 7px;
      background:
        linear-gradient(180deg, color-mix(in srgb, currentColor 20%, transparent), transparent 78%),
        color-mix(in srgb, currentColor 11%, transparent);
      color: color-mix(in srgb, currentColor 88%, var(--text));
      font-size: 0.66rem;
      line-height: 1;
      font-weight: 760;
      box-shadow:
        inset 0 0 0 1px color-mix(in srgb, currentColor 18%, transparent),
        0 1px 0 rgba(8, 12, 18, 0.08);
    }}
    .entity-cartouche::after,
    .message-body .entity-cartouche::after,
    .raw-view .entity-cartouche::after {{
      content: attr(data-decorator);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      align-self: stretch;
      min-width: 0.82rem;
      padding-left: 0.22rem;
      margin-left: 0.02rem;
      border-left: 1px solid color-mix(in srgb, currentColor 16%, transparent);
      background: linear-gradient(180deg, transparent, color-mix(in srgb, currentColor 7%, transparent), transparent);
      color: color-mix(in srgb, currentColor 78%, var(--text));
      font-size: 0.6rem;
      line-height: 1;
      opacity: 0.72;
    }}
    .entity-cartouche[data-kind="host"],
    .message-body .entity-cartouche[data-kind="host"],
    .raw-view .entity-cartouche[data-kind="host"] {{
      --cartouche-tone: color-mix(in srgb, var(--agent-accent-2) 82%, var(--text));
      --cartouche-border: color-mix(in srgb, var(--agent-accent-2) 38%, var(--border));
      --cartouche-fill: color-mix(in srgb, var(--agent-accent-2) 7%, var(--surface-2));
      --cartouche-rail: color-mix(in srgb, var(--agent-accent-2) 42%, transparent);
      border-radius: 3px;
      font-family: var(--font-mono);
      background:
        linear-gradient(90deg, var(--cartouche-rail) 0 0.14rem, transparent 0.14rem),
        repeating-linear-gradient(90deg, color-mix(in srgb, currentColor 10%, transparent) 0 1px, transparent 1px 0.42rem),
        linear-gradient(180deg, color-mix(in srgb, currentColor 9%, transparent), transparent 72%),
        var(--cartouche-fill);
    }}
    .entity-cartouche[data-kind="host"]::before,
    .message-body .entity-cartouche[data-kind="host"]::before,
    .raw-view .entity-cartouche[data-kind="host"]::before {{
      border-radius: 2px;
    }}
    .entity-cartouche[data-kind="tui"],
    .message-body .entity-cartouche[data-kind="tui"],
    .raw-view .entity-cartouche[data-kind="tui"] {{
      --cartouche-tone: color-mix(in srgb, #b8ccff 86%, var(--text));
      --cartouche-border: color-mix(in srgb, #b8ccff 38%, var(--border));
      --cartouche-fill: color-mix(in srgb, #b8ccff 8%, var(--surface-2));
      --cartouche-rail: color-mix(in srgb, #b8ccff 48%, transparent);
      border-radius: 4px 10px 4px 10px;
      background:
        linear-gradient(90deg, var(--cartouche-rail) 0 0.18rem, transparent 0.18rem),
        linear-gradient(180deg, color-mix(in srgb, rgba(255, 255, 255, 0.09) 58%, transparent), transparent 68%),
        linear-gradient(120deg, color-mix(in srgb, currentColor 16%, transparent), transparent 34%),
        var(--cartouche-fill);
    }}
    .entity-cartouche[data-kind="bot"],
    .message-body .entity-cartouche[data-kind="bot"],
    .raw-view .entity-cartouche[data-kind="bot"] {{
      --cartouche-tone: color-mix(in srgb, var(--agent-accent) 84%, var(--text));
      --cartouche-border: color-mix(in srgb, var(--agent-accent) 36%, var(--border));
      --cartouche-fill: color-mix(in srgb, var(--agent-accent) 7%, var(--surface-2));
      --cartouche-rail: color-mix(in srgb, var(--agent-accent) 42%, transparent);
    }}
    .entity-cartouche[data-kind="person"],
    .message-body .entity-cartouche[data-kind="person"],
    .raw-view .entity-cartouche[data-kind="person"] {{
      --cartouche-tone: color-mix(in srgb, #d7b8ff 84%, var(--text));
      --cartouche-border: color-mix(in srgb, #d7b8ff 36%, var(--border));
      --cartouche-fill: color-mix(in srgb, #d7b8ff 8%, var(--surface-2));
      --cartouche-rail: color-mix(in srgb, #d7b8ff 42%, transparent);
    }}
    .entity-cartouche[data-kind="location"],
    .message-body .entity-cartouche[data-kind="location"],
    .raw-view .entity-cartouche[data-kind="location"] {{
      --cartouche-tone: color-mix(in srgb, #9ad7c7 86%, var(--text));
      --cartouche-border: color-mix(in srgb, #9ad7c7 34%, var(--border));
      --cartouche-fill: color-mix(in srgb, #9ad7c7 8%, var(--surface-2));
      --cartouche-rail: color-mix(in srgb, #9ad7c7 42%, transparent);
    }}
    .entity-cartouche[data-alias="true"],
    .message-body .entity-cartouche[data-alias="true"],
    .raw-view .entity-cartouche[data-alias="true"] {{
      --cartouche-border: color-mix(in srgb, currentColor 30%, var(--border));
      --cartouche-fill: color-mix(in srgb, currentColor 5%, var(--surface-2));
      border-style: dashed;
      background:
        linear-gradient(90deg, var(--cartouche-rail) 0 0.11rem, transparent 0.11rem),
        linear-gradient(180deg, color-mix(in srgb, currentColor 8%, transparent), transparent 74%),
        var(--cartouche-fill);
    }}
    .entity-cartouche[data-alias="true"]::after,
    .message-body .entity-cartouche[data-alias="true"]::after,
    .raw-view .entity-cartouche[data-alias="true"]::after {{
      content: "aka";
      min-width: 1.06rem;
      padding-left: 0.18rem;
      font-family: var(--font-mono);
      font-size: 0.5rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .entity-cartouche[data-group="work"],
    .message-body .entity-cartouche[data-group="work"],
    .raw-view .entity-cartouche[data-group="work"] {{
      --cartouche-tone: color-mix(in srgb, var(--warn) 84%, var(--text));
      --cartouche-border: color-mix(in srgb, var(--warn) 32%, var(--border));
      --cartouche-rail: color-mix(in srgb, var(--warn) 42%, transparent);
    }}
    .entity-cartouche[data-group="shared"],
    .message-body .entity-cartouche[data-group="shared"],
    .raw-view .entity-cartouche[data-group="shared"] {{
      --cartouche-tone: color-mix(in srgb, var(--accent-2) 84%, var(--text));
      --cartouche-border: color-mix(in srgb, var(--accent-2) 32%, var(--border));
      --cartouche-rail: color-mix(in srgb, var(--accent-2) 42%, transparent);
    }}
    .entity-cartouche[data-group="private"],
    .message-body .entity-cartouche[data-group="private"],
    .raw-view .entity-cartouche[data-group="private"] {{
      --cartouche-tone: color-mix(in srgb, #d7a9d9 84%, var(--text));
      --cartouche-border: color-mix(in srgb, #d7a9d9 30%, var(--border));
      --cartouche-rail: color-mix(in srgb, #d7a9d9 42%, transparent);
    }}
    .entity-cartouche[data-group="operator"],
    .message-body .entity-cartouche[data-group="operator"],
    .raw-view .entity-cartouche[data-group="operator"] {{
      --cartouche-tone: color-mix(in srgb, #ffe1a3 86%, var(--text));
      --cartouche-border: color-mix(in srgb, #ffe1a3 34%, var(--border));
      --cartouche-rail: color-mix(in srgb, #ffe1a3 42%, transparent);
    }}
    .entity-cartouche[data-group="family"],
    .message-body .entity-cartouche[data-group="family"],
    .raw-view .entity-cartouche[data-group="family"] {{
      --cartouche-tone: color-mix(in srgb, #ffb7cc 84%, var(--text));
      --cartouche-border: color-mix(in srgb, #ffb7cc 32%, var(--border));
      --cartouche-rail: color-mix(in srgb, #ffb7cc 42%, transparent);
    }}
    .entity-cartouche[data-group="norman"],
    .message-body .entity-cartouche[data-group="norman"],
    .raw-view .entity-cartouche[data-group="norman"] {{
      --cartouche-tone: color-mix(in srgb, #9cb6ef 86%, var(--text));
      --cartouche-border: color-mix(in srgb, #9cb6ef 32%, var(--border));
      --cartouche-rail: color-mix(in srgb, #9cb6ef 42%, transparent);
    }}
    .entity-cartouche[data-mention="true"],
    .message-body .entity-cartouche[data-mention="true"],
    .raw-view .entity-cartouche[data-mention="true"] {{
      --cartouche-fill: color-mix(in srgb, currentColor 8%, var(--surface-2));
      transform: translateY(-1px);
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.06) 50%, transparent),
        inset 0 0 0 1px color-mix(in srgb, currentColor 8%, transparent),
        0 4px 14px rgba(8, 12, 18, 0.1);
    }}
    .entity-cartouche[data-tone="mention-host"],
    .message-body .entity-cartouche[data-tone="mention-host"],
    .raw-view .entity-cartouche[data-tone="mention-host"] {{
      --cartouche-tone: color-mix(in srgb, var(--agent-accent-2) 92%, var(--text));
      --cartouche-border: color-mix(in srgb, var(--agent-accent-2) 46%, var(--border));
      --cartouche-rail: color-mix(in srgb, var(--agent-accent-2) 54%, transparent);
    }}
    .entity-cartouche[data-tone="mention-bot"],
    .message-body .entity-cartouche[data-tone="mention-bot"],
    .raw-view .entity-cartouche[data-tone="mention-bot"] {{
      --cartouche-tone: color-mix(in srgb, var(--agent-accent) 92%, var(--text));
      --cartouche-border: color-mix(in srgb, var(--agent-accent) 46%, var(--border));
      --cartouche-rail: color-mix(in srgb, var(--agent-accent) 54%, transparent);
    }}
    .entity-cartouche[data-tone="mention"],
    .message-body .entity-cartouche[data-tone="mention"],
    .raw-view .entity-cartouche[data-tone="mention"] {{
      --cartouche-tone: color-mix(in srgb, var(--text) 88%, var(--agent-accent));
      --cartouche-border: color-mix(in srgb, var(--text) 22%, var(--border));
      --cartouche-rail: color-mix(in srgb, var(--text) 30%, transparent);
    }}
    .entity-cartouche[data-compact="true"] {{
      min-height: 1.16rem;
      gap: 0.26rem;
      padding: 0.05rem 0.38rem 0.05rem 0.18rem;
      border-radius: 6px 9px 6px 9px;
      font-size: 0.72rem;
    }}
    .entity-cartouche[data-compact="true"]::before {{
      min-width: 0.96rem;
      height: 0.9rem;
      padding: 0 0.1rem;
      border-radius: 3px 6px 3px 6px;
      font-size: 0.56rem;
    }}
    .entity-cartouche[data-compact="true"]::after {{
      min-width: 0.58rem;
      padding-left: 0.16rem;
      font-size: 0.54rem;
    }}
    .message-role .entity-cartouche,
    .message-state-badge .entity-cartouche,
    .relay-target .entity-cartouche {{
      margin: 0;
      vertical-align: middle;
    }}
    .relay-target-status {{
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
      color: color-mix(in srgb, var(--muted) 74%, var(--text));
      font-size: 0.64rem;
      white-space: nowrap;
    }}
    .message-body a {{
      color: var(--agent-accent);
      text-decoration: underline;
      text-decoration-color: color-mix(in srgb, currentColor 72%, transparent);
      text-decoration-thickness: 0.08em;
      text-underline-offset: 0.16em;
      overflow-wrap: anywhere;
      cursor: pointer;
      font-weight: 600;
    }}
    .message-body a:hover {{
      color: color-mix(in srgb, var(--agent-accent) 82%, var(--text));
    }}
    .message-body a.file-link,
    .raw-view a.file-link {{
      display: inline-flex;
      align-items: center;
      gap: 0.34rem;
      padding: 0.1rem 0.38rem;
      border-radius: 8px;
      border: 1px solid color-mix(in srgb, var(--border) 34%, transparent);
      background: color-mix(in srgb, var(--surface-2) 22%, transparent);
      font-weight: 620;
      text-decoration: none;
      vertical-align: baseline;
      max-width: 100%;
    }}
    .message-body a.file-link::before,
    .raw-view a.file-link::before {{
      content: "↗";
      font-size: 0.78em;
      opacity: 0.74;
    }}
    .message-body a.file-link:hover,
    .raw-view a.file-link:hover {{
      background: color-mix(in srgb, var(--surface-3) 84%, transparent);
      border-color: color-mix(in srgb, var(--border-strong) 82%, transparent);
    }}
    .message-body a.inline-code-link,
    .raw-view a.inline-code-link {{
      display: inline-flex;
      align-items: baseline;
      max-width: 100%;
      text-decoration: none;
      font-weight: inherit;
      vertical-align: baseline;
    }}
    .message-body a.inline-code-link code,
    .raw-view a.inline-code-link code {{
      color: var(--agent-accent);
      text-decoration: underline;
      text-decoration-color: color-mix(in srgb, currentColor 58%, transparent);
      text-underline-offset: 0.14em;
      overflow-wrap: anywhere;
      cursor: pointer;
    }}
    .message-body a.inline-code-link:hover code,
    .raw-view a.inline-code-link:hover code {{
      color: color-mix(in srgb, var(--agent-accent) 82%, var(--text));
      background: color-mix(in srgb, var(--surface-2) 44%, var(--surface));
    }}
    .message-body code {{
      font-family: var(--font-mono);
      font-size: 0.85em;
      padding: 0.08rem 0.28rem;
      border-radius: 0.32rem;
      background:
        repeating-linear-gradient(
          90deg,
          color-mix(in srgb, var(--agent-accent-3) 8%, transparent) 0 1px,
          transparent 1px 18px
        ),
        color-mix(in srgb, var(--bg-soft) 92%, var(--surface));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--agent-accent) 8%, transparent);
    }}
    .secret-spoiler {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 1.42rem;
      border: 0;
      border-radius: 0.5rem;
      padding: 0.08rem 0.42rem;
      margin: 0 0.08rem;
      background: color-mix(in srgb, var(--surface-3) 82%, var(--bg-soft));
      color: var(--text);
      font: inherit;
      line-height: 1;
      vertical-align: baseline;
      cursor: pointer;
      transition:
        background 140ms ease,
        box-shadow 140ms ease,
        transform 140ms ease;
    }}
    .secret-spoiler:hover,
    .secret-spoiler:focus-visible {{
      background: color-mix(in srgb, var(--surface-3) 92%, var(--bg-soft));
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--border-strong) 56%, transparent);
      outline: none;
    }}
    .secret-spoiler:active {{
      transform: translateY(1px);
    }}
    .secret-spoiler-mask {{
      color: var(--muted);
      letter-spacing: 0.08em;
      font-size: 0.82em;
      white-space: nowrap;
    }}
    .secret-spoiler-value {{
      display: none;
      font-family: var(--font-mono);
      font-size: 0.86em;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .secret-spoiler.revealed .secret-spoiler-mask {{
      display: none;
    }}
    .secret-spoiler.revealed .secret-spoiler-value {{
      display: inline;
    }}
    .code-block {{
      margin-top: 8px;
      border-radius: 10px;
      border: 1px solid color-mix(in srgb, var(--border) 52%, transparent);
      background: color-mix(in srgb, var(--bg-soft) 92%, var(--surface));
      overflow: hidden;
    }}
    .code-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 4px 8px;
      border-bottom: 1px solid color-mix(in srgb, var(--border) 44%, transparent);
      background: color-mix(in srgb, var(--surface-2) 28%, transparent);
      color: var(--muted);
      font-size: 0.63rem;
      letter-spacing: 0.01em;
      text-transform: none;
      font-family: var(--font-ui-wide);
    }}
    .code-head-actions {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-left: auto;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .code-head span:last-child {{
      font-size: 0.68rem;
      text-transform: none;
      letter-spacing: 0;
      opacity: 0.82;
    }}
    .code-toggle-button {{
      min-height: 22px;
      padding: 2px 7px;
      font-size: 0.66rem;
      letter-spacing: 0;
      text-transform: none;
    }}
    .code-copy-button {{
      min-height: 22px;
      padding: 2px 7px;
      font-size: 0.66rem;
      letter-spacing: 0;
      text-transform: none;
    }}
    .code-preview {{
      display: none;
      padding: 9px 12px 11px;
      border-top: 1px solid color-mix(in srgb, var(--border) 34%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface-2) 8%, transparent), color-mix(in srgb, var(--bg-soft) 82%, transparent));
    }}
    .code-preview pre {{
      margin: 0;
      padding: 0;
      background: transparent;
      border: 0;
      font-family: var(--font-mono);
      font-size: 0.78rem;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
      color: color-mix(in srgb, var(--text) 92%, var(--muted));
    }}
    .code-preview-meta {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      margin-top: 7px;
      color: var(--muted);
      font-size: 0.66rem;
      line-height: 1.25;
    }}
    .code-preview-meta::before {{
      content: "…";
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1rem;
      height: 1rem;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-2) 46%, transparent);
      color: color-mix(in srgb, var(--text) 78%, var(--muted));
      font-size: 0.7rem;
      line-height: 1;
    }}
    .code-scroll {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    .code-block.compactable.collapsed .code-preview {{
      display: block;
    }}
    .code-block.compactable.collapsed .code-scroll {{
      display: none;
    }}
    .code-block pre {{
      margin: 0;
      padding: 9px 10px 10px;
      background: transparent;
      border: 0;
      border-radius: 0;
      max-height: none;
      overflow: visible;
      white-space: pre;
      word-break: normal;
      line-height: 1.52;
      font-size: 0.78rem;
    }}
    .code-block code {{
      display: block;
      padding: 0;
      background: transparent;
      border-radius: 0;
      font-size: inherit;
      white-space: inherit;
      word-break: inherit;
      color: var(--text);
      font-family: var(--font-mono);
    }}
    .tok-keyword,
    .tok-atom {{
      color: var(--agent-accent);
      font-weight: 650;
    }}
    .tok-string {{
      color: var(--agent-accent-2);
    }}
    .tok-number {{
      color: var(--warn);
    }}
    .tok-comment {{
      color: var(--muted);
      font-style: italic;
    }}
    .tok-key,
    .tok-attr {{
      color: color-mix(in srgb, var(--agent-accent) 78%, var(--text));
    }}
    .message-footer {{
      position: absolute;
      top: 30px;
      right: 11px;
      z-index: 6;
      display: grid;
      gap: 6px;
      margin-top: 0;
      min-width: 178px;
      max-width: min(320px, calc(100% - 18px));
      padding: 10px;
      border-radius: 14px;
      border: 1px solid color-mix(in srgb, var(--border) 56%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 99%, rgba(255, 255, 255, 0.02)), color-mix(in srgb, var(--surface-2) 94%, rgba(0, 0, 0, 0.12)));
      box-shadow:
        0 18px 34px rgba(8, 12, 18, 0.16),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 44%, transparent);
      backdrop-filter: blur(18px) saturate(116%);
      overflow: hidden;
    }}
    .message-footer::before {{
      content: "";
      position: absolute;
      inset: 0;
      border-radius: inherit;
      background: linear-gradient(180deg, color-mix(in srgb, var(--agent-accent) 5%, transparent), transparent 32%);
      pointer-events: none;
      opacity: 0.7;
    }}
    .message-footer.collapsed {{
      display: none;
    }}
    .message-footer > * {{
      scroll-snap-align: start;
      min-width: 0;
      position: relative;
      z-index: 1;
    }}
    .message-footer > * + * {{
      padding-top: 6px;
      border-top: 1px solid color-mix(in srgb, var(--border) 26%, transparent);
    }}
    .reply-shortcuts {{
      display: grid;
      gap: 5px;
      min-width: 0;
    }}
    .reply-tail-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 6px;
      padding-top: 5px;
      min-width: 0;
      border-top: 1px solid color-mix(in srgb, var(--border) 12%, transparent);
    }}
    .reply-tail-action {{
      min-height: 22px;
      padding: 2px 7px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 24%, transparent);
      background: color-mix(in srgb, var(--surface-2) 40%, transparent);
      color: color-mix(in srgb, var(--text) 76%, var(--muted));
      font-size: 0.66rem;
      letter-spacing: 0.01em;
      box-shadow: none;
      opacity: 0.88;
    }}
    .relay-group {{
      display: grid;
      gap: 5px;
      min-width: 0;
    }}
    .relay-targets {{
      display: grid;
      gap: 5px;
      min-width: 0;
    }}
    .relay-target {{
      display: inline-flex;
      align-items: center;
      gap: 0.36rem;
      min-height: 24px;
      width: 100%;
      justify-content: flex-start;
      padding: 3px 8px;
      font-size: 0.68rem;
      text-decoration: none;
    }}
    .relay-target[data-relay-state] {{
      gap: 0.36rem;
      color: var(--text);
    }}
    .relay-target[aria-disabled="true"],
    .relay-target.is-busy {{
      cursor: wait;
      opacity: 0.66;
    }}
    .relay-target[data-relay-state="sending"] {{
      border-color: color-mix(in srgb, var(--agent-accent) 32%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 8%, var(--surface));
    }}
    .relay-target[data-relay-state="picked-up"],
    .relay-target[data-relay-state="running"] {{
      border-color: color-mix(in srgb, #22c55e 42%, var(--border-strong));
      background: color-mix(in srgb, #22c55e 11%, var(--surface));
    }}
    .relay-target[data-relay-state="queued"] {{
      border-color: color-mix(in srgb, var(--agent-accent) 42%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 12%, var(--surface));
    }}
    .relay-target[data-relay-state="error"] {{
      border-color: color-mix(in srgb, var(--danger) 48%, var(--border-strong));
      background: color-mix(in srgb, var(--danger) 10%, var(--surface));
    }}
    .message-attachments {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 5px;
    }}
    .message-file-previews {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr));
      align-items: start;
      gap: 4px;
      margin-top: 5px;
      min-width: 0;
    }}
    .message-file-preview-gallery {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 6px;
      min-width: 0;
    }}
    .inline-image-preview-tile {{
      position: relative;
      display: block;
      min-width: 0;
      overflow: hidden;
      aspect-ratio: 1 / 1;
      border-radius: 11px;
      border: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 88%, transparent), color-mix(in srgb, var(--surface-2) 76%, transparent));
      box-shadow: inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 34%, transparent);
      text-decoration: none;
      color: inherit;
    }}
    .inline-image-preview-tile img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center;
      background:
        radial-gradient(circle at top, color-mix(in srgb, var(--surface-3) 76%, transparent), color-mix(in srgb, var(--surface) 90%, transparent));
    }}
    .inline-image-preview-caption {{
      position: absolute;
      right: 0;
      bottom: 0;
      left: 0;
      display: flex;
      align-items: center;
      min-width: 0;
      min-height: 24px;
      padding: 4px 7px;
      background: linear-gradient(180deg, transparent, color-mix(in srgb, rgba(5, 9, 18, 0.94) 96%, transparent));
      color: color-mix(in srgb, var(--text) 94%, white);
      font-size: 0.66rem;
      font-weight: 620;
      line-height: 1.15;
      letter-spacing: 0.01em;
    }}
    .inline-image-preview-caption span {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .inline-image-preview-more {{
      display: flex;
      align-items: center;
      justify-content: center;
      min-width: 0;
      aspect-ratio: 1 / 1;
      border-radius: 11px;
      border: 1px dashed color-mix(in srgb, var(--border) 72%, transparent);
      background: color-mix(in srgb, var(--surface-2) 72%, transparent);
      color: color-mix(in srgb, var(--muted) 88%, var(--agent-accent));
      font-size: 0.72rem;
      font-weight: 650;
      letter-spacing: 0.02em;
    }}
    .inline-file-preview {{
      display: block;
      min-width: 0;
      padding: 3px 5px;
      border-radius: 10px;
      border: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 88%, transparent), color-mix(in srgb, var(--surface-2) 76%, transparent));
      box-shadow: inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 34%, transparent);
    }}
    .inline-file-preview.loading {{
      opacity: 0.9;
    }}
    .inline-file-preview-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      min-width: 0;
    }}
    .inline-file-preview-meta {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      flex: 1 1 auto;
    }}
    .inline-file-preview-label {{
      display: inline-flex;
      align-items: center;
      min-height: 16px;
      padding: 0 5px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 58%, transparent);
      background: color-mix(in srgb, var(--surface-2) 62%, transparent);
      font-size: 0.52rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: color-mix(in srgb, var(--muted) 86%, var(--agent-accent));
      flex: 0 0 auto;
    }}
    .inline-file-preview-thumb {{
      width: 28px;
      height: 20px;
      flex: 0 0 auto;
      display: block;
      object-fit: cover;
      object-position: center;
      border-radius: 6px;
      border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
      background: color-mix(in srgb, var(--surface-3) 82%, transparent);
      box-shadow: 0 1px 0 rgba(0, 0, 0, 0.08);
    }}
    .inline-file-preview.attachment-kind-image .inline-file-preview-label {{
      display: none;
    }}
    .inline-file-preview-name {{
      min-width: 0;
      max-width: min(22vw, 184px);
      font-size: 0.74rem;
      font-weight: 620;
      line-height: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 0 1 auto;
    }}
    .inline-file-preview-subtle {{
      min-width: 0;
      flex: 1 1 auto;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 0.58rem;
      line-height: 1;
      color: var(--muted);
    }}
    .inline-file-preview-actions {{
      display: inline-flex;
      align-items: center;
      gap: 3px;
      justify-content: flex-end;
      flex: 0 0 auto;
    }}
    .inline-file-preview .inline-action {{
      min-height: 18px;
      padding: 0 5px;
      font-size: 0.58rem;
      border-radius: 8px;
    }}
    .inline-file-preview-summary {{
      display: none;
    }}
    .inline-file-preview-body {{
      min-width: 0;
      margin-top: 7px;
    }}
    .inline-file-preview-body img {{
      display: block;
      width: 100%;
      max-height: min(340px, 46vh);
      object-fit: contain;
      object-position: center;
      border-radius: 10px;
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      background:
        radial-gradient(circle at top, color-mix(in srgb, var(--surface-3) 76%, transparent), color-mix(in srgb, var(--surface) 90%, transparent));
    }}
    .inline-file-preview-text {{
      margin: 0;
      padding: 9px 10px;
      border-radius: 10px;
      border: 1px solid color-mix(in srgb, var(--border) 58%, transparent);
      background: color-mix(in srgb, var(--surface-2) 84%, transparent);
      color: color-mix(in srgb, var(--text) 94%, var(--muted));
      font: 500 0.77rem/1.45 var(--font-mono);
      white-space: pre-wrap;
      word-break: break-word;
      overflow-x: auto;
      max-height: min(260px, 40vh);
    }}
    .inline-file-preview-note {{
      margin-top: 6px;
      font-size: 0.65rem;
      line-height: 1.2;
      color: var(--muted);
    }}
    .message-attachments.gallery {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 7px;
    }}
    .draft-attachments {{
      display: flex;
      flex-wrap: wrap;
      grid-column: 1 / -1;
      grid-row: 1;
      gap: 5px;
      min-width: 0;
      margin: 0;
      padding: 0 0 2px;
    }}
    .attachment-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      max-width: 100%;
      min-height: 24px;
      padding: 3px 7px 3px 8px;
      border-radius: 11px;
      border: 1px solid color-mix(in srgb, var(--border) 68%, transparent);
      background: color-mix(in srgb, var(--surface-2) 62%, transparent);
      color: var(--text);
      box-shadow: none;
    }}
    .message-attachments.gallery .attachment-chip.is-media {{
      width: 100%;
      min-height: 0;
      padding: 6px;
      border-radius: 10px;
      align-items: stretch;
      background: color-mix(in srgb, var(--surface-2) 76%, transparent);
    }}
    .message-attachments.gallery .attachment-chip.is-media .attachment-chip-link {{
      display: grid;
      gap: 7px;
      align-items: stretch;
    }}
    .attachment-chip.removable {{
      padding-right: 3px;
    }}
    .attachment-chip-link {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      max-width: 100%;
      flex: 1 1 auto;
      color: inherit;
      text-decoration: none;
    }}
    .attachment-chip-link:hover {{
      color: var(--agent-accent);
    }}
    .attachment-chip-copy {{
      display: inline-flex;
      align-items: baseline;
      gap: 6px;
      min-width: 0;
      flex: 1 1 auto;
      white-space: nowrap;
    }}
    .message-attachments.gallery .attachment-chip.is-media .attachment-chip-copy {{
      display: grid;
      gap: 3px;
      align-items: start;
      white-space: normal;
    }}
    .attachment-chip.attachment-has-thumb {{
      padding-left: 4px;
      gap: 7px;
    }}
    .attachment-chip:hover {{
      border-color: color-mix(in srgb, var(--border-strong) 88%, transparent);
      background: color-mix(in srgb, var(--surface-3) 70%, transparent);
    }}
    .attachment-thumb {{
      width: 24px;
      height: 24px;
      border-radius: 7px;
      border: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
      object-fit: cover;
      object-position: center;
      flex: 0 0 auto;
      background: var(--surface-3);
      display: block;
      box-shadow: 0 1px 0 rgba(0, 0, 0, 0.05);
    }}
    .message-attachments.gallery .attachment-chip.is-media .attachment-thumb {{
      width: 100%;
      height: 132px;
      border-radius: 8px;
    }}
    .attachment-name {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      min-width: 0;
      font-size: 0.69rem;
      font-weight: 620;
      line-height: 1.1;
    }}
    .attachment-meta {{
      color: var(--muted);
      white-space: nowrap;
      font-size: 0.61rem;
      line-height: 1.05;
      flex: 0 0 auto;
    }}
    .message-attachments.gallery .attachment-chip.is-media .attachment-meta {{
      white-space: normal;
      font-size: 0.64rem;
      line-height: 1.2;
    }}
    .attachment-remove {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 16px;
      min-width: 16px;
      min-height: 16px;
      padding: 0;
      border-radius: 999px;
      border: 0;
      background: transparent;
      color: var(--muted);
      font-size: 0.76rem;
      line-height: 1;
      box-shadow: none;
    }}
    .attachment-remove:hover {{
      color: var(--text);
    }}
    .attachment-kind-image {{
      border-color: color-mix(in srgb, var(--agent-accent-2) 52%, var(--border));
    }}
    .attachment-kind-text {{
      border-color: color-mix(in srgb, var(--agent-accent) 44%, var(--border));
    }}
    .attachment-kind-file {{
      border-color: color-mix(in srgb, var(--warn) 40%, var(--border));
    }}
    .message-links {{
      display: grid;
      gap: 5px;
      margin-top: 0;
      min-width: 0;
    }}
    .link-chip-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 4px;
      min-width: 0;
      max-width: 100%;
    }}
    .link-chip {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      max-width: 100%;
      padding: 2px 8px;
      border-radius: 10px;
      border: 1px solid color-mix(in srgb, var(--border) 84%, transparent);
      background: color-mix(in srgb, var(--surface) 82%, transparent);
      color: var(--agent-accent);
      text-decoration: none;
      font-size: 0.71rem;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      transition: background 0.12s ease, border-color 0.12s ease;
    }}
    .link-chip:hover {{
      background: color-mix(in srgb, var(--surface-3) 82%, transparent);
      border-color: var(--border-strong);
    }}
    .link-copy-button {{
      min-height: 24px;
      padding: 2px 6px;
      font-size: 0.69rem;
    }}
    .message .link-copy-button {{
      display: inline-flex;
      justify-content: center;
    }}
    .message.pending.live-status .message-body {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .activity-strip {{
      display: none;
      grid-template-columns: auto minmax(0, 1fr) minmax(124px, 22vw) auto;
      align-items: center;
      gap: 7px 10px;
      min-height: 34px;
      padding: 7px 11px;
      border-radius: 18px;
      background:
        radial-gradient(circle at 0% 50%, color-mix(in srgb, var(--agent-accent) 5%, transparent), transparent 36%),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 34%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 74%, transparent);
      border: 1px solid color-mix(in srgb, var(--border) 28%, transparent);
      box-shadow:
        0 16px 32px rgba(8, 12, 18, 0.10),
        inset 0 1px 0 color-mix(in srgb, var(--surface-3) 16%, transparent);
      backdrop-filter: blur(14px) saturate(118%);
      overflow: hidden;
      transition: padding 0.16s ease, opacity 0.14s ease, max-height 0.16s ease, margin 0.14s ease, min-height 0.16s ease;
    }}
    .activity-strip.visible {{
      display: grid;
    }}
    .activity-strip.working {{
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--warn) 8%, transparent), transparent 30%),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 28%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 72%, transparent);
      border-color: color-mix(in srgb, var(--warn) 16%, var(--border));
    }}
    .activity-strip.console {{
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--agent-accent-2) 8%, transparent), transparent 30%),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 28%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 72%, transparent);
      border-color: color-mix(in srgb, var(--agent-accent-2) 16%, var(--border));
    }}
    .activity-strip.queue {{
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--agent-accent) 8%, transparent), transparent 30%),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 28%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 72%, transparent);
      border-color: color-mix(in srgb, var(--agent-accent) 16%, var(--border));
    }}
    .activity-strip.broker {{
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--agent-accent-2) 8%, transparent), transparent 30%),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 28%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 72%, transparent);
      border-color: color-mix(in srgb, var(--agent-accent-2) 16%, var(--border));
    }}
    .activity-icon {{
      grid-column: 1;
      grid-row: 1;
      width: 0.72rem;
      height: 0.72rem;
      margin-top: 0;
      border-radius: 999px;
      flex: 0 0 auto;
      background: currentColor;
      opacity: 0.88;
      align-self: center;
    }}
    .activity-strip.working .activity-icon {{
      width: 0.78rem;
      height: 0.78rem;
      border: 2px solid currentColor;
      border-right-color: transparent;
      background: transparent;
      animation: spin 0.9s linear infinite;
    }}
    .activity-copy {{
      grid-column: 2;
      grid-row: 1;
      min-width: 0;
      display: grid;
      gap: 1px;
      align-self: center;
      overflow: hidden;
    }}
    .activity-title {{
      flex: 0 0 auto;
      font-size: 0.68rem;
      font-weight: 670;
      letter-spacing: 0.01em;
      color: var(--text);
      font-family: var(--font-ui-wide);
      white-space: nowrap;
      line-height: 1.05;
    }}
    .activity-detail {{
      min-width: 0;
      font-size: 0.6rem;
      color: var(--muted);
      line-height: 1.18;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: none;
    }}
    .activity-actions {{
      grid-column: 4;
      grid-row: 1;
      display: inline-flex;
      align-items: center;
      gap: 3px;
      justify-self: end;
      align-self: center;
      flex-wrap: nowrap;
      min-width: 0;
    }}
    .activity-track {{
      grid-column: 3;
      grid-row: 1;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      width: 100%;
      justify-content: flex-end;
      align-self: center;
    }}
    .activity-track[hidden] {{
      display: none;
    }}
    .activity-track-bar {{
      position: relative;
      flex: 1 1 auto;
      min-width: 56px;
      height: 4px;
      border-radius: 999px;
      overflow: hidden;
      background: color-mix(in srgb, var(--surface-3) 36%, transparent);
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border) 34%, transparent);
    }}
    .activity-track-fill {{
      display: block;
      height: 100%;
      width: 0%;
      border-radius: inherit;
      background: color-mix(in srgb, var(--text) 72%, transparent);
      transition: width 180ms ease-out;
    }}
    .activity-track-summary {{
      display: inline-block;
      max-width: 12ch;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--muted);
      font-size: 0.54rem;
      letter-spacing: 0.01em;
      font-variant-numeric: tabular-nums;
    }}
    .activity-strip.working .activity-track-fill {{
      background: linear-gradient(90deg, color-mix(in srgb, var(--warn) 84%, white), color-mix(in srgb, var(--warn) 56%, var(--agent-accent)));
      box-shadow: 0 0 12px color-mix(in srgb, var(--warn) 28%, transparent);
    }}
    .activity-strip.console .activity-track-fill {{
      background: linear-gradient(90deg, color-mix(in srgb, var(--agent-accent-2) 76%, white), color-mix(in srgb, var(--agent-accent-2) 58%, var(--text)));
    }}
    .activity-strip.queue .activity-track-fill,
    .activity-strip.broker .activity-track-fill {{
      background: linear-gradient(90deg, color-mix(in srgb, var(--agent-accent) 78%, white), color-mix(in srgb, var(--agent-accent-2) 54%, var(--text)));
    }}
    .activity-peek-toggle,
    .activity-log-link,
    .activity-peek-close {{
      min-height: 0;
      padding: 1px 5px;
      border-radius: 4px;
      border: 1px solid color-mix(in srgb, var(--border) 46%, transparent);
      background: color-mix(in srgb, var(--surface-3) 34%, transparent);
      color: var(--muted);
      font-size: 0.55rem;
      letter-spacing: 0.01em;
      text-transform: none;
    }}
    .activity-peek-toggle:hover,
    .activity-log-link:hover,
    .activity-peek-close:hover {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 38%, var(--border));
      background: color-mix(in srgb, var(--surface-3) 46%, transparent);
    }}
    .activity-action-link {{
      text-decoration: none;
    }}
    .activity-peek {{
      display: none;
      gap: 10px;
      padding: 9px 10px;
      border: 1px solid color-mix(in srgb, var(--border) 46%, transparent);
      background: color-mix(in srgb, var(--surface) 98%, var(--bg-soft));
      color: var(--text);
      box-shadow: 0 12px 26px rgba(6, 10, 16, 0.10);
    }}
    .activity-peek.visible {{
      display: grid;
    }}
    .activity-peek-head {{
      display: flex;
      align-items: center;
      gap: 8px;
      justify-content: space-between;
    }}
    .activity-peek-title {{
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .activity-peek-head-actions {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .activity-sim-line {{
      font-size: 0.86rem;
      line-height: 1.45;
      color: var(--text);
    }}
    .activity-sim-meta {{
      font-size: 0.68rem;
      color: var(--muted);
      line-height: 1.4;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .activity-steps {{
      display: grid;
      gap: 6px;
    }}
    .activity-step {{
      display: grid;
      grid-template-columns: 12px minmax(0, 1fr);
      gap: 8px;
      align-items: flex-start;
      font-size: 0.72rem;
      color: var(--muted);
    }}
    .activity-step-dot {{
      width: 8px;
      height: 8px;
      border-radius: 999px;
      margin-top: 0.24rem;
      border: 1px solid color-mix(in srgb, var(--border) 56%, transparent);
      background: transparent;
    }}
    .activity-step.is-done .activity-step-dot {{
      background: color-mix(in srgb, var(--agent-accent) 68%, var(--surface-3));
      border-color: color-mix(in srgb, var(--agent-accent) 52%, var(--border));
    }}
    .activity-step.is-active .activity-step-dot {{
      background: transparent;
      border: 2px solid var(--warn);
      border-right-color: transparent;
      animation: spin 0.9s linear infinite;
    }}
    .activity-step.is-upnext .activity-step-dot {{
      background: color-mix(in srgb, var(--surface-3) 72%, transparent);
      border-color: color-mix(in srgb, var(--border) 62%, transparent);
    }}
    .activity-step-label {{
      color: var(--text);
      font-weight: 600;
    }}
    .activity-step-note {{
      margin-top: 2px;
      color: var(--muted);
      line-height: 1.4;
      word-break: break-word;
    }}
    .activity-log-preview details {{
      border-top: 1px solid color-mix(in srgb, var(--border) 34%, transparent);
      padding-top: 8px;
    }}
    .activity-log-preview summary {{
      cursor: pointer;
      color: var(--muted);
      font-size: 0.68rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      list-style: none;
    }}
    .activity-log-preview summary::-webkit-details-marker {{
      display: none;
    }}
    .activity-log-preview pre {{
      margin: 8px 0 0;
      max-height: 180px;
      overflow: auto;
      padding: 10px;
      border: 1px solid color-mix(in srgb, var(--border) 32%, transparent);
      background: color-mix(in srgb, #000 20%, transparent);
      color: color-mix(in srgb, var(--text) 92%, #d7e0ea);
      font-size: 0.7rem;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .composer-wrap {{
      display: grid;
      gap: 6px;
      margin-top: auto;
      padding: 8px 0 calc(10px + env(safe-area-inset-bottom));
      position: sticky;
      bottom: 0;
      z-index: 6;
      background:
        linear-gradient(
          180deg,
          transparent 0%,
          color-mix(in srgb, var(--surface) 22%, transparent) 12%,
          color-mix(in srgb, var(--bg) 90%, transparent) 28%,
          color-mix(in srgb, var(--bg) 96%, transparent) 58%,
          var(--bg) 100%
      );
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, var(--border) 16%, transparent),
        0 -10px 26px rgba(8, 12, 18, 0.04);
      overflow: visible;
    }}
    .composer-wrap::before {{
      content: "";
      position: absolute;
      inset: -4px -16px -3px;
      border-radius: 20px 20px 0 0;
      background:
        radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--agent-accent) 5%, transparent), transparent 42%),
        linear-gradient(180deg, transparent 0%, color-mix(in srgb, var(--surface) 14%, transparent) 20%, color-mix(in srgb, var(--bg) 94%, transparent) 58%, var(--bg) 100%);
      pointer-events: none;
      z-index: 0;
    }}
    .composer-wrap::after {{
      content: none;
    }}
    .composer-wrap > * {{
      position: relative;
      z-index: 1;
    }}
    .composer-toolbar {{
      order: 2;
      position: absolute;
      left: 12px;
      right: auto;
      width: min(520px, calc(100vw - 24px));
      bottom: calc(100% + 6px);
      display: flex;
      flex-direction: column;
      align-items: stretch;
      justify-content: flex-start;
      gap: 2px;
      min-width: 0;
      padding: 0;
      pointer-events: none;
      z-index: 4;
      opacity: 0;
      transform: translateY(6px);
      transition: opacity 0.14s ease, transform 0.14s ease;
    }}
    .composer-toolbar-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      min-width: 0;
    }}
    .composer-tools-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 0.42rem;
      min-height: 24px;
      padding: 2px 7px;
      border-radius: 999px;
      font-size: 0.66rem;
      color: var(--muted);
      border-color: transparent;
      background: transparent;
      transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease;
    }}
    .composer-tools-toggle[data-icon]::before {{
      content: attr(data-icon);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 0.86rem;
      height: 0.86rem;
      border-radius: 999px;
      background: transparent;
      color: currentColor;
      font-size: 0.66rem;
      line-height: 1;
      flex: 0 0 auto;
      opacity: 0.84;
    }}
    .composer-tools-toggle.active {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 26%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 9%, var(--surface-2));
    }}
    .composer-toolbar-panels {{
      display: grid;
      gap: 7px;
      padding: 10px 11px;
      border-radius: 12px;
      border: 1px solid color-mix(in srgb, var(--border-strong) 24%, var(--border));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 99%, rgba(255, 255, 255, 0.02)), color-mix(in srgb, var(--surface-2) 94%, rgba(0, 0, 0, 0.12)));
      box-shadow:
        0 14px 30px rgba(6, 10, 16, 0.14),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 40%, transparent);
      pointer-events: auto;
    }}
    .composer-toolbar-panels[hidden] {{
      display: none;
    }}
    .composer.compact {{
      padding-top: 0;
      padding-bottom: 0;
    }}
    .composer.compact .composer-toolbar {{
      display: flex;
      opacity: 0;
      transform: translateY(6px);
      pointer-events: none;
    }}
    .composer:not(.compact) .composer-toolbar {{
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
    }}
    .composer.compact .response-summary {{
      display: none;
    }}
    .composer-tools-inline .response-summary {{
      display: none;
    }}
    .composer-upload-button {{
      width: auto;
      min-width: 28px;
      padding: 0 8px;
      gap: 4px;
      border-color: color-mix(in srgb, var(--border) 60%, transparent);
      background: color-mix(in srgb, var(--surface-2) 68%, transparent);
      color: var(--text-dim);
    }}
    .composer-upload-label {{
      display: none;
      font-size: 0.62rem;
      font-weight: 650;
      letter-spacing: 0;
      line-height: 1;
    }}
    .response-bar {{
      display: flex;
      flex: 1 1 320px;
      flex-wrap: wrap;
      align-items: center;
      gap: 4px 8px;
      padding: 0;
      min-width: 0;
    }}
    .response-summary {{
      display: inline-flex;
      align-items: center;
      gap: 0.28rem;
      min-width: 0;
      color: inherit;
      font-size: inherit;
      font-weight: 650;
      letter-spacing: 0;
      white-space: nowrap;
    }}
    .response-summary::before {{
      content: "◌";
      color: color-mix(in srgb, var(--agent-accent) 78%, var(--muted));
      font-size: 0.72rem;
      line-height: 1;
    }}
    .response-rail {{
      min-width: 128px;
      flex: 1 1 148px;
      display: grid;
      gap: 1px;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .response-rail-meta {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
    }}
    .response-rail-name {{
      display: inline-flex;
      align-items: center;
      gap: 0.32rem;
      color: var(--muted);
      font-size: 0.57rem;
      line-height: 1;
      letter-spacing: 0.03em;
      text-transform: none;
    }}
    .response-rail-value {{
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      min-width: 0;
      min-height: 16px;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--text);
      font-size: 0.62rem;
      font-weight: 700;
      line-height: 1;
      white-space: nowrap;
    }}
    .response-track {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
      gap: 4px;
      min-width: 0;
    }}
    .response-edge {{
      color: var(--muted);
      font-size: 0.56rem;
      line-height: 1;
      white-space: nowrap;
      opacity: 0.72;
    }}
    .response-range {{
      margin: 0;
      width: 100%;
      min-width: 54px;
      appearance: none;
      -webkit-appearance: none;
      background: transparent;
      accent-color: var(--agent-accent);
      cursor: pointer;
    }}
    .response-range::-webkit-slider-runnable-track {{
      height: 4px;
      border-radius: 999px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface-3) 84%, transparent), color-mix(in srgb, var(--surface-2) 88%, transparent));
      border: 1px solid color-mix(in srgb, var(--border) 86%, transparent);
    }}
    .response-range::-webkit-slider-thumb {{
      -webkit-appearance: none;
      appearance: none;
      width: 11px;
      height: 11px;
      margin-top: -4px;
      border-radius: 50%;
      border: 1px solid color-mix(in srgb, var(--border-strong) 84%, transparent);
      background: color-mix(in srgb, var(--agent-accent) 72%, white 12%);
      box-shadow: 0 1px 6px rgba(0, 0, 0, 0.22);
    }}
    .response-range::-moz-range-track {{
      height: 4px;
      border-radius: 999px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface-3) 84%, transparent), color-mix(in srgb, var(--surface-2) 88%, transparent));
      border: 1px solid color-mix(in srgb, var(--border) 86%, transparent);
    }}
    .response-range::-moz-range-thumb {{
      width: 11px;
      height: 11px;
      border-radius: 50%;
      border: 1px solid color-mix(in srgb, var(--border-strong) 84%, transparent);
      background: color-mix(in srgb, var(--agent-accent) 72%, white 12%);
      box-shadow: 0 1px 6px rgba(0, 0, 0, 0.22);
    }}
    .suggestions {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-start;
      gap: 3px;
      padding: 0;
      min-width: 0;
      opacity: 0.84;
    }}
    .suggestion-chip {{
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      min-height: 18px;
      padding: 1px 6px;
      border-radius: 999px;
      font-size: 0.61rem;
      background: transparent;
      color: var(--muted);
      border-color: color-mix(in srgb, var(--border) 76%, transparent);
    }}
    .sample-prompt-strip {{
      grid-column: 1 / -1;
      grid-row: 1;
      display: flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      padding: 0 2px 2px;
    }}
    .sample-prompt-strip[hidden] {{
      display: none;
    }}
    .sample-prompt-label {{
      flex: 0 0 auto;
      color: color-mix(in srgb, var(--muted) 86%, transparent);
      font-size: 0.58rem;
      font-weight: 700;
      letter-spacing: 0;
      line-height: 1;
      text-transform: uppercase;
    }}
    .sample-prompt-list {{
      display: flex;
      flex: 1 1 auto;
      align-items: center;
      gap: 4px;
      min-width: 0;
      overflow-x: auto;
      overflow-y: hidden;
      scrollbar-width: none;
      scroll-snap-type: x proximity;
    }}
    .sample-prompt-list::-webkit-scrollbar {{
      display: none;
    }}
    .sample-prompt-strip .suggestion-chip {{
      flex: 0 0 auto;
      min-height: 22px;
      padding: 2px 8px;
      color: color-mix(in srgb, var(--text) 82%, var(--muted));
      border-color: color-mix(in srgb, var(--border) 62%, transparent);
      background: color-mix(in srgb, var(--surface-2) 46%, transparent);
      scroll-snap-align: start;
    }}
    .sample-prompt-strip .suggestion-chip:hover,
    .sample-prompt-strip .suggestion-chip:focus-visible {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 24%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 9%, var(--surface-2));
    }}
    .composer {{
      position: relative;
      display: grid;
      gap: 2px;
      padding: 0;
      border-radius: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
      transition: border-color 0.14s ease, background 0.14s ease, box-shadow 0.14s ease, transform 0.14s ease;
    }}
    .composer.idle {{
      background: transparent;
      box-shadow: none;
    }}
    .composer.is-focused,
    .composer.has-text,
    .composer.has-drafts {{
      background: transparent;
      box-shadow: none;
    }}
    body[data-finish="engraved"] .composer {{
      background-image: none;
    }}
    body[data-finish="etched"] .composer {{
      box-shadow:
        0 2px 10px rgba(12, 16, 22, 0.018),
        inset 0 1px 0 rgba(255, 255, 255, 0.018),
        inset 0 0 0 1px color-mix(in srgb, var(--border) 18%, transparent);
    }}
    body[data-finish="glow"] .composer {{
      box-shadow:
        0 3px 12px rgba(12, 16, 22, 0.022),
        0 0 14px color-mix(in srgb, var(--agent-accent) 5%, transparent),
        inset 0 1px 0 rgba(255, 255, 255, 0.022);
    }}
    .composer-drop-hint {{
      color: var(--muted);
      font-size: 0.66rem;
      line-height: 1.3;
      opacity: 0.84;
      display: none;
    }}
    .composer-input-shell {{
      order: 1;
      position: relative;
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      grid-template-rows: auto minmax(44px, auto);
      align-items: end;
      gap: 8px 10px;
      overflow: visible;
      isolation: isolate;
      border-radius: 8px;
      background:
        radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--agent-accent) 6%, transparent), transparent 58%),
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 99%, rgba(255, 255, 255, 0.035)), color-mix(in srgb, var(--surface-2) 92%, rgba(0, 0, 0, 0.07)));
      border: 1px solid color-mix(in srgb, var(--agent-accent) 18%, var(--border));
      padding: 10px;
      box-shadow:
        0 18px 42px rgba(8, 12, 18, 0.13),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.08) 58%, transparent),
        inset 0 -1px 0 color-mix(in srgb, var(--agent-accent) 10%, rgba(0, 0, 0, 0.10));
      transition:
        border-color 0.14s ease,
        box-shadow 0.14s ease,
        background 0.14s ease,
        transform 0.14s ease;
    }}
    .composer-input-shell::before {{
      content: "";
      position: absolute;
      inset: 1px 1px auto;
      height: 44%;
      border-radius: inherit;
      background:
        linear-gradient(180deg, color-mix(in srgb, rgba(255, 255, 255, 0.045) 58%, transparent), transparent 88%);
      pointer-events: none;
    }}
    .composer-input-shell::after {{
      content: "";
      position: absolute;
      inset: auto 14px 0;
      height: 2px;
      background:
        linear-gradient(90deg, transparent, color-mix(in srgb, var(--agent-accent) 14%, transparent), transparent);
      opacity: 0.42;
      pointer-events: none;
    }}
    .composer-input-shell > * {{
      position: relative;
      z-index: 1;
    }}
    .composer-input-shell:focus-within {{
      border-color: color-mix(in srgb, var(--agent-accent) 30%, var(--border-strong));
      box-shadow:
        0 22px 48px rgba(8, 12, 18, 0.14),
        inset 0 0 0 1px color-mix(in srgb, var(--agent-accent) 10%, transparent),
        0 0 0 1px color-mix(in srgb, var(--agent-accent) 7%, transparent);
    }}
    .composer.has-text .composer-input-shell,
    .composer.has-drafts .composer-input-shell {{
      border-color: color-mix(in srgb, var(--agent-accent) 24%, var(--border-strong));
    }}
    .composer-file-input {{
      display: none;
    }}
    .composer-inline-actions {{
      position: relative;
      left: auto;
      bottom: auto;
      grid-column: 1;
      grid-row: 2;
      align-self: end;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .composer-upload-shell {{
      position: relative;
      display: inline-flex;
      align-items: center;
    }}
    .composer-upload-menu {{
      position: absolute;
      left: 0;
      bottom: calc(100% + 8px);
      min-width: 180px;
      display: grid;
      gap: 3px;
      padding: 6px;
      border-radius: 10px;
      border: 1px solid color-mix(in srgb, var(--border) 84%, transparent);
      background: color-mix(in srgb, var(--surface) 96%, var(--bg-soft));
      box-shadow: 0 12px 30px rgba(9, 12, 18, 0.18);
      z-index: 8;
    }}
    .composer-upload-menu[hidden] {{
      display: none;
    }}
    .composer-upload-item {{
      justify-content: flex-start;
      min-height: 28px;
      padding: 4px 8px;
      border-radius: 7px;
      border-color: transparent;
      background: transparent;
      color: var(--text);
      font-size: 0.68rem;
      text-align: left;
    }}
    .composer-upload-item:hover,
    .composer-upload-item:focus-visible {{
      background: color-mix(in srgb, var(--surface-3) 72%, transparent);
      border-color: color-mix(in srgb, var(--border-strong) 58%, transparent);
    }}
    .composer-inline-action {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      min-width: 30px;
      min-height: 30px;
      padding: 0;
      border-radius: 7px;
      border-color: color-mix(in srgb, var(--border) 42%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 92%, transparent), color-mix(in srgb, var(--surface-2) 78%, transparent));
      color: var(--muted);
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 42%, transparent),
        0 1px 0 rgba(8, 12, 18, 0.08);
    }}
    .composer-inline-action:hover,
    .composer-inline-action.active,
    .composer.has-drafts .composer-upload-button {{
      color: var(--text);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, transparent), color-mix(in srgb, var(--surface-3) 78%, transparent));
      border-color: color-mix(in srgb, var(--agent-accent) 24%, transparent);
      transform: translateY(-1px);
    }}
    .composer-upload-button:hover,
    .composer-upload-button:focus-visible,
    .composer.has-drafts .composer-upload-button {{
      border-color: color-mix(in srgb, var(--agent-accent) 26%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 10%, var(--surface-2));
      color: var(--text);
    }}
    .composer-inline-action[data-icon]::before,
    .composer-send[data-icon]::before {{
      width: auto;
      height: auto;
      background: transparent;
      font-size: 0.78rem;
      opacity: 0.96;
    }}
    .composer-tools-inline {{
      position: static;
      width: 30px;
      min-width: 30px;
      min-height: 30px;
      padding: 0;
      justify-content: center;
      gap: 0;
    }}
    .composer.compact .composer-tools-inline {{
      width: 26px;
      min-width: 26px;
      justify-content: center;
      gap: 0;
    }}
    .composer-input-shell.dragover {{
      filter: brightness(1.02);
      box-shadow:
        inset 0 0 0 1px color-mix(in srgb, var(--agent-accent) 16%, transparent),
        0 0 0 1px color-mix(in srgb, var(--agent-accent) 10%, transparent);
      outline: 0;
    }}
    textarea {{
      grid-column: 2;
      grid-row: 2;
      align-self: stretch;
      width: 100%;
      min-height: 44px;
      resize: none;
      overflow-y: hidden;
      border-radius: 0;
      border: 0;
      background: transparent;
      color: var(--text);
      font: inherit;
      line-height: 1.42;
      padding: 7px 0 8px;
      margin: 0;
      caret-color: color-mix(in srgb, var(--agent-accent) 78%, var(--text));
      scrollbar-gutter: stable;
    }}
    #prompt-input:focus-visible {{
      outline: none;
    }}
    textarea::placeholder {{
      color: color-mix(in srgb, var(--muted) 84%, transparent);
    }}
    textarea:focus-visible,
    button:focus-visible,
    a:focus-visible,
    summary:focus-visible {{
      outline: 2px solid rgba(125, 211, 252, 0.4);
      outline-offset: 2px;
    }}
    .composer-send {{
      position: relative;
      right: auto;
      bottom: auto;
      grid-column: 3;
      grid-row: 2;
      align-self: end;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0;
      width: 32px;
      min-width: 32px;
      min-height: 32px;
      padding: 0;
      font-size: 0;
      border-radius: 8px;
      border-color: color-mix(in srgb, var(--agent-accent) 32%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--agent-accent) 34%, var(--surface)), color-mix(in srgb, var(--agent-accent) 14%, var(--surface-2)));
      box-shadow:
        0 12px 24px rgba(8, 12, 18, 0.18),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.06) 48%, transparent),
        0 0 0 1px color-mix(in srgb, var(--agent-accent) 10%, transparent);
      transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
    }}
    .composer.idle .composer-send {{
      border-color: color-mix(in srgb, var(--border) 62%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 90%, transparent), color-mix(in srgb, var(--surface-2) 80%, transparent));
      color: color-mix(in srgb, var(--muted) 88%, var(--text));
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 44%, transparent),
        0 3px 10px rgba(8, 12, 18, 0.08);
    }}
    .composer.has-text .composer-send,
    .composer.has-drafts .composer-send {{
      border-color: color-mix(in srgb, var(--agent-accent) 34%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--agent-accent) 36%, var(--surface)), color-mix(in srgb, var(--agent-accent) 16%, var(--surface-2)));
    }}
    .composer-send:hover,
    .composer-send:focus-visible {{
      transform: translateY(-1px) scale(1.01);
      box-shadow:
        0 14px 30px rgba(8, 12, 18, 0.22),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.07) 52%, transparent),
        0 0 0 1px color-mix(in srgb, var(--agent-accent) 14%, transparent);
    }}
    .composer.idle .composer-send {{
      width: 32px;
      min-width: 32px;
      min-height: 32px;
    }}
    .button-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}
    .copy-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 6px;
    }}
    .copy-button {{
      display: inline-flex;
      align-items: center;
      gap: 0.34rem;
      min-height: 30px;
      padding: 5px 8px;
      font-size: 0.74rem;
      opacity: 0.82;
      transition: opacity 0.12s ease, background 0.12s ease;
    }}
    .message-footer .copy-button,
    .message-footer .inline-action,
    .message-footer .relay-toggle,
    .message-footer .relay-target {{
      width: 100%;
      justify-content: flex-start;
      min-height: 28px;
      padding: 4px 10px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 38%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 86%, transparent), color-mix(in srgb, var(--surface-2) 78%, transparent));
      color: color-mix(in srgb, var(--text) 84%, var(--muted));
      box-shadow: inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 38%, transparent);
    }}
    .message-footer .copy-button,
    .message-footer .link-chip,
    .message-footer .link-copy-button {{
      opacity: 0.96;
    }}
    .inline-action {{
      display: inline-flex;
      align-items: center;
      gap: 0.34rem;
      min-height: 30px;
      padding: 5px 8px;
      border-radius: 999px;
      font-size: 0.73rem;
    }}
    .message-footer .copy-button:hover,
    .message-footer .inline-action:hover,
    .message-footer .relay-toggle:hover,
    .message-footer .relay-target:hover,
    .message-footer .link-chip:hover,
    .message-footer .link-copy-button:hover {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 22%, var(--border-strong));
      transform: translateY(-1px);
    }}
    .reply-tail-action:hover,
    .reply-tail-action:focus-visible {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 22%, var(--border-strong));
      background: color-mix(in srgb, var(--surface-3) 48%, transparent);
      transform: translateY(-1px);
      opacity: 1;
    }}
    .message:hover .copy-button,
    .message:focus-within .copy-button,
    .copy-button:hover {{
      opacity: 1;
    }}
    .raw-view {{
      margin: 0;
      padding: 9px 10px;
      border-radius: 13px;
      background: color-mix(in srgb, var(--bg-soft) 84%, var(--surface));
      border: 1px solid var(--border);
      white-space: normal;
      word-break: break-word;
      overflow: auto;
      max-height: 22vh;
      font-size: 0.95rem;
      line-height: 1.64;
      scrollbar-gutter: stable;
      -webkit-overflow-scrolling: touch;
      overscroll-behavior: contain;
    }}
    .raw-view a {{
      color: var(--accent);
      text-decoration: underline;
      text-decoration-color: color-mix(in srgb, currentColor 72%, transparent);
      text-underline-offset: 0.16em;
      overflow-wrap: anywhere;
      cursor: pointer;
      font-weight: 600;
    }}
    .raw-links {{
      margin-top: 8px;
    }}
    .jump-latest {{
      position: absolute;
      right: 10px;
      bottom: 88px;
      z-index: 5;
      display: none;
      align-items: center;
      gap: 6px;
      min-height: 30px;
      padding: 5px 9px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 92%, transparent);
      box-shadow:
        0 10px 22px rgba(8, 12, 18, 0.10),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.03) 42%, transparent);
      font-size: 0.73rem;
    }}
    .jump-latest.visible {{
      display: inline-flex;
    }}
    .system-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.48);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease;
      z-index: 30;
    }}
    .switcher-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.34);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease;
      z-index: 47;
    }}
    .settings-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.38);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease;
      z-index: 45;
    }}
    .settings-panel {{
      position: fixed;
      right: 12px;
      top: 78px;
      width: min(100vw - 24px, 340px);
      display: grid;
      gap: 12px;
      padding: 14px;
      z-index: 50;
      opacity: 0;
      pointer-events: none;
      transform: translateY(-8px);
      transition: opacity 0.18s ease, transform 0.18s ease;
      border: 1px solid color-mix(in srgb, var(--border) 52%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 98%, rgba(255, 255, 255, 0.02)), color-mix(in srgb, var(--surface-2) 92%, rgba(0, 0, 0, 0.12)));
      box-shadow:
        0 22px 46px rgba(8, 12, 18, 0.18),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 46%, transparent);
      backdrop-filter: blur(18px) saturate(120%);
    }}
    .settings-body {{
      display: grid;
      gap: 12px;
      max-height: min(calc(100dvh - 92px), 760px);
      overflow-y: auto;
      overscroll-behavior: contain;
      padding-right: 2px;
    }}
    .switcher-panel {{
      position: fixed;
      right: 12px;
      top: 78px;
      width: min(100vw - 24px, 420px);
      display: grid;
      gap: 10px;
      padding: 14px;
      z-index: 48;
      opacity: 0;
      pointer-events: none;
      transform: translateY(-8px);
      transition: opacity 0.18s ease, transform 0.18s ease;
      border: 1px solid color-mix(in srgb, var(--border) 52%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 98%, rgba(255, 255, 255, 0.02)), color-mix(in srgb, var(--surface-2) 92%, rgba(0, 0, 0, 0.12)));
      box-shadow:
        0 22px 46px rgba(8, 12, 18, 0.18),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 46%, transparent);
      backdrop-filter: blur(18px) saturate(120%);
    }}
    body.switcher-open .switcher-backdrop {{
      opacity: 1;
      pointer-events: auto;
    }}
    body.switcher-open .switcher-panel {{
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }}
    body.settings-open .settings-backdrop {{
      opacity: 1;
      pointer-events: auto;
    }}
    body.settings-open .settings-panel {{
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }}
    .notices-panel {{
      position: fixed;
      right: 12px;
      top: 78px;
      width: min(100vw - 24px, 360px);
      display: grid;
      gap: 10px;
      padding: 14px;
      z-index: 55;
      opacity: 0;
      pointer-events: none;
      transform: translateY(-8px);
      transition: opacity 0.18s ease, transform 0.18s ease;
      border: 1px solid color-mix(in srgb, var(--border) 52%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 98%, rgba(255, 255, 255, 0.02)), color-mix(in srgb, var(--surface-2) 92%, rgba(0, 0, 0, 0.12)));
      box-shadow:
        0 22px 46px rgba(8, 12, 18, 0.18),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 46%, transparent);
      backdrop-filter: blur(18px) saturate(120%);
    }}
    body.notices-open .settings-backdrop {{
      opacity: 1;
      pointer-events: auto;
    }}
    body.notices-open .notices-panel {{
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }}
    .notices-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }}
    .notices-head h2 {{
      margin: 0;
      font-size: 0.98rem;
      line-height: 1.2;
    }}
    .notices-actions {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .notifications-list {{
      display: grid;
      gap: 8px;
      max-height: min(58dvh, 520px);
      overflow: auto;
      scrollbar-gutter: stable;
      -webkit-overflow-scrolling: touch;
    }}
    .notification-item {{
      display: grid;
      gap: 3px;
      padding: 9px 10px;
      border-radius: 14px;
      border: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 12%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 52%, transparent);
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 36%, transparent),
        0 8px 18px rgba(8, 12, 18, 0.08);
    }}
    .notification-item[role="button"] {{
      cursor: pointer;
    }}
    .notification-item[role="button"]:hover,
    .notification-item[role="button"]:focus-visible {{
      border-color: color-mix(in srgb, var(--accent) 52%, var(--border-strong));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 18%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 64%, transparent);
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.07) 42%, transparent),
        0 10px 24px rgba(8, 12, 18, 0.12);
      outline: none;
    }}
    .notification-tone {{
      display: inline-flex;
      align-items: center;
      gap: 0.38rem;
      font-weight: 700;
      letter-spacing: 0.01em;
    }}
    .notification-tone::before {{
      content: attr(data-icon);
      display: inline-grid;
      place-items: center;
      width: 1.1rem;
      height: 1.1rem;
      border-radius: 999px;
      background: color-mix(in srgb, var(--border) 82%, transparent);
      color: var(--text);
      font-size: 0.62rem;
      line-height: 1;
    }}
    .notification-item.unread {{
      border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent);
    }}
    .notification-meta {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 0.63rem;
      line-height: 1.2;
    }}
    .notification-title {{
      color: var(--text);
      font-size: 0.77rem;
      font-weight: 680;
      line-height: 1.25;
    }}
    .notification-detail {{
      color: color-mix(in srgb, var(--muted) 54%, var(--text));
      font-size: 0.71rem;
      line-height: 1.4;
    }}
    .notification-item.alert {{
      border-color: color-mix(in srgb, var(--danger) 48%, var(--border));
    }}
    .notification-item.alert .notification-tone::before {{
      background: color-mix(in srgb, var(--danger) 18%, var(--surface));
      color: var(--danger);
    }}
    .notification-item.queue {{
      border-color: color-mix(in srgb, var(--warn) 46%, var(--border));
    }}
    .notification-item.queue .notification-tone::before {{
      background: color-mix(in srgb, var(--warn) 18%, var(--surface));
      color: var(--warn);
    }}
    .notification-item.console {{
      border-color: color-mix(in srgb, var(--accent-2) 42%, var(--border));
    }}
    .notification-item.console .notification-tone::before {{
      background: color-mix(in srgb, var(--accent-2) 18%, var(--surface));
      color: var(--accent-2);
    }}
    .notification-item.info {{
      border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
    }}
    .notification-item.info .notification-tone::before {{
      background: color-mix(in srgb, var(--accent) 18%, var(--surface));
      color: var(--accent);
    }}
    .notification-empty {{
      color: var(--muted);
      font-size: 0.74rem;
      line-height: 1.45;
      padding: 4px 0 2px;
    }}
    .toast-stack {{
      position: fixed;
      right: 12px;
      top: calc(env(safe-area-inset-top) + 56px);
      z-index: 60;
      display: grid;
      gap: 8px;
      width: min(100vw - 24px, 360px);
      pointer-events: none;
      align-items: end;
    }}
    .toast {{
      display: grid;
      gap: 4px;
      padding: 10px 11px;
      border-radius: 12px;
      border: 1px solid color-mix(in srgb, var(--border) 78%, transparent);
      background: color-mix(in srgb, var(--surface) 95%, transparent);
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.16);
      pointer-events: auto;
      transition: transform 0.18s ease, opacity 0.18s ease, box-shadow 0.18s ease;
      touch-action: pan-y;
      will-change: transform, opacity;
    }}
    .toast.monitor {{
      width: 100%;
      font: inherit;
      text-align: left;
      border-color: color-mix(in srgb, var(--agent-accent) 34%, var(--border-strong));
      background:
        linear-gradient(180deg, color-mix(in srgb, rgba(255, 255, 255, 0.04) 54%, transparent), transparent 82%),
        color-mix(in srgb, var(--surface) 97%, transparent);
      box-shadow:
        0 12px 26px rgba(0, 0, 0, 0.2),
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 42%, transparent);
      cursor: pointer;
    }}
    .toast.monitor .toast-title-wrap::before {{
      animation: toastPulse 1.7s ease-in-out infinite;
    }}
    .toast.swiping {{
      transition: none;
    }}
    .toast.dismissing {{
      opacity: 0;
      transform: translateX(calc(100% + 18px));
      pointer-events: none;
    }}
    .system-panel::before,
    .switcher-panel::before,
    .settings-panel::before,
    .notices-panel::before {{
      content: "";
      display: none;
      width: 42px;
      height: 4px;
      margin: 0 auto;
      border-radius: 999px;
      background: color-mix(in srgb, var(--border-strong) 58%, transparent);
      opacity: 0.8;
    }}
    .toast-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .toast-title-wrap {{
      display: inline-flex;
      align-items: center;
      gap: 0.42rem;
      min-width: 0;
    }}
    .toast-title-wrap::before {{
      content: attr(data-icon);
      display: inline-grid;
      place-items: center;
      width: 1.08rem;
      height: 1.08rem;
      border-radius: 999px;
      background: color-mix(in srgb, var(--border) 82%, transparent);
      color: var(--text);
      font-size: 0.62rem;
      line-height: 1;
      flex: 0 0 auto;
    }}
    .toast-title {{
      color: var(--text);
      font-size: 0.76rem;
      font-weight: 700;
      line-height: 1.2;
    }}
    .toast-detail {{
      color: color-mix(in srgb, var(--muted) 52%, var(--text));
      font-size: 0.7rem;
      line-height: 1.35;
    }}
    .toast-time {{
      color: var(--muted);
      font-size: 0.62rem;
      white-space: nowrap;
    }}
    .toast.alert {{
      border-color: color-mix(in srgb, var(--danger) 50%, var(--border));
    }}
    .toast.alert .toast-title-wrap::before {{
      background: color-mix(in srgb, var(--danger) 18%, var(--surface));
      color: var(--danger);
    }}
    .toast.queue {{
      border-color: color-mix(in srgb, var(--warn) 48%, var(--border));
    }}
    .toast.queue .toast-title-wrap::before {{
      background: color-mix(in srgb, var(--warn) 18%, var(--surface));
      color: var(--warn);
    }}
    .toast.console {{
      border-color: color-mix(in srgb, var(--accent-2) 42%, var(--border));
    }}
    .toast.console .toast-title-wrap::before {{
      background: color-mix(in srgb, var(--accent-2) 18%, var(--surface));
      color: var(--accent-2);
    }}
    .toast.info {{
      border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
    }}
    .toast.info .toast-title-wrap::before {{
      background: color-mix(in srgb, var(--accent) 18%, var(--surface));
      color: var(--accent);
    }}
    .toast.active {{
      border-color: color-mix(in srgb, var(--agent-accent) 44%, var(--border));
    }}
    .toast.active .toast-title-wrap::before {{
      background: color-mix(in srgb, var(--agent-accent) 18%, var(--surface));
      color: var(--agent-accent);
    }}
    @keyframes toastPulse {{
      0%,
      100% {{
        transform: scale(1);
        box-shadow: 0 0 0 0 color-mix(in srgb, var(--agent-accent) 0%, transparent);
      }}
      50% {{
        transform: scale(1.08);
        box-shadow: 0 0 0 5px color-mix(in srgb, var(--agent-accent) 14%, transparent);
      }}
    }}
    .settings-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }}
    .switcher-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }}
    .switcher-head h2 {{
      margin: 0;
      font-size: 0.98rem;
      line-height: 1.2;
    }}
    .switcher-search-shell {{
      display: grid;
    }}
    .switcher-search-input {{
      width: 100%;
      min-height: 38px;
      padding: 9px 11px;
      border-radius: 14px;
      border: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
      background: color-mix(in srgb, var(--surface-2) 48%, transparent);
      color: var(--text);
      font: inherit;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }}
    .switcher-search-input::placeholder {{
      color: color-mix(in srgb, var(--muted) 82%, transparent);
    }}
    .switcher-views,
    .switcher-groups {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .switcher-chip {{
      display: inline-flex;
      align-items: center;
      gap: 0.38rem;
      min-height: 28px;
      padding: 4px 9px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
      background: color-mix(in srgb, var(--surface-2) 34%, transparent);
      color: var(--muted);
      font-size: 0.72rem;
      font-weight: 650;
    }}
    .switcher-chip.active {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 24%, var(--border-strong));
      background: color-mix(in srgb, var(--agent-accent) 10%, var(--surface-2));
      box-shadow: 0 8px 18px rgba(12, 16, 22, 0.08);
    }}
    .switcher-chip-count {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 18px;
      min-height: 18px;
      padding: 0 6px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 84%, transparent);
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      color: var(--text);
      font-size: 0.64rem;
      line-height: 1;
    }}
    .switcher-note {{
      color: var(--muted);
      font-size: 0.72rem;
      line-height: 1.4;
    }}
    .switcher-list {{
      display: grid;
      gap: 8px;
      max-height: min(58dvh, 520px);
      overflow: auto;
      scrollbar-gutter: stable;
      -webkit-overflow-scrolling: touch;
    }}
    .switcher-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 10px;
      padding: 9px 10px;
      border-radius: 15px;
      border: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 10%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 46%, transparent);
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 34%, transparent),
        0 8px 18px rgba(8, 12, 18, 0.08);
    }}
    .switcher-item.is-current {{
      border-color: color-mix(in srgb, var(--agent-accent) 34%, var(--border));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--agent-accent) 14%, transparent);
    }}
    .switcher-link {{
      display: grid;
      gap: 4px;
      min-width: 0;
      color: inherit;
      text-decoration: none;
    }}
    .switcher-link:hover .switcher-item-title,
    .switcher-link:focus-visible .switcher-item-title {{
      color: var(--agent-accent);
    }}
    .switcher-item-title-row {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      flex-wrap: wrap;
    }}
    .switcher-item-title {{
      color: var(--text);
      font-size: 0.82rem;
      font-weight: 720;
      line-height: 1.2;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .switcher-item-group,
    .switcher-item-host,
    .switcher-item-current {{
      display: inline-flex;
      align-items: center;
      min-height: 18px;
      padding: 0 6px;
      border-radius: 999px;
      font-size: 0.62rem;
      line-height: 1;
      border: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
      background: color-mix(in srgb, var(--surface) 76%, transparent);
      color: var(--muted);
      white-space: nowrap;
    }}
    .switcher-item-current {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--agent-accent) 28%, var(--border));
      background: color-mix(in srgb, var(--agent-accent) 10%, var(--surface));
    }}
    .switcher-item-host {{
      min-height: 0;
      padding: 0;
      border: 0;
      background: transparent;
      color: inherit;
    }}
    .switcher-item-host::before {{
      content: none;
    }}
    .switcher-item-host .entity-cartouche {{
      margin: 0;
    }}
    .switcher-item-meta {{
      color: color-mix(in srgb, var(--muted) 56%, var(--text));
      font-size: 0.7rem;
      line-height: 1.35;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .switcher-pin {{
      min-height: 28px;
      min-width: 28px;
      padding: 0 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      line-height: 1;
    }}
    .switcher-pin.active {{
      color: var(--text);
      border-color: color-mix(in srgb, var(--warn) 36%, var(--border-strong));
      background: color-mix(in srgb, var(--warn) 10%, var(--surface-2));
    }}
    .switcher-empty {{
      color: var(--muted);
      font-size: 0.74rem;
      line-height: 1.45;
      padding: 4px 0 2px;
    }}
    .settings-head h2 {{
      margin: 0;
      font-size: 0.98rem;
      line-height: 1.2;
    }}
    .settings-head p {{
      margin: 4px 0 0;
    }}
    .settings-card {{
      display: grid;
      gap: 8px;
    }}
    .settings-label {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      color: var(--muted);
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.045em;
    }}
    .settings-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }}
    .setting-pill {{
      min-height: 30px;
      padding: 5px 9px;
      font-size: 0.76rem;
    }}
    .setting-pill.active {{
      background: var(--surface-3);
      border-color: var(--border-strong);
      color: var(--text);
    }}
    .settings-note {{
      color: var(--muted);
      font-size: 0.78rem;
      line-height: 1.45;
    }}
    .system-panel {{
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      z-index: 40;
    }}
    .system-panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      padding: 14px 14px 0;
    }}
    .system-panel-head h2,
    .system-card h2 {{
      margin: 0;
      font-size: 1rem;
      line-height: 1.2;
    }}
    .system-panel-body {{
      display: grid;
      gap: 14px;
      overflow: auto;
      padding: 12px 14px 14px;
      scrollbar-gutter: stable;
      -webkit-overflow-scrolling: touch;
    }}
    .system-card {{
      display: grid;
      gap: 10px;
      min-width: 0;
      padding: 12px;
      border-top: 0;
      border-radius: 16px;
      border: 1px solid color-mix(in srgb, var(--border) 30%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 18%, transparent), transparent 74%),
        color-mix(in srgb, var(--surface-2) 34%, transparent);
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.04) 38%, transparent),
        0 10px 22px rgba(8, 12, 18, 0.08);
    }}
    .system-card:first-child {{
      padding-top: 12px;
    }}
    .system-card h3 {{
      margin: 0;
      font-size: 0.76rem;
      line-height: 1.2;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .system-card-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
    }}
    .raw-grid {{
      display: grid;
      gap: 10px;
    }}
    .mono {{
      font-family: "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace;
    }}
    .subtle {{
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .system-note {{
      font-size: 0.84rem;
      color: var(--muted);
    }}
    .services {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .service-chip {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      border-radius: 999px;
      padding: 7px 10px;
      background: var(--surface-2);
      color: var(--muted);
      border: 1px solid var(--border);
      font-size: 0.82rem;
    }}
    .service-chip::before {{
      content: "";
      width: 0.55rem;
      height: 0.55rem;
      border-radius: 999px;
      background: currentColor;
      opacity: 0.72;
      flex: 0 0 auto;
    }}
    .service-chip.active {{
      color: var(--accent-2);
      border-color: var(--border);
    }}
    .service-chip.failed,
    .service-chip.inactive {{
      color: var(--danger);
      border-color: var(--danger);
    }}
    .service-chip.activating,
    .service-chip.deactivating {{
      color: var(--warn);
      border-color: var(--warn);
    }}
    details {{
      border-top: 1px solid var(--border);
      padding-top: 10px;
    }}
    details:first-of-type {{
      border-top: 0;
      padding-top: 0;
    }}
    details summary {{
      cursor: pointer;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    pre {{
      margin: 0;
      padding: 10px 11px;
      border-radius: 14px;
      background: var(--bg-soft);
      border: 1px solid var(--border);
      white-space: pre-wrap;
      word-break: break-word;
      overflow: auto;
      max-height: 22vh;
      font-size: 0.86rem;
      font-family: "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace;
      scrollbar-gutter: stable;
      -webkit-overflow-scrolling: touch;
      overscroll-behavior: contain;
    }}
    pre,
    textarea {{
      user-select: text;
      -webkit-user-select: text;
    }}
    @keyframes spin {{
      to {{
        transform: rotate(360deg);
      }}
    }}
    @media (min-width: 980px) {{
      .app-shell {{
        max-width: none;
      }}
      .topbar {{
        width: 100%;
        margin-inline: 0;
      }}
      .console-nav {{
        width: min(100%, 1080px);
        margin-inline: auto;
      }}
      .topbar {{
        padding: 10px 14px 9px;
      }}
      .brand h1 {{
        font-size: 1.62rem;
      }}
      .brand-line {{
        gap: 8px;
      }}
      .status-copy {{
        font-size: 0.74rem;
        max-width: 40rem;
      }}
      .pill {{
        font-size: 0.76rem;
      }}
      .topbar-menu-button {{
        min-height: 30px;
        padding: 3px 11px;
        font-size: 0.73rem;
      }}
      .topbar-menu {{
        width: min(340px, calc(100vw - 28px));
      }}
      .console-nav {{
        gap: 6px;
        padding-bottom: 0;
      }}
      .console-nav-shell {{
        gap: 5px;
      }}
      .console-nav-groups,
      .console-nav-panel {{
        flex-wrap: wrap;
        overflow: visible;
      }}
      .console-group-pill {{
        min-height: 30px;
        font-size: 0.74rem;
        padding: 3px 12px;
      }}
      .console-nav .quick-link {{
        min-height: 24px;
        padding: 3px 9px;
        font-size: 0.7rem;
      }}
      .workspace {{
        grid-template-columns: minmax(0, 1fr);
        padding: 0 14px 14px;
      }}
      .chat-shell,
      .system-panel {{
        min-height: calc(100dvh - 74px);
      }}
      .chat-shell {{
        --reading-lane: 820px;
        --conversation-lane: 980px;
        padding-inline: clamp(8px, 1.4vw, 18px);
      }}
      .chat-main {{
        gap: 1px;
        padding-bottom: calc(22px + var(--composer-reserve));
      }}
      .chat-main > .chat-summary-bar,
      .chat-main > .notice-rail,
      .chat-main > .history-toolbar,
      .chat-main > .conversation,
      .chat-shell > .activity-strip,
      .chat-shell > .composer-wrap {{
        margin-inline: auto;
      }}
      .chat-main > .chat-summary-bar,
      .chat-main > .notice-rail,
      .chat-main > .history-toolbar,
      .chat-shell > .activity-strip {{
        width: min(100%, calc(var(--reading-lane) - 12px));
      }}
      .chat-main > .conversation {{
        width: min(100%, var(--conversation-lane));
      }}
      .chat-shell > .composer-wrap {{
        width: 100%;
      }}
      .conversation {{
        gap: 3px;
        padding: 2px 1px calc(76px + var(--composer-reserve));
        min-height: clamp(180px, 38vh, 440px);
      }}
      .message {{
        padding: 5px 7px 6px;
      }}
      .message.assistant .message-body,
      .raw-view {{
        font-size: 1rem;
        line-height: 1.7;
      }}
      .message.user .message-body,
      .message.pending .message-body,
      .message.queued .message-body,
      .message.error .message-body {{
        font-size: 0.94rem;
        line-height: 1.6;
      }}
      .message.assistant .message-body > p,
      .message.assistant .message-body > ul,
      .message.assistant .message-body > ol,
      .message.assistant .message-body > blockquote,
      .message.assistant .message-body > .callout,
      .message.assistant .message-body > .kv-list,
      .message.assistant .message-body > .task-list,
      .message.assistant .message-body > hr {{
        max-width: min(70ch, 100%);
      }}
      textarea {{
        min-height: 44px;
        font-size: 0.96rem;
        line-height: 1.4;
      }}
      .jump-latest {{
        right: max(12px, calc((100% - var(--reading-lane)) / 2 + 14px));
      }}
      .system-panel {{
        position: fixed;
        top: 74px;
        right: 14px;
        bottom: 14px;
        width: min(360px, calc(100vw - 28px));
        max-height: none;
        opacity: 0;
        pointer-events: none;
        transform: translateX(calc(100% + 18px));
        transition: transform 0.2s ease, opacity 0.2s ease;
        box-shadow:
          0 18px 46px rgba(10, 14, 20, 0.22),
          inset 0 1px 0 rgba(255, 255, 255, 0.03);
      }}
      body.system-open .system-panel {{
        opacity: 1;
        pointer-events: auto;
        transform: translateX(0);
      }}
      .system-toggle,
      .system-close {{
        display: inline-flex;
      }}
      .system-backdrop {{
        display: block;
      }}
      body.system-open .system-backdrop {{
        opacity: 1;
        pointer-events: auto;
      }}
    }}
    @media (max-width: 979px) {{
      .app-shell {{
        padding: 0;
      }}
      .topbar {{
        align-items: flex-start;
        top: 0;
        padding: 8px 12px 7px;
      }}
      .topbar-actions {{
        justify-content: flex-start;
      }}
      .switcher-toggle-button {{
        min-width: 32px;
        min-height: 30px;
        padding: 0 9px;
        font-size: 0;
      }}
      .switcher-toggle-label {{
        display: none;
      }}
      .topbar-menu {{
        position: fixed;
        left: 10px;
        right: 10px;
        top: auto;
        bottom: 10px;
        width: auto;
        transform: translateY(calc(100% + 18px));
        transform-origin: bottom center;
      }}
      body.topbar-menu-open .topbar-menu {{
        transform: translateY(0);
      }}
      .topbar-menu-links {{
        grid-template-columns: 1fr;
      }}
      .workspace {{
        display: block;
        padding: 0 6px 8px;
      }}
      .chat-shell {{
        min-height: calc(100dvh - 64px);
      }}
      .system-backdrop {{
        display: block;
      }}
      body.system-open .system-backdrop {{
        opacity: 1;
        pointer-events: auto;
      }}
      .system-panel {{
        position: fixed;
        left: 10px;
        right: 10px;
        bottom: 10px;
        max-height: min(84dvh, 820px);
        transform: translateY(calc(100% + 18px));
        opacity: 0;
        pointer-events: none;
        transition: transform 0.2s ease, opacity 0.2s ease;
      }}
      body.system-open .system-panel {{
        transform: translateY(0);
        opacity: 1;
        pointer-events: auto;
      }}
      .switcher-panel {{
        left: 10px;
        right: 10px;
        top: auto;
        bottom: 10px;
        width: auto;
        max-height: min(84dvh, 820px);
        transform: translateY(calc(100% + 18px));
      }}
      body.switcher-open .switcher-panel {{
        transform: translateY(0);
      }}
      .settings-panel {{
        left: 10px;
        right: 10px;
        top: auto;
        bottom: 10px;
        width: auto;
        transform: translateY(calc(100% + 18px));
      }}
      .notices-panel {{
        left: 10px;
        right: 10px;
        top: auto;
        bottom: 10px;
        width: auto;
        transform: translateY(calc(100% + 18px));
      }}
      body.settings-open .settings-panel {{
        transform: translateY(0);
      }}
      body.notices-open .notices-panel {{
        transform: translateY(0);
      }}
      .console-nav {{
        display: none;
      }}
      .message {{
        max-width: 100%;
      }}
    }}
    @media (min-width: 1440px) {{
      .app-shell {{
        max-width: 1320px;
      }}
      .topbar,
      .console-nav {{
        width: min(100%, 1080px);
      }}
      .chat-shell {{
        --reading-lane: 820px;
        --conversation-lane: 920px;
      }}
      .message.assistant .message-body,
      .raw-view {{
        font-size: 1.03rem;
        line-height: 1.72;
      }}
      .message-body h1,
      .raw-view h1 {{
        font-size: 1.34rem;
      }}
      .message-body h2,
      .raw-view h2 {{
        font-size: 1.18rem;
      }}
    }}
    @media (max-width: 640px) {{
      body::after {{
        inset: 4px;
        border-radius: 18px;
        opacity: 0.48;
      }}
      body {{
        overscroll-behavior-y: auto;
      }}
      .app-shell {{
        padding:
          max(6px, env(safe-area-inset-top))
          6px
          calc(8px + env(safe-area-inset-bottom));
      }}
      .topbar,
      .chat-shell {{
        padding: 7px;
      }}
      .topbar {{
        top: 4px;
        flex-direction: row;
        align-items: center;
        gap: 6px;
      }}
      .topbar.surface {{
        border-radius: 15px;
      }}
      .brand {{
        flex: 1 1 auto;
      }}
      .brand-line {{
        flex-wrap: nowrap;
        justify-content: flex-start;
        gap: 6px;
      }}
      .brand h1 {{
        min-width: 0;
        max-width: 100%;
        font-size: 0.9rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      body.quiet-status .brand {{
        min-width: 0;
        flex: 1;
      }}
      .brand-line {{
        justify-content: flex-start;
      }}
      .topbar-actions {{
        width: auto;
        justify-content: flex-end;
        flex-wrap: nowrap;
        gap: 3px;
      }}
      #prime-home-button,
      #directory-home-button {{
        display: none;
      }}
      .switcher-toggle-button,
      .topbar-menu-button {{
        min-width: 32px;
        min-height: 30px;
        padding: 0 8px;
        font-size: 0;
      }}
      .switcher-toggle-label,
      .topbar-menu-button-label {{
        display: none;
      }}
      .status-copy {{
        display: none;
      }}
      .console-nav {{
        padding-left: 0;
        padding-right: 0;
        padding-bottom: 1px;
      }}
      .console-nav-label,
      .console-group-count {{
        display: none;
      }}
      #route-chip,
      #last-updated-head {{
        display: none;
      }}
      #chat-session-chip {{
        display: none;
      }}
      .chat-summary-bar {{
        gap: 2px;
        padding-bottom: 0;
      }}
      .kpi-strip {{
        flex-wrap: nowrap;
        overflow-x: auto;
        padding-bottom: 2px;
        scrollbar-width: none;
        scroll-snap-type: x proximity;
      }}
      .kpi-strip::-webkit-scrollbar {{
        display: none;
      }}
      .kpi-capsule {{
        min-width: max-content;
        flex: 0 0 auto;
        padding: 4px 8px;
        border-radius: 999px;
        scroll-snap-align: start;
      }}
      .kpi-capsule-label {{
        font-size: 0.47rem;
      }}
      .kpi-capsule-value {{
        font-size: 0.66rem;
      }}
      .meta-chip {{
        font-size: 0.62rem;
      }}
      .topbar-menu-shortcuts {{
        display: none;
      }}
      .context-meter-track {{
        flex-basis: 24px;
        width: 24px;
      }}
      .context-save-button {{
        min-height: 20px;
        padding: 1px 7px;
        font-size: 0.57rem;
      }}
      .activity-strip {{
        padding: 3px 6px;
        grid-template-columns: auto minmax(0, 1fr) auto;
        gap: 6px 8px;
      }}
      .activity-title {{
        font-size: 0.66rem;
      }}
      .activity-detail {{
        font-size: 0.6rem;
      }}
      .activity-copy {{
        grid-column: 2;
        gap: 5px;
      }}
      .activity-actions {{
        grid-column: 3;
        grid-row: 1;
        justify-self: end;
      }}
      .activity-track {{
        grid-column: 2;
        grid-row: 2;
        justify-content: flex-start;
        width: 100%;
      }}
      .activity-track-summary {{
        max-width: 11ch;
      }}
      .system-panel-head,
      .system-panel-body {{
        padding-left: 12px;
        padding-right: 12px;
      }}
      .system-panel,
      .settings-panel,
      .notices-panel {{
        left: 0;
        right: 0;
        bottom: 0;
        width: auto;
        max-height: min(90dvh, 920px);
        border-radius: 18px 18px 0 0;
        box-shadow:
          0 -18px 42px rgba(10, 14, 20, 0.22),
          inset 0 1px 0 rgba(255, 255, 255, 0.03);
      }}
      .system-panel::before,
      .settings-panel::before,
      .notices-panel::before {{
        display: block;
        margin-top: 8px;
      }}
      .system-panel-body,
      .settings-panel,
      .notices-panel,
      .notifications-list {{
        padding-bottom: calc(12px + env(safe-area-inset-bottom));
      }}
      .settings-panel,
      .notices-panel {{
        padding-top: 10px;
      }}
      .system-panel-head,
      .settings-head,
      .notices-head {{
        padding-top: 2px;
      }}
      .suggestions {{
        overflow-x: auto;
        flex-wrap: nowrap;
        padding-bottom: 2px;
        justify-content: flex-start;
        width: 100%;
        scrollbar-width: none;
        scroll-snap-type: x proximity;
      }}
      .suggestions::-webkit-scrollbar {{
        display: none;
      }}
      .sample-prompt-strip {{
        gap: 5px;
        padding: 0 0 1px;
      }}
      .sample-prompt-label {{
        display: none;
      }}
      .sample-prompt-list {{
        width: 100%;
      }}
      .draft-attachments {{
        overflow-x: auto;
        flex-wrap: nowrap;
        padding-bottom: 2px;
        scrollbar-width: none;
        scroll-snap-type: x proximity;
      }}
      .draft-attachments::-webkit-scrollbar {{
        display: none;
      }}
      .notice-rail {{
        flex-wrap: nowrap;
        scroll-snap-type: x proximity;
      }}
      .notice-chip,
      .link-chip-row {{
        flex: 0 0 auto;
      }}
      .attachment-chip-row,
      .suggestion-chip {{
        scroll-snap-align: start;
      }}
      .attachment-chip {{
        max-width: min(100%, 220px);
      }}
      .attachment-thumb {{
        width: 22px;
        height: 22px;
        border-radius: 7px;
      }}
      .message-file-previews {{
        grid-template-columns: 1fr;
        gap: 4px;
      }}
      .message-file-preview-gallery {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 5px;
      }}
      .inline-file-preview {{
        padding: 3px 5px;
        border-radius: 10px;
      }}
      .inline-file-preview-head {{
        gap: 5px;
      }}
      .inline-file-preview-meta {{
        gap: 4px;
      }}
      .inline-file-preview-actions {{
        gap: 2px;
      }}
      .inline-file-preview-name {{
        max-width: 36vw;
      }}
      .inline-file-preview .inline-action {{
        min-height: 18px;
        padding: 1px 5px;
        font-size: 0.6rem;
      }}
      .inline-image-preview-caption {{
        min-height: 22px;
        padding: 4px 6px;
        font-size: 0.62rem;
      }}
      .inline-file-preview-body img {{
        max-height: min(240px, 34vh);
      }}
      .inline-file-preview-text {{
        font-size: 0.72rem;
        max-height: min(190px, 28vh);
      }}
      .jump-latest {{
        right: 8px;
        bottom: calc(92px + env(safe-area-inset-bottom));
        min-height: 32px;
        padding: 5px 10px;
        box-shadow: 0 10px 22px rgba(0, 0, 0, 0.18);
      }}
      .toast-stack {{
        left: 8px;
        right: 8px;
        top: calc(env(safe-area-inset-top) + 62px);
        width: auto;
        align-items: stretch;
      }}
      .attachment-meta {{
        display: none;
      }}
      .attachment-chip-row {{
        flex: 0 0 auto;
      }}
      .response-bar {{
        width: 100%;
        gap: 7px;
        display: grid;
        grid-template-columns: minmax(0, 1fr);
      }}
      .composer-toolbar-head {{
        align-items: center;
      }}
    .composer-tools-toggle {{
        min-height: 23px;
        padding: 2px 7px;
        font-size: 0.64rem;
      }}
      .composer-upload-button {{
        min-width: 28px;
        padding: 0;
      }}
      .composer-upload-label {{
        display: none;
      }}
      .composer-inline-actions {{
        left: 6px;
        bottom: 6px;
        gap: 2px;
      }}
      .composer-inline-action {{
        width: 24px;
        min-width: 24px;
        min-height: 24px;
        border-radius: 8px;
      }}
      .composer-toolbar {{
        left: 6px;
        right: auto;
        width: min(420px, calc(100vw - 20px));
        bottom: calc(100% + 6px);
      }}
      .response-range {{
        min-width: 52px;
      }}
      .kv-row {{
        grid-template-columns: 1fr;
        gap: 0.3rem;
      }}
      .kv-key {{
        font-size: 0.62rem;
      }}
      .suggestion-chip {{
        flex: 0 0 auto;
      }}
      .message-footer,
      .message-links {{
        flex-wrap: nowrap;
        overflow-x: auto;
        padding-bottom: 2px;
        scrollbar-width: none;
        scroll-snap-type: x proximity;
      }}
      .message-footer {{
        position: static;
        max-width: 100%;
        width: auto;
        align-self: stretch;
        display: flex;
        align-items: center;
        gap: 4px;
        min-width: 0;
        margin-top: 7px;
        padding: 5px 6px;
        border-radius: 14px;
        box-shadow: none;
        backdrop-filter: none;
      }}
      .message-tools-toggle {{
        min-width: 24px;
        min-height: 24px;
        padding: 0;
        border-radius: 999px;
      }}
      .reply-tail-actions {{
        flex-wrap: nowrap;
        gap: 4px;
        margin-top: 6px;
        padding-top: 0;
        padding-bottom: 2px;
        border-top: 0;
        overflow-x: auto;
        scrollbar-width: none;
        scroll-snap-type: x proximity;
      }}
      .reply-tail-actions::-webkit-scrollbar {{
        display: none;
      }}
      .reply-tail-action {{
        min-height: 22px;
        padding: 2px 7px;
        font-size: 0.66rem;
        white-space: nowrap;
        scroll-snap-align: start;
      }}
      .message-links {{
        display: flex;
      }}
      .message-footer::-webkit-scrollbar,
      .message-links::-webkit-scrollbar {{
        display: none;
      }}
      .code-head {{
        gap: 8px;
        padding: 5px 9px;
      }}
      .code-head span:last-child {{
        display: none;
      }}
      .code-head-actions {{
        gap: 5px;
      }}
      .code-toggle-button,
      .code-copy-button {{
        min-height: 24px;
        padding: 2px 7px;
        font-size: 0.65rem;
      }}
      .code-preview {{
        padding: 8px 10px 10px;
      }}
      .code-preview pre {{
        font-size: 0.74rem;
        line-height: 1.48;
      }}
      .code-preview-meta {{
        margin-top: 6px;
        font-size: 0.63rem;
      }}
      .code-block pre {{
        padding: 10px 10px 11px;
        font-size: 0.76rem;
        line-height: 1.52;
      }}
      .link-copy-button {{
        flex: 0 0 auto;
      }}
      textarea {{
        min-height: 46px;
        padding: 6px 0 7px;
        line-height: 1.34;
      }}
      .composer-send {{
        width: 26px;
        min-width: 26px;
        min-height: 26px;
        padding: 0;
      }}
      .composer-wrap {{
        position: sticky;
        bottom: 0;
        z-index: 6;
        margin-inline: 0;
        padding: 4px 0 calc(4px + env(safe-area-inset-bottom));
        background:
          linear-gradient(
            180deg,
            color-mix(in srgb, var(--bg) 28%, transparent) 0%,
            color-mix(in srgb, var(--bg) 90%, transparent) 24%,
            var(--bg) 100%
          );
      }}
      .composer-wrap::before {{
        content: none;
      }}
      .composer-wrap::after {{
        left: 16px;
        right: 16px;
        top: 0;
        height: 18px;
      }}
      body.mobile-keyboard-open .topbar {{
        top: 0;
      }}
      body.mobile-keyboard-open .workspace {{
        scroll-padding-bottom: calc(var(--composer-reserve) + 56px + env(safe-area-inset-bottom));
      }}
      body.mobile-compose-mode .workspace {{
        padding-bottom: 2px;
        overscroll-behavior-y: auto;
      }}
      body.mobile-compose-mode .chat-shell {{
        gap: 2px;
      }}
      body.mobile-compose-mode .chat-summary-bar,
      body.mobile-compose-mode .kpi-strip,
      body.mobile-compose-mode .notice-rail,
      body.mobile-compose-mode .history-toolbar,
      body.mobile-compose-mode .activity-strip {{
        opacity: 0;
        max-height: 0;
        min-height: 0;
        margin: 0;
        padding-top: 0;
        padding-bottom: 0;
        overflow: hidden;
        pointer-events: none;
      }}
      body.mobile-compose-mode .activity-strip.visible,
      body.mobile-compose-mode .kpi-strip.visible,
      body.mobile-compose-mode .notice-rail.visible,
      body.mobile-compose-mode .history-toolbar.visible {{
        display: flex;
      }}
      body.mobile-compose-mode .activity-strip.visible {{
        display: grid;
      }}
      body.mobile-compose-mode .context-save-button {{
        display: none;
      }}
      body.mobile-compose-mode #switcher-toggle-button {{
        display: none;
      }}
      body.mobile-compose-mode .message-tools,
      body.mobile-compose-mode .message-footer,
      body.mobile-compose-mode .reply-tail-actions {{
        display: none;
      }}
      body.mobile-compose-mode .composer-wrap {{
        gap: 4px;
      }}
      body.mobile-keyboard-open .composer-wrap {{
        padding-bottom: max(2px, env(safe-area-inset-bottom));
        background:
          linear-gradient(
            180deg,
            color-mix(in srgb, var(--bg) 14%, transparent) 0%,
            color-mix(in srgb, var(--bg) 96%, transparent) 26%,
            var(--bg) 100%
          );
      }}
      body.mobile-keyboard-open .chat-main {{
        padding-bottom: calc(16px + var(--composer-reserve));
      }}
      body.mobile-keyboard-open .conversation {{
        padding-bottom: calc(58px + var(--composer-reserve));
      }}
      body.mobile-compose-mode .composer-input-shell {{
        border-radius: 16px;
        padding: 8px;
        gap: 7px 8px;
        box-shadow:
          0 14px 30px rgba(8, 12, 18, 0.12),
          inset 0 1px 0 color-mix(in srgb, rgba(255, 255, 255, 0.05) 44%, transparent),
          inset 0 -1px 0 color-mix(in srgb, rgba(0, 0, 0, 0.10) 30%, transparent);
      }}
      .composer.idle .composer-send {{
        min-height: 24px;
      }}
      .composer-toolbar {{
        gap: 6px;
      }}
      .chat-main {{
        padding-bottom: calc(24px + var(--composer-reserve));
      }}
      .conversation {{
        padding: 2px 0 calc(74px + var(--composer-reserve));
        border-radius: 0;
        gap: 3px;
        min-height: clamp(168px, 32vh, 340px);
      }}
      .message {{
        padding: 5px 6px 6px;
        border-radius: 8px;
      }}
      .message.assistant .message-body,
      .raw-view {{
        font-size: 0.97rem;
        line-height: 1.68;
      }}
      .message.user .message-body,
      .message.pending .message-body,
      .message.queued .message-body,
      .message.error .message-body {{
        font-size: 0.89rem;
        line-height: 1.53;
      }}
      .message-head {{
        margin-bottom: 4px;
      }}
      .message-role {{
        min-height: 18px;
        padding: 1px 6px;
      }}
      .timeline-divider {{
        padding: 4px 0 2px;
        font-size: 0.63rem;
      }}
      .toast-stack {{
        right: 8px;
        left: 8px;
        width: auto;
        top: calc(env(safe-area-inset-top) + 58px);
      }}
      body[data-density="compact"] .topbar,
      body[data-density="compact"] .chat-shell {{
        padding: 8px;
      }}
      body[data-density="compact"] .composer-wrap {{
        padding-top: 6px;
      }}
      body[data-density="compact"] .brand h1 {{
        font-size: 1.12rem;
      }}
    }}
    body[data-density="compact"] .app-shell {{
      gap: 5px;
      padding: 0;
    }}
    body[data-density="compact"] .chat-shell {{
      padding: 6px;
    }}
    body[data-density="compact"] .conversation {{
      gap: 3px;
      padding: 2px 1px calc(74px + var(--composer-reserve));
    }}
    body[data-density="compact"] .message {{
      padding: 4px 6px;
      border-radius: 8px;
    }}
    body[data-view-mode="stage"] .message {{
      max-width: min(94%, 1020px);
      padding: 10px 12px;
      border-radius: 16px;
    }}
    body[data-view-mode="stage"] .message.assistant {{
      max-width: min(96%, 1140px);
    }}
    body[data-view-mode="stage"] .message-body {{
      font-size: 1.03rem;
      line-height: 1.68;
    }}
    body[data-view-mode="stage"] .message.assistant .message-body {{
      font-size: 1.08rem;
      line-height: 1.74;
    }}
    body[data-view-mode="stage"] .history-inline-teaser,
    body[data-view-mode="stage"] .history-toggle,
    body[data-view-mode="stage"] .jump-latest {{
      font-size: 0.8rem;
    }}
    body[data-view-mode="stage"] .activity-strip {{
      padding: 6px 8px;
    }}
    body[data-view-mode="stage"] .composer-drop-hint {{
      font-size: 0.72rem;
    }}
    body[data-density="compact"] .composer-wrap {{
      gap: 4px;
      padding-top: 6px;
    }}
    body[data-density="compact"] .composer-meta {{
      gap: 3px;
      margin-bottom: 0;
    }}
    body[data-density="compact"] .response-bar {{
      gap: 8px;
    }}
    body[data-density="compact"] textarea {{
      min-height: 48px;
      padding: 5px 0 6px;
    }}
    body[data-density="compact"] .topbar {{
      padding: 5px 7px;
    }}
    body[data-layout-mode="tile"] .app-shell {{
      gap: 4px;
      padding: 0;
      max-width: 100%;
    }}
    body[data-layout-mode="tile"] .topbar {{
      padding: 3px 5px;
      min-height: 34px;
      gap: 8px;
    }}
    body[data-layout-mode="tile"] .brand {{
      gap: 6px;
    }}
    body[data-layout-mode="tile"] .brand h1 {{
      font-size: 1.08rem;
      letter-spacing: 0;
    }}
    body[data-layout-mode="tile"] .status-copy {{
      font-size: 0.64rem;
      line-height: 1.18;
      max-width: 34ch;
    }}
    body[data-layout-mode="tile"] .topbar-actions {{
      gap: 4px;
    }}
    body[data-layout-mode="tile"] .console-nav {{
      gap: 3px;
      padding: 1px 0 2px;
    }}
    body[data-layout-mode="tile"] .console-nav-shell {{
      gap: 4px;
    }}
    body[data-layout-mode="tile"] .console-focus {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4px;
    }}
    body[data-layout-mode="tile"] .console-focus-toggle {{
      min-height: 22px;
      padding: 3px 6px;
    }}
    body[data-layout-mode="tile"] .console-focus-toggle-label {{
      font-size: 0.64rem;
    }}
    body[data-layout-mode="tile"] .console-focus-toggle-summary {{
      font-size: 0.6rem;
    }}
    body[data-layout-mode="tile"] .console-focus-panel {{
      padding: 4px;
    }}
    body[data-layout-mode="tile"] .focus-lane {{
      padding: 6px 7px 7px;
      gap: 5px;
    }}
    body[data-layout-mode="tile"] .focus-lane p {{
      display: none;
    }}
    body[data-layout-mode="tile"] .focus-card {{
      min-height: 62px;
      padding: 8px;
      gap: 4px;
    }}
    body[data-layout-mode="tile"] .focus-card-title {{
      font-size: 0.78rem;
    }}
    body[data-layout-mode="tile"] .focus-card-note {{
      font-size: 0.63rem;
      -webkit-line-clamp: 1;
    }}
    body[data-layout-mode="tile"] .console-group-pill,
    body[data-layout-mode="tile"] .console-nav .quick-link {{
      min-height: 18px;
      padding: 1px 6px;
      font-size: 0.56rem;
    }}
    body[data-layout-mode="tile"] .activity-strip {{
      grid-template-columns: auto minmax(0, 1fr) auto;
      gap: 5px 6px;
      padding: 3px 6px;
    }}
    body[data-layout-mode="tile"] .activity-actions {{
      grid-column: 3;
      grid-row: 1;
      justify-self: end;
    }}
    body[data-layout-mode="tile"] .activity-track {{
      grid-column: 2;
      grid-row: 2;
      justify-content: flex-start;
      gap: 4px;
      width: 100%;
    }}
    body[data-layout-mode="tile"] .activity-track-summary {{
      max-width: 11ch;
    }}
    body[data-layout-mode="tile"] .workspace {{
      scroll-padding-bottom: calc(var(--composer-reserve) + 56px + env(safe-area-inset-bottom));
    }}
    body[data-layout-mode="tile"] .workspace::-webkit-scrollbar {{
      width: 6px;
    }}
    body[data-layout-mode="tile"] .workspace::-webkit-scrollbar-thumb {{
      border-width: 1px;
      min-height: 22px;
      background: color-mix(in srgb, var(--text-dim) 42%, transparent);
    }}
    body[data-layout-mode="tile"] .chat-shell {{
      --reading-lane: 680px;
      --conversation-lane: 760px;
      gap: 2px;
      padding: 3px 4px 6px;
    }}
    body[data-layout-mode="tile"] .chat-main {{
      gap: 1px;
      padding-bottom: calc(18px + var(--composer-reserve));
    }}
    body[data-layout-mode="tile"] .chat-summary-bar {{
      gap: 2px;
      padding-bottom: 0;
    }}
    body[data-layout-mode="tile"] .notice-rail {{
      padding-bottom: 1px;
    }}
    body[data-layout-mode="tile"] .meta-chip {{
      min-height: 16px;
      padding: 1px 4px;
      font-size: 0.54rem;
    }}
    body[data-layout-mode="tile"] .context-meter-track {{
      flex-basis: 20px;
      width: 20px;
    }}
    body[data-layout-mode="tile"] .conversation {{
      gap: 2px;
      min-height: clamp(124px, 26vh, 260px);
      padding: 1px 0 calc(58px + var(--composer-reserve));
    }}
    body[data-layout-mode="tile"] .message {{
      padding: 4px 5px 5px;
      border-radius: 7px;
    }}
    body[data-layout-mode="tile"] .message-head {{
      margin-bottom: 3px;
    }}
    body[data-layout-mode="tile"] .message.assistant .message-body,
    body[data-layout-mode="tile"] .raw-view {{
      font-size: 0.93rem;
      line-height: 1.57;
    }}
    body[data-layout-mode="tile"] .message.user .message-body,
    body[data-layout-mode="tile"] .message.pending .message-body,
    body[data-layout-mode="tile"] .message.queued .message-body,
    body[data-layout-mode="tile"] .message.error .message-body {{
      font-size: 0.84rem;
      line-height: 1.45;
    }}
    body[data-layout-mode="tile"] .history-toolbar {{
      padding-top: 1px;
    }}
    body[data-layout-mode="tile"] .timeline-divider {{
      padding: 3px 0 1px;
      font-size: 0.61rem;
    }}
    body[data-layout-mode="tile"] .composer-wrap {{
      gap: 5px;
      padding-top: 5px;
    }}
    body[data-layout-mode="tile"] .composer-input-shell {{
      border-radius: 16px;
      padding: 8px;
      gap: 6px 7px;
      box-shadow:
        0 10px 22px rgba(6, 10, 16, 0.11),
        inset 0 1px 0 rgba(255, 255, 255, 0.018);
    }}
    body[data-layout-mode="tile"] .composer-inline-actions {{
      gap: 3px;
    }}
    body[data-layout-mode="tile"] .composer-inline-action,
    body[data-layout-mode="tile"] .composer-tools-inline {{
      width: 22px;
      min-width: 22px;
      min-height: 22px;
    }}
    body[data-layout-mode="tile"] textarea {{
      min-height: 46px;
      padding: 5px 0 6px;
      line-height: 1.36;
    }}
    body[data-layout-mode="tile"] .composer-send {{
      width: 26px;
      min-width: 26px;
      min-height: 26px;
    }}
    body[data-layout-mode="tile"] .composer-toolbar {{
      gap: 4px;
      padding-inline: 2px;
    }}
    @media (max-width: 980px) {{
      .console-focus {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .console-nav-shell {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 680px) {{
      .console-focus {{
        grid-template-columns: 1fr;
      }}
      .focus-lane p {{
        display: none;
      }}
    }}
    body,
    body::after,
    .surface,
    .topbar,
    .topbar-menu,
    .version-chip,
    .console-group-pill,
    .quick-link,
    .profile-chip,
    .notice-chip,
    .meta-chip,
    .history-inline-teaser,
    .history-toggle,
    .message,
    .message.assistant,
    .composer-input-shell,
    .sample-prompt-strip .suggestion-chip,
    .composer-send,
    .composer-inline-action,
    .composer-tools-inline,
    .composer-upload-item,
    .composer-upload-button,
    button,
    .button-link {{
      border-radius: 0 !important;
    }}
    .topbar-menu-count,
    .notice-count,
    .pill,
    .focus-card,
    .focus-lane {{
      border-radius: var(--flat-1) !important;
    }}
    .brand,
    .topbar-actions .utility-button,
    .topbar-actions .button-link,
    .status-action-button {{
      border-radius: 8px !important;
    }}
    .composer-input-shell {{
      border-radius: 8px !important;
    }}
    .composer-inline-action,
    .composer-tools-inline,
    .composer-upload-button {{
      border-radius: 7px !important;
    }}
    .composer-send {{
      border-radius: 8px !important;
    }}
    .composer-upload-menu,
    .composer-toolbar-panels {{
      border-radius: 8px !important;
    }}
    .composer-upload-item {{
      border-radius: 7px !important;
    }}
  </style>
</head>
<body>
  <div class="app-shell">
    <header id="topbar" class="topbar surface">
        <div class="brand">
        <div class="brand-line">
          <h1>{html.escape(AGENT_NAME)}</h1>
          <span id="run-state" class="pill {html.escape(initial_tone)}">{html.escape(initial_run_label)}</span>
          <span class="topbar-version" title="Console UI version">v{html.escape(UI_VERSION)}</span>
          <button id="status-action-button" type="button" class="ghost status-action-button" data-icon="?" data-tone="idle" aria-expanded="false" title="Status and actions">Status</button>
        </div>
        <p id="status-message" class="status-copy">{html.escape(initial_status_message)}</p>
        <div id="status-action-panel" class="status-action-panel surface" aria-hidden="true" hidden>
          <div class="status-action-head">
            <strong id="status-action-title" class="status-action-title">Status</strong>
            <span id="status-action-state" class="status-action-state">idle</span>
          </div>
          <p id="status-action-summary" class="status-action-summary">Loading current status…</p>
          <div id="status-action-meta" class="status-action-meta"></div>
          <div class="status-action-controls">
            <button id="status-refresh-button" type="button" class="ghost utility-button" data-icon="↻">Refresh</button>
            <button id="status-ask-button" type="button" class="ghost utility-button" data-icon="?">Ask status</button>
            <button id="status-handle-button" type="button" class="ghost utility-button" data-icon=">">Handle it</button>
          </div>
        </div>
      </div>
      <div class="topbar-actions">
        <a id="prime-home-button" class="ghost utility-button button-link prime-home-button" data-icon="{html.escape(icon_for_label('Prime', '⌂'))}" href="{html.escape(norman_prime_href)}" title="Back to Norman Prime">
          <span class="prime-home-label">Prime</span>
        </a>
        <a id="directory-home-button" class="ghost utility-button button-link directory-home-button" data-icon="{html.escape(icon_for_label('Directory', '≡'))}" href="{html.escape(norman_directory_href)}" title="Open Norman Directory">
          <span class="directory-home-label">Dir</span>
        </a>
        <button id="switcher-toggle-button" type="button" class="ghost utility-button switcher-toggle-button" data-icon="{html.escape(icon_for_label("Switch", "⇆"))}" title="Switch agents (Ctrl/Cmd+K)">
          <span class="switcher-toggle-label">Switch</span>
        </button>
        <button id="topbar-menu-button" type="button" class="ghost utility-button topbar-menu-button" data-icon="{html.escape(icon_for_label("Settings", "⚙"))}" aria-expanded="false" title="Console controls">
          <span class="topbar-menu-button-label">Menu</span>
          <span id="topbar-menu-count" class="topbar-menu-count" hidden>0</span>
        </button>
      </div>
    </header>
    <div id="topbar-menu" class="topbar-menu surface" aria-hidden="true">
          <div class="topbar-menu-meta">
            <span class="version-chip" title="Console UI version">UI v{html.escape(UI_VERSION)}</span>
            <span id="transport-state-menu" class="topbar-menu-status">Connecting live updates…</span>
          </div>
          <div class="topbar-menu-links">
            <a class="ghost utility-button button-link" data-icon="{html.escape(icon_for_label('Prime', '⌂'))}" href="{html.escape(norman_prime_href)}" title="Back to Norman Prime">Prime</a>
            <a class="ghost utility-button button-link" data-icon="{html.escape(icon_for_label('Directory', '≡'))}" href="{html.escape(norman_directory_href)}" title="Open Norman Directory">Directory</a>
            <button id="context-save-menu-button" type="button" class="ghost utility-button context-save-button" data-icon="{html.escape(icon_for_label('Save', '↓'))}" hidden>Save</button>
            <a id="theme-toggle-button" class="ghost utility-button button-link" data-icon="{html.escape(icon_for_label(theme_toggle_label, "◐"))}" href="{html.escape(build_console_href(token=local_token_value, profile=theme_toggle_target, route=route_preference, prefix=path_prefix))}" title="Switch to {html.escape(theme_toggle_label)} mode">{html.escape(theme_toggle_label)}</a>
            <button id="auth-browser-button" type="button" class="ghost utility-button" data-icon="{html.escape(icon_for_label('Sign In', '↗'))}" hidden>Sign in</button>
            <button id="auth-device-button" type="button" class="ghost utility-button" data-icon="{html.escape(icon_for_label('Device Code', '#'))}" hidden>Device code</button>
            <a id="auth-helper-link" class="ghost utility-button button-link" data-icon="{html.escape(icon_for_label('Auth Helper', '⌁'))}" href="{html.escape(prefixed_path('/auth/browser/callback', path_prefix))}" hidden>Auth Helper</a>
            <button id="notice-toggle-button" type="button" class="ghost utility-button notice-toggle" title="Recent notifications">
              <span class="notice-toggle-label"><span>✺</span><span>Alerts</span></span>
              <span id="notice-count" class="notice-count" hidden>0</span>
            </button>
            <button id="refresh-button" type="button" class="ghost utility-button" data-icon="{html.escape(icon_for_label("Refresh"))}">Refresh</button>
            <button id="settings-toggle-button" type="button" class="ghost utility-button" data-icon="{html.escape(icon_for_label("View"))}">View</button>
            <button id="system-toggle-button" type="button" class="ghost utility-button system-toggle" data-icon="{html.escape(icon_for_label("System"))}">System</button>
          </div>
          {f'<div class="topbar-menu-links topbar-menu-links--context">{topbar_context_links_html}</div>' if topbar_context_links_html else ''}
          <div class="topbar-menu-shortcuts" aria-label="Quick shortcuts">
            <span class="shortcut-chip"><kbd>/</kbd><span>Prompt</span></span>
            <span class="shortcut-chip"><kbd>Mod+K</kbd><span>Switch</span></span>
            <span class="shortcut-chip"><kbd>End</kbd><span>Latest</span></span>
            <span class="shortcut-chip"><kbd>Esc</kbd><span>Close</span></span>
            <span class="shortcut-chip"><kbd>?</kbd><span>Help</span></span>
          </div>
    </div>
    <div id="topbar-menu-backdrop" class="topbar-menu-backdrop"></div>
    <div id="console-switcher-seed" hidden aria-hidden="true" inert>{console_nav_html}</div>

    <div id="workspace" class="workspace">
      <main id="chat-shell" class="chat-shell surface">
        <div id="chat-main" class="chat-main" tabindex="0">
          <div class="chat-summary-bar"{' hidden' if initial_chat_summary_hidden else ''}>
            <span id="chat-session-chip" class="meta-chip strong" data-icon="◈">{html.escape(initial_chat_session_text)}</span>
            <span id="chat-activity-chip" class="meta-chip" data-icon="◔"{' hidden' if initial_chat_activity_hidden else ''}>{html.escape(initial_chat_activity_text)}</span>
            <span id="context-meter-chip" class="meta-chip subtle context-meter-chip" data-icon="◌" data-load-tone="{html.escape(str(initial_context_meter['tone']))}" style="--context-load: {int(initial_context_meter['fill_pct'])}%;" title="{html.escape(str(initial_context_meter['title']))}"{' hidden' if initial_context_meter['hidden'] else ''}>
              <span id="context-meter-status">{html.escape(str(initial_context_meter["label"]))}</span>
              <span id="context-meter-value">{html.escape(str(initial_context_meter["value"]))}</span>
              <span class="context-meter-track" aria-hidden="true"><span class="context-meter-fill"></span></span>
            </span>
            <button id="context-save-button" type="button" class="ghost context-save-button" hidden>Save</button>
            <span id="route-chip" class="meta-chip subtle" data-icon="{html.escape(icon_for_label(active_route_mode, "⇄"))}">{html.escape("LAN route" if active_route_mode == "lan" else "Host route")}</span>
            <span id="history-summary" class="meta-chip subtle">{html.escape(initial_history_summary)}</span>
            <span id="last-updated-head" class="meta-chip subtle">{html.escape(initial_last_updated)}</span>
          </div>
          <div id="kpi-strip" class="kpi-strip" hidden></div>
          <div id="notice-rail" class="notice-rail" hidden></div>
          <div id="history-toolbar" class="history-toolbar">
            <span id="history-window-note" class="history-note"></span>
            <button id="history-toggle-button" type="button" class="ghost history-toggle" data-icon="{html.escape(icon_for_label("History"))}" title="Show older turns">Timeline</button>
          </div>
          <div id="conversation" class="conversation">
            {initial_conversation_html}
          </div>
        </div>
        <button id="jump-latest-button" type="button" class="ghost jump-latest" data-icon="{html.escape(icon_for_label("Latest"))}" title="Jump to latest (End)">Latest</button>
        <div class="composer-wrap">
          <div id="activity-strip" class="activity-strip">
            <div id="activity-icon" class="activity-icon"></div>
            <div class="activity-copy">
              <div id="activity-title" class="activity-title"></div>
              <div id="activity-detail" class="activity-detail"></div>
            </div>
            <div id="activity-track" class="activity-track" hidden></div>
            <div id="activity-actions" class="activity-actions">
              <button id="activity-peek-toggle" type="button" class="ghost activity-peek-toggle" hidden>Peek</button>
            </div>
          </div>
          <div id="activity-peek" class="activity-peek" hidden>
            <div class="activity-peek-head">
              <div id="activity-peek-title" class="activity-peek-title">Background</div>
              <div class="activity-peek-head-actions">
                <button id="activity-log-link" type="button" class="ghost activity-log-link">System</button>
                <button id="activity-peek-close" type="button" class="ghost activity-peek-close">Hide</button>
              </div>
            </div>
            <div id="activity-sim-line" class="activity-sim-line"></div>
            <div id="activity-sim-meta" class="activity-sim-meta"></div>
            <div id="activity-steps" class="activity-steps"></div>
            <div id="activity-log-preview" class="activity-log-preview">
              <details id="activity-log-details">
                <summary>Live tail</summary>
                <pre id="activity-log-output"></pre>
              </details>
              <details id="activity-pane-details">
                <summary>Live pane</summary>
                <pre id="activity-pane-output"></pre>
              </details>
            </div>
          </div>
          <form id="ask-form" class="composer" method="post" action="{html.escape(prefixed_path('/ask', path_prefix))}">
            <input type="hidden" name="token" value="{html.escape(TOKEN)}">
            <input type="hidden" name="profile" value="{html.escape(active_profile)}">
            <input id="prompt-speed-input" type="hidden" name="speed" value="{html.escape(DEFAULT_RESPONSE_SPEED)}">
            <input id="prompt-detail-input" type="hidden" name="detail" value="{DEFAULT_RESPONSE_DETAIL}">
            <input id="prompt-file-input" class="composer-file-input" type="file" multiple>
            <div class="composer-toolbar">
              <div id="composer-toolbar-panels" class="composer-toolbar-panels" hidden>
                <div class="response-bar" aria-label="Response tuning">
                  <label class="response-rail" for="response-speed-range">
                    <span class="response-rail-meta">
                      <span class="response-rail-name" data-icon="{html.escape(icon_for_label("Pace"))}">Pace</span>
                      <strong id="response-speed-label" class="response-rail-value">Std</strong>
                    </span>
                    <span class="response-track">
                      <span class="response-edge">Fast</span>
                      <input id="response-speed-range" class="response-range" type="range" min="1" max="3" step="1" value="{1 if DEFAULT_RESPONSE_SPEED == 'fast' else 2 if DEFAULT_RESPONSE_SPEED == 'balanced' else 3}">
                      <span class="response-edge">Deep</span>
                    </span>
                  </label>
                  <label class="response-rail" for="response-detail-range">
                    <span class="response-rail-meta">
                      <span class="response-rail-name" data-icon="{html.escape(icon_for_label("Depth"))}">Depth</span>
                      <strong id="response-detail-label" class="response-rail-value">Balanced</strong>
                    </span>
                    <span class="response-track">
                      <span class="response-edge">Lean</span>
                      <input id="response-detail-range" class="response-range" type="range" min="1" max="5" step="1" value="{DEFAULT_RESPONSE_DETAIL}">
                      <span class="response-edge">Deep</span>
                    </span>
                  </label>
                </div>
                <div id="prompt-suggestions" class="suggestions">
                  {prompt_suggestions_html}
                </div>
              </div>
            </div>
            <div class="composer-input-shell">
                <div id="draft-attachments" class="draft-attachments" hidden></div>
              <div id="sample-prompt-strip" class="sample-prompt-strip" aria-label="Sample prompts" hidden>
                <span class="sample-prompt-label">Samples</span>
                <div class="sample-prompt-list">
                  {prompt_suggestions_html}
                </div>
              </div>
              <div class="composer-inline-actions">
                <div class="composer-upload-shell">
                  <button id="composer-upload-button" type="button" class="ghost composer-inline-action composer-upload-button" data-icon="+" title="Add file, screenshot, or context" aria-label="Add file, screenshot, or context" aria-expanded="false">
                    <span class="composer-upload-label">Add</span>
                    <span class="visually-hidden">Add file, screenshot, or context</span>
                  </button>
                  <div id="composer-upload-menu" class="composer-upload-menu" hidden>
                    <button type="button" class="ghost composer-upload-item" data-upload-action="file" data-icon="+">Files</button>
                    <button type="button" class="ghost composer-upload-item" data-upload-action="capture-console" data-icon="◧">Capture console</button>
                    <button type="button" class="ghost composer-upload-item" data-upload-action="capture-link" data-icon="↗">Capture link</button>
                    <button type="button" class="ghost composer-upload-item" data-upload-action="logs" data-icon="⌘">Attach logs</button>
                    <button type="button" class="ghost composer-upload-item" data-upload-action="history" data-icon="◴">Attach history</button>
                    <button type="button" class="ghost composer-upload-item" data-upload-action="pane" data-icon="▤">Attach pane</button>
                  </div>
                </div>
                <button id="composer-tools-toggle" type="button" class="ghost composer-tools-toggle composer-inline-action composer-tools-inline" data-icon="⚙" aria-expanded="false" title="Tune prompt">
                  <span class="visually-hidden">Tune prompt</span>
                </button>
              </div>
              <textarea id="prompt-input" name="message" placeholder="{html.escape(PROMPT_PLACEHOLDER)}"></textarea>
              <span id="response-summary" class="response-summary visually-hidden">Balanced · Balanced</span>
              <button id="ask-button" type="submit" class="primary composer-send" data-icon="→" title="Send prompt. Press Enter to send and Shift+Enter for a new line." aria-label="Send prompt"><span id="ask-button-label" class="composer-send-label">Next</span></button>
            </div>
          </form>
        </div>
      </main>

      <div id="switcher-backdrop" class="switcher-backdrop"></div>
      <div id="system-backdrop" class="system-backdrop"></div>
      <div id="settings-backdrop" class="settings-backdrop"></div>
      <aside id="switcher-panel" class="switcher-panel surface" aria-hidden="true">
        <div class="switcher-head">
          <div>
            <h2>Switch Agents</h2>
            <p class="hint">Jump between Norman sessions, pinned bots, and recent stops.</p>
          </div>
          <div class="switcher-head-actions">
            <a class="ghost utility-button button-link prime-home-button" data-icon="{html.escape(icon_for_label('Prime', '⌂'))}" href="{html.escape(norman_prime_href)}" title="Back to Norman Prime">Prime</a>
            <button id="switcher-close-button" type="button" class="ghost utility-button">Close</button>
          </div>
        </div>
        <div class="switcher-search-shell">
          <input id="switcher-search-input" class="switcher-search-input" type="search" autocomplete="off" placeholder="Search agent, group, or host">
        </div>
        <div id="switcher-views" class="switcher-views"></div>
        <div id="switcher-groups" class="switcher-groups"></div>
        <div id="switcher-note" class="switcher-note">Loading agents…</div>
        <div id="switcher-list" class="switcher-list">
          <div class="notification-empty">Loading agents…</div>
        </div>
      </aside>
      <aside id="settings-panel" class="settings-panel surface" aria-hidden="true">
        <div class="settings-head">
          <div>
            <h2>View</h2>
            <p class="hint">Mode, palette, finish, history, and reading density.</p>
          </div>
          <button id="settings-close-button" type="button" class="ghost utility-button">Close</button>
        </div>
        <div id="settings-body" class="settings-body">
        <section class="settings-card" data-chat-model="{html.escape(configured_chat_model())}">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Model"))}">Model</span>
          <div class="settings-row">
            <button type="button" class="ghost setting-pill" data-chat-model="{html.escape(configured_chat_model())}" data-model-endpoint="/api/model">{html.escape(configured_chat_model())}</button>
          </div>
          <div class="settings-note">{"Model update available" if chat_model_update_available() else "Model current"}</div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Mode"))}">Mode</span>
          <div class="settings-row">{settings_mode_links_html}</div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Palette"))}">Palette</span>
          <div class="settings-row">{settings_profile_links_html}</div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Route"))}">Route</span>
          <div class="settings-row">{settings_route_links_html}</div>
          <div class="settings-note">Auto follows how you opened the console. Use LAN or Host to force one path across the fleet.</div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Material"))}">Material</span>
          <div id="style-variant-row" class="settings-row">
            <button type="button" class="ghost setting-pill" data-setting="styleVariant" data-value="auto">Auto</button>
            <button type="button" class="ghost setting-pill" data-setting="styleVariant" data-value="anchor">Anchor</button>
            <button type="button" class="ghost setting-pill" data-setting="styleVariant" data-value="signal">Signal</button>
            <button type="button" class="ghost setting-pill" data-setting="styleVariant" data-value="grove">Grove</button>
            <button type="button" class="ghost setting-pill" data-setting="styleVariant" data-value="editorial">Editorial</button>
            <button type="button" class="ghost setting-pill" data-setting="styleVariant" data-value="alloy">Alloy</button>
            <button type="button" class="ghost setting-pill" data-setting="styleVariant" data-value="quiet">Quiet</button>
          </div>
          <div class="settings-note">Auto follows the bot default. Override it if you want a different material treatment without changing the bot itself.</div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Finish"))}">Finish</span>
          <div id="finish-row" class="settings-row">
            <button type="button" class="ghost setting-pill" data-setting="finish" data-value="flat">Flat</button>
            <button type="button" class="ghost setting-pill" data-setting="finish" data-value="engraved">Engraved</button>
            <button type="button" class="ghost setting-pill" data-setting="finish" data-value="etched">Etched</button>
            <button type="button" class="ghost setting-pill" data-setting="finish" data-value="glow">Glow</button>
          </div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Bell"))}">Bell</span>
          <div id="completion-bell-row" class="settings-row">
            <button type="button" class="ghost setting-pill" data-setting="completionBell" data-value="auto">Auto</button>
            <button type="button" class="ghost setting-pill" data-setting="completionBell" data-value="work">Work</button>
            <button type="button" class="ghost setting-pill" data-setting="completionBell" data-value="shared">Shared</button>
            <button type="button" class="ghost setting-pill" data-setting="completionBell" data-value="personal">Personal</button>
            <button type="button" class="ghost setting-pill" data-setting="completionBell" data-value="norman">Norman</button>
            <button type="button" class="ghost setting-pill" data-setting="completionBell" data-value="agents">Other</button>
            <button type="button" class="ghost setting-pill" data-setting="completionBell" data-value="off">Off</button>
          </div>
          <div class="settings-row">
            <button id="completion-bell-test-button" type="button" class="ghost utility-button">Test bell</button>
          </div>
          <div class="settings-note">Auto follows this console’s lane. Work is clean and precise, shared is warm bronze, personal is lighter, Norman is glassy and lower, and Other stays neutral.</div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Phone History"))}">Phone History</span>
          <div id="mobile-turns-row" class="settings-row">
            <button type="button" class="ghost setting-pill" data-setting="mobileTurns" data-value="1">1 turn</button>
            <button type="button" class="ghost setting-pill" data-setting="mobileTurns" data-value="2">2 turns</button>
            <button type="button" class="ghost setting-pill" data-setting="mobileTurns" data-value="3">3 turns</button>
          </div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Desktop History"))}">Desktop History</span>
          <div id="desktop-turns-row" class="settings-row">
            <button type="button" class="ghost setting-pill" data-setting="desktopTurns" data-value="1">1 turn</button>
            <button type="button" class="ghost setting-pill" data-setting="desktopTurns" data-value="2">2 turns</button>
            <button type="button" class="ghost setting-pill" data-setting="desktopTurns" data-value="4">4 turns</button>
            <button type="button" class="ghost setting-pill" data-setting="desktopTurns" data-value="6">6 turns</button>
          </div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Screen"))}">Screen</span>
          <div id="view-mode-row" class="settings-row">
            <button type="button" class="ghost setting-pill" data-setting="viewMode" data-value="console">Console</button>
            <button type="button" class="ghost setting-pill" data-setting="viewMode" data-value="stage">Presenter</button>
          </div>
        </section>
        <section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Density"))}">Density</span>
          <div id="density-row" class="settings-row">
            <button type="button" class="ghost setting-pill" data-setting="density" data-value="compact">Compact</button>
            <button type="button" class="ghost setting-pill" data-setting="density" data-value="comfortable">Comfortable</button>
          </div>
          <div class="settings-note">Saved on this device for this console.</div>
        </section>
        {f'''<section class="settings-card">
          <span class="settings-label" data-icon="{html.escape(icon_for_label("Browse"))}">Browse</span>
          <div class="settings-row">{settings_browse_links_html}</div>
          <div class="settings-note">Open the agent workspace and bridge state in a separate viewer tab.</div>
        </section>''' if settings_browse_links_html else ''}
        </div>
      </aside>
      <aside id="notices-panel" class="notices-panel surface" aria-hidden="true">
        <div class="notices-head">
          <div>
            <h2>Notifications</h2>
            <p class="hint">Recent activity, warnings, and completions.</p>
          </div>
          <div class="notices-actions">
            <button id="clear-notices-button" type="button" class="ghost utility-button">Clear</button>
            <button id="notices-close-button" type="button" class="ghost utility-button">Close</button>
          </div>
        </div>
        <div id="notifications-list" class="notifications-list">
          <div class="notification-empty">No notifications yet.</div>
        </div>
      </aside>
      <aside id="system-panel" class="system-panel surface" aria-hidden="true">
        <div class="system-panel-head">
          <div>
            <h2>System</h2>
            <p class="hint">Runtime, logs, and direct operator controls.</p>
          </div>
          <button id="system-close-button" type="button" class="ghost system-close">Close</button>
        </div>
        <div id="system-panel-body" class="system-panel-body">
          <section class="system-card">
            <div class="system-card-head">
              <h2>Runtime</h2>
              <span id="thread-id-head" class="mono subtle">loading</span>
            </div>
            <div id="services" class="services"></div>
            <div id="system-summary" class="system-note">{html.escape(summarize_services(initial_snapshot_data.get("services") or []))}</div>
            <div id="system-runtime-metrics" class="system-runtime-metrics"></div>
            <div class="system-note">ui <strong>v{html.escape(UI_VERSION)}</strong> · tmux <strong>{html.escape(SESSION)}</strong> · web chat <strong>{html.escape(MODEL)}</strong> · tuning <strong>Fast/low ↔ Careful/xhigh</strong> · full access · <a href="{html.escape(prefixed_path('/healthz', path_prefix))}{token_suffix}">healthz</a></div>
          </section>

          <section class="system-card">
            <details>
              <summary>Latest raw turn</summary>
              <div class="raw-grid">
                <div>
                  <div class="copy-row">
                    <h3>Last Prompt</h3>
                    <button id="copy-prompt-button" type="button" class="ghost copy-button" data-icon="⎘">Copy</button>
                  </div>
                  <div id="last-prompt" class="raw-view mono">{_mask_sensitive_multiline_html(initial_snapshot_data.get("last_prompt") or "[no prompt yet]")}</div>
                  <div id="last-prompt-links" class="message-links raw-links" hidden></div>
                </div>
                <div>
                  <div class="copy-row">
                    <h3>Last Reply</h3>
                    <button id="copy-response-button" type="button" class="ghost copy-button" data-icon="⎘">Copy</button>
                  </div>
                  <div id="last-response" class="raw-view">{_mask_sensitive_multiline_html(initial_snapshot_data.get("last_response") or "[no response yet]")}</div>
                  <div id="last-response-links" class="message-links raw-links" hidden></div>
                </div>
              </div>
            </details>
            <details id="error-details">
              <summary>Error / Warning</summary>
              <pre id="last-error">{_mask_sensitive_pre_html(initial_snapshot_data.get("last_error") or "[none]")}</pre>
            </details>
          </section>

          <section class="system-card">
            <details>
              <summary>Operator tools</summary>
              <form id="tmux-form" method="post" action="{html.escape(prefixed_path('/send', path_prefix))}">
                <input type="hidden" name="token" value="{html.escape(TOKEN)}">
                <input type="hidden" name="profile" value="{html.escape(active_profile)}">
                <textarea id="tmux-input" name="message" placeholder="Paste raw text directly into the live interactive tmux session."></textarea>
                <div class="composer-actions">
                  <span class="hint">Use this only for direct tmux control.</span>
                  <button id="tmux-send-button" type="submit">Paste Into tmux</button>
                </div>
              </form>
              <div class="button-row">
                <button id="cancel-web-button" type="button" class="warn">Cancel Current Web Reply</button>
                <button id="clear-queue-button" type="button" class="warn">Clear Queue</button>
                <button id="cancel-all-button" type="button" class="danger">Cancel + Clear Queue</button>
                <button id="promote-latest-button" type="button" class="ghost">Promote Latest</button>
                <button id="interrupt-button" type="button" class="warn">Interrupt tmux Session</button>
                <button id="restart-button" type="button" class="danger">Restart Session</button>
              </div>
              <details>
                <summary>Live tmux pane</summary>
                <pre id="pane-output">{_mask_sensitive_pre_html(initial_snapshot_data.get("pane") or "[pane unavailable]")}</pre>
              </details>
              <details>
                <summary>{html.escape(AGENT_NAME)} journal</summary>
                <pre id="journal-output">{_mask_sensitive_pre_html(initial_snapshot_data.get("logs") or "[no journal output]")}</pre>
              </details>
            </details>
          </section>
        </div>
      </aside>
    </div>
  </div>
  <div id="toast-stack" class="toast-stack" aria-live="polite"></div>

  <script>
    const TOKEN = {token_value};
    const LOCAL_TOKEN = {script_json(local_token_value)};
    const TRUSTED_CONSOLE_CLIENT = {script_json(trusted_request)};
    const BROWSER_AUTH_BRIDGE_ALLOWED = {script_json(browser_auth_supported)};
    const INITIAL_SNAPSHOT = {initial_snapshot};
    const AGENT_LABEL = {json.dumps(AGENT_NAME)};
    const AGENT_SLUG = {json.dumps(AGENT_SLUG)};
    const AGENT_MARK = {json.dumps(entity_mark_for_label(AGENT_NAME, "•"))};
    const AGENT_STYLE_VARIANT = {json.dumps(AGENT_STYLE_VARIANT)};
    const AGENT_GROUP = {json.dumps(semantic_agent_group(AGENT_SLUG, AGENT_GROUP) or "agents")};
    const INLINE_ENTITY_DEFS = {script_json(build_inline_entity_defs())};
    const UI_VERSION = {json.dumps(UI_VERSION)};
    const ACTIVE_PROFILE = {active_profile_name_json};
    const ACTIVE_PROFILE_LABEL = {active_profile_label_json};
    const ACTIVE_ROUTE = {json.dumps(route_preference)};
    const REQUEST_BASE_PATH = {json.dumps(path_prefix)};
    const NORMAN_PRIME_HEARTBEAT_URL = {json.dumps(f"{norman_prime_href}api/console-ui/ping")};
    const TAB_TITLE_LABEL = {json.dumps(CONSOLE_TAB_TITLE)};
    const FAVICON_AGENT_PALETTE = {script_json({
        "bg": rgb_css(favicon_palette(AGENT_SLUG or AGENT_NAME.lower()).get("bg", (48, 56, 70))),
        "surface": rgb_css(favicon_palette(AGENT_SLUG or AGENT_NAME.lower()).get("surface", (63, 71, 85))),
        "border": rgb_css(favicon_palette(AGENT_SLUG or AGENT_NAME.lower()).get("border", (85, 97, 116))),
        "accent": rgb_css(favicon_palette(AGENT_SLUG or AGENT_NAME.lower()).get("accent", (156, 182, 239))),
        "accent2": rgb_css(favicon_palette(AGENT_SLUG or AGENT_NAME.lower()).get("accent_2", (136, 208, 222))),
        "text": rgb_css(favicon_palette(AGENT_SLUG or AGENT_NAME.lower()).get("text", (248, 250, 252))),
    })};
    const RELAY_TARGETS = {relay_targets_json};
    const CHAT_MODEL = {json.dumps(MODEL)};
    const MODEL_ENDPOINT = "/api/model";
    const CHAT_REASONING = {json.dumps(response_reasoning_effort(DEFAULT_RESPONSE_SPEED))};
    const DEFAULT_RESPONSE_SPEED = {default_response_speed_json};
    const DEFAULT_RESPONSE_DETAIL = {default_response_detail_json};
    const LARGE_PASTE_MIN_CHARS = 640;
    const LARGE_PASTE_MIN_LINES = 10;
    const LARGE_REPLY_COLLAPSE_MIN_CHARS = 16000;
    const LARGE_REPLY_COLLAPSE_MIN_LINES = 120;
    const INLINE_FILE_TARGET_LIMIT = 4;
    const INLINE_FILE_TARGET_SCAN_CHARS = 24000;
    const INLINE_IMAGE_GALLERY_LIMIT = 3;
    const INLINE_PREVIEW_VISIBLE_MESSAGE_LIMIT = 2;
    const INLINE_TEXT_PREVIEW_MAX_CHARS = 24000;
    const INLINE_TEXT_PREVIEW_RANGE_BYTES = 32768;
    const INLINE_PREVIEW_TIMEOUT_MS = 4500;
    const INLINE_PREVIEW_CACHE_LIMIT = 24;
    const VISIBLE_PENDING_STATUS_POLL_MS = 2000;
    const VISIBLE_IDLE_STATUS_POLL_MS = 12000;
    const BACKGROUND_PENDING_STATUS_POLL_MS = 12000;
    const BACKGROUND_IDLE_STATUS_POLL_MS = 30000;
    const RESPONSE_DETAIL_LABELS = {{
      1: "Simple",
      2: "Lean",
      3: "Balanced",
      4: "Detailed",
      5: "Deep",
    }};
    const SETTINGS_STORAGE_KEY = `${{AGENT_LABEL.toLowerCase().replace(/[^a-z0-9]+/g, "-")}}-console-settings-v1`;
    const PROMPT_DRAFT_STORAGE_KEY = `${{AGENT_LABEL.toLowerCase().replace(/[^a-z0-9]+/g, "-")}}-console-draft-v2:${{window.location.hostname}}${{window.location.pathname}}`;
    const PROMPT_DRAFT_MAX_AGE_MS = 1000 * 60 * 60 * 24 * 7;
    const SWITCHER_STORAGE_KEY = "agent-console-switcher-v1";
    const SWITCHER_STATE_PARAM = "fleet";
    const SWITCHER_RECENTS_LIMIT = 8;
    const DEFAULT_PREFERENCES = {{
      density: "compact",
      mobileTurns: 1,
      desktopTurns: 1,
      viewMode: "console",
      styleVariant: "auto",
      finish: {json.dumps(DEFAULT_UI_FINISH if DEFAULT_UI_FINISH in FINISH_OPTIONS else "flat")},
      completionBell: "auto",
      responseSpeed: DEFAULT_RESPONSE_SPEED,
      responseDetail: DEFAULT_RESPONSE_DETAIL,
    }};
    const COMPLETION_BELL_PROFILES = {{
      norman: {{
        label: "Norman",
        wave: "sine",
        frequency: 432,
        sweep: 9,
        duration: 0.96,
        peak: 0.05,
        sustain: 0.015,
        attack: 0.018,
        hold: 0.11,
        filter: 1750,
        q: 1.1,
        echoDelay: 0.11,
        echoGain: 0.18,
        voices: [
          {{ ratio: 1, gain: 1, wave: "sine", duration: 1.12, filterMul: 1, q: 1.2 }},
          {{ ratio: 1.5, gain: 0.38, wave: "triangle", offset: 0.018, duration: 0.84, sweepMul: 0.7, filterMul: 1.35 }},
          {{ ratio: 2.23, gain: 0.16, wave: "sine", offset: 0.038, duration: 1.24, attackMul: 1.8, filterMul: 1.8 }},
        ],
        answer: {{ ratio: 2, gain: 0.18, delay: 0.15, duration: 0.46, wave: "triangle", filterMul: 1.45 }},
      }},
      personal: {{
        label: "Personal",
        wave: "triangle",
        frequency: 588,
        sweep: 11,
        duration: 0.7,
        peak: 0.054,
        sustain: 0.018,
        attack: 0.01,
        hold: 0.07,
        filter: 2240,
        q: 1.3,
        echoDelay: 0.084,
        echoGain: 0.16,
        voices: [
          {{ ratio: 1, gain: 1, wave: "triangle", duration: 0.76, filterMul: 1 }},
          {{ ratio: 2, gain: 0.24, wave: "sine", offset: 0.012, duration: 0.52, attackMul: 0.8, filterMul: 1.5 }},
          {{ ratio: 3.01, gain: 0.09, wave: "triangle", offset: 0.03, duration: 0.88, attackMul: 1.6, filterMul: 1.95 }},
        ],
        answer: {{ ratio: 1.3348, gain: 0.13, delay: 0.102, duration: 0.34, wave: "sine", filterMul: 1.2 }},
      }},
      shared: {{
        label: "Shared",
        wave: "triangle",
        frequency: 396,
        sweep: 8,
        duration: 1.04,
        peak: 0.052,
        sustain: 0.016,
        attack: 0.016,
        hold: 0.12,
        filter: 1420,
        q: 1.05,
        echoDelay: 0.126,
        echoGain: 0.22,
        voices: [
          {{ ratio: 1, gain: 1, wave: "triangle", duration: 1.16, filterMul: 1 }},
          {{ ratio: 1.498, gain: 0.34, wave: "sine", offset: 0.02, duration: 0.9, attackMul: 1.2, filterMul: 1.3 }},
          {{ ratio: 2.66, gain: 0.11, wave: "triangle", offset: 0.048, duration: 1.3, attackMul: 2.2, filterMul: 1.85 }},
        ],
        answer: {{ ratio: 0.75, gain: 0.12, delay: 0.18, duration: 0.52, wave: "sine", filterMul: 0.92 }},
      }},
      work: {{
        label: "Work",
        wave: "sine",
        frequency: 528,
        sweep: 6,
        duration: 0.56,
        peak: 0.05,
        sustain: 0.014,
        attack: 0.006,
        hold: 0.04,
        filter: 2380,
        q: 1.45,
        echoDelay: 0.068,
        echoGain: 0.1,
        voices: [
          {{ ratio: 1, gain: 1, wave: "sine", duration: 0.56, filterMul: 1.1 }},
          {{ ratio: 2, gain: 0.18, wave: "triangle", offset: 0.008, duration: 0.34, attackMul: 0.8, filterMul: 1.55 }},
          {{ ratio: 3, gain: 0.06, wave: "sine", offset: 0.018, duration: 0.48, attackMul: 1.4, filterMul: 1.95 }},
        ],
        answer: {{ ratio: 1.5, gain: 0.09, delay: 0.08, duration: 0.22, wave: "triangle", filterMul: 1.22 }},
      }},
      agents: {{
        label: "Other",
        wave: "triangle",
        frequency: 474,
        sweep: 5,
        duration: 0.62,
        peak: 0.042,
        sustain: 0.012,
        attack: 0.009,
        hold: 0.05,
        filter: 1560,
        q: 1.15,
        echoDelay: 0.078,
        echoGain: 0.11,
        voices: [
          {{ ratio: 1, gain: 1, wave: "triangle", duration: 0.66, filterMul: 1 }},
          {{ ratio: 2.01, gain: 0.16, wave: "sine", offset: 0.016, duration: 0.42, filterMul: 1.45 }},
          {{ ratio: 2.75, gain: 0.07, wave: "triangle", offset: 0.03, duration: 0.7, attackMul: 1.8, filterMul: 1.85 }},
        ],
        answer: {{ ratio: 1.25, gain: 0.08, delay: 0.1, duration: 0.24, wave: "sine", filterMul: 1.1 }},
      }},
    }};
    const AGENT_COMPLETION_BELL_OVERRIDES = {{
      "gold-book": {{
        wave: "triangle",
        frequency: 552,
        filter: 1720,
        echoGain: 0.19,
      }},
      "platinum-standard": {{
        wave: "sine",
        frequency: 708,
        filter: 2380,
        echoDelay: 0.064,
      }},
      uplink: {{
        wave: "triangle",
        frequency: 516,
        sweep: 24,
        filter: 1960,
      }},
      networking: {{
        wave: "triangle",
        frequency: 574,
        filter: 1840,
      }},
      theseus: {{
        wave: "sine",
        frequency: 648,
        sweep: 18,
        echoGain: 0.16,
      }},
      parkergale: {{
        wave: "triangle",
        frequency: 642,
        filter: 1680,
      }},
      pefb: {{
        wave: "triangle",
        frequency: 642,
        filter: 1680,
      }},
    }};
    const STYLE_VARIANT_MAP = {script_json(STYLE_VARIANTS)};

    function textSeed(value) {{
      return String(value || "")
        .split("")
        .reduce((total, ch) => total + ch.charCodeAt(0), 0) || 1;
    }}

    function buildAgentCompletionBellProfile(styleVariant = AGENT_STYLE_VARIANT) {{
      const fallbackKey = Object.prototype.hasOwnProperty.call(COMPLETION_BELL_PROFILES, AGENT_GROUP)
        ? AGENT_GROUP
        : "agents";
      const base = COMPLETION_BELL_PROFILES[fallbackKey] || COMPLETION_BELL_PROFILES.agents;
      if (!base) {{
        return null;
      }}
      const seed = textSeed(AGENT_SLUG || AGENT_LABEL);
      const profile = {{
        ...base,
        label: AGENT_LABEL,
        frequency: Math.max(360, Number(base.frequency || 520) + (((seed % 9) - 4) * 9)),
        sweep: Math.max(6, Number(base.sweep || 12) + ((((seed >> 3) % 5) - 2) * 3)),
        duration: Number((Math.max(0.28, Number(base.duration || 0.38) + ((((seed >> 5) % 5) - 2) * 0.02))).toFixed(3)),
        filter: Math.max(880, Number(base.filter || 1400) + ((((seed >> 7) % 7) - 3) * 90)),
        echoDelay: Number((Math.max(0.045, Number(base.echoDelay || 0.07) + ((((seed >> 10) % 5) - 2) * 0.006))).toFixed(3)),
        echoGain: Number((Math.max(0.06, Math.min(0.3, Number(base.echoGain || 0.12) + ((((seed >> 12) % 5) - 2) * 0.018)))).toFixed(3)),
      }};
      if (styleVariant === "editorial") {{
        profile.wave = "triangle";
        profile.filter = Math.max(profile.filter, 1620);
      }} else if (styleVariant === "alloy") {{
        profile.wave = "sine";
        profile.attack = 0.005;
        profile.hold = Math.max(0.024, Number(profile.hold || 0.03));
      }} else if (styleVariant === "signal") {{
        profile.filter = Math.max(profile.filter, 1820);
      }} else if (styleVariant === "grove") {{
        profile.echoGain = Math.max(profile.echoGain, 0.14);
      }} else if (styleVariant === "quiet") {{
        profile.duration = Number(Math.min(profile.duration, 0.34).toFixed(3));
        profile.echoGain = Number(Math.min(profile.echoGain, 0.1).toFixed(3));
      }}
      const explicit = AGENT_COMPLETION_BELL_OVERRIDES[AGENT_SLUG] || null;
      return explicit ? {{ ...profile, ...explicit }} : profile;
    }}

    const AGENT_COMPLETION_BELL_PROFILE = buildAgentCompletionBellProfile();
    const INLINE_ENTITY_ENTRIES = buildInlineEntityEntries(INLINE_ENTITY_DEFS);
    function indexInlineEntityAliasMap(entries) {{
      const indexed = new Map();
      for (const entry of Array.isArray(entries) ? entries : []) {{
        const entity = entry?.entity || null;
        if (!entity) {{
          continue;
        }}
        const key = normalizeInlineEntityKey(entry.alias || entity.label || entity.key || "");
        if (key && !indexed.has(key)) {{
          indexed.set(key, {{
            entity,
            aliasFor: String(entry.aliasFor || ""),
          }});
        }}
      }}
      return indexed;
    }}

    function indexInlineEntityMap(entries) {{
      const indexed = new Map();
      for (const entry of Array.isArray(entries) ? entries : []) {{
        const entity = entry?.entity || null;
        if (!entity) {{
          continue;
        }}
        const keys = [entity.key, entity.label, entry.alias].map(normalizeInlineEntityKey).filter(Boolean);
        for (const key of keys) {{
          if (!indexed.has(key)) {{
            indexed.set(key, entity);
          }}
        }}
      }}
      return indexed;
    }}

    const INLINE_ENTITY_ALIAS_MAP = indexInlineEntityAliasMap(INLINE_ENTITY_ENTRIES);
    const INLINE_ENTITY_MAP = indexInlineEntityMap(INLINE_ENTITY_ENTRIES);
    const state = {{
      snapshot: INITIAL_SNAPSHOT,
      previousSnapshot: null,
      pollTimer: null,
      stream: null,
      streamReconnectTimer: 0,
      streamConnected: false,
      transportLabel: "Connecting…",
      transportConnected: false,
      transientOperatorBanner: "",
      historyExpanded: false,
      deferredSnapshot: null,
      userPinnedHistory: false,
      hiddenHistoryTurns: 0,
      touchStartY: null,
      attachmentBusy: false,
      activeThreadId: null,
      initialBottomSnapDone: false,
      initialViewportSettleDone: false,
      lastConversationTailKey: "",
      toolbarExpanded: false,
      uploadMenuOpen: false,
      activityPeekOpen: false,
      promptFocused: false,
      preferences: null,
      switcher: null,
      notices: [],
      noticeSerial: 0,
      composerReserveFrame: 0,
      pendingComposerReserveLiveEdge: false,
      lastComposerReserve: 0,
      keyboardOpen: false,
      lastViewportHeight: 0,
      lastViewportTop: 0,
      escapeInterruptAt: 0,
      promptEnterMeta: null,
      lastPromptSubmitAt: 0,
      primePingTimer: 0,
      lastPrimePingAt: 0,
      authRedirectTriggered: false,
      lastTabChromeKey: "",
      tabFaviconTimer: 0,
      tabFaviconFrame: 0,
      tabFaviconState: "",
      statusPanelOpen: false,
      statusKpis: null,
      statusActionBusy: false,
      renderCache: {{
        conversation: "",
        promptResponse: "",
        noticeRail: "",
        activity: "",
        suggestions: "",
        draftAttachments: "",
        capsules: "",
        contextMeter: "",
        systemMetrics: "",
        services: "",
      }},
      inlinePreviewCache: {{}},
      audioContext: null,
      lastCompletionBellAt: 0,
    }};
    const desktopLayout = window.matchMedia("(min-width: 980px)");

    const el = {{
      runState: document.getElementById("run-state"),
      statusMessage: document.getElementById("status-message"),
      statusActionButton: document.getElementById("status-action-button"),
      statusActionPanel: document.getElementById("status-action-panel"),
      statusActionTitle: document.getElementById("status-action-title"),
      statusActionState: document.getElementById("status-action-state"),
      statusActionSummary: document.getElementById("status-action-summary"),
      statusActionMeta: document.getElementById("status-action-meta"),
      statusRefreshButton: document.getElementById("status-refresh-button"),
      statusAskButton: document.getElementById("status-ask-button"),
      statusHandleButton: document.getElementById("status-handle-button"),
      topbar: document.getElementById("topbar"),
      primeHomeButton: document.getElementById("prime-home-button"),
      directoryHomeButton: document.getElementById("directory-home-button"),
      switcherToggleButton: document.getElementById("switcher-toggle-button"),
      topbarMenuButton: document.getElementById("topbar-menu-button"),
      topbarMenuCount: document.getElementById("topbar-menu-count"),
      topbarMenu: document.getElementById("topbar-menu"),
      topbarMenuBackdrop: document.getElementById("topbar-menu-backdrop"),
      contextSaveMenuButton: document.getElementById("context-save-menu-button"),
      noticeToggleButton: document.getElementById("notice-toggle-button"),
      noticeCount: document.getElementById("notice-count"),
      appShell: document.querySelector(".app-shell"),
      workspace: document.getElementById("workspace"),
      chatShell: document.getElementById("chat-shell"),
      chatMain: document.getElementById("chat-main"),
      composerWrap: document.querySelector(".composer-wrap"),
      promptInput: document.getElementById("prompt-input"),
      promptFileInput: document.getElementById("prompt-file-input"),
      askForm: document.getElementById("ask-form"),
      askButton: document.getElementById("ask-button"),
      composerUploadButton: document.getElementById("composer-upload-button"),
      composerUploadMenu: document.getElementById("composer-upload-menu"),
      conversation: document.getElementById("conversation"),
      jumpLatestButton: document.getElementById("jump-latest-button"),
      historyToolbar: document.getElementById("history-toolbar"),
      historyWindowNote: document.getElementById("history-window-note"),
      historyToggleButton: document.getElementById("history-toggle-button"),
      historySummary: document.getElementById("history-summary"),
      noticeRail: document.getElementById("notice-rail"),
      chatSummaryBar: document.querySelector(".chat-summary-bar"),
      kpiStrip: document.getElementById("kpi-strip"),
      chatSessionChip: document.getElementById("chat-session-chip"),
      chatActivityChip: document.getElementById("chat-activity-chip"),
      contextMeterChip: document.getElementById("context-meter-chip"),
      contextMeterStatus: document.getElementById("context-meter-status"),
      contextMeterValue: document.getElementById("context-meter-value"),
      contextSaveButton: document.getElementById("context-save-button"),
      systemSummary: document.getElementById("system-summary"),
      systemRuntimeMetrics: document.getElementById("system-runtime-metrics"),
      activityStrip: document.getElementById("activity-strip"),
      activityTitle: document.getElementById("activity-title"),
      activityDetail: document.getElementById("activity-detail"),
      activityTrack: document.getElementById("activity-track"),
      activityActions: document.getElementById("activity-actions"),
      activityPeekToggle: document.getElementById("activity-peek-toggle"),
      activityPeek: document.getElementById("activity-peek"),
      activityPeekTitle: document.getElementById("activity-peek-title"),
      activityPeekClose: document.getElementById("activity-peek-close"),
      activityLogLink: document.getElementById("activity-log-link"),
      activitySimLine: document.getElementById("activity-sim-line"),
      activitySimMeta: document.getElementById("activity-sim-meta"),
      activitySteps: document.getElementById("activity-steps"),
      activityLogDetails: document.getElementById("activity-log-details"),
      activityPaneDetails: document.getElementById("activity-pane-details"),
      activityLogOutput: document.getElementById("activity-log-output"),
      activityPaneOutput: document.getElementById("activity-pane-output"),
      composerToolsToggle: document.getElementById("composer-tools-toggle"),
      composerToolbarPanels: document.getElementById("composer-toolbar-panels"),
      responseSummary: document.getElementById("response-summary"),
      askButtonLabel: document.getElementById("ask-button-label"),
      responseSpeedRange: document.getElementById("response-speed-range"),
      responseSpeedLabel: document.getElementById("response-speed-label"),
      responseDetailRange: document.getElementById("response-detail-range"),
      responseDetailLabel: document.getElementById("response-detail-label"),
      promptSpeedInput: document.getElementById("prompt-speed-input"),
      promptDetailInput: document.getElementById("prompt-detail-input"),
      promptSuggestions: document.getElementById("prompt-suggestions"),
      samplePromptStrip: document.getElementById("sample-prompt-strip"),
      draftAttachments: document.getElementById("draft-attachments"),
      lastPrompt: document.getElementById("last-prompt"),
      lastPromptLinks: document.getElementById("last-prompt-links"),
      lastResponse: document.getElementById("last-response"),
      lastResponseLinks: document.getElementById("last-response-links"),
      lastError: document.getElementById("last-error"),
      errorDetails: document.getElementById("error-details"),
      copyPromptButton: document.getElementById("copy-prompt-button"),
      copyResponseButton: document.getElementById("copy-response-button"),
      services: document.getElementById("services"),
      paneOutput: document.getElementById("pane-output"),
      journalOutput: document.getElementById("journal-output"),
      themeToggleButton: document.getElementById("theme-toggle-button"),
      authBrowserButton: document.getElementById("auth-browser-button"),
      authDeviceButton: document.getElementById("auth-device-button"),
      authHelperLink: document.getElementById("auth-helper-link"),
      refreshButton: document.getElementById("refresh-button"),
      transportStateMenu: document.getElementById("transport-state-menu"),
      tmuxForm: document.getElementById("tmux-form"),
      tmuxInput: document.getElementById("tmux-input"),
      tmuxSendButton: document.getElementById("tmux-send-button"),
      cancelWebButton: document.getElementById("cancel-web-button"),
      clearQueueButton: document.getElementById("clear-queue-button"),
      cancelAllButton: document.getElementById("cancel-all-button"),
      promoteLatestButton: document.getElementById("promote-latest-button"),
      interruptButton: document.getElementById("interrupt-button"),
      restartButton: document.getElementById("restart-button"),
      threadIdHead: document.getElementById("thread-id-head"),
      lastUpdatedHead: document.getElementById("last-updated-head"),
      settingsToggleButton: document.getElementById("settings-toggle-button"),
      switcherCloseButton: document.getElementById("switcher-close-button"),
      switcherPanel: document.getElementById("switcher-panel"),
      switcherBackdrop: document.getElementById("switcher-backdrop"),
      switcherSearchInput: document.getElementById("switcher-search-input"),
      switcherViews: document.getElementById("switcher-views"),
      switcherGroups: document.getElementById("switcher-groups"),
      switcherNote: document.getElementById("switcher-note"),
      switcherList: document.getElementById("switcher-list"),
      settingsCloseButton: document.getElementById("settings-close-button"),
      settingsPanel: document.getElementById("settings-panel"),
      settingsBackdrop: document.getElementById("settings-backdrop"),
      noticesPanel: document.getElementById("notices-panel"),
      noticesCloseButton: document.getElementById("notices-close-button"),
      clearNoticesButton: document.getElementById("clear-notices-button"),
      notificationsList: document.getElementById("notifications-list"),
      toastStack: document.getElementById("toast-stack"),
      systemToggleButton: document.getElementById("system-toggle-button"),
      systemCloseButton: document.getElementById("system-close-button"),
      systemPanel: document.getElementById("system-panel"),
      systemPanelBody: document.getElementById("system-panel-body"),
      systemBackdrop: document.getElementById("system-backdrop"),
      consoleFocusShell: document.getElementById("console-focus-shell"),
      consoleFocusToggle: document.getElementById("console-focus-toggle"),
      consoleFocusPanel: document.getElementById("console-focus-panel"),
      consoleFocusCaret: document.getElementById("console-focus-caret"),
      completionBellTestButton: document.getElementById("completion-bell-test-button"),
    }};
    const suggestionButtons = Array.from(document.querySelectorAll("[data-suggestion]"));
    const settingButtons = Array.from(document.querySelectorAll("[data-setting]"));
    const consoleGroupButtons = Array.from(document.querySelectorAll(".console-group-pill"));
    const consoleNavPanels = Array.from(document.querySelectorAll(".console-nav-panel"));
    const consoleNavLinks = Array.from(document.querySelectorAll(".console-nav .quick-link[data-group]"));

    document.addEventListener("click", (event) => {{
      const button = event.target.closest(".secret-spoiler");
      if (!button) {{
        return;
      }}
      const revealing = !button.classList.contains("revealed");
      button.classList.toggle("revealed", revealing);
      button.setAttribute("aria-pressed", revealing ? "true" : "false");
    }});

    function setConsoleNavGroup(group) {{
      const nextGroup = String(group || "").trim();
      if (!nextGroup || !consoleGroupButtons.length || !consoleNavPanels.length) {{
        return;
      }}
      consoleGroupButtons.forEach((button) => {{
        const active = button.dataset.group === nextGroup;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.tabIndex = active ? 0 : -1;
      }});
      consoleNavPanels.forEach((panel) => {{
        const active = panel.dataset.group === nextGroup;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      }});
    }}

    function formatTs(ts) {{
      if (!ts) return "n/a";
      try {{
        return new Date(ts * 1000).toLocaleString([], {{
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
          second: "2-digit",
        }});
      }} catch (_) {{
        return String(ts);
      }}
    }}

    function stateTone(snapshot) {{
      const issue = runtimeIssue(snapshot);
      if (issue?.code === "browser_signin" || issue?.code === "device_code" || issue?.code === "signin_choice") return ["error", "Sign in"];
      if (issue?.code === "needs_reauth") return ["error", "Needs reauth"];
      if (issue?.code === "update_prompt") return ["running", "Blocked"];
      if (snapshot.pending) return ["running", "Running"];
      if (snapshot.state === "cancelling") return ["running", "Cancelling"];
      if (snapshot.state === "cancelled") return ["idle", "Cancelled"];
      if (snapshot.state === "recovered" || snapshot.stale_queue) return ["idle", "Recovered"];
      if (snapshot.last_error) return ["error", "Attention"];
      if (snapshot.state === "ok") return ["ok", "Ready"];
      if (snapshot.state === "error") return ["error", "Error"];
      return ["idle", "Idle"];
    }}

    function labelizeStatus(value) {{
      const clean = String(value || "unknown").replace(/[_-]+/g, " ").trim();
      return clean.replace(/\b\w/g, (letter) => letter.toUpperCase());
    }}

    function statusKpisForSnapshot(snapshot = state.snapshot) {{
      const live = state.statusKpis && typeof state.statusKpis === "object"
        ? state.statusKpis
        : null;
      const embedded = snapshot && typeof snapshot.kpis === "object"
        ? snapshot.kpis
        : null;
      if (!live) return embedded || {{}};
      if (!embedded) return live;
      return Number(live.observed_at || 0) >= Number(embedded.observed_at || 0)
        ? live
        : embedded;
    }}

    function serviceIssues(snapshot = state.snapshot) {{
      return (Array.isArray(snapshot?.services) ? snapshot.services : [])
        .filter((item) => ["failed", "inactive", "dead"].includes(String(item?.state || "").toLowerCase()))
        .map((item) => `${{item.name || "service"}}: ${{item.state || "unknown"}}`);
    }}

    function statusActionDescriptor(snapshot = state.snapshot) {{
      const kpis = statusKpisForSnapshot(snapshot);
      const kpiState = String(kpis?.state || "").toLowerCase();
      const signals = Array.isArray(kpis?.signals) ? kpis.signals : [];
      const badServices = serviceIssues(snapshot);
      const queueDepth = Number(snapshot?.queue_depth || 0);
      const pending = Boolean(snapshot?.pending);
      const stateName = kpiState || (pending ? "working" : String(snapshot?.state || "idle").toLowerCase());
      const signalSummary = signals
        .map((signal) => signal?.summary || signal?.code || "")
        .filter(Boolean);
      const actionable = (
        ["blocked", "wedged", "degraded", "error"].includes(stateName)
        || Boolean(snapshot?.last_error)
        || Boolean(snapshot?.stale_queue)
        || signals.length > 0
        || badServices.length > 0
      );
      const summary = String(
        kpis?.diagnosis
        || signalSummary[0]
        || snapshot?.status_message
        || (pending ? `${{AGENT_LABEL}} is working.` : `${{AGENT_LABEL}} is ready.`)
      );
      let tone = stateName;
      if (snapshot?.last_error || ["blocked", "wedged", "error"].includes(stateName)) {{
        tone = stateName === "blocked" ? "blocked" : stateName === "wedged" ? "wedged" : "error";
      }} else if (stateName === "degraded" || signals.length || badServices.length) {{
        tone = "degraded";
      }} else if (pending || stateName === "working") {{
        tone = "working";
      }} else if (stateName === "idle" || stateName === "ok") {{
        tone = "ok";
      }}
      const metrics = kpis?.metrics && typeof kpis.metrics === "object" ? kpis.metrics : {{}};
      const meta = [
        `activity: ${{labelizeStatus(kpis?.activity_state || (pending ? "working" : "idle"))}}`,
        queueDepth > 0 ? `queue: ${{queueDepth}}` : "queue: clear",
        Number(kpis?.stale_seconds || 0) > 0
          ? `stale: ${{formatElapsedCompact(Number(kpis.stale_seconds || 0))}}`
          : "stale: fresh",
        Number(metrics.turns || 0) > 0
          ? `turns: ${{formatCount(metrics.turns)}}`
          : "turns: none tracked",
      ];
      if (badServices.length) {{
        meta.push(`services: ${{badServices.slice(0, 2).join(", ")}}`);
      }}
      if (signals.length) {{
        meta.push(`signals: ${{signals.map((signal) => signal.code || signal.severity || "signal").slice(0, 3).join(", ")}}`);
      }}
      if (Number(kpis?.observed_at || 0) > 0) {{
        meta.push(`observed: ${{formatTs(kpis.observed_at)}}`);
      }}
      return {{
        actionable,
        badServices,
        kpis,
        meta,
        queueDepth,
        signals,
        stateName,
        summary,
        title: `${{AGENT_LABEL}} · ${{labelizeStatus(stateName)}}`,
        tone,
      }};
    }}

    function renderStatusActionPanel(snapshot = state.snapshot) {{
      if (!el.statusActionButton || !el.statusActionPanel) {{
        return;
      }}
      const descriptor = statusActionDescriptor(snapshot);
      el.statusActionButton.dataset.tone = descriptor.tone || "idle";
      el.statusActionButton.setAttribute("aria-expanded", state.statusPanelOpen ? "true" : "false");
      el.statusActionButton.title = `${{descriptor.title}} · ${{descriptor.summary}}`;
      el.statusActionPanel.hidden = !state.statusPanelOpen;
      el.statusActionPanel.setAttribute("aria-hidden", state.statusPanelOpen ? "false" : "true");
      if (!state.statusPanelOpen) {{
        return;
      }}
      el.statusActionTitle.textContent = descriptor.title;
      el.statusActionState.textContent = labelizeStatus(descriptor.stateName);
      el.statusActionSummary.textContent = descriptor.summary;
      el.statusActionMeta.innerHTML = descriptor.meta
        .slice(0, 8)
        .map((item) => `<span>${{escapeHtml(item)}}</span>`)
        .join("");
      if (el.statusRefreshButton) {{
        el.statusRefreshButton.disabled = state.statusActionBusy;
      }}
      if (el.statusAskButton) {{
        el.statusAskButton.disabled = state.statusActionBusy;
      }}
      if (el.statusHandleButton) {{
        el.statusHandleButton.disabled = state.statusActionBusy || !descriptor.actionable;
        el.statusHandleButton.title = descriptor.actionable
          ? "Send a focused recovery prompt with the current status context."
          : "No actionable status issue is visible.";
      }}
    }}

    function tabStateDescriptor(snapshot) {{
      const issue = runtimeIssue(snapshot);
      if (issue?.code === "browser_signin" || issue?.code === "device_code" || issue?.code === "signin_choice") {{
        return {{
          key: "signin",
          prefix: "↗",
          label: "Sign in",
          color: "#d7b97a",
          border: "#e8d49a",
          background: "#15120d",
        }};
      }}
      if (issue?.code === "needs_reauth") {{
        return {{
          key: "reauth",
          prefix: "↺",
          label: "Needs reauth",
          color: "#e0a65a",
          border: "#f0c27a",
          background: "#14110d",
        }};
      }}
      if (issue?.code === "update_prompt") {{
        return {{
          key: "blocked",
          prefix: "■",
          label: "Blocked",
          color: "#d8bf70",
          border: "#e7d48e",
          background: "#14130d",
        }};
      }}
      if (snapshot.pending) {{
        return {{
          key: "working",
          prefix: "●",
          label: "Working",
          color: "#70d08d",
          border: "#8ce0a5",
          background: "#0d1410",
        }};
      }}
      if (snapshot.last_error) {{
        return {{
          key: "attention",
          prefix: "!",
          label: "Needs attention",
          color: "#d97c7c",
          border: "#e09a9a",
          background: "#160f10",
        }};
      }}
      if (snapshot.state === "ok") {{
        return {{
          key: "ready",
          prefix: "○",
          label: "Ready",
          color: "#8eb5ff",
          border: "#abc8ff",
          background: "#0e131b",
        }};
      }}
      return {{
        key: "idle",
        prefix: "·",
        label: "Idle",
        color: "#9ca7ba",
        border: "#b3bccb",
        background: "#11151b",
      }};
    }}

    function ensureDynamicFaviconLink() {{
      let link = document.querySelector('link[data-dynamic-favicon="state"]');
      if (!link) {{
        link = document.createElement("link");
        link.setAttribute("rel", "icon");
        link.setAttribute("type", "image/svg+xml");
        link.dataset.dynamicFavicon = "state";
        document.head.appendChild(link);
      }}
      return link;
    }}

    function buildStateFaviconHref(descriptor, frame = 0) {{
      const mark = escapeHtml(String(AGENT_MARK || "•").slice(0, 2).toUpperCase());
      const fontSize = mark.length > 1 ? 16 : 22;
      const rotation = descriptor.key === "working" ? (frame % 12) * 30 : 0;
      const identity = FAVICON_AGENT_PALETTE || {{}};
      const svg = `
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
          <defs>
            <linearGradient id="agent-g" x1="10" y1="10" x2="54" y2="54" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="${{identity.accent || descriptor.border}}"/>
              <stop offset="100%" stop-color="${{identity.accent2 || descriptor.color}}"/>
            </linearGradient>
          </defs>
          <rect x="4" y="4" width="56" height="56" rx="12" fill="${{descriptor.background}}" stroke="${{descriptor.border}}" stroke-width="2"/>
          <rect x="10" y="10" width="44" height="44" rx="12" fill="${{identity.surface || 'rgba(255,255,255,0.035)'}}"/>
          <circle cx="32" cy="32" r="14" fill="none" stroke="${{identity.border || descriptor.border}}" stroke-width="4" opacity="0.28"/>
          <g transform="rotate(${{rotation}} 32 32)">
            <path d="M 32 18 A 14 14 0 1 1 18 32" fill="none" stroke="url(#agent-g)" stroke-width="4.5" stroke-linecap="round"/>
          </g>
          <g>
            <circle cx="45" cy="24" r="4.25" fill="${{descriptor.color}}"/>
          </g>
          <rect x="21" y="21" width="22" height="22" rx="8" fill="${{identity.bg || descriptor.background}}" stroke="${{identity.accent || descriptor.border}}" stroke-width="1.4"/>
          <text x="32" y="36.5" text-anchor="middle" font-size="${{fontSize}}" font-weight="700" letter-spacing="0.04em" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" fill="${{identity.text || descriptor.border}}">${{mark}}</text>
        </svg>
      `.trim();
      return `data:image/svg+xml,${{encodeURIComponent(svg)}}`;
    }}

    function syncTabFaviconMotion(descriptor) {{
      const link = ensureDynamicFaviconLink();
      const nextState = String(descriptor.key || "idle");
      const animated = nextState === "working";
      if (state.tabFaviconState !== nextState) {{
        if (state.tabFaviconTimer) {{
          window.clearInterval(state.tabFaviconTimer);
          state.tabFaviconTimer = 0;
        }}
        state.tabFaviconFrame = 0;
      }}
      link.href = buildStateFaviconHref(descriptor, state.tabFaviconFrame);
      state.tabFaviconState = nextState;
      if (!animated || state.tabFaviconTimer) {{
        return;
      }}
      state.tabFaviconTimer = window.setInterval(() => {{
        state.tabFaviconFrame = (state.tabFaviconFrame + 1) % 12;
        ensureDynamicFaviconLink().href = buildStateFaviconHref(descriptor, state.tabFaviconFrame);
      }}, 220);
    }}

    function updateTabChrome(snapshot) {{
      const descriptor = tabStateDescriptor(snapshot);
      const queueDepth = Number(snapshot.queue_depth || 0);
      const title = descriptor.key === "ready" && queueDepth <= 0
        ? TAB_TITLE_LABEL
        : queueDepth > 0 && descriptor.key === "working"
          ? `${{TAB_TITLE_LABEL}} +${{queueDepth}}`
          : `${{TAB_TITLE_LABEL}} · ${{descriptor.label}}`;
      const chromeKey = `${{descriptor.key}}:${{queueDepth}}`;
      syncTabFaviconMotion(descriptor);
      if (state.lastTabChromeKey === chromeKey && document.title === title) {{
        return;
      }}
      document.title = title;
      state.lastTabChromeKey = chromeKey;
    }}

    function serviceTone(value) {{
      const clean = String(value || "").toLowerCase();
      if (clean === "active") return "active";
      if (clean === "failed" || clean === "inactive") return "failed";
      if (clean === "activating" || clean === "deactivating") return "activating";
      return "";
    }}

    function normalizeResponseSpeed(value) {{
      const clean = String(value || "").toLowerCase();
      if (["fast", "balanced", "careful"].includes(clean)) {{
        return clean;
      }}
      return DEFAULT_RESPONSE_SPEED;
    }}

    function normalizeResponseDetail(value) {{
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {{
        return Math.min(5, Math.max(1, Math.round(parsed)));
      }}
      return DEFAULT_RESPONSE_DETAIL;
    }}

    function responseSpeedLabel(value) {{
      const speed = normalizeResponseSpeed(value);
      if (speed === "fast") return "Fast";
      if (speed === "balanced") return "Balanced";
      return "Careful";
    }}

    function responseSpeedControlLabel(value) {{
      const speed = normalizeResponseSpeed(value);
      if (speed === "fast") return "Fast";
      if (speed === "balanced") return "Std";
      return "Deep";
    }}

    function responseSpeedIndex(value) {{
      const speed = normalizeResponseSpeed(value);
      if (speed === "fast") return 1;
      if (speed === "balanced") return 2;
      return 3;
    }}

    function responseSpeedFromIndex(value) {{
      const index = Number(value);
      if (index <= 1) return "fast";
      if (index >= 3) return "careful";
      return "balanced";
    }}

    function responseDetailLabel(value) {{
      return RESPONSE_DETAIL_LABELS[normalizeResponseDetail(value)] || RESPONSE_DETAIL_LABELS[DEFAULT_RESPONSE_DETAIL];
    }}

    function responseProfileText(speed, detail) {{
      return `${{responseSpeedLabel(speed)}} · ${{responseDetailLabel(detail)}}`;
    }}

    function normalizeCompletionBell(value) {{
      const clean = String(value || "").toLowerCase();
      if (clean === "auto" || clean === "off" || clean === "agent") {{
        return clean;
      }}
      if (Object.prototype.hasOwnProperty.call(COMPLETION_BELL_PROFILES, clean)) {{
        return clean;
      }}
      return "auto";
    }}

    function normalizeStyleVariant(value) {{
      const clean = String(value || "").toLowerCase();
      if (clean === "auto") {{
        return clean;
      }}
      if (Object.prototype.hasOwnProperty.call(STYLE_VARIANT_MAP, clean)) {{
        return clean;
      }}
      return "auto";
    }}

    function resolvedStyleVariantKey(value = state.preferences?.styleVariant) {{
      const clean = normalizeStyleVariant(value);
      return clean === "auto" ? AGENT_STYLE_VARIANT : clean;
    }}

    function applyStyleVariantPreference() {{
      const key = resolvedStyleVariantKey(state.preferences?.styleVariant);
      const variant = STYLE_VARIANT_MAP[key] || {{}};
      document.body.dataset.styleVariant = key;
      for (const [token, rawValue] of Object.entries(variant)) {{
        document.documentElement.style.setProperty(`--${{token}}`, String(rawValue));
      }}
    }}

    function defaultCompletionBell() {{
      if (AGENT_COMPLETION_BELL_PROFILE) {{
        return "agent";
      }}
      if (Object.prototype.hasOwnProperty.call(COMPLETION_BELL_PROFILES, AGENT_GROUP)) {{
        return AGENT_GROUP;
      }}
      return "agents";
    }}

    function resolvedCompletionBellKey(value = state.preferences?.completionBell) {{
      const clean = normalizeCompletionBell(value);
      return clean === "auto" ? defaultCompletionBell() : clean;
    }}

    function primeCompletionAudio() {{
      const AudioCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtor) {{
        return null;
      }}
      if (!state.audioContext) {{
        state.audioContext = new AudioCtor();
      }}
      if (state.audioContext.state === "suspended") {{
        state.audioContext.resume().catch(() => {{}});
      }}
      return state.audioContext;
    }}

    function scheduleCompletionBellVoice(ctx, destination, profile, voice, startTime) {{
      const baseFrequency = Math.max(120, Number(profile.frequency || 520));
      const ratio = Math.max(0.125, Number(voice?.ratio || 1));
      const frequency = Math.max(120, baseFrequency * ratio + Number(voice?.detuneHz || 0));
      const attack = Math.max(0.003, Number(profile.attack || 0.008) * Math.max(0.3, Number(voice?.attackMul || 1)));
      const hold = Math.max(0.008, Number(profile.hold || 0.04) * Math.max(0.3, Number(voice?.holdMul || 1)));
      const duration = Math.max(0.12, Number(profile.duration || 0.38) * Math.max(0.2, Number(voice?.duration || voice?.durationMul || 1)));
      const attackEnd = startTime + attack;
      const holdEnd = attackEnd + hold;
      const releaseEnd = startTime + duration;
      const peak = Math.max(0.003, Number(profile.peak || 0.06) * Math.max(0.04, Number(voice?.gain || 1)));
      const sustain = Math.max(0.0016, Number(profile.sustain || 0.02) * Math.max(0.05, Number(voice?.gain || 1)) * Math.max(0.35, Number(voice?.sustainMul || 1)));
      const sweep = Number(profile.sweep || 0) * Number(voice?.sweepMul || 1);
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const filter = ctx.createBiquadFilter();

      osc.type = String(voice?.wave || profile.wave || "sine");
      osc.frequency.setValueAtTime(frequency, startTime);
      osc.frequency.linearRampToValueAtTime(frequency + sweep, holdEnd);
      if (voice?.detuneCents) {{
        osc.detune.setValueAtTime(Number(voice.detuneCents), startTime);
      }}

      filter.type = String(voice?.filterType || "bandpass");
      filter.frequency.setValueAtTime(
        Math.max(320, Number(profile.filter || 1400) * Math.max(0.4, Number(voice?.filterMul || 1))),
        startTime
      );
      filter.Q.value = Math.max(0.2, Number(voice?.q || profile.q || 1));

      gain.gain.setValueAtTime(0.0001, startTime);
      gain.gain.linearRampToValueAtTime(peak, attackEnd);
      gain.gain.exponentialRampToValueAtTime(sustain, holdEnd);
      gain.gain.exponentialRampToValueAtTime(0.0001, releaseEnd);

      osc.connect(filter);
      filter.connect(gain);
      gain.connect(destination);

      osc.start(startTime);
      osc.stop(releaseEnd + 0.02);
    }}

    function playCompletionBell(options = {{}}) {{
      const requested = normalizeCompletionBell(options.profile || state.preferences?.completionBell);
      if (requested === "off") {{
        return;
      }}
      const ctx = primeCompletionAudio();
      if (!ctx || ctx.state !== "running") {{
        return;
      }}
      const key = resolvedCompletionBellKey(requested);
      const activeStyleVariant = resolvedStyleVariantKey(state.preferences?.styleVariant);
      const profile = key === "agent"
        ? buildAgentCompletionBellProfile(activeStyleVariant)
        : (COMPLETION_BELL_PROFILES[key] || COMPLETION_BELL_PROFILES.agents);
      if (!profile) {{
        return;
      }}
      const nowMs = Date.now();
      if (!options.force && nowMs - Number(state.lastCompletionBellAt || 0) < 320) {{
        return;
      }}
      state.lastCompletionBellAt = nowMs;
      const now = ctx.currentTime + 0.012;
      const masterGain = ctx.createGain();
      const delay = ctx.createDelay();
      const delayGain = ctx.createGain();
      const masterLevel = Math.max(0.42, Math.min(0.86, Number(profile.master || 0.68)));
      const baseVoices = Array.isArray(profile.voices) && profile.voices.length
        ? profile.voices
        : [{{ ratio: 1, gain: 1 }}];

      delay.delayTime.setValueAtTime(Math.max(0, Number(profile.echoDelay || 0.07)), now);
      delayGain.gain.setValueAtTime(Math.max(0, Number(profile.echoGain || 0.12)), now);
      masterGain.gain.setValueAtTime(masterLevel, now);
      masterGain.connect(ctx.destination);
      masterGain.connect(delay);
      delay.connect(delayGain);
      delayGain.connect(ctx.destination);

      baseVoices.forEach((voice) => {{
        const startTime = now + Math.max(0, Number(voice?.offset || 0));
        scheduleCompletionBellVoice(ctx, masterGain, profile, voice, startTime);
      }});
      if (profile.answer && typeof profile.answer === "object") {{
        const answerDelay = Math.max(0.03, Number(profile.answer.delay || 0.1));
        scheduleCompletionBellVoice(ctx, masterGain, profile, {{
          ...profile.answer,
          gain: Number(profile.answer.gain || 0.12),
          sweepMul: Number(profile.answer.sweepMul || 0.4),
          duration: Number(profile.answer.duration || 0.28),
          attackMul: Number(profile.answer.attackMul || 1.1),
          offset: 0,
        }}, now + answerDelay);
      }}
    }}

    function containsTokenReuseError(value) {{
      const text = String(value || "").toLowerCase();
      if (!text) return false;
      return text.includes("refresh_token_reused")
        || text.includes("refresh token was already used")
        || text.includes("log out and sign in again");
    }}

    function containsOpenAIAuthError(value) {{
      const text = String(value || "").toLowerCase();
      if (!text) return false;
      return text.includes("missing bearer basic authentication in header")
        || (
          text.includes("401 unauthorized")
          && (
            text.includes("api.openai.com/v1/responses")
            || text.includes("missing bearer")
            || text.includes("basic authentication in header")
          )
        );
    }}

    function containsCodexAuthFailure(value) {{
      return containsTokenReuseError(value) || containsOpenAIAuthError(value);
    }}

    function containsCodexCliUpgradeError(value) {{
      const text = String(value || "").toLowerCase();
      return text.includes("requires a newer version of codex")
        || text.includes("please upgrade to the latest app or cli");
    }}

    function containsOpenAITransportError(value) {{
      const text = String(value || "").toLowerCase();
      if (!text || containsOpenAIAuthError(text)) return false;
      return (
        text.includes("codex_api::endpoint::responses_websocket")
        && text.includes("failed to connect to websocket")
      ) || (
        text.includes("api.openai.com/v1/responses")
        && text.includes("500 internal server error")
      );
    }}

    function containsCertWorkflowError(value) {{
      const text = String(value || "").toLowerCase();
      if (!text) return false;
      if (
        text.includes("certificate_verify_failed")
        || text.includes("certbot")
        || text.includes("acme")
        || text.includes("x509")
        || text.includes("make_cert")
        || text.includes("cert queue")
        || text.includes("cert-worker")
        || text.includes("cert_enqueue")
      ) {{
        return true;
      }}
      const hasCertish = text.includes("certificate") || text.includes("ssl") || text.includes("tls");
      const hasFailure =
        text.includes("error")
        || text.includes("failed")
        || text.includes("invalid")
        || text.includes("expired")
        || text.includes("mismatch")
        || text.includes("verify")
        || text.includes("handshake");
      return hasCertish && hasFailure;
    }}

    function isPlaceholderAssistantResponse(value) {{
      const response = String(value || "").trim().toLowerCase();
      return response === "[no response returned]" || response === "[waiting for reply]";
    }}

    function staleHistoryError(snapshot, value) {{
      const error = String(value || "").trim();
      if (!error || !(containsCodexAuthFailure(error) || containsCodexCliUpgradeError(error))) {{
        return false;
      }}
      if (latestHistoryRequiresReauth(snapshot)) {{
        return false;
      }}
      const auth = currentAuthState(snapshot);
      if (auth.required) {{
        return false;
      }}
      const pane = String(snapshot?.pane || "");
      return containsCodexReadyPrompt(pane)
        || pane.includes("Signed in with your ChatGPT account")
        || pane.includes("Do you trust the contents of this directory?")
        || containsActiveUpdateInterstitial(pane);
    }}

    function containsUsageLimitError(value) {{
      const text = String(value || "").toLowerCase();
      if (!text) return false;
      return text.includes("you've hit your usage limit")
        || text.includes("you hit your usage limit")
        || (text.includes("usage limit") && text.includes("try again at"))
        || (text.includes("usage limit") && text.includes("send a request to your admin"));
    }}

    function containsUpdateInterstitial(value) {{
      const text = String(value || "");
      if (!text) return false;
      return text.includes("Update available!") && text.includes("Press enter to continue");
    }}

    function containsCodexReadyPrompt(value) {{
      const text = String(value || "");
      if (!text) return false;
      return (text.includes("OpenAI Codex (v") && text.includes("directory:"))
        || (text.includes("› ") && text.includes("gpt-") && text.includes("% left ·"));
    }}

    function historyEntryRequiresReauth(entry) {{
      if (!entry || typeof entry !== "object") {{
        return false;
      }}
      const error = String(entry.error || "").trim();
      if (!containsCodexAuthFailure(error)) {{
        return false;
      }}
      const response = String(entry.response || "").trim().toLowerCase();
      if (response && !isPlaceholderAssistantResponse(response)) {{
        return false;
      }}
      const usage = entry.usage && typeof entry.usage === "object" ? entry.usage : {{}};
      if (Boolean(usage.success)) {{
        return false;
      }}
      if (Math.max(0, Number(usage.total_tokens || 0)) > 0) {{
        return false;
      }}
      return Boolean(String(entry.prompt || "").trim());
    }}

    function latestHistoryRequiresReauth(snapshot) {{
      const history = Array.isArray(snapshot?.history) ? snapshot.history : [];
      for (let index = history.length - 1; index >= 0; index -= 1) {{
        const item = history[index];
        if (historyEntryRequiresReauth(item)) {{
          return true;
        }}
        if (!item || typeof item !== "object") {{
          continue;
        }}
        if (String(item.prompt || "").trim() || String(item.response || "").trim() || String(item.error || "").trim()) {{
          return false;
        }}
      }}
      return false;
    }}

    function updateInterstitialIsStale(value) {{
      const text = String(value || "");
      if (!text || !containsUpdateInterstitial(text)) return false;
      const updateIndex = Math.max(
        text.lastIndexOf("Update available!"),
        text.lastIndexOf("Run npm install -g @openai/codex to update.")
      );
      const readyIndex = Math.max(
        text.lastIndexOf("OpenAI Codex (v"),
        text.lastIndexOf("Tip: Use /status to see the current model, approvals, and token usage."),
        text.lastIndexOf("% left ·")
      );
      return updateIndex >= 0 && readyIndex > updateIndex;
    }}

    function containsActiveUpdateInterstitial(value) {{
      return containsUpdateInterstitial(value) && !updateInterstitialIsStale(value);
    }}

    function currentAuthState(snapshot = state.snapshot) {{
      if (!snapshot || typeof snapshot !== "object") {{
        return {{}};
      }}
      const auth = snapshot.auth;
      return auth && typeof auth === "object" ? auth : {{}};
    }}

    function browserAuthHelperHref() {{
      const query = new URLSearchParams();
      if (ACTIVE_PROFILE) {{
        query.set("profile", ACTIVE_PROFILE);
      }}
      if (ACTIVE_ROUTE && ACTIVE_ROUTE !== "auto") {{
        query.set("route", ACTIVE_ROUTE);
      }}
      const suffix = query.toString();
      const base = clientPath("/auth/browser/callback");
      return suffix ? `${{base}}?${{suffix}}` : base;
    }}

    function browserAuthHelperAbsoluteHref() {{
      try {{
        return new URL(browserAuthHelperHref(), window.location.href).toString();
      }} catch (_) {{
        return browserAuthHelperHref();
      }}
    }}

    function browserAuthBridgeApiBase() {{
      return "http://127.0.0.1:1455";
    }}

    function browserAuthBridgeLaunchHref(authUrl) {{
      const stateToken = extractAuthStateToken(authUrl);
      if (!stateToken) {{
        return String(authUrl || "").trim();
      }}
      const launch = new URL("/arm", browserAuthBridgeApiBase());
      launch.searchParams.set("state", stateToken);
      launch.searchParams.set("forward_url", browserAuthHelperAbsoluteHref());
      if (AGENT_LABEL) {{
        launch.searchParams.set("label", AGENT_LABEL);
      }}
      launch.searchParams.set("console_url", window.location.href);
      launch.searchParams.set("next_url", String(authUrl || "").trim());
      return launch.toString();
    }}

    function extractAuthStateToken(authUrl) {{
      try {{
        const parsed = new URL(String(authUrl || ""), window.location.href);
        return String(parsed.searchParams.get("state") || "").trim();
      }} catch (_) {{
        return "";
      }}
    }}

    async function armLocalBrowserAuthBridge(authUrl) {{
      const stateToken = extractAuthStateToken(authUrl);
      if (!stateToken) {{
        return false;
      }}
      const payload = {{
        state: stateToken,
        forward_url: browserAuthHelperAbsoluteHref(),
        label: AGENT_LABEL,
        console_url: window.location.href,
      }};
      const response = await window.fetch(`${{browserAuthBridgeApiBase()}}/api/arm`, {{
        method: "POST",
        mode: "cors",
        cache: "no-store",
        headers: {{
          "Content-Type": "application/json",
        }},
        body: JSON.stringify(payload),
      }});
      if (!response.ok) {{
        throw new Error(`auth bridge returned ${{response.status}}`);
      }}
      return true;
    }}

    function browserAuthActionHref() {{
      const query = new URLSearchParams();
      if (ACTIVE_PROFILE) {{
        query.set("profile", ACTIVE_PROFILE);
      }}
      if (ACTIVE_ROUTE && ACTIVE_ROUTE !== "auto") {{
        query.set("route", ACTIVE_ROUTE);
      }}
      const suffix = query.toString();
      const base = clientPath("/auth/browser");
      return suffix ? `${{base}}?${{suffix}}` : base;
    }}

    function runtimeIssue(snapshot) {{
      const auth = currentAuthState(snapshot);
      const authMode = String(auth.mode || "");
      if (auth.required) {{
        if (authMode === "browser_signin") {{
          return {{
            code: "browser_signin",
            tone: "alert",
            title: "Continue sign-in",
            label: "Sign in",
            summary: auth.summary || "Finish browser sign-in in a new tab and relay the callback.",
          }};
        }}
        if (authMode === "device_code") {{
          return {{
            code: "device_code",
            tone: "alert",
            title: "Device code ready",
            label: "Device code",
            summary: auth.summary || "Complete device-code sign-in in your browser.",
          }};
        }}
        if (authMode === "signin_choice") {{
          return {{
            code: "signin_choice",
            tone: "alert",
            title: "Choose sign-in",
            label: "Auth",
            summary: auth.summary || "Choose a sign-in method to continue.",
          }};
        }}
      }}
      const pane = String(snapshot?.pane || "");
      const error = String(snapshot?.last_error || "");
      const combined = `${{error}}\n${{pane}}`.trim();
      if (containsUsageLimitError(combined)) {{
        return {{
          code: "needs_billing",
          tone: "alert",
          title: "Needs billing",
          label: "Needs billing",
          summary: "This bot hit its usage limit. Open billing or limits, or switch it to the right account.",
        }};
      }}
      if (latestHistoryRequiresReauth(snapshot)) {{
        return {{
          code: "needs_reauth",
          tone: "alert",
          title: "Needs reauth",
          label: "Needs reauth",
          summary: "Recent web prompts are failing because this bot needs a fresh sign-in.",
        }};
      }}
      if (containsCodexAuthFailure(combined)) {{
        return {{
          code: "needs_reauth",
          tone: "alert",
          title: "Needs reauth",
          label: "Needs reauth",
          summary: containsTokenReuseError(combined)
            ? "Codex needs a fresh sign-in. The stored refresh token was already used."
            : "OpenAI rejected this turn because the bot lost its auth headers. Reauthenticate this bot.",
        }};
      }}
      if (containsCertWorkflowError(combined)) {{
        return {{
          code: "cert_workflow",
          tone: "alert",
          title: "Cert issue",
          label: "Cert issue",
          summary: "Certificate/TLS workflow failed. Expand details if you need the raw log, then retry from the right host family.",
        }};
      }}
      if (containsOpenAITransportError(combined)) {{
        return {{
          code: "openai_transport",
          tone: "alert",
          title: "OpenAI issue",
          label: "API issue",
          summary: "OpenAI's responses websocket failed during this turn. Retry if it clears; reauthenticate if it keeps turning into 401s.",
        }};
      }}
      if (containsActiveUpdateInterstitial(pane)) {{
        return {{
          code: "update_prompt",
          tone: "queue",
          title: "Needs unblock",
          label: "Needs unblock",
          summary: "Codex is paused on its update screen. The supervisor should clear it shortly.",
        }};
      }}
      return null;
    }}

    function activeRunningSpeed(snapshot) {{
      return normalizeResponseSpeed(snapshot.running_speed || snapshot.last_speed || DEFAULT_RESPONSE_SPEED);
    }}

    function activeRunningDetail(snapshot) {{
      return normalizeResponseDetail(snapshot.running_detail || snapshot.last_detail || DEFAULT_RESPONSE_DETAIL);
    }}

    function historyEntries(snapshot) {{
      const items = Array.isArray(snapshot.history) ? [...snapshot.history] : [];
      if (!items.length && !snapshot.pending && snapshot.last_prompt && snapshot.last_prompt !== "[no prompt yet]") {{
        items.push({{
          attachments: Array.isArray(snapshot.last_attachments) ? snapshot.last_attachments : [],
          detail: snapshot.last_detail || DEFAULT_RESPONSE_DETAIL,
          prompt: snapshot.last_prompt,
          response: snapshot.last_response || "",
          error: snapshot.last_error || "",
          speed: snapshot.last_speed || DEFAULT_RESPONSE_SPEED,
          finished_at: snapshot.last_finished_at || 0,
          started_at: snapshot.last_started_at || 0,
          thread_id: snapshot.thread_id || "",
        }});
      }}
      return items.map((item) => {{
        if (!item || typeof item !== "object") {{
          return item;
        }}
        if (!staleHistoryError(snapshot, item.error)) {{
          return item;
        }}
        return {{
          ...item,
          error: "",
        }};
      }});
    }}

    function latestAssistantEntry(snapshot = state.snapshot) {{
      const items = historyEntries(snapshot);
      for (let index = items.length - 1; index >= 0; index -= 1) {{
        const item = items[index];
        if (!item) {{
          continue;
        }}
        if (String(item.response || "").trim() || String(item.error || "").trim()) {{
          return item;
        }}
      }}
      return null;
    }}

    function conversationTailKey(snapshot = state.snapshot) {{
      const items = historyEntries(snapshot);
      const last = items.length ? items[items.length - 1] : null;
      return JSON.stringify({{
        thread_id: String(snapshot?.thread_id || ""),
        pending: Boolean(snapshot?.pending && snapshot?.running_prompt),
        running_prompt: String(snapshot?.running_prompt || ""),
        running_status: String(snapshot?.status_message || ""),
        last_started_at: Number(snapshot?.last_started_at || 0),
        last_finished_at: Number(snapshot?.last_finished_at || 0),
        history_count: items.length,
        last_prompt: String(last?.prompt || ""),
        last_response: String(last?.response || ""),
        last_error: String(last?.error || ""),
        queue_depth: Number(snapshot?.queue_depth || 0),
      }});
    }}

    function brokerInsight(snapshot = state.snapshot) {{
      if (!snapshot || snapshot.pending) {{
        return null;
      }}
      const latest = latestAssistantEntry(snapshot);
      if (!latest) {{
        return null;
      }}
      const response = String(latest.response || "").trim();
      if (!response) {{
        return null;
      }}
      const text = response.toLowerCase();
      const triggers = [
        /coordinate with norman/,
        /norman prime/,
        /subprime/,
        /switchboard/,
        /\buse ask another\b/,
        /\bmost useful handoff\b/,
        /\bhand ?off\b/,
        /\blinked bot\b/,
        /\banother bot\b/,
        /\bother bot\b/,
        /\bother agent\b/,
        /\bagent id\b/,
        /\bparty line\b/,
        /\black a transport\b/,
        /\bdon'?t have a transport\b/,
        /\bno transport\b/,
        /\bchannel tool\b/,
        /session\/thread log path/,
        /repo\/folder\/path/,
      ];
      if (!triggers.some((pattern) => pattern.test(text))) {{
        return null;
      }}
      const targets = RELAY_TARGETS.map((item) => String(item?.label || "").trim()).filter(Boolean);
      const linkedSummary = targets.length
        ? `Linked: ${{targets.slice(0, 3).join(", ")}}${{targets.length > 3 ? ` +${{targets.length - 3}}` : ""}}. Use the Switchboard or Norman/Subprime if another lane should carry it.`
        : "Norman Prime or Switchboard should broker the next step.";
      const copy = targets.length
        ? "This bot is asking for another bot's context or a Switchboard-brokered handoff."
        : "This bot is asking Norman Prime or Switchboard to broker the next step.";
      return {{
        title: "Broker via Norman",
        label: "Broker",
        copy,
        detail: summarizePrompt(response, window.innerWidth <= 640 ? 96 : 156),
        linkedSummary,
        targets,
        sourcePrompt: String(latest.prompt || ""),
        sourceResponse: response,
      }};
    }}

    function inferBackgroundTask(snapshot = state.snapshot) {{
      if (!snapshot || snapshot.pending) {{
        return null;
      }}
      const latest = latestAssistantEntry(snapshot);
      if (!latest) {{
        return null;
      }}
      const response = String(latest.response || "").trim();
      if (!response) {{
        return null;
      }}
      const lines = response
        .replace(/\\r\\n/g, "\\n")
        .split("\\n")
        .map(trimConsoleLine)
        .filter(Boolean);
      if (!lines.length) {{
        return null;
      }}
      const runtimeMatchers = [
        /^(?:[-*•]\s*)?runtime paths?:?$/i,
        /^(?:[-*•]\s*)?pid:\s*/i,
        /^(?:[-*•]\s*)?run dir:\s*/i,
        /^(?:[-*•]\s*)?log:\s*/i,
        /^(?:[-*•]\s*)?pid file:\s*/i,
      ];
      const lifecycleMatchers = [
        /\brunning now\b/i,
        /\bstarted cleanly\b/i,
        /\bworker is alive\b/i,
        /\breconnect in\b/i,
        /\bcheck back in\b/i,
        /\bcome back in\b/i,
        /\bstill running\b/i,
        /\bbatch is live\b/i,
        /\bin the background\b/i,
      ];
      const runtimeLines = lines.filter((line) => runtimeMatchers.some((pattern) => pattern.test(line)));
      const lifecycleLines = lines.filter((line) => lifecycleMatchers.some((pattern) => pattern.test(line)));
      if (
        !(
          (runtimeLines.length >= 2 && lifecycleLines.length >= 1)
          || (runtimeLines.length >= 1 && lifecycleLines.length >= 2)
        )
      ) {{
        return null;
      }}
      const titleLine = lifecycleLines.find((line) => /running now|batch is live|still running/i.test(line))
        || lifecycleLines[0]
        || "Background task is still running.";
      const pidLine = runtimeLines.find((line) => /pid:/i.test(line)) || "";
      const etaLine = lines.find((line) => /\b(reconnect|check back|come back) in\b/i.test(line)) || "";
      const pidMatch = pidLine.match(/pid:\s*([0-9]+)/i);
      const etaMatch = etaLine.match(/(\d+)\s*(?:minute|min|hour|hr)/i);
      const metaParts = [];
      if (pidMatch) {{
        metaParts.push(`PID ${{pidMatch[1]}}`);
      }}
      if (etaMatch) {{
        metaParts.push(etaMatch[0].replace(/^0+/, ""));
      }}
      if (!metaParts.length && runtimeLines.length) {{
        metaParts.push("launched");
      }}
      const detailLine = etaLine
        || lifecycleLines.find((line) => line !== titleLine)
        || runtimeLines.find((line) => line !== pidLine && !/runtime paths?/i.test(line))
        || "Open the latest reply for runtime paths and log links.";
      return {{
        title: summarizePrompt(titleLine, window.innerWidth <= 640 ? 64 : 96),
        detail: summarizePrompt(detailLine, window.innerWidth <= 640 ? 72 : 112),
        meta: metaParts.join(" · ") || "background task live",
        key: `${{Number(latest.finished_at || snapshot.last_finished_at || 0)}}:${{titleLine}}`,
      }};
    }}

    function queuedEntries(snapshot) {{
      return Array.isArray(snapshot.queued_prompts) ? snapshot.queued_prompts : [];
    }}

    function queueRelayCallback(item) {{
      const relay = item && typeof item === "object" ? item.relay_callback : null;
      return relay && typeof relay === "object" ? relay : null;
    }}

    function relayQueueLabel(relay) {{
      return String(relay?.target_connector_name || relay?.target || relay?.relay_id || "Switchboard").trim() || "Switchboard";
    }}

    function safeStorageGet(key) {{
      try {{
        return window.localStorage.getItem(key);
      }} catch (_) {{
        return null;
      }}
    }}

    function safeStorageSet(key, value) {{
      try {{
        window.localStorage.setItem(key, value);
      }} catch (_) {{
        // Ignore unavailable storage and continue with in-memory preferences.
      }}
    }}

    function safeStorageRemove(key) {{
      try {{
        window.localStorage.removeItem(key);
      }} catch (_) {{
        // Ignore unavailable storage and continue with in-memory state.
      }}
    }}

    function textBlockSignature(value) {{
      const text = String(value || "");
      if (!text) {{
        return "0";
      }}
      if (text.length <= 280) {{
        return text;
      }}
      return `${{text.length}}:${{text.slice(0, 80)}}:${{text.slice(-160)}}`;
    }}

    function attachmentSignature(items) {{
      if (!Array.isArray(items) || !items.length) {{
        return "";
      }}
      return items.map((item) => {{
        if (!item || typeof item !== "object") {{
          return String(item || "");
        }}
        return [
          String(item.token || ""),
          String(item.kind || ""),
          String(item.name || ""),
          String(item.path || ""),
          String(item.content_type || ""),
        ].join("::");
      }}).join("||");
    }}

    function conversationRenderSignature(snapshot) {{
      const items = historyEntries(snapshot);
      const queued = queuedEntries(snapshot);
      const windowSize = recentHistoryWindow();
      const visibleItems = state.historyExpanded ? items : items.slice(-windowSize);
      return JSON.stringify({{
        thread_id: String(snapshot?.thread_id || ""),
        expanded: Boolean(state.historyExpanded),
        window_size: windowSize,
        total_turns: items.length,
        visible: visibleItems.map((item) => ({{
          started_at: Number(item?.started_at || 0),
          finished_at: Number(item?.finished_at || 0),
          speed: String(item?.speed || ""),
          detail: Number(item?.detail || 0),
          prompt: textBlockSignature(item?.prompt || ""),
          response: textBlockSignature(item?.response || ""),
          error: textBlockSignature(item?.error || ""),
          attachments: attachmentSignature(item?.attachments),
        }})),
        pending: Boolean(snapshot?.pending && snapshot?.running_prompt),
        running_prompt: textBlockSignature(snapshot?.running_prompt || ""),
        running_profile: responseProfileText(snapshot?.running_speed, snapshot?.running_detail),
        running_started_at: Number(snapshot?.last_started_at || 0),
        model_process_alive: Boolean(snapshot?.model_process_alive),
        running_attachments: attachmentSignature(snapshot?.running_attachments),
        queued: queued.map((item) => ({{
          queued_at: Number(item?.queued_at || 0),
          speed: String(item?.speed || ""),
          detail: Number(item?.detail || 0),
          source: String(item?.source || ""),
          recovered: Boolean(item?.recovered),
          prompt: textBlockSignature(item?.prompt || ""),
          attachments: attachmentSignature(item?.attachments),
        }})),
      }});
    }}

    function loadPromptDraft() {{
      const raw = safeStorageGet(PROMPT_DRAFT_STORAGE_KEY);
      if (!raw) {{
        return "";
      }}
      try {{
        const payload = JSON.parse(raw);
        const updatedAt = Number(payload?.updatedAt || 0);
        const value = String(payload?.value || "");
        if (!value.trim()) {{
          safeStorageRemove(PROMPT_DRAFT_STORAGE_KEY);
          return "";
        }}
        if (updatedAt > 0 && Date.now() - updatedAt > PROMPT_DRAFT_MAX_AGE_MS) {{
          safeStorageRemove(PROMPT_DRAFT_STORAGE_KEY);
          return "";
        }}
        return value;
      }} catch (_) {{
        const fallback = String(raw || "");
        if (!fallback.trim()) {{
          safeStorageRemove(PROMPT_DRAFT_STORAGE_KEY);
          return "";
        }}
        return fallback;
      }}
    }}

    function persistPromptDraft(value = el.promptInput.value) {{
      const text = String(value ?? "");
      if (!text.trim()) {{
        safeStorageRemove(PROMPT_DRAFT_STORAGE_KEY);
        return false;
      }}
      const payload = {{
        value: text.slice(0, 20000),
        updatedAt: Date.now(),
        threadId: String(state.activeThreadId || state.snapshot?.thread_id || ""),
        uiVersion: UI_VERSION,
      }};
      safeStorageSet(PROMPT_DRAFT_STORAGE_KEY, JSON.stringify(payload));
      return true;
    }}

    function restorePromptDraft() {{
      if (!el.promptInput || el.promptInput.value.trim()) {{
        return false;
      }}
      const draft = loadPromptDraft();
      if (!draft) {{
        return false;
      }}
      el.promptInput.value = draft;
      autoresize(el.promptInput);
      updateComposerToolbar(state.snapshot);
      renderSuggestions(state.snapshot);
      return true;
    }}

    function clearPromptDraft() {{
      safeStorageRemove(PROMPT_DRAFT_STORAGE_KEY);
    }}

    function encodeSwitcherToken(payload) {{
      try {{
        const json = JSON.stringify(payload || {{}});
        return btoa(unescape(encodeURIComponent(json)))
          .replace(/\\+/g, "-")
          .replace(/\\//g, "_")
          .replace(/=+$/g, "");
      }} catch (_) {{
        return "";
      }}
    }}

    function decodeSwitcherToken(value) {{
      const raw = String(value || "").trim();
      if (!raw) {{
        return null;
      }}
      try {{
        const padded = raw.replace(/-/g, "+").replace(/_/g, "/");
        const normalized = padded + "=".repeat((4 - (padded.length % 4 || 4)) % 4);
        return JSON.parse(decodeURIComponent(escape(atob(normalized))));
      }} catch (_) {{
        return null;
      }}
    }}

    function normalizeSwitcherHref(value) {{
      try {{
        const url = new URL(String(value || ""), window.location.href);
        url.searchParams.delete(SWITCHER_STATE_PARAM);
        url.hash = "";
        return url.toString();
      }} catch (_) {{
        return String(value || "").trim();
      }}
    }}

    function compactHostLabel(value) {{
      try {{
        const url = new URL(String(value || ""), window.location.href);
        let host = url.hostname || "";
        host = host.replace(/\\.tail[0-9]+\\.ts\\.net$/i, "");
        if (!host || host === window.location.hostname || host === "127.0.0.1" || host === "localhost") {{
          host = "Here";
        }}
        if (url.port && !["80", "443"].includes(url.port)) {{
          return `${{host}}:${{url.port}}`;
        }}
        return host;
      }} catch (_) {{
        return "";
      }}
    }}

    function switcherItemKey(group, label) {{
      const cleanGroup = String(group || "agents").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
      const cleanLabel = String(label || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
      return `${{cleanGroup}}::${{cleanLabel}}`;
    }}

    function activeConsoleGroupFallback() {{
      return document.querySelector(".console-group-pill.active")?.dataset.group
        || consoleGroupButtons[0]?.dataset.group
        || "all";
    }}

    function buildSwitcherCatalog() {{
      const groupLabels = new Map(
        consoleGroupButtons.map((button) => [
          button.dataset.group || "",
          button.querySelector("span")?.textContent?.trim() || button.dataset.group || "",
        ])
      );
      const currentHref = normalizeSwitcherHref(window.location.href);
      const seen = new Set();
      const items = [];
      for (const link of consoleNavLinks) {{
        const group = String(link.dataset.group || "").trim() || "agents";
        const label = link.dataset.label || link.textContent?.trim() || "Agent";
        const href = normalizeSwitcherHref(link.href);
        const key = switcherItemKey(group, label);
        if (!href || seen.has(key)) {{
          continue;
        }}
        seen.add(key);
        link.dataset.switcherKey = key;
        link.dataset.switcherBase = href;
        items.push({{
          key,
          label,
          group,
          groupLabel: groupLabels.get(group) || group,
          href,
          host: compactHostLabel(href),
          current: href === currentHref || label === AGENT_LABEL,
        }});
      }}
      return items;
    }}

    function switcherCatalogMap() {{
      return new Map((state.switcher?.catalog || []).map((item) => [item.key, item]));
    }}

    function tuiHrefForLabel(label) {{
      const clean = normalizeInlineEntityKey(label);
      if (!clean) {{
        return "";
      }}
      const knownAlias = INLINE_ENTITY_ALIAS_MAP.get(clean);
      const matchKeys = new Set([clean]);
      if (knownAlias?.entity?.label) {{
        matchKeys.add(normalizeInlineEntityKey(knownAlias.entity.label));
      }}
      if (knownAlias?.entity?.key) {{
        matchKeys.add(normalizeInlineEntityKey(knownAlias.entity.key));
      }}
      const matchesCleanLabel = (value) => {{
        const candidate = normalizeInlineEntityKey(value);
        for (const key of matchKeys) {{
          if (candidate === key || candidate.startsWith(`${{key}}-`) || key.startsWith(`${{candidate}}-`)) {{
            return true;
          }}
        }}
        return false;
      }};
      if (clean === normalizeInlineEntityKey(AGENT_LABEL)) {{
        return normalizeSwitcherHref(window.location.href);
      }}
      const relayTarget = RELAY_TARGETS.find((target) => (
        matchesCleanLabel(target?.label || "")
      ));
      if (relayTarget?.url) {{
        return relayTarget.url;
      }}
      const catalog = Array.isArray(state.switcher?.catalog) ? state.switcher.catalog : [];
      const catalogItem = catalog.find((item) => (
        matchesCleanLabel(item?.label || "")
        || matchesCleanLabel(String(item?.key || "").split("::").pop() || "")
      ));
      if (catalogItem?.href) {{
        return state.switcher
          ? buildSwitcherHref(catalogItem.href, catalogItem.key)
          : normalizeSwitcherHref(catalogItem.href);
      }}
      const navLink = consoleNavLinks.find((link) => (
        matchesCleanLabel(link.dataset.label || link.textContent || "")
      ));
      if (navLink?.href) {{
        const baseHref = navLink.dataset.switcherBase || navLink.href;
        const key = navLink.dataset.switcherKey || "";
        return state.switcher ? buildSwitcherHref(baseHref, key) : normalizeSwitcherHref(baseHref);
      }}
      return "";
    }}

    function normalizeSwitcherKeys(values, catalogMap) {{
      return Array.from(
        new Set(
          (Array.isArray(values) ? values : [])
            .map((item) => String(item || "").trim())
            .filter((item) => catalogMap.has(item))
        )
      );
    }}

    function switcherPayloadFromState(model = state.switcher) {{
      return {{
        activeGroup: model?.activeGroup || activeConsoleGroupFallback(),
        activeView: model?.activeView || "recent",
        recents: normalizeSwitcherKeys(model?.recents, switcherCatalogMap()).slice(0, SWITCHER_RECENTS_LIMIT),
        pins: normalizeSwitcherKeys(model?.pins, switcherCatalogMap()),
      }};
    }}

    function stripSwitcherStateFromUrl() {{
      try {{
        const url = new URL(window.location.href);
        if (!url.searchParams.has(SWITCHER_STATE_PARAM)) {{
          return;
        }}
        url.searchParams.delete(SWITCHER_STATE_PARAM);
        window.history.replaceState(null, "", url.toString());
      }} catch (_) {{
        // Ignore malformed current URL state.
      }}
    }}

    function loadSwitcherState() {{
      const catalog = buildSwitcherCatalog();
      const catalogMap = new Map(catalog.map((item) => [item.key, item]));
      const queryValue = new URLSearchParams(window.location.search).get(SWITCHER_STATE_PARAM);
      const queryPayload = decodeSwitcherToken(queryValue);
      const storedRaw = safeStorageGet(SWITCHER_STORAGE_KEY);
      let storedPayload = null;
      if (storedRaw) {{
        try {{
          storedPayload = JSON.parse(storedRaw);
        }} catch (_) {{
          storedPayload = null;
        }}
      }}
      const payload = queryPayload || storedPayload || {{}};
      const activeGroup = String(payload.activeGroup || activeConsoleGroupFallback()).trim() || activeConsoleGroupFallback();
      const activeView = ["recent", "pinned", "all"].includes(String(payload.activeView || ""))
        ? String(payload.activeView)
        : "recent";
      const model = {{
        catalog,
        activeGroup,
        activeView,
        recents: normalizeSwitcherKeys(payload.recents, catalogMap).slice(0, SWITCHER_RECENTS_LIMIT),
        pins: normalizeSwitcherKeys(payload.pins, catalogMap),
        query: "",
      }};
      if (model.activeView === "recent" && !model.recents.length) {{
        model.activeView = "all";
      }}
      stripSwitcherStateFromUrl();
      return model;
    }}

    function saveSwitcherState() {{
      safeStorageSet(SWITCHER_STORAGE_KEY, JSON.stringify(switcherPayloadFromState()));
    }}

    function recordRecentSwitcherKey(key) {{
      const clean = String(key || "").trim();
      if (!clean || !switcherCatalogMap().has(clean)) {{
        return;
      }}
      state.switcher.recents = [clean, ...state.switcher.recents.filter((item) => item !== clean)].slice(0, SWITCHER_RECENTS_LIMIT);
      saveSwitcherState();
    }}

    function togglePinnedSwitcherKey(key) {{
      const clean = String(key || "").trim();
      if (!clean || !switcherCatalogMap().has(clean)) {{
        return;
      }}
      if (state.switcher.pins.includes(clean)) {{
        state.switcher.pins = state.switcher.pins.filter((item) => item !== clean);
      }} else {{
        state.switcher.pins = [clean, ...state.switcher.pins.filter((item) => item !== clean)];
      }}
      saveSwitcherState();
      renderSwitcher();
    }}

    function renderSwitcherHostCartouche(host) {{
      const label = String(host || "").trim();
      if (!label) {{
        return "";
      }}
      return `<span class="switcher-item-host" title="${{escapeHtml(label)}}">${{renderNameCartouche(label, {{ kind: "host", tone: "host", compact: true }})}}</span>`;
    }}

    function buildSwitcherHref(baseHref, recentKey = "") {{
      try {{
        const url = new URL(String(baseHref || ""), window.location.href);
        const nextPayload = switcherPayloadFromState();
        if (recentKey && switcherCatalogMap().has(recentKey)) {{
          nextPayload.recents = [recentKey, ...nextPayload.recents.filter((item) => item !== recentKey)].slice(0, SWITCHER_RECENTS_LIMIT);
        }}
        const encoded = encodeSwitcherToken(nextPayload);
        if (encoded) {{
          url.searchParams.set(SWITCHER_STATE_PARAM, encoded);
        }}
        return url.toString();
      }} catch (_) {{
        return String(baseHref || "");
      }}
    }}

    function switcherViewItems() {{
      const catalog = Array.isArray(state.switcher?.catalog) ? state.switcher.catalog : [];
      const byKey = switcherCatalogMap();
      const groupFilter = String(state.switcher?.activeGroup || "all");
      let items;
      if (state.switcher?.activeView === "pinned") {{
        items = state.switcher.pins.map((key) => byKey.get(key)).filter(Boolean);
      }} else if (state.switcher?.activeView === "recent") {{
        items = state.switcher.recents.map((key) => byKey.get(key)).filter(Boolean);
      }} else {{
        items = [...catalog];
      }}
      if (groupFilter && groupFilter !== "all") {{
        items = items.filter((item) => item.group === groupFilter);
      }}
      const query = String(state.switcher?.query || "").trim().toLowerCase();
      if (query) {{
        items = items.filter((item) =>
          `${{item.label}} ${{item.groupLabel}} ${{item.host}}`.toLowerCase().includes(query)
        );
      }}
      return items;
    }}

    function renderSwitcher() {{
      if (!state.switcher) {{
        return;
      }}
      el.switcherSearchInput.value = state.switcher.query || "";
      const catalog = state.switcher.catalog || [];
      const groupCounts = new Map([["all", catalog.length]]);
      for (const item of catalog) {{
        groupCounts.set(item.group, (groupCounts.get(item.group) || 0) + 1);
      }}
      const groupOptions = [
        {{ slug: "all", label: "All", count: catalog.length }},
        ...consoleGroupButtons.map((button) => {{
          const slug = button.dataset.group || "";
          return {{
            slug,
            label: button.querySelector("span")?.textContent?.trim() || slug,
            count: groupCounts.get(slug) || 0,
          }};
        }}),
      ].filter((item, index, array) => item.count > 0 && array.findIndex((entry) => entry.slug === item.slug) === index);
      if (!groupOptions.some((item) => item.slug === state.switcher.activeGroup)) {{
        state.switcher.activeGroup = "all";
      }}
      const viewOptions = [
        {{ slug: "recent", label: "Recent", count: state.switcher.recents.length }},
        {{ slug: "pinned", label: "Pinned", count: state.switcher.pins.length }},
        {{ slug: "all", label: "All", count: catalog.length }},
      ];
      if (state.switcher.activeView !== "all" && !viewOptions.find((item) => item.slug === state.switcher.activeView)?.count) {{
        state.switcher.activeView = "all";
      }}
      el.switcherViews.innerHTML = viewOptions.map((item) => `
        <button type="button" class="ghost switcher-chip${{item.slug === state.switcher.activeView ? " active" : ""}}" data-switcher-view="${{escapeHtml(item.slug)}}">
          <span>${{escapeHtml(item.label)}}</span>
          <span class="switcher-chip-count">${{escapeHtml(String(item.count))}}</span>
        </button>
      `).join("");
      el.switcherGroups.innerHTML = groupOptions.map((item) => `
        <button type="button" class="ghost switcher-chip${{item.slug === state.switcher.activeGroup ? " active" : ""}}" data-switcher-group="${{escapeHtml(item.slug)}}">
          <span>${{escapeHtml(item.label)}}</span>
          <span class="switcher-chip-count">${{escapeHtml(String(item.count))}}</span>
        </button>
      `).join("");
      const items = switcherViewItems();
      const viewLabel = viewOptions.find((item) => item.slug === state.switcher.activeView)?.label || "All";
      const groupLabel = groupOptions.find((item) => item.slug === state.switcher.activeGroup)?.label || "All";
      el.switcherNote.textContent = items.length
        ? `${{viewLabel}} · ${{groupLabel}} · ${{items.length}} agent${{items.length === 1 ? "" : "s"}}`
        : `${{viewLabel}} · ${{groupLabel}} · no agents match right now`;
      if (!items.length) {{
        el.switcherList.innerHTML = '<div class="switcher-empty">Nothing matches this view. Clear the search or switch groups.</div>';
        refreshConsoleNavLinkHrefs();
        return;
      }}
      el.switcherList.innerHTML = items.map((item) => `
        <article class="switcher-item${{item.current ? " is-current" : ""}}">
          <a class="switcher-link" href="${{escapeHtml(buildSwitcherHref(item.href, item.key))}}" data-switcher-link="${{escapeHtml(item.key)}}">
            <div class="switcher-item-title-row">
              <span class="switcher-item-title">${{renderNameCartouche(item.label, {{ kind: "bot", tone: "bot", group: item.group }})}}</span>
              <span class="switcher-item-group">${{escapeHtml(item.groupLabel)}}</span>
              ${{renderSwitcherHostCartouche(item.host)}}
              ${{item.current ? '<span class="switcher-item-current">Current</span>' : ""}}
            </div>
          </a>
          <button type="button" class="ghost switcher-pin${{state.switcher.pins.includes(item.key) ? " active" : ""}}" data-switcher-pin="${{escapeHtml(item.key)}}" title="${{state.switcher.pins.includes(item.key) ? "Unpin" : "Pin"}}">★</button>
        </article>
      `).join("");
      refreshConsoleNavLinkHrefs();
    }}

    function refreshConsoleNavLinkHrefs() {{
      for (const link of consoleNavLinks) {{
        const base = link.dataset.switcherBase || normalizeSwitcherHref(link.href);
        const label = link.dataset.label || link.textContent || "";
        const key = link.dataset.switcherKey || switcherItemKey(link.dataset.group || "", label);
        link.href = buildSwitcherHref(base, key);
      }}
    }}

    function normalizePreferenceNumber(value, fallback, choices) {{
      const parsed = Number(value);
      if (choices.includes(parsed)) {{
        return parsed;
      }}
      return fallback;
    }}

    function normalizePreferences(value) {{
      const base = {{
        density: "compact",
        mobileTurns: 1,
        desktopTurns: 1,
        viewMode: "console",
        styleVariant: "auto",
        finish: {json.dumps(DEFAULT_UI_FINISH if DEFAULT_UI_FINISH in FINISH_OPTIONS else "flat")},
        completionBell: "auto",
        responseSpeed: DEFAULT_RESPONSE_SPEED,
        responseDetail: DEFAULT_RESPONSE_DETAIL,
      }};
      const payload = value && typeof value === "object" ? value : {{}};
      const density = payload.density === "comfortable" ? "comfortable" : "compact";
      const viewMode = payload.viewMode === "stage" ? "stage" : "console";
      const styleVariant = normalizeStyleVariant(payload.styleVariant);
      const finish = {json.dumps(list(FINISH_OPTIONS))}.includes(String(payload.finish || "").toLowerCase())
        ? String(payload.finish).toLowerCase()
        : base.finish;
      return {{
        density,
        mobileTurns: normalizePreferenceNumber(payload.mobileTurns, base.mobileTurns, [1, 2, 3]),
        desktopTurns: normalizePreferenceNumber(payload.desktopTurns, base.desktopTurns, [1, 2, 4, 6]),
        viewMode,
        styleVariant,
        finish,
        completionBell: normalizeCompletionBell(payload.completionBell),
        responseSpeed: normalizeResponseSpeed(payload.responseSpeed),
        responseDetail: normalizeResponseDetail(payload.responseDetail),
      }};
    }}

    function loadPreferences() {{
      const raw = safeStorageGet(SETTINGS_STORAGE_KEY);
      if (!raw) {{
        return normalizePreferences(DEFAULT_PREFERENCES);
      }}
      try {{
        return normalizePreferences(JSON.parse(raw));
      }} catch (_) {{
        return normalizePreferences(DEFAULT_PREFERENCES);
      }}
    }}

    function savePreferences() {{
      safeStorageSet(SETTINGS_STORAGE_KEY, JSON.stringify(state.preferences));
    }}

    function responseControlsAtDefault() {{
      return normalizeResponseSpeed(state.preferences.responseSpeed) === DEFAULT_RESPONSE_SPEED
        && normalizeResponseDetail(state.preferences.responseDetail) === DEFAULT_RESPONSE_DETAIL;
    }}

    function composerToolbarShouldExpand(snapshot = state.snapshot) {{
      return Boolean(state.toolbarExpanded);
    }}

    function currentKeyboardInsetBottom() {{
      const viewport = window.visualViewport;
      if (!viewport) {{
        return 0;
      }}
      return Math.max(
        0,
        Math.round(window.innerHeight - viewport.height - viewport.offsetTop)
      );
    }}

    function keyboardLikelyOpen() {{
      if (window.innerWidth > 820) {{
        return false;
      }}
      return currentKeyboardInsetBottom() > 140;
    }}

    function stickConversationToBottom() {{
      const scroller = chatScrollRoot();
      if (!scroller) {{
        return;
      }}
      scroller.scrollTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      state.userPinnedHistory = false;
      updateScrollChrome();
      el.jumpLatestButton.classList.remove("visible");
    }}

    function syncMobileComposeMode() {{
      const active = document.activeElement;
      const composing = window.innerWidth <= 640
        && state.keyboardOpen
        && (
          state.promptFocused
          || active === el.promptInput
          || active === el.tmuxInput
        );
      document.body.classList.toggle("mobile-compose-mode", composing);
      if (!composing) {{
        return;
      }}
      if (state.toolbarExpanded) {{
        state.toolbarExpanded = false;
        updateComposerToolbar(state.snapshot);
      }}
      if (state.uploadMenuOpen) {{
        setUploadMenuOpen(false);
      }}
      if (document.body.classList.contains("topbar-menu-open")) {{
        setTopbarMenuOpen(false);
      }}
      if (document.body.classList.contains("switcher-open")) {{
        setSwitcherOpen(false);
      }}
      closeMessageActionMenus();
    }}

    function applyViewportMetrics(options = {{}}) {{
      const preserveLiveEdge = Boolean(options.preserveLiveEdge);
      const scroller = chatScrollRoot();
      const wasNearBottom = preserveLiveEdge
        && !state.historyExpanded
        && Boolean(scroller)
        && isNearConversationBottom();
      const viewport = window.visualViewport;
      const nextHeight = Math.max(
        320,
        Math.round(viewport ? viewport.height : window.innerHeight)
      );
      const nextTop = Math.max(0, Math.round(viewport ? viewport.offsetTop : 0));
      const nextKeyboardInset = currentKeyboardInsetBottom();
      const nextKeyboardOpen = keyboardLikelyOpen();
      state.keyboardOpen = nextKeyboardOpen;
      state.lastViewportHeight = nextHeight;
      state.lastViewportTop = nextTop;
      (el.appShell || document.documentElement).style.setProperty(
        "--viewport-height",
        `${{nextHeight}}px`
      );
      (el.appShell || document.documentElement).style.setProperty(
        "--keyboard-inset",
        `${{nextKeyboardInset}}px`
      );
      document.body.classList.toggle("mobile-keyboard-open", nextKeyboardOpen);
      syncMobileComposeMode();
      if (nextKeyboardOpen && wasNearBottom && scroller) {{
        window.requestAnimationFrame(() => {{
          if (!state.historyExpanded && !state.userPinnedHistory) {{
            stickConversationToBottom();
          }}
        }});
      }}
    }}

    function currentComposerReserve() {{
      if (!el.composerWrap) {{
        return 0;
      }}
      const style = window.getComputedStyle(el.composerWrap);
      if (style.position !== "sticky") {{
        return 0;
      }}
      const isMobile = window.innerWidth <= 640;
      const keyboardInset = currentKeyboardInsetBottom();
      const height = Math.ceil(el.composerWrap.getBoundingClientRect().height || 0);
      const baselineHeight = isMobile ? 74 : 82;
      const liveExpansion = Math.max(0, height - baselineHeight);
      const cushion = keyboardInset > 0 ? (isMobile ? 4 : 8) : (isMobile ? 8 : 12);
      return Math.max(0, liveExpansion + cushion + keyboardInset);
    }}

    function applyComposerReserve(options = {{}}) {{
      const preserveLiveEdge = Boolean(options.preserveLiveEdge);
      const scroller = chatScrollRoot();
      const wasNearBottom = preserveLiveEdge
        && !state.historyExpanded
        && Boolean(scroller)
        && isNearConversationBottom();
      const previousReserve = Number(state.lastComposerReserve || 0);
      const nextReserve = currentComposerReserve();
      state.lastComposerReserve = nextReserve;
      (el.appShell || document.documentElement).style.setProperty(
        "--composer-reserve",
        `${{nextReserve}}px`
      );
      const delta = nextReserve - previousReserve;
      if (wasNearBottom && scroller && delta !== 0) {{
        scroller.scrollTop = Math.max(0, scroller.scrollTop + delta);
        state.userPinnedHistory = false;
        updateScrollChrome();
        el.jumpLatestButton.classList.remove("visible");
      }}
    }}

    function scheduleComposerReserve(options = {{}}) {{
      if (options.preserveLiveEdge) {{
        state.pendingComposerReserveLiveEdge = true;
      }}
      if (state.composerReserveFrame) {{
        return;
      }}
      state.composerReserveFrame = window.requestAnimationFrame(() => {{
        state.composerReserveFrame = 0;
        const preserveLiveEdge = state.pendingComposerReserveLiveEdge;
        state.pendingComposerReserveLiveEdge = false;
        applyViewportMetrics({{ preserveLiveEdge }});
        applyComposerReserve({{ preserveLiveEdge }});
      }});
    }}

    function buildNormanPrimeHeartbeatUrl(reason = "interval") {{
      const base = String(NORMAN_PRIME_HEARTBEAT_URL || "").trim();
      if (!base) {{
        return "";
      }}
      try {{
        const url = new URL(base, window.location.href);
        url.searchParams.set("agent", AGENT_LABEL);
        url.searchParams.set("ui_version", UI_VERSION);
        url.searchParams.set("profile", ACTIVE_PROFILE);
        url.searchParams.set("route", ACTIVE_ROUTE || "auto");
        url.searchParams.set("host", window.location.host || "");
        url.searchParams.set("href", window.location.origin + window.location.pathname);
        url.searchParams.set("reason", reason);
        url.searchParams.set("_", String(Date.now()));
        return url.toString();
      }} catch (_) {{
        return "";
      }}
    }}

    function pingNormanPrime(reason = "interval") {{
      const url = buildNormanPrimeHeartbeatUrl(reason);
      if (!url) {{
        return;
      }}
      state.lastPrimePingAt = Date.now();
      fetch(url, {{
        method: "GET",
        mode: "no-cors",
        cache: "no-store",
        keepalive: true,
      }}).catch(() => {{}});
    }}

    function schedulePrimePing(delayMs = 90000) {{
      if (state.primePingTimer) {{
        window.clearTimeout(state.primePingTimer);
      }}
      state.primePingTimer = window.setTimeout(() => {{
        state.primePingTimer = 0;
        if (document.visibilityState === "visible") {{
          pingNormanPrime("interval");
        }}
        schedulePrimePing(90000);
      }}, Math.max(15000, Number(delayMs) || 0));
    }}

    function updateComposerToolbar(snapshot = state.snapshot) {{
      const expanded = composerToolbarShouldExpand(snapshot);
      const promptHasText = Boolean(el.promptInput.value.trim());
      const draftAttachmentCount = Array.isArray(snapshot?.draft_attachments)
        ? snapshot.draft_attachments.length
        : 0;
      el.askForm.classList.toggle("compact", !expanded);
      el.askForm.classList.toggle("idle", !expanded && !state.promptFocused && !promptHasText && !draftAttachmentCount);
      el.askForm.classList.toggle("is-focused", state.promptFocused);
      el.askForm.classList.toggle("has-text", promptHasText);
      el.askForm.classList.toggle("has-drafts", Boolean(draftAttachmentCount));
      el.composerToolsToggle.classList.toggle("active", expanded || !responseControlsAtDefault());
      el.composerToolsToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
      const nextProfile = responseProfileText(state.preferences.responseSpeed, state.preferences.responseDetail);
      el.composerToolsToggle.title = expanded
        ? `Hide prompt tools · ${{nextProfile}}`
        : `Show prompt tools · ${{nextProfile}}`;
      el.composerToolbarPanels.hidden = !expanded;
      renderSuggestions(snapshot);
      scheduleComposerReserve();
    }}

    function updateAuthActions(snapshot = state.snapshot) {{
      const auth = currentAuthState(snapshot);
      const required = Boolean(auth.required);
      const mode = String(auth.mode || "");
      const verificationUrl = String(auth.verification_url || "").trim();
      const bridgeAllowed = Boolean(BROWSER_AUTH_BRIDGE_ALLOWED);
      if (el.authBrowserButton) {{
        el.authBrowserButton.hidden = !required;
        el.authBrowserButton.disabled = !required || !bridgeAllowed;
        el.authBrowserButton.textContent = mode === "browser_signin" ? "Continue sign-in" : "Browser sign-in";
        el.authBrowserButton.title = !required
          ? "Already signed in."
          : !bridgeAllowed
            ? "Browser sign-in is only available from Hal or the Plasma phone."
            : verificationUrl
              ? "Open browser sign-in"
              : "Prepare browser sign-in";
      }}
      if (el.authDeviceButton) {{
        el.authDeviceButton.hidden = !required;
        el.authDeviceButton.disabled = !required;
        el.authDeviceButton.textContent = mode === "device_code"
          ? "Refresh device code"
          : mode === "needs_reauth"
            ? "Repair sign-in"
            : "Device code";
        el.authDeviceButton.title = required ? "Prepare device-code sign-in." : "Already signed in.";
      }}
      if (el.authHelperLink) {{
        el.authHelperLink.hidden = !required || mode !== "browser_signin";
        el.authHelperLink.href = bridgeAllowed ? browserAuthHelperHref() : "#";
        el.authHelperLink.setAttribute(
          "aria-disabled",
          required && bridgeAllowed ? "false" : "true"
        );
        el.authHelperLink.title = !required
          ? "Already signed in."
          : bridgeAllowed
          ? "Open the local callback helper"
          : "Auth Helper is only available from Hal or the Plasma phone.";
      }}
    }}

    function setUploadMenuOpen(shouldOpen) {{
      state.uploadMenuOpen = Boolean(shouldOpen);
      if (el.composerUploadMenu) {{
        el.composerUploadMenu.hidden = !state.uploadMenuOpen;
      }}
      if (el.composerUploadButton) {{
        el.composerUploadButton.classList.toggle("active", state.uploadMenuOpen);
        el.composerUploadButton.setAttribute("aria-expanded", state.uploadMenuOpen ? "true" : "false");
      }}
    }}

    function setAskButtonState(label, icon) {{
      el.askButton.dataset.icon = icon;
      el.askButton.title = label;
      el.askButton.setAttribute("aria-label", label);
      if (el.askButtonLabel) {{
        el.askButtonLabel.textContent = label;
      }}
    }}

    function applyPreferences() {{
      document.body.dataset.density = state.preferences.density;
      document.body.dataset.viewMode = state.preferences.viewMode;
      applyStyleVariantPreference();
      document.body.dataset.finish = state.preferences.finish;
      document.body.dataset.completionBell = resolvedCompletionBellKey(state.preferences.completionBell);
      document.body.dataset.layoutMode = detectLayoutMode();
      for (const button of settingButtons) {{
        const key = button.dataset.setting;
        const value = button.dataset.value;
        const active = String(state.preferences[key]) === String(value);
        button.classList.toggle("active", active);
      }}
      el.responseSpeedRange.value = String(responseSpeedIndex(state.preferences.responseSpeed));
      el.responseSpeedLabel.textContent = responseSpeedControlLabel(state.preferences.responseSpeed);
      el.responseDetailRange.value = String(state.preferences.responseDetail);
      el.responseDetailLabel.textContent = responseDetailLabel(state.preferences.responseDetail);
      el.promptSpeedInput.value = state.preferences.responseSpeed;
      el.promptDetailInput.value = String(state.preferences.responseDetail);
      const nextProfile = responseProfileText(
        state.preferences.responseSpeed,
        state.preferences.responseDetail
      );
      if (state.snapshot.pending) {{
        const currentProfile = responseProfileText(
          activeRunningSpeed(state.snapshot),
          activeRunningDetail(state.snapshot)
        );
        el.responseSummary.textContent = currentProfile === nextProfile
          ? currentProfile
          : `${{currentProfile}} → ${{nextProfile}}`;
      }} else {{
        el.responseSummary.textContent = nextProfile;
      }}
      updateComposerToolbar(state.snapshot);
      scheduleComposerReserve();
    }}

    function isDesktopLayout() {{
      return desktopLayout.matches;
    }}

    function detectLayoutMode() {{
      const width = window.innerWidth || document.documentElement.clientWidth || 0;
      const height = window.innerHeight || document.documentElement.clientHeight || 0;
      if (width <= 720) {{
        return "mobile";
      }}
      if (width <= 1280 || height <= 780 || (width <= 1500 && height <= 860)) {{
        return "tile";
      }}
      return "full";
    }}

    function recentHistoryWindow() {{
      let baseWindow = window.innerWidth <= 640
        ? state.preferences.mobileTurns
        : state.preferences.desktopTurns;
      const layoutMode = document.body.dataset.layoutMode || detectLayoutMode();
      if (layoutMode === "tile") {{
        baseWindow = Math.min(baseWindow, 1);
      }}
      if (
        isDesktopLayout()
        && window.innerWidth >= 1400
        && window.innerHeight >= 860
        && Number(baseWindow || 0) <= 2
      ) {{
        baseWindow = 1;
      }}
      if (state.preferences.viewMode === "stage" && isDesktopLayout()) {{
        return Math.max(baseWindow, 4);
      }}
      return Math.max(1, baseWindow);
    }}

    function setSystemOpen(open) {{
      if (open) {{
        setTopbarMenuOpen(false);
        setSwitcherOpen(false);
        setSettingsOpen(false);
        setNoticesOpen(false);
        setStatusActionOpen(false);
      }}
      const shouldOpen = Boolean(open);
      document.body.classList.toggle("system-open", shouldOpen);
      el.systemPanel.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
    }}

    function setSettingsOpen(open) {{
      if (open) {{
        setTopbarMenuOpen(false);
        setSwitcherOpen(false);
        setSystemOpen(false);
        setNoticesOpen(false);
        setStatusActionOpen(false);
      }}
      const shouldOpen = Boolean(open);
      document.body.classList.toggle("settings-open", shouldOpen);
      el.settingsPanel.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
    }}

    function markNoticesRead() {{
      for (const item of state.notices) {{
        item.unread = false;
      }}
      renderNotifications();
    }}

    function setNoticesOpen(open) {{
      if (open) {{
        setTopbarMenuOpen(false);
        setSwitcherOpen(false);
        setSettingsOpen(false);
        setSystemOpen(false);
        setStatusActionOpen(false);
      }}
      const shouldOpen = Boolean(open);
      document.body.classList.toggle("notices-open", shouldOpen);
      el.noticesPanel.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
      if (shouldOpen) {{
        markNoticesRead();
      }}
    }}

    function syncSystemPanelMode() {{
      el.systemPanel.setAttribute("aria-hidden", document.body.classList.contains("system-open") ? "false" : "true");
    }}

    function syncTopbarMenuPosition() {{
      if (!el.topbarMenuButton) {{
        return;
      }}
      const rect = el.topbarMenuButton.getBoundingClientRect();
      const right = Math.max(8, window.innerWidth - rect.right);
      const top = Math.max(8, rect.bottom + 8);
      document.documentElement.style.setProperty("--topbar-menu-right", `${{Math.round(right)}}px`);
      document.documentElement.style.setProperty("--topbar-menu-top", `${{Math.round(top)}}px`);
    }}

    function setTopbarMenuOpen(open) {{
      const shouldOpen = Boolean(open);
      if (shouldOpen) {{
        syncTopbarMenuPosition();
        setStatusActionOpen(false);
      }}
      document.body.classList.toggle("topbar-menu-open", shouldOpen);
      el.topbarMenu.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
      el.topbarMenuButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
    }}

    function setStatusActionOpen(open) {{
      const shouldOpen = Boolean(open);
      state.statusPanelOpen = shouldOpen;
      if (shouldOpen) {{
        setTopbarMenuOpen(false);
        setSwitcherOpen(false);
        setSettingsOpen(false);
        setSystemOpen(false);
        setNoticesOpen(false);
        void refreshStatusActions({{ keepOpen: true }});
      }}
      renderStatusActionPanel(state.snapshot);
    }}

    function setConsoleFocusExpanded(open) {{
      if (!el.consoleFocusShell || !el.consoleFocusToggle || !el.consoleFocusPanel) {{
        return;
      }}
      const shouldOpen = Boolean(open);
      el.consoleFocusShell.classList.toggle("expanded", shouldOpen);
      el.consoleFocusToggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
      el.consoleFocusPanel.hidden = !shouldOpen;
      if (el.consoleFocusCaret) {{
        el.consoleFocusCaret.textContent = shouldOpen ? "−" : "+";
      }}
    }}

    function setSwitcherOpen(open) {{
      const shouldOpen = Boolean(open);
      if (shouldOpen) {{
        setTopbarMenuOpen(false);
        setSettingsOpen(false);
        setNoticesOpen(false);
        setSystemOpen(false);
        setStatusActionOpen(false);
      }}
      document.body.classList.toggle("switcher-open", shouldOpen);
      el.switcherPanel.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
      if (shouldOpen && isDesktopLayout()) {{
        window.setTimeout(() => {{
          el.switcherSearchInput.focus();
          el.switcherSearchInput.select();
        }}, 20);
      }}
    }}

    function setTransportState(label, connected) {{
      state.transportLabel = String(label || "").trim() || "Connecting…";
      state.transportConnected = Boolean(connected);
      el.transportStateMenu.textContent = label;
      el.transportStateMenu.dataset.connected = connected ? "true" : "false";
      if (state.snapshot) {{
        renderStatusCapsules(state.snapshot);
        renderSystemRuntimeMetrics(state.snapshot);
      }}
    }}

    function triggerAuthRefresh(reason = "Authentication required.") {{
      if (state.authRedirectTriggered) {{
        return;
      }}
      state.authRedirectTriggered = true;
      if (state.stream) {{
        state.stream.close();
        state.stream = null;
      }}
      clearTimeout(state.pollTimer);
      state.streamConnected = false;
      el.runState.className = "pill error";
      el.runState.textContent = "Auth";
      el.statusMessage.textContent = reason;
      updateTabChrome({{
        ...state.snapshot,
        state: "error",
        last_error: reason,
      }});
      setTransportState("Auth required", false);
      window.setTimeout(() => {{
        window.location.reload();
      }}, 120);
    }}

    function escapeHtml(value) {{
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }}

    function consoleLinkAttrsForHref(href) {{
      try {{
        const url = new URL(String(href || ""), window.location.href);
        const scheme = url.protocol.replace(/:$/, "").toLowerCase();
        if (!scheme || scheme === "http" || scheme === "https") {{
          return ' target="_blank" rel="noreferrer"';
        }}
      }} catch (_) {{
        return "";
      }}
      return "";
    }}

    const SENSITIVE_QUERY_PARAM_NAMES = new Set([
      "api_key",
      "apikey",
      "access_token",
      "refresh_token",
      "client_secret",
      "signing_secret",
      "webhook_secret",
      "app_password",
      "password",
      "passwd",
      "passcode",
      "secret",
      "token",
      "pwd",
    ]);
    const SENSITIVE_LABEL_PATTERN = "(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|signing[_ -]?secret|webhook[_ -]?secret|app[_ -]?password|mcp[_ -]?api[_ -]?key|password|passwd|passphrase|passcode|secret|token|pwd)";
    const SENSITIVE_ASSIGNMENT_RE = new RegExp(
      "((?<![?&\\\\w])(?:\\\"|')?" + SENSITIVE_LABEL_PATTERN + "(?:\\\"|')?\\\\s*[:=]\\\\s*)(\\\"([^\\\"\\\\n]|\\\\.)*\\\"|'([^'\\\\n]|\\\\.)*'|[^\\\\s,;]+)",
      "gi"
    );
    const SENSITIVE_QUERY_RE = /((?:[?&])(?:api(?:[_-]?key)?|access[_-]?token|refresh[_-]?token|client[_-]?secret|signing[_-]?secret|webhook[_-]?secret|app[_-]?password|password|passwd|passcode|secret|token|pwd)=)([^&#\\s]+)/gi;
    const SENSITIVE_BEARER_RE = /(\\bBearer\\s+)([A-Za-z0-9._~+/=-]+)/gi;
    const RAW_HTML_ANCHOR_RE = /<a\\b([^>]*)>([\\s\\S]*?)<\\/a>/gi;
    const RAW_HTML_HREF_RE = /\\bhref\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))/i;
    let renderSegmentSerial = 0;

    function nextRenderToken(prefix) {{
      const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
      let current = renderSegmentSerial;
      renderSegmentSerial += 1;
      let suffix = "";
      while (true) {{
        suffix = `${{alphabet[current % 26]}}${{suffix}}`;
        current = Math.floor(current / 26);
        if (current === 0) {{
          break;
        }}
        current -= 1;
      }}
      return `__${{prefix}}_${{suffix}}__`;
    }}

    function buildSecretSpoiler(value) {{
      return `<button type="button" class="secret-spoiler" aria-pressed="false" aria-label="Reveal hidden value" title="Reveal hidden value"><span class="secret-spoiler-mask" aria-hidden="true">&bull;&bull;&bull;&bull;&bull;&bull;</span><span class="secret-spoiler-value">${{escapeHtml(value)}}</span></button>`;
    }}

    function stashSensitiveSegments(text, options = {{}}) {{
      let nextText = String(text || "");
      const stash = {{}};
      const apply = (regex) => {{
        nextText = nextText.replace(regex, (_, prefix, value) => {{
          const token = nextRenderToken("SECRET_SEGMENT");
          stash[token] = buildSecretSpoiler(value);
          return `${{prefix}}${{token}}`;
        }});
      }};
      apply(SENSITIVE_ASSIGNMENT_RE);
      if (options.maskQueryParams) {{
        apply(SENSITIVE_QUERY_RE);
      }}
      apply(SENSITIVE_BEARER_RE);
      return {{ text: nextText, stash }};
    }}

    function renderPlainTextWithSecrets(value) {{
      const sensitive = stashSensitiveSegments(String(value || "").replace(/\\r\\n/g, "\\n"), {{ maskQueryParams: true }});
      return restoreSegments(
        escapeHtml(sensitive.text).replace(/\\n/g, "<br>"),
        [sensitive.stash]
      );
    }}

    function renderPreformattedText(value) {{
      const sensitive = stashSensitiveSegments(String(value || "").replace(/\\r\\n/g, "\\n"), {{ maskQueryParams: true }});
      return restoreSegments(escapeHtml(sensitive.text), [sensitive.stash]);
    }}

    function maskSensitiveUrlText(url) {{
      return String(url || "").replace(
        /([?&]([^=&]+)=)([^&#\s]+)/g,
        (match, prefix, key, value) => (
          SENSITIVE_QUERY_PARAM_NAMES.has(String(key || "").toLowerCase()) ? `${{prefix}}••••••` : `${{prefix}}${{value}}`
        )
      );
    }}

    function decodeHtmlEntities(value) {{
      const textarea = document.createElement("textarea");
      textarea.innerHTML = String(value || "");
      return textarea.value;
    }}

    function entityMarkForLabel(value) {{
      const text = String(value || "").trim();
      if (!text) {{
        return "•";
      }}
      const tokens = text.match(/[A-Za-z0-9]+/g) || [];
      if (!tokens.length) {{
        return "•";
      }}
      if (tokens.length === 1) {{
        return tokens[0].slice(0, 2).toUpperCase();
      }}
      return `${{tokens[0][0]}}${{tokens[1][0]}}`.toUpperCase();
    }}

    function normalizeInlineEntityKey(value) {{
      return String(value || "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "");
    }}

    function escapeRegExp(value) {{
      return String(value || "").replace(/[.*+?^${{}}()|[\\\\]\\\\\\\\]/g, "\\\\$&");
    }}

    function inlineEntityPattern(alias, strictCase = false) {{
      const escaped = escapeRegExp(String(alias || "").trim()).replace(/\\ /g, "\\s+");
      return new RegExp(
        `(^|[\\s([{{"'“‘])(${{escaped}})(?=$|[\\s).,:;!?\\]}}"'”’])`,
        strictCase ? "g" : "gi"
      );
    }}

    function buildInlineEntityEntries(defs) {{
      const entries = [];
      for (const raw of Array.isArray(defs) ? defs : []) {{
        const aliases = Array.from(
          new Set(
            (Array.isArray(raw?.aliases) ? raw.aliases : [raw?.label || raw?.key || ""])
              .map((item) => String(item || "").trim())
              .filter(Boolean)
          )
        );
        if (!aliases.length) {{
          continue;
        }}
        const entity = {{
          key: normalizeInlineEntityKey(raw?.key || raw?.label || aliases[0]),
          label: String(raw?.label || aliases[0] || ""),
          mark: String(raw?.mark || entityMarkForLabel(raw?.label || aliases[0] || "•")).slice(0, 2).toUpperCase(),
          kind: String(raw?.kind || "entity"),
          tone: String(raw?.tone || raw?.kind || "entity"),
          group: String(raw?.group || ""),
          decorator: String(raw?.decorator || ""),
          strictCase: Boolean(raw?.strict_case),
        }};
        for (const alias of aliases) {{
          const canonicalKey = normalizeInlineEntityKey(entity.label);
          const aliasKey = normalizeInlineEntityKey(alias);
          entries.push({{
            alias,
            aliasFor: canonicalKey && aliasKey && canonicalKey !== aliasKey ? entity.label : "",
            entity,
            pattern: inlineEntityPattern(alias, entity.strictCase),
          }});
        }}
      }}
      entries.sort((left, right) => String(right.alias || "").length - String(left.alias || "").length);
      return entries;
    }}

    function entityDecoratorForKind(kind) {{
      const clean = String(kind || "").trim().toLowerCase();
      if (clean === "host") {{
        return "NET";
      }}
      if (clean === "tui") {{
        return "TUI";
      }}
      if (clean === "bot") {{
        return "◈";
      }}
      if (clean === "person") {{
        return "◦";
      }}
      if (clean === "location") {{
        return "⌂";
      }}
      if (clean === "mention") {{
        return "@";
      }}
      return "·";
    }}

    function renderEntityCartouche(entity, visibleLabel, options = {{}}) {{
      const kind = String(entity?.kind || "entity");
      const tone = String(entity?.tone || kind);
      const group = String(entity?.group || "");
      const key = String(entity?.key || normalizeInlineEntityKey(visibleLabel));
      const mark = String(entity?.mark || entityMarkForLabel(visibleLabel, "•")).slice(0, 2).toUpperCase() || "•";
      const decorator = String(entity?.decorator || entityDecoratorForKind(kind));
      const aliasFor = String(options.aliasFor || entity?.aliasFor || "").trim();
      const mentionAttr = options.mention ? ' data-mention="true"' : "";
      const groupAttr = group ? ` data-group="${{escapeHtml(group)}}"` : "";
      const aliasAttr = aliasFor
        ? ` data-alias="true" data-alias-for="${{escapeHtml(aliasFor)}}" title="${{escapeHtml("Alias for " + aliasFor)}}"`
        : "";
      const compactAttr = options.compact ? ' data-compact="true"' : "";
      const href = String(options.href || "").trim();
      const tag = href ? "a" : "span";
      const hrefAttr = href ? ` href="${{escapeHtml(href)}}"${{consoleLinkAttrsForHref(href)}}` : "";
      return `<${{tag}} class="entity-cartouche" data-kind="${{escapeHtml(kind)}}" data-tone="${{escapeHtml(tone)}}" data-entity-key="${{escapeHtml(key)}}" data-mark="${{escapeHtml(mark)}}" data-decorator="${{escapeHtml(decorator)}}"${{hrefAttr}}${{groupAttr}}${{mentionAttr}}${{aliasAttr}}${{compactAttr}}><span class="entity-cartouche__label">${{escapeHtml(visibleLabel)}}</span></${{tag}}>`;
    }}

    function inlineEntityForLabel(label, fallback = {{}}) {{
      const clean = String(label || "").trim();
      const key = normalizeInlineEntityKey(clean);
      const known = key ? INLINE_ENTITY_ALIAS_MAP.get(key) : null;
      if (known) {{
        return {{ ...known.entity, aliasFor: known.aliasFor || "" }};
      }}
      const kind = String(fallback.kind || "name");
      return {{
        key: key || normalizeInlineEntityKey(fallback.key || kind),
        label: clean || String(fallback.label || ""),
        mark: String(fallback.mark || entityMarkForLabel(clean || fallback.label || "•", "•")),
        kind,
        tone: String(fallback.tone || kind),
        group: String(fallback.group || ""),
        aliasFor: "",
      }};
    }}

    function renderNameCartouche(label, options = {{}}) {{
      const clean = String(label || "").trim();
      if (!clean) {{
        return "";
      }}
      const base = inlineEntityForLabel(clean, {{
        key: options.key,
        label: clean,
        mark: options.mark,
        kind: options.kind || "name",
        tone: options.tone || options.kind || "name",
        group: options.group || "",
      }});
      const kind = String(options.kind || base.kind || "name");
      const tone = String(options.tone || base.tone || kind);
      const group = Object.prototype.hasOwnProperty.call(options, "group")
        ? String(options.group || "")
        : String(base.group || "");
      const mark = String(options.mark || base.mark || entityMarkForLabel(clean, "•"));
      return renderEntityCartouche(
        {{ ...base, kind, tone, group, mark }},
        clean,
        {{
          compact: options.compact !== false,
          href: options.href || "",
          mention: Boolean(options.mention),
          aliasFor: String(options.aliasFor || base.aliasFor || ""),
        }}
      );
    }}

    function renderLinkedNameCartouche(label, options = {{}}) {{
      const href = String(options.href || tuiHrefForLabel(label) || "").trim();
      return renderNameCartouche(label, {{ ...options, href }});
    }}

    function buildDynamicHostEntity(visibleLabel) {{
      const label = String(visibleLabel || "").trim();
      const key = normalizeInlineEntityKey(label);
      const known = INLINE_ENTITY_MAP.get(key);
      if (known) {{
        return known;
      }}
      return {{
        key,
        label,
        mark: entityMarkForLabel(label),
        kind: "host",
        tone: "host",
        group: "shared",
      }};
    }}

    function highlightDynamicHostEntities(text, stashMarkup) {{
      return String(text || "").replace(
        /(^|[\s([{{"'“‘])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:home\.arpa|home\.lollie\.org|kris\.openbrand\.com|tail[0-9]+\.ts\.net)|(?:\d{1,3}\.){3}\d{1,3})(?=$|[\s).,:;!?\]}}\"'”’])/gi,
        (match, prefix, host) => `${{prefix}}${{stashMarkup(renderEntityCartouche(buildDynamicHostEntity(host), host))}}`
      );
    }}

    function stripInlineHtmlText(value) {{
      return decodeHtmlEntities(String(value || "").replace(/<[^>]+>/g, ""));
    }}

    function displayTextForLink(target, label) {{
      const plainLabel = stripInlineHtmlText(label).trim();
      if (!plainLabel) {{
        return /^https?:\\/\\//i.test(target) ? maskSensitiveUrlText(target) : target;
      }}
      if (/^https?:\\/\\//i.test(target) && /^https?:\\/\\//i.test(plainLabel)) {{
        if (normalizeUrlCandidate(plainLabel) === normalizeUrlCandidate(target)) {{
          return maskSensitiveUrlText(target);
        }}
      }}
      return plainLabel;
    }}

    function normalizeUrlCandidate(value) {{
      let clean = String(value || "").trim();
      while (/[.,!?;:]$/.test(clean)) {{
        clean = clean.slice(0, -1);
      }}
      while (clean.endsWith(")") && (clean.match(/\\(/g) || []).length < (clean.match(/\\)/g) || []).length) {{
        clean = clean.slice(0, -1);
      }}
      return clean;
    }}

    function normalizeFileTarget(value) {{
      let clean = String(value || "").trim();
      while (/[.,!?;:]$/.test(clean)) {{
        clean = clean.slice(0, -1);
      }}
      return clean;
    }}

    function splitFileTarget(value) {{
      const clean = normalizeFileTarget(value);
      const match = clean.match(/^(.*?)(#L\d+(?:C\d+)?)$/);
      if (match) {{
        return {{ path: match[1], fragment: match[2] }};
      }}
      return {{ path: clean, fragment: "" }};
    }}

    function unwrapMarkdownLinkTarget(value) {{
      const clean = String(value || "").trim();
      return clean.startsWith("<") && clean.endsWith(">")
        ? clean.slice(1, -1).trim()
        : clean;
    }}

    function isFileTarget(value) {{
      const clean = splitFileTarget(value).path;
      return clean.startsWith("/") || clean.startsWith("~/") || clean.startsWith("file://");
    }}

    function clientPath(path) {{
      const clean = String(path || "").trim() || "/";
      if (!REQUEST_BASE_PATH) {{
        return clean;
      }}
      return clean === "/" ? `${{REQUEST_BASE_PATH}}/` : `${{REQUEST_BASE_PATH}}${{clean}}`;
    }}

    function buildFileViewHref(value) {{
      const target = splitFileTarget(value);
      const query = new URLSearchParams({{
        profile: ACTIVE_PROFILE,
        path: target.path,
      }});
      if (LOCAL_TOKEN) {{
        query.set("token", LOCAL_TOKEN);
      }}
      if (ACTIVE_ROUTE && ACTIVE_ROUTE !== "auto") {{
        query.set("route", ACTIVE_ROUTE);
      }}
      const href = `${{clientPath("/api/file")}}?${{query.toString()}}`;
      return `${{href}}${{target.fragment}}`;
    }}

    function buildFileRawHref(value) {{
      const target = splitFileTarget(value);
      const query = new URLSearchParams({{
        profile: ACTIVE_PROFILE,
        raw: "1",
        path: target.path,
      }});
      if (LOCAL_TOKEN) {{
        query.set("token", LOCAL_TOKEN);
      }}
      if (ACTIVE_ROUTE && ACTIVE_ROUTE !== "auto") {{
        query.set("route", ACTIVE_ROUTE);
      }}
      const href = `${{clientPath("/api/file")}}?${{query.toString()}}`;
      return `${{href}}${{target.fragment}}`;
    }}

    function buildFileDownloadHref(value) {{
      const target = splitFileTarget(value);
      const query = new URLSearchParams({{
        profile: ACTIVE_PROFILE,
        download: "1",
        path: target.path,
      }});
      if (LOCAL_TOKEN) {{
        query.set("token", LOCAL_TOKEN);
      }}
      if (ACTIVE_ROUTE && ACTIVE_ROUTE !== "auto") {{
        query.set("route", ACTIVE_ROUTE);
      }}
      const href = `${{clientPath("/api/file")}}?${{query.toString()}}`;
      return `${{href}}${{target.fragment}}`;
    }}

    function compactInlineFilePath(value) {{
      const clean = splitFileTarget(value).path.replace(/^file:\\/\\//i, "");
      if (!clean) {{
        return "";
      }}
      const normalized = clean.replace(/^\\/home\\/[^/]+/, "~");
      const root = normalized.startsWith("~/")
        ? "~/"
        : normalized.startsWith("/")
          ? "/"
          : "";
      const parts = normalized.split("/").filter(Boolean);
      const directories = parts.slice(0, -1);
      if (!directories.length) {{
        return root || normalized;
      }}
      if (directories.length <= 2) {{
        return `${{root}}${{directories.join("/")}}`.replace(/\\/\\//g, "/");
      }}
      return `${{root}}…/${{directories.slice(-2).join("/")}}`;
    }}

    function extractUrls(value) {{
      const text = String(value || "");
      const urls = [];
      const seen = new Set();
      const push = (candidate) => {{
        const clean = normalizeUrlCandidate(candidate);
        if (!/^https?:\\/\\//i.test(clean) || seen.has(clean)) {{
          return;
        }}
        seen.add(clean);
        urls.push(clean);
      }};
      for (const match of text.matchAll(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+)\\)/g)) {{
        push(match[2]);
      }}
      for (const match of text.matchAll(/https?:\\/\\/[^\\s<>"']+/g)) {{
        push(match[0]);
      }}
      return urls;
    }}

    function formatUrlLabel(url) {{
      try {{
        const parsed = new URL(url);
        const host = parsed.hostname.replace(/^www\\./, "");
        const detail = maskSensitiveUrlText(`${{parsed.pathname || ""}}${{parsed.search || ""}}`);
        if (!detail || detail === "/") {{
          return host;
        }}
        const compact = detail.length > 28 ? `${{detail.slice(0, 27)}}…` : detail;
        return `${{host}}${{compact}}`;
      }} catch (_) {{
        const clean = maskSensitiveUrlText(String(url || ""));
        return clean.length > 40 ? `${{clean.slice(0, 39)}}…` : clean;
      }}
    }}

    function humanSize(value) {{
      const bytes = Number(value || 0);
      if (!Number.isFinite(bytes) || bytes <= 0) {{
        return "0 B";
      }}
      const units = ["B", "KB", "MB", "GB", "TB"];
      let amount = bytes;
      let unitIndex = 0;
      while (amount >= 1024 && unitIndex < units.length - 1) {{
        amount /= 1024;
        unitIndex += 1;
      }}
      if (unitIndex === 0) {{
        return `${{Math.round(amount)}} ${{units[unitIndex]}}`;
      }}
      return `${{amount.toFixed(1)}} ${{units[unitIndex]}}`;
    }}

    function formatCount(value) {{
      const number = Number(value || 0);
      if (!Number.isFinite(number)) {{
        return "0";
      }}
      return number.toLocaleString();
    }}

    function formatCompactMetric(value) {{
      const number = Number(value || 0);
      if (!Number.isFinite(number) || number <= 0) {{
        return "0";
      }}
      if (number >= 1000000) {{
        return `${{(number / 1000000).toFixed(1).replace(/\\.0$/, "")}}M`;
      }}
      if (number >= 10000) {{
        return `${{Math.round(number / 1000)}}k`;
      }}
      if (number >= 1000) {{
        return `${{(number / 1000).toFixed(1).replace(/\\.0$/, "")}}k`;
      }}
      return formatCount(Math.round(number));
    }}

    function attachmentKind(entry) {{
      const kind = String(entry && entry.kind || "").toLowerCase();
      if (["image", "text", "file"].includes(kind)) {{
        return kind;
      }}
      const contentType = String(entry && entry.content_type || "").toLowerCase();
      if (contentType.startsWith("image/")) {{
        return "image";
      }}
      if (contentType.startsWith("text/")) {{
        return "text";
      }}
      return "file";
    }}

    function attachmentDisplayName(entry) {{
      if (!entry) {{
        return "attachment";
      }}
      const source = String(entry.source || "").toLowerCase();
      const name = String(entry.name || "").trim();
      if (source === "paste-block") {{
        return "Paste";
      }}
      if (source === "web-capture" && !name) {{
        return "Snapshot";
      }}
      return name || attachmentTokenLabel(entry);
    }}

    function attachmentSummary(entry) {{
      if (!entry) {{
        return "";
      }}
      const parts = [];
      const source = String(entry.source || "").toLowerCase();
      const kind = attachmentKind(entry);
      const lineCount = Number(entry.line_count || 0);
      const charCount = Number(entry.char_count || 0);
      const contentType = String(entry.content_type || "").split(";", 1)[0];
      const captureHost = (() => {{
        try {{
          return entry.url ? new URL(String(entry.url)).host : "";
        }} catch (_) {{
          return "";
        }}
      }})();
      if (source === "web-capture") {{
        parts.push("snapshot");
        if (captureHost) {{
          parts.push(captureHost);
        }}
      }}
      if (source === "history-export") {{
        parts.push("session history");
      }}
      if (source === "log-tail") {{
        parts.push("log tail");
      }}
      if (source === "pane-capture") {{
        parts.push("live pane");
      }}
      if (kind === "text" && lineCount > 0) {{
        parts.push(lineCount === 1 ? "1 line" : `${{formatCount(lineCount)}} lines`);
      }} else if (source === "paste-block" && charCount > 0) {{
        parts.push(`${{formatCount(charCount)}} chars`);
      }}
      if (entry.size) {{
        parts.push(humanSize(entry.size));
      }}
      if (contentType && !(source === "paste-block" && contentType === "text/plain")) {{
        parts.push(contentType);
      }} else if (!parts.length && kind !== "text") {{
        parts.push(kind);
      }}
      return parts.join(" · ");
    }}

    function attachmentCountPhrase(attachments) {{
      const counts = {{ image: 0, text: 0, file: 0 }};
      for (const entry of Array.isArray(attachments) ? attachments : []) {{
        const kind = attachmentKind(entry);
        counts[kind] = (counts[kind] || 0) + 1;
      }}
      const labels = {{
        image: ["image", "images"],
        text: ["text block", "text blocks"],
        file: ["file", "files"],
      }};
      const parts = ["image", "text", "file"]
        .filter((kind) => counts[kind] > 0)
        .map((kind) => {{
          const count = counts[kind];
          const [singular, plural] = labels[kind];
          return `${{formatCount(count)}} ${{count === 1 ? singular : plural}}`;
        }});
      if (!parts.length) {{
        return "";
      }}
      if (parts.length === 1) {{
        return parts[0];
      }}
      if (parts.length === 2) {{
        return `${{parts[0]}} and ${{parts[1]}}`;
      }}
      return `${{parts[0]}}, ${{parts[1]}}, and ${{parts[2]}}`;
    }}

    function attachmentTokenLabel(entry) {{
      return String(entry && entry.token || "attachment");
    }}

    function basenameForPath(value) {{
      const clean = splitFileTarget(value).path.replace(/^file:\\/\\//i, "");
      const parts = clean.split("/").filter(Boolean);
      return parts.length ? parts[parts.length - 1] : clean || "file";
    }}

    function previewableFileKind(value) {{
      const clean = splitFileTarget(value).path.toLowerCase();
      if (!isFileTarget(clean)) {{
        return "";
      }}
      if (/\.(svg|png|apng|jpe?g|gif|webp|avif|bmp)$/i.test(clean)) {{
        return "image";
      }}
      if (/\.(txt|md|markdown|rst|json|ya?ml|toml|ini|cfg|conf|env|py|js|jsx|ts|tsx|sh|bash|zsh|log|csv|tsv|sql|xml|html|css)$/i.test(clean)) {{
        return "text";
      }}
      return "";
    }}

    function extractPreviewableFileTargets(value, limit = 2) {{
      const rawText = String(value || "");
      const text = rawText.length > INLINE_FILE_TARGET_SCAN_CHARS
        ? `${{rawText.slice(0, Math.floor(INLINE_FILE_TARGET_SCAN_CHARS / 2))}}\\n${{rawText.slice(-Math.ceil(INLINE_FILE_TARGET_SCAN_CHARS / 2))}}`
        : rawText;
      const results = [];
      const seen = new Set();
      const maxTargets = Math.max(0, Number(limit || 0));
      if (!maxTargets) {{
        return [];
      }}
      const push = (candidate, label = "") => {{
        if (results.length >= maxTargets) {{
          return true;
        }}
        const clean = normalizeFileTarget(unwrapMarkdownLinkTarget(candidate));
        if (!isFileTarget(clean)) {{
          return false;
        }}
        const path = splitFileTarget(clean).path;
        const kind = previewableFileKind(path) || "file";
        if (seen.has(path)) {{
          return false;
        }}
        seen.add(path);
        results.push({{
          path,
          kind,
          label: stripInlineHtmlText(label).trim() || basenameForPath(path),
        }});
        return results.length >= maxTargets;
      }};
      for (const match of text.matchAll(/\[([^\]]+)\]\s*\(\s*(<[^>\\n]+>|[^\s)]+)\s*\)/g)) {{
        if (push(match[2], match[1])) {{
          return results;
        }}
      }}
      for (const match of text.matchAll(/`([^`]+)`/g)) {{
        if (push(match[1], match[1])) {{
          return results;
        }}
      }}
      for (const match of text.matchAll(/(^|[\s(])((?:\/|~\/)[^\s<)"']+)/g)) {{
        if (push(match[2], match[2])) {{
          return results;
        }}
      }}
      return results;
    }}

    function rememberInlineFilePreview(cacheKey, payload) {{
      if (!cacheKey) {{
        return payload;
      }}
      delete state.inlinePreviewCache[cacheKey];
      state.inlinePreviewCache[cacheKey] = payload;
      const keys = Object.keys(state.inlinePreviewCache);
      while (keys.length > INLINE_PREVIEW_CACHE_LIMIT) {{
        const oldest = keys.shift();
        if (oldest) {{
          delete state.inlinePreviewCache[oldest];
        }}
      }}
      return payload;
    }}

    async function loadInlineFilePreview(entry) {{
      const cacheKey = String(entry?.path || "").trim();
      if (!cacheKey) {{
        return {{ kind: "", error: "missing path" }};
      }}
      if (state.inlinePreviewCache[cacheKey]) {{
        return state.inlinePreviewCache[cacheKey];
      }}
      const kind = previewableFileKind(cacheKey);
      if (!kind) {{
        const payload = {{ kind: "", error: "not previewable" }};
        return rememberInlineFilePreview(cacheKey, payload);
      }}
      if (kind === "image") {{
        const payload = {{
          kind,
          src: buildFileRawHref(cacheKey),
        }};
        return rememberInlineFilePreview(cacheKey, payload);
      }}
      const controller = typeof AbortController === "function" ? new AbortController() : null;
      const timeout = controller
        ? window.setTimeout(() => controller.abort(), INLINE_PREVIEW_TIMEOUT_MS)
        : 0;
      try {{
        const fetchOptions = {{
          method: "GET",
          credentials: "same-origin",
          cache: "force-cache",
          headers: {{
            Range: `bytes=0-${{INLINE_TEXT_PREVIEW_RANGE_BYTES - 1}}`,
          }},
        }};
        if (controller) {{
          fetchOptions.signal = controller.signal;
        }}
        const response = await fetch(buildFileRawHref(cacheKey), fetchOptions);
        if (!response.ok) {{
          throw new Error(`preview fetch failed: ${{response.status}}`);
        }}
        const raw = await response.text();
        const contentRange = response.headers.get("Content-Range") || "";
        const totalMatch = contentRange.match(/\/(\d+)$/);
        const totalBytes = totalMatch ? Number(totalMatch[1]) : 0;
        const normalized = raw.replace(/\\r\\n/g, "\\n").replace(/\\r/g, "\\n");
        const truncated = normalized.length > INLINE_TEXT_PREVIEW_MAX_CHARS || totalBytes > raw.length;
        const lines = normalized.split("\\n");
        const visibleLines = lines.slice(0, 8);
        const payload = {{
          kind,
          text: visibleLines.join("\\n").trimEnd(),
          lineCount: lines.length,
          hiddenLines: Math.max(0, lines.length - visibleLines.length),
          truncated,
        }};
        return rememberInlineFilePreview(cacheKey, payload);
      }} catch (_) {{
        const payload = {{ kind, error: "preview unavailable" }};
        return rememberInlineFilePreview(cacheKey, payload);
      }} finally {{
        if (timeout) {{
          window.clearTimeout(timeout);
        }}
      }}
    }}

    function extractInlineFileTargets(value, limit = INLINE_FILE_TARGET_LIMIT) {{
      return extractPreviewableFileTargets(value, limit);
    }}

    function buildInlineFilePreviewCard(entry) {{
      const card = document.createElement("section");
      card.className = `inline-file-preview attachment-kind-${{escapeHtml(entry.kind)}}`;

      const head = document.createElement("div");
      head.className = "inline-file-preview-head";

      const meta = document.createElement("div");
      meta.className = "inline-file-preview-meta";

      if (entry.kind === "image") {{
        const thumb = document.createElement("img");
        thumb.className = "inline-file-preview-thumb";
        thumb.src = buildFileRawHref(entry.path);
        thumb.alt = entry.label || basenameForPath(entry.path);
        thumb.loading = "lazy";
        thumb.decoding = "async";
        meta.appendChild(thumb);
      }}

      const label = document.createElement("div");
      label.className = "inline-file-preview-label";
      label.textContent = entry.kind === "image" ? "IMG" : "FILE";
      label.title = entry.kind === "image" ? "Image preview" : "File artifact";
      meta.appendChild(label);

      const name = document.createElement("div");
      name.className = "inline-file-preview-name";
      name.textContent = entry.label || basenameForPath(entry.path);
      meta.appendChild(name);

      const subtle = document.createElement("div");
      subtle.className = "inline-file-preview-subtle";
      subtle.textContent = compactInlineFilePath(entry.path);
      subtle.title = entry.path;
      meta.appendChild(subtle);

      head.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "inline-file-preview-actions";

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "ghost inline-action inline-file-preview-toggle";
      toggle.textContent = "View";
      actions.appendChild(toggle);

      const open = document.createElement("a");
      open.className = "ghost inline-action";
      open.href = buildFileViewHref(entry.path);
      open.target = "_blank";
      open.rel = "noreferrer";
      open.textContent = "Open";
      open.title = "Open dedicated file view";
      actions.appendChild(open);

      const download = document.createElement("a");
      download.className = "ghost inline-action";
      download.href = buildFileDownloadHref(entry.path);
      download.textContent = "Save";
      download.title = "Download original file";
      actions.appendChild(download);

      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "ghost inline-action";
      copy.textContent = "Path";
      copy.title = "Copy full path";
      copy.addEventListener("click", () => copyText(entry.path, copy));
      actions.appendChild(copy);

      head.appendChild(actions);
      card.appendChild(head);

      const summary = document.createElement("div");
      summary.className = "inline-file-preview-summary";
      summary.textContent = entry.kind === "image"
        ? "Image preview collapsed by default."
        : entry.kind === "file"
          ? "File ready. Download keeps the original artifact."
          : "Preview collapsed by default. Open if you need inline detail.";
      card.appendChild(summary);

      const body = document.createElement("div");
      body.className = "inline-file-preview-body";
      body.hidden = true;
      card.appendChild(body);

      let loaded = false;
      async function ensureLoaded() {{
        if (loaded) {{
          return;
        }}
        loaded = true;
        card.classList.add("loading");
        body.textContent = entry.kind === "image" ? "Loading preview…" : "Loading file preview…";
        const payload = await loadInlineFilePreview(entry);
        card.classList.remove("loading");
        body.innerHTML = "";
        if (payload.kind === "image" && payload.src) {{
          const image = document.createElement("img");
          image.src = payload.src;
          image.alt = entry.label || basenameForPath(entry.path);
          image.loading = "lazy";
          image.decoding = "async";
          body.appendChild(image);
          return;
        }}
        if (payload.kind === "text" && payload.text) {{
          const pre = document.createElement("pre");
          pre.className = "inline-file-preview-text";
          pre.textContent = payload.text;
          body.appendChild(pre);
          const note = document.createElement("div");
          note.className = "inline-file-preview-note";
          note.textContent = payload.truncated
            ? "Preview clipped. Open the file view for the full content."
            : payload.hiddenLines > 0
            ? `${{payload.hiddenLines}} more lines in file`
            : `${{payload.lineCount || 0}} lines total`;
          body.appendChild(note);
          return;
        }}
        const note = document.createElement("div");
        note.className = "inline-file-preview-note";
        note.textContent = "Preview unavailable here. Open the file view for the full content.";
        body.appendChild(note);
      }}

      async function setExpanded(nextExpanded) {{
        const expanded = Boolean(nextExpanded);
        card.classList.toggle("expanded", expanded);
        body.hidden = !expanded;
        toggle.textContent = expanded ? "Hide" : "View";
        toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
        if (expanded) {{
          await ensureLoaded();
        }}
      }}

      toggle.addEventListener("click", async () => {{
        await setExpanded(body.hidden);
      }});

      return {{ card, body, setExpanded }};
    }}

    function buildInlineImagePreviewTile(entry) {{
      const tile = document.createElement("a");
      tile.className = "inline-image-preview-tile";
      tile.href = buildFileViewHref(entry.path);
      tile.target = "_blank";
      tile.rel = "noreferrer";
      tile.title = entry.path;

      const image = document.createElement("img");
      image.src = buildFileRawHref(entry.path);
      image.alt = entry.label || basenameForPath(entry.path);
      image.loading = "lazy";
      image.decoding = "async";
      tile.appendChild(image);

      const caption = document.createElement("div");
      caption.className = "inline-image-preview-caption";
      const captionText = document.createElement("span");
      captionText.textContent = entry.label || basenameForPath(entry.path);
      caption.appendChild(captionText);
      tile.appendChild(caption);

      return tile;
    }}

    function renderInlineImagePreviewGallery(items) {{
      const imageEntries = Array.isArray(items) ? items.filter((entry) => entry?.kind === "image") : [];
      if (imageEntries.length < 2) {{
        return null;
      }}
      const gallery = document.createElement("div");
      gallery.className = "message-file-preview-gallery";
      const visible = imageEntries.slice(0, INLINE_IMAGE_GALLERY_LIMIT);
      for (const entry of visible) {{
        gallery.appendChild(buildInlineImagePreviewTile(entry));
      }}
      if (imageEntries.length > visible.length) {{
        const more = document.createElement("div");
        more.className = "inline-image-preview-more";
        more.textContent = `+${{imageEntries.length - visible.length}} more`;
        gallery.appendChild(more);
      }}
      return gallery;
    }}

    async function renderInlineFilePreviews(container, targets) {{
      const items = Array.isArray(targets) ? targets : [];
      container.innerHTML = "";
      if (!items.length) {{
        container.hidden = true;
        return;
      }}
      container.hidden = false;
      const imageGallery = renderInlineImagePreviewGallery(items);
      if (imageGallery) {{
        container.appendChild(imageGallery);
      }}
      const compactItems = imageGallery ? items.filter((entry) => entry?.kind !== "image") : items;
      for (const entry of compactItems) {{
        const preview = buildInlineFilePreviewCard(entry);
        container.appendChild(preview.card);
      }}
    }}

    function looksLikeLargePaste(value) {{
      const text = String(value || "");
      if (!text.trim()) {{
        return false;
      }}
      const lineCount = text.split(/\\r?\\n/).length;
      if (lineCount >= LARGE_PASTE_MIN_LINES) {{
        return true;
      }}
      return text.length >= LARGE_PASTE_MIN_CHARS && lineCount >= 4;
    }}

    function normalizeCodeLanguage(value) {{
      const clean = String(value || "").trim().toLowerCase();
      if (!clean) return "";
      if (["py", "python"].includes(clean)) return "python";
      if (["js", "jsx", "javascript"].includes(clean)) return "javascript";
      if (["ts", "tsx", "typescript"].includes(clean)) return "typescript";
      if (["sh", "bash", "zsh", "shell"].includes(clean)) return "bash";
      if (["yml", "yaml"].includes(clean)) return "yaml";
      return clean;
    }}

    function stashSegments(text, regex, className) {{
      const stash = {{}};
      const nextText = text.replace(regex, (match) => {{
        const token = nextRenderToken("CODE_SEGMENT");
        stash[token] = `<span class="${{className}}">${{match}}</span>`;
        return token;
      }});
      return {{ text: nextText, stash }};
    }}

    function restoreSegments(text, stashes) {{
      let output = text;
      for (const stash of stashes) {{
        for (const [token, value] of Object.entries(stash)) {{
          output = output.split(token).join(value);
        }}
      }}
      return output;
    }}

    function stashHtmlTags(text) {{
      const stash = {{}};
      const nextText = String(text || "").replace(/<[^>]+>/g, (match) => {{
        const token = nextRenderToken("HTML_TAG");
        stash[token] = match;
        return token;
      }});
      return {{ text: nextText, stash }};
    }}

    function stashRawHtmlAnchors(text) {{
      const stash = {{}};
      const nextText = String(text || "").replace(RAW_HTML_ANCHOR_RE, (match, attrs, innerHtml) => {{
        const hrefMatch = String(attrs || "").match(RAW_HTML_HREF_RE);
        if (!hrefMatch) {{
          return stripInlineHtmlText(innerHtml);
        }}
        const href = decodeHtmlEntities(hrefMatch[1] || hrefMatch[2] || hrefMatch[3] || "");
        const cleanHref = unwrapMarkdownLinkTarget(href);
        const labelText = displayTextForLink(cleanHref, innerHtml);
        let markup = "";
        if (/^https?:\\/\\//i.test(cleanHref)) {{
          const url = normalizeUrlCandidate(cleanHref);
          markup = `<a href="${{escapeHtml(url)}}" target="_blank" rel="noreferrer">${{escapeHtml(displayTextForLink(url, innerHtml))}}</a>`;
        }} else if (isFileTarget(cleanHref)) {{
          markup = `<a class="file-link" href="${{escapeHtml(buildFileViewHref(cleanHref))}}" target="_blank" rel="noreferrer">${{escapeHtml(labelText || normalizeFileTarget(cleanHref))}}</a>`;
        }} else {{
          return labelText || cleanHref;
        }}
        const token = nextRenderToken("RAW_ANCHOR");
        stash[token] = markup;
        return token;
      }});
      return {{ text: nextText, stash }};
    }}

    function highlightInlineEntities(text) {{
      const stash = {{}};
      const stashMarkup = (markup) => {{
        const token = nextRenderToken("INLINE_ENTITY");
        stash[token] = markup;
        return token;
      }};
      let nextText = String(text || "");
      nextText = highlightDynamicHostEntities(nextText, stashMarkup);
      nextText = nextText.replace(
        /(^|[^A-Za-z0-9_&])@([A-Za-z][A-Za-z0-9._-]{1,31})\b/g,
        (match, prefix, label) => {{
          const key = normalizeInlineEntityKey(label);
          const base = INLINE_ENTITY_MAP.get(key) || {{
            key,
            label: String(label || ""),
            mark: "@",
            kind: "mention",
            tone: "mention",
            group: "",
          }};
          const mark = base.mark && base.mark !== "•" ? base.mark : "@";
          const baseKind = String(base.kind || "mention");
          const tone = baseKind === "bot" ? "mention-bot" : baseKind === "host" ? "mention-host" : "mention";
          const mentionable = baseKind !== "host";
          return `${{prefix}}${{stashMarkup(
            renderEntityCartouche({{ ...base, mark, tone }}, `@${{label}}`, {{ mention: mentionable }})
          )}}`;
        }}
      );
      for (const entry of INLINE_ENTITY_ENTRIES) {{
        nextText = nextText.replace(entry.pattern, (match, prefix, visible) => {{
          return `${{prefix}}${{stashMarkup(renderEntityCartouche(entry.entity, visible))}}`;
        }});
      }}
      return {{ text: nextText, stash }};
    }}

    function highlightEscapedCode(code, language) {{
      const lang = normalizeCodeLanguage(language);
      const sensitive = stashSensitiveSegments(
        String(code || "").replace(/\\r\\n/g, "\\n"),
        {{ maskQueryParams: true }}
      );
      let text = escapeHtml(sensitive.text);
      const stashes = [sensitive.stash];

      const strings = stashSegments(
        text,
        /(&quot;(?:[^&]|&(?!quot;))*?&quot;|&#39;(?:[^&]|&(?!#39;))*?&#39;)/g,
        "tok-string"
      );
      text = strings.text;
      stashes.push(strings.stash);

      const commentPattern = lang === "python" || lang === "bash"
        ? /#[^\\n]*/g
        : ["javascript", "typescript"].includes(lang)
          ? /\/\/[^\\n]*/g
          : null;
      if (commentPattern) {{
        const comments = stashSegments(text, commentPattern, "tok-comment");
        text = comments.text;
        stashes.push(comments.stash);
      }}

      if (lang === "json") {{
        text = text.replace(
          /(&quot;[^\\n]*?&quot;)(\\s*:)/g,
          '<span class="tok-key">$1</span>$2'
        );
        text = text.replace(/\\b(true|false|null)\\b/g, '<span class="tok-atom">$1</span>');
        text = text.replace(/\\b(-?\\d+(?:\\.\\d+)?)\\b/g, '<span class="tok-number">$1</span>');
      }} else if (lang === "yaml" || lang === "toml") {{
        text = text.replace(
          /(^|\\n)(\\s*[A-Za-z0-9_.-]+)(\\s*:)/g,
          '$1<span class="tok-key">$2</span>$3'
        );
        text = text.replace(/\\b(true|false|null)\\b/gi, '<span class="tok-atom">$1</span>');
        text = text.replace(/\\b(-?\\d+(?:\\.\\d+)?)\\b/g, '<span class="tok-number">$1</span>');
      }} else {{
        const keywordMap = {{
          python: /\\b(def|class|return|if|elif|else|for|while|try|except|finally|with|import|from|as|pass|break|continue|lambda|yield|async|await|True|False|None|and|or|not|in|is)\\b/g,
          javascript: /\\b(function|return|const|let|var|if|else|for|while|try|catch|finally|import|from|export|default|class|extends|new|await|async|true|false|null|undefined|switch|case|break|continue)\\b/g,
          typescript: /\\b(function|return|const|let|var|if|else|for|while|try|catch|finally|import|from|export|default|class|extends|new|await|async|true|false|null|undefined|switch|case|break|continue|type|interface|implements|public|private|protected|readonly)\\b/g,
          bash: /\\b(if|then|else|fi|for|do|done|case|esac|function|local|export|return|in|while)\\b/g,
        }};
        if (keywordMap[lang]) {{
          text = text.replace(keywordMap[lang], '<span class="tok-keyword">$1</span>');
        }}
        text = text.replace(/\\b(-?\\d+(?:\\.\\d+)?)\\b/g, '<span class="tok-number">$1</span>');
        if (lang === "bash") {{
          text = text.replace(/(\\$[A-Za-z_][A-Za-z0-9_]*)/g, '<span class="tok-attr">$1</span>');
          text = text.replace(/(^|\\s)(--?[A-Za-z0-9._-]+)/g, '$1<span class="tok-attr">$2</span>');
        }}
      }}

      return restoreSegments(text, stashes);
    }}

    function renderCodeBlock(body, language) {{
      const lang = normalizeCodeLanguage(language);
      const code = String(body || "").replace(/^\\n+|\\n+$/g, "");
      const label = lang || "text";
      const lines = code ? code.split(/\\r?\\n/) : [];
      const lineCount = lines.length;
      const compactable = lineCount >= 9 || code.length >= 520;
      const previewLines = lines.slice(0, 4).join("\\n");
      const hiddenLines = Math.max(0, lineCount - 4);
      const toggleButton = compactable
        ? '<button type="button" class="ghost code-toggle-button" data-icon="⋯" aria-expanded="false">View</button>'
        : "";
      const previewBlock = compactable
        ? `<div class="code-preview"><pre><code class="language-${{escapeHtml(label)}}">${{highlightEscapedCode(previewLines, lang)}}</code></pre><div class="code-preview-meta">${{hiddenLines > 0 ? `${{hiddenLines}} more lines hidden` : "Tap to expand"}}</div></div>`
        : "";
      return `
        <div class="code-block${{compactable ? " compactable collapsed" : ""}}" data-lines="${{lineCount}}">
          <div class="code-head">
            <span>${{escapeHtml(label)}}</span>
            <div class="code-head-actions">
              ${{toggleButton}}
              <span>${{code ? code.split(/\\r?\\n/).length : 0}} lines</span>
              <button type="button" class="ghost code-copy-button" data-icon="⎘">Copy</button>
            </div>
          </div>
          ${{previewBlock}}
          <div class="code-scroll">
            <pre><code class="language-${{escapeHtml(label)}}">${{highlightEscapedCode(code, lang)}}</code></pre>
          </div>
        </div>
      `;
    }}

    function renderInlineCodeMarkup(value) {{
      const raw = String(value || "");
      const trimmed = raw.trim();
      if (!trimmed) {{
        return "<code></code>";
      }}
      if (/^https?:\\/\\//i.test(trimmed)) {{
        const url = normalizeUrlCandidate(trimmed);
        return `<a class="inline-code-link" href="${{escapeHtml(url)}}" target="_blank" rel="noreferrer"><code>${{escapeHtml(maskSensitiveUrlText(trimmed))}}</code></a>`;
      }}
      if (isFileTarget(trimmed)) {{
        const clean = normalizeFileTarget(trimmed);
        return `<a class="inline-code-link" href="${{escapeHtml(buildFileViewHref(clean))}}" target="_blank" rel="noreferrer"><code>${{escapeHtml(clean)}}</code></a>`;
      }}
      return `<code>${{escapeHtml(raw)}}</code>`;
    }}

    function renderInlineMarkup(value) {{
      const rawAnchors = stashRawHtmlAnchors(String(value || "").replace(/\\r\\n/g, "\\n"));
      const sensitive = stashSensitiveSegments(rawAnchors.text);
      const inlineCode = {{}};
      sensitive.text = sensitive.text.replace(/`([^`]+)`/g, (_, code) => {{
        const token = nextRenderToken("INLINE_CODE");
        inlineCode[token] = renderInlineCodeMarkup(code);
        return token;
      }});
      let text = escapeHtml(sensitive.text);
      const stashes = [rawAnchors.stash, sensitive.stash];
      stashes.push(inlineCode);
      text = text.replace(/\\*\\*([^*\\n][\\s\\S]*?[^*\\n])\\*\\*/g, "<strong>$1</strong>");
      text = text.replace(/(^|[^\\w*])\\*([^*\\n][\\s\\S]*?[^*\\n])\\*(?!\\*)/g, "$1<em>$2</em>");
      text = text.replace(
        /\\[([^\\]]+)\\]\\s*\\(\\s*(<[^>\\n]+>|[^\\s)]+)\\s*\\)/g,
        (_, label, target) => {{
          const clean = unwrapMarkdownLinkTarget(String(target || "").trim());
          if (/^https?:\\/\\//i.test(clean)) {{
            const url = normalizeUrlCandidate(clean);
            return `<a href="${{escapeHtml(url)}}" target="_blank" rel="noreferrer">${{escapeHtml(displayTextForLink(url, label))}}</a>`;
          }}
          if (isFileTarget(clean)) {{
            return `<a class="file-link" href="${{escapeHtml(buildFileViewHref(clean))}}" target="_blank" rel="noreferrer">${{escapeHtml(displayTextForLink(clean, label))}}</a>`;
          }}
          return `[${{label}}](${{escapeHtml(clean)}})`;
        }}
      );
      text = text.replace(
        /(^|[\\s(])((?:\\/|~\\/)[^\\s<)"']+)/g,
        (_, prefix, target) => {{
          const clean = normalizeFileTarget(target);
          if (!isFileTarget(clean)) {{
            return `${{prefix}}${{target}}`;
          }}
          return `${{prefix}}<a class="file-link" href="${{escapeHtml(buildFileViewHref(clean))}}" target="_blank" rel="noreferrer">${{escapeHtml(clean)}}</a>`;
        }}
      );
      text = text.replace(
        /(^|[\\s(])(https?:\\/\\/[^\\s<]+)/g,
        (_, prefix, url) => {{
          const clean = normalizeUrlCandidate(url);
          const trailing = escapeHtml(url.slice(clean.length));
          return `${{prefix}}<a href="${{escapeHtml(clean)}}" target="_blank" rel="noreferrer">${{escapeHtml(maskSensitiveUrlText(clean))}}</a>${{trailing}}`;
        }}
      );
      const htmlTags = stashHtmlTags(text);
      const entities = highlightInlineEntities(htmlTags.text);
      stashes.push(htmlTags.stash, entities.stash);
      return restoreSegments(entities.text, stashes);
    }}

    function isRuleLine(line) {{
      return /^\\s*([-*_])(?:\\s*\\1){{2,}}\\s*$/.test(line);
    }}

    function isHeadingLine(line) {{
      return /^\\s*#{1,4}\\s+\\S/.test(line);
    }}

    function isQuoteLine(line) {{
      return /^\\s*>\\s?/.test(line);
    }}

    function isBulletLine(line) {{
      return Boolean(bulletLineMatch(line));
    }}

    function isNumberedLine(line) {{
      return Boolean(numberedLineMatch(line));
    }}

    function isTaskLine(line) {{
      return Boolean(taskLineMatch(line));
    }}

    function isKeyValueLine(line) {{
      return /^\\s*[A-Za-z][A-Za-z0-9 /&()._-]{1,40}:\\s+\\S/.test(String(line || ""));
    }}

    function calloutMatch(line) {{
      return String(line || "").match(/^\\s*(Alert|Note|Decision|Next|Watch|Heads up)\\s*:\\s+(.+)$/i);
    }}

    function splitTableCells(line) {{
      let clean = String(line || "").trim();
      if (!clean.includes("|")) {{
        return [];
      }}
      if (clean.startsWith("|")) {{
        clean = clean.slice(1);
      }}
      if (clean.endsWith("|")) {{
        clean = clean.slice(0, -1);
      }}
      return clean.split("|").map((cell) => cell.trim());
    }}

    function isTableSeparatorCell(cell) {{
      return /^:?-{1,}:?$/.test(String(cell || "").trim());
    }}

    function isTableSeparatorLine(line) {{
      const cells = splitTableCells(line);
      return cells.length > 0 && cells.every((cell) => isTableSeparatorCell(cell));
    }}

    function isTableStart(lines, index) {{
      if (index + 1 >= lines.length) {{
        return false;
      }}
      const header = splitTableCells(lines[index]);
      const separator = splitTableCells(lines[index + 1]);
      return Boolean(
        header.length
        && header.length === separator.length
        && separator.every((cell) => isTableSeparatorCell(cell))
      );
    }}

    function hasOuterPipe(line) {{
      const clean = String(line || "").trim();
      return clean.startsWith("|") || clean.endsWith("|");
    }}

    function isPipeTableLikeStart(lines, index) {{
      if (index + 1 >= lines.length) {{
        return false;
      }}
      const headerLine = String(lines[index] || "");
      const header = splitTableCells(headerLine);
      if (header.length < 2 || header.every((cell) => !cell) || isTableSeparatorLine(headerLine)) {{
        return false;
      }}
      let rowCount = 0;
      for (let scan = index + 1; scan < lines.length; scan += 1) {{
        const current = String(lines[scan] || "");
        if (!current.trim()) {{
          break;
        }}
        if (isStructuredLine(current) || isTableSeparatorLine(current)) {{
          break;
        }}
        const row = splitTableCells(current);
        if (row.length !== header.length || row.every((cell) => !cell)) {{
          break;
        }}
        rowCount += 1;
        if (rowCount >= 2 || (rowCount >= 1 && hasOuterPipe(headerLine) && hasOuterPipe(current))) {{
          return true;
        }}
      }}
      return false;
    }}

    function isStructuredLine(line) {{
      return (
        isRuleLine(line)
        || isHeadingLine(line)
        || isQuoteLine(line)
        || isTaskLine(line)
        || isKeyValueLine(line)
        || Boolean(calloutMatch(line))
        || Boolean(standaloneStrongLineMatch(line))
        || isBulletLine(line)
        || isNumberedLine(line)
      );
    }}

    function bulletLineMatch(line) {{
      return String(line || "").match(/^\\s*(?:[-*•‣]|\\u2013|\\u2014)\\s+(.+)$/);
    }}

    function numberedLineMatch(line) {{
      return String(line || "").match(/^\\s*(\\d+)(?:\\.|\\))\\s+(.+)$/);
    }}

    function taskLineMatch(line) {{
      return String(line || "").match(/^\\s*(?:[-*•‣]|\\u2013|\\u2014)\\s+\\[( |x|X)\\]\\s+(.+)$/);
    }}

    function standaloneStrongLineMatch(line) {{
      return String(line || "").match(/^\\s*(?:\\*\\*|__)(.+?)(?:\\*\\*|__)\\s*$/);
    }}

    function renderParagraphBlock(lines) {{
      const body = String(lines.join("\\n") || "").trim();
      if (!body) {{
        return "";
      }}
      return `<p>${{renderInlineMarkup(body).replace(/\\n/g, "<br>")}}</p>`;
    }}

    function renderListBlock(items, ordered, start = 1) {{
      if (!items.length) {{
        return "";
      }}
      const tag = ordered ? "ol" : "ul";
      const startAttr = ordered && start > 1 ? ` start="${{start}}"` : "";
      return `<${{tag}}${{startAttr}}>${{items.map((item) => `<li>${{renderInlineMarkup(item)}}</li>`).join("")}}</${{tag}}>`;
    }}

    function renderTaskListBlock(items) {{
      if (!items.length) {{
        return "";
      }}
      return `
        <ul class="task-list">
          ${{items.map((item) => `
            <li class="task-item${{item.checked ? " checked" : ""}}">
              <span class="task-check">${{item.checked ? "x" : ""}}</span>
              <span class="task-copy">${{renderInlineMarkup(item.text)}}</span>
            </li>
          `).join("")}}
        </ul>
      `;
    }}

    function renderKeyValueBlock(items) {{
      if (!items.length) {{
        return "";
      }}
      return `
        <div class="kv-list">
          ${{items.map((item) => `
            <div class="kv-row">
              <div class="kv-key">${{escapeHtml(item.key)}}</div>
              <div class="kv-value">${{renderInlineMarkup(item.value).replace(/\\n/g, "<br>")}}</div>
            </div>
          `).join("")}}
        </div>
      `;
    }}

    function calloutTone(label) {{
      const clean = String(label || "").trim().toLowerCase();
      if (clean === "alert" || clean === "heads up") return ["callout-alert", "!"];
      if (clean === "decision") return ["callout-decision", ">"];
      if (clean === "next") return ["callout-next", ">"];
      if (clean === "watch") return ["callout-watch", "!"];
      return ["callout-note", "i"];
    }}

    function renderCalloutBlock(label, lines) {{
      const [tone, icon] = calloutTone(label);
      const body = renderTextBlocks(lines.join("\\n"));
      return `
        <div class="callout ${{tone}}">
          <div class="callout-head" data-icon="${{icon}}">${{escapeHtml(label)}}</div>
          <div class="callout-copy">${{body}}</div>
        </div>
      `;
    }}

    function tableAlignment(cell) {{
      if (cell.startsWith(":") && cell.endsWith(":")) return "center";
      if (cell.endsWith(":")) return "right";
      return "left";
    }}

    function renderTableBlock(header, separator, rows) {{
      const alignments = separator.map((cell) => tableAlignment(cell));
      const headHtml = header.map((cell, index) => `<th style="text-align:${{alignments[index]}}">${{renderInlineMarkup(cell)}}</th>`).join("");
      const bodyHtml = rows.map((row) => `
        <tr>
          ${{row.map((cell, index) => `<td style="text-align:${{alignments[index]}}">${{renderInlineMarkup(cell)}}</td>`).join("")}}
        </tr>
      `).join("");
      return `
        <div class="table-wrap">
          <table class="rich-table">
            <thead><tr>${{headHtml}}</tr></thead>
            <tbody>${{bodyHtml}}</tbody>
          </table>
        </div>
      `;
    }}

    function renderTextBlocks(value) {{
      const lines = String(value || "").replace(/\\r\\n/g, "\\n").split("\\n");
      const blocks = [];
      let index = 0;

      while (index < lines.length) {{
        const line = lines[index];
        if (!line.trim()) {{
          index += 1;
          continue;
        }}

        if (isRuleLine(line)) {{
          blocks.push("<hr>");
          index += 1;
          continue;
        }}

        const headingMatch = line.match(/^\\s*(#{1,4})\\s+(.+?)\\s*$/);
        if (headingMatch) {{
          const level = Math.min(4, headingMatch[1].length);
          blocks.push(`<h${{level}}>${{renderInlineMarkup(headingMatch[2])}}</h${{level}}>`);
          index += 1;
          continue;
        }}

        const strongLineMatch = standaloneStrongLineMatch(line);
        if (strongLineMatch) {{
          blocks.push(`<div class="section-label">${{renderInlineMarkup(strongLineMatch[1])}}</div>`);
          index += 1;
          continue;
        }}

        if (isQuoteLine(line)) {{
          const quoteLines = [];
          while (index < lines.length && (isQuoteLine(lines[index]) || !lines[index].trim())) {{
            if (isQuoteLine(lines[index])) {{
              quoteLines.push(lines[index].replace(/^\\s*>\\s?/, ""));
            }} else {{
              quoteLines.push("");
            }}
            index += 1;
          }}
          blocks.push(`<blockquote>${{renderTextBlocks(quoteLines.join("\\n"))}}</blockquote>`);
          continue;
        }}

        if (isTableStart(lines, index)) {{
          const header = splitTableCells(lines[index]);
          const separator = splitTableCells(lines[index + 1]);
          const rows = [];
          index += 2;
          while (index < lines.length) {{
            if (!lines[index].trim()) {{
              break;
            }}
            const row = splitTableCells(lines[index]);
            if (!row.length || row.length !== header.length || isTableSeparatorLine(lines[index])) {{
              break;
            }}
            rows.push(row);
            index += 1;
          }}
          blocks.push(renderTableBlock(header, separator, rows));
          continue;
        }}

        if (isPipeTableLikeStart(lines, index)) {{
          const header = splitTableCells(lines[index]);
          const rows = [];
          index += 1;
          while (index < lines.length) {{
            const current = String(lines[index] || "");
            if (!current.trim()) {{
              break;
            }}
            if (isStructuredLine(current) || isTableSeparatorLine(current)) {{
              break;
            }}
            const row = splitTableCells(current);
            if (row.length !== header.length || row.every((cell) => !cell)) {{
              break;
            }}
            rows.push(row);
            index += 1;
          }}
          if (rows.length) {{
            blocks.push(renderTableBlock(header, header.map(() => "-"), rows));
            continue;
          }}
        }}

        const callout = calloutMatch(line);
        if (callout) {{
          const label = callout[1];
          const contentLines = [callout[2]];
          index += 1;
          while (index < lines.length) {{
            const current = lines[index];
            if (!current.trim()) {{
              break;
            }}
            if (isTableStart(lines, index) || isStructuredLine(current)) {{
              break;
            }}
            contentLines.push(current);
            index += 1;
          }}
          blocks.push(renderCalloutBlock(label, contentLines));
          continue;
        }}

        const taskMatch = taskLineMatch(line);
        if (taskMatch) {{
          const items = [];
          while (index < lines.length) {{
            const match = taskLineMatch(lines[index]);
            if (!match) {{
              break;
            }}
            items.push({{ checked: match[1].toLowerCase() === "x", text: match[2] }});
            index += 1;
          }}
          blocks.push(renderTaskListBlock(items));
          continue;
        }}

        const keyValueMatch = line.match(/^\\s*([A-Za-z][A-Za-z0-9 /&()._-]{1,40}):\\s+(.+)$/);
        if (keyValueMatch) {{
          const items = [];
          while (index < lines.length) {{
            const match = lines[index].match(/^\\s*([A-Za-z][A-Za-z0-9 /&()._-]{1,40}):\\s+(.+)$/);
            if (!match) {{
              break;
            }}
            items.push({{ key: match[1], value: match[2] }});
            index += 1;
          }}
          blocks.push(renderKeyValueBlock(items));
          continue;
        }}

        const bulletMatch = bulletLineMatch(line);
        if (bulletMatch) {{
          const items = [];
          while (index < lines.length) {{
            const match = bulletLineMatch(lines[index]);
            if (!match) {{
              break;
            }}
            items.push(match[1]);
            index += 1;
          }}
          blocks.push(renderListBlock(items, false));
          continue;
        }}

        const numberedMatch = numberedLineMatch(line);
        if (numberedMatch) {{
          const items = [];
          const start = Number(numberedMatch[1]) || 1;
          while (index < lines.length) {{
            const match = numberedLineMatch(lines[index]);
            if (!match) {{
              break;
            }}
            items.push(match[2]);
            index += 1;
          }}
          blocks.push(renderListBlock(items, true, start));
          continue;
        }}

        const paragraph = [];
        while (
          index < lines.length
          && lines[index].trim()
          && !isStructuredLine(lines[index])
          && !isTableStart(lines, index)
        ) {{
          paragraph.push(lines[index]);
          index += 1;
        }}
        blocks.push(renderParagraphBlock(paragraph));
      }}

      return blocks.filter(Boolean).join("");
    }}

    function renderAttachmentChips(container, attachments, options = {{}}) {{
      const items = Array.isArray(attachments) ? attachments : [];
      container.innerHTML = "";
      const gallery = Boolean(options.gallery);
      container.classList.toggle("gallery", gallery);
      if (!items.length) {{
        container.hidden = true;
        return;
      }}
      const removable = Boolean(options.removable);
      container.hidden = false;
      for (const entry of items) {{
        const kind = attachmentKind(entry);
        const chip = document.createElement("div");
        chip.className = `attachment-chip attachment-kind-${{kind}}${{kind === "image" && entry.path ? " attachment-has-thumb" : ""}}${{removable ? " removable" : ""}}`;
        if (gallery && kind === "image" && entry.path) {{
          chip.classList.add("is-media");
        }}

        const content = entry.path ? document.createElement("a") : document.createElement("div");
        content.className = "attachment-chip-link";
        if (entry.path) {{
          content.href = buildFileViewHref(entry.path || "");
          content.target = "_blank";
          content.rel = "noreferrer";
          content.title = entry.path || attachmentDisplayName(entry);
        }}

        if (kind === "image" && entry.path) {{
          const thumb = document.createElement("img");
          thumb.className = "attachment-thumb";
          thumb.src = buildFileRawHref(entry.path);
          thumb.alt = attachmentDisplayName(entry);
          thumb.loading = "lazy";
          thumb.decoding = "async";
          content.appendChild(thumb);
        }}

        const copy = document.createElement("span");
        copy.className = "attachment-chip-copy";

        const name = document.createElement("span");
        name.className = "attachment-name";
        name.textContent = attachmentDisplayName(entry);
        copy.appendChild(name);

        const metaText = attachmentSummary(entry);
        if (metaText) {{
          const meta = document.createElement("span");
          meta.className = "attachment-meta";
          meta.textContent = metaText;
          copy.appendChild(meta);
        }}

        content.appendChild(copy);
        chip.appendChild(content);

        if (removable) {{
          const removeButton = document.createElement("button");
          removeButton.type = "button";
          removeButton.className = "ghost attachment-remove";
          removeButton.dataset.icon = "×";
          removeButton.title = `Remove ${{attachmentDisplayName(entry)}}`;
          removeButton.setAttribute("aria-label", `Remove ${{attachmentDisplayName(entry)}}`);
          removeButton.addEventListener("click", () => removeAttachment(entry.token));
          chip.appendChild(removeButton);
        }}

        container.appendChild(chip);
      }}
    }}

    function renderRichText(value) {{
      const text = String(value || "");
      const pattern = /```([A-Za-z0-9_+-]*)\\n?([\\s\\S]*?)```/g;
      const parts = [];
      let cursor = 0;
      for (const match of text.matchAll(pattern)) {{
        const index = match.index || 0;
        if (index > cursor) {{
          parts.push(renderTextBlocks(text.slice(cursor, index)));
        }}
        parts.push(renderCodeBlock(match[2] || "", match[1] || ""));
        cursor = index + match[0].length;
      }}
      if (cursor < text.length) {{
        parts.push(renderTextBlocks(text.slice(cursor)));
      }}
      if (!parts.length) {{
        return renderTextBlocks(text);
      }}
      return parts.join("");
    }}

    function summarizePrompt(value, limit = 120) {{
      const clean = String(value || "").replace(/\\s+/g, " ").trim();
      if (clean.length <= limit) {{
        return clean;
      }}
      return `${{clean.slice(0, limit - 1)}}…`;
    }}

    function formatCompactInteger(value) {{
      const clean = Math.max(0, Number(value || 0));
      if (!Number.isFinite(clean)) {{
        return "0";
      }}
      try {{
        return new Intl.NumberFormat(undefined, {{ notation: "compact", maximumFractionDigits: 1 }}).format(clean);
      }} catch (_) {{
        return String(Math.round(clean));
      }}
    }}

    function promptBodyStats(value) {{
      const text = String(value || "").replace(/\\r\\n/g, "\\n");
      const trimmed = text.trim();
      const lines = trimmed ? trimmed.split("\\n") : [];
      const nonEmptyLines = lines.filter((line) => line.trim());
      const previewLine = nonEmptyLines[0] || lines[0] || "";
      return {{
        charCount: trimmed.length,
        lineCount: nonEmptyLines.length || lines.length || (trimmed ? 1 : 0),
        preview: summarizePrompt(previewLine, 84),
      }};
    }}

    function hasPasteBlockAttachment(attachments) {{
      return Array.isArray(attachments) && attachments.some((entry) => String(entry?.source || "").trim() === "paste-block");
    }}

    function collapsedPromptDescriptor(role, body, options = {{}}) {{
      const cleanRole = String(role || "").trim().toLowerCase();
      if (cleanRole.includes("pending")) {{
        return null;
      }}
      const stats = promptBodyStats(body);
      if (!stats.charCount) {{
        return null;
      }}
      if (cleanRole === "user" || cleanRole.includes("queued")) {{
        const pasted = hasPasteBlockAttachment(options.attachments);
        const multiline = stats.lineCount >= LARGE_PASTE_MIN_LINES || (stats.lineCount >= 4 && stats.charCount >= LARGE_PASTE_MIN_CHARS);
        if (!pasted && !multiline) {{
          return null;
        }}
        const title = stats.lineCount <= 1
          ? "Pasted text"
          : `${{stats.lineCount}} lines pasted`;
        const meta = `${{formatCompactInteger(stats.charCount)}} chars`;
        return {{
          badge: "Paste",
          title,
          meta,
          preview: stats.preview,
        }};
      }}
      if (cleanRole.includes("assistant") || cleanRole.includes("error")) {{
        const largeReply = stats.lineCount >= LARGE_REPLY_COLLAPSE_MIN_LINES
          || stats.charCount >= LARGE_REPLY_COLLAPSE_MIN_CHARS;
        if (!largeReply) {{
          return null;
        }}
        const title = stats.lineCount <= 1
          ? "Long reply collapsed"
          : `${{stats.lineCount}} lines collapsed`;
        const meta = `${{formatCompactInteger(stats.charCount)}} chars`;
        return {{
          badge: cleanRole.includes("error") ? "Error" : "Reply",
          title,
          meta,
          preview: stats.preview,
        }};
      }}
      return null;
    }}

    const REPLY_ACTIONS = {{
      make_it_so: {{
        label: "Make it so",
        icon: "!",
        prompt: "Make it so. Do the concrete thing you just proposed instead of describing it again.",
      }},
      proceed: {{
        label: "Proceed",
        icon: ">",
        prompt: "Proceed from your last answer. Continue with the next concrete step and do not repeat the setup.",
      }},
      dig: {{
        label: "Dig",
        icon: "?",
        prompt: "Dig into the uncertain part of your last answer. Find the root cause, missing fact, or next proof point before moving on.",
      }},
      unwind: {{
        label: "Unwind",
        icon: "↺",
        mode: "invoke",
        action: "unwind_latest_turn",
        prompt: "",
      }},
      verify: {{
        label: "Verify",
        icon: "✓",
        prompt: "Verify the last answer against the code, tests, logs, or source material before proceeding. Call out anything that does not hold.",
      }},
      simpler: {{
        label: "Simpler",
        icon: "~",
        prompt: "Make that simpler. Use plainer language, fewer words, and keep only the essential points.",
      }},
    }};

    const STABLE_REPLY_ACTION_KINDS = ["proceed", "dig", "unwind"];

    function messageVariantSeed(value) {{
      const text = String(value || "");
      let seed = 0;
      for (let index = 0; index < text.length; index += 1) {{
        seed = ((seed * 33) + text.charCodeAt(index)) >>> 0;
      }}
      return seed;
    }}

    function replyShortcutDescriptor(kind, seed, offset = 0) {{
      const action = REPLY_ACTIONS[kind];
      if (!action) {{
        return null;
      }}
      return {{
        kind,
        ...action,
      }};
    }}

    function scoreReplyActionKind(kind, sourcePrompt, body) {{
      const text = `${{sourcePrompt || ""}}\\n${{body || ""}}`.toLowerCase();
      let score = STABLE_REPLY_ACTION_KINDS.includes(kind) ? 20 : 0;
      if (kind === "verify" && /\b(test|verify|check|failed|failure|bug|error|regression|logs?)\b/.test(text)) {{
        score += 40;
      }}
      if (kind === "dig" && /\b(why|root cause|uncertain|investigate|trace|missing|failure|failed)\b/.test(text)) {{
        score += 34;
      }}
      if (kind === "make_it_so" && /\b(should|could|next step|implement|fix|patch|change)\b/.test(text)) {{
        score += 26;
      }}
      if (kind === "simpler" && text.length > 900) {{
        score += 18;
      }}
      return score;
    }}

    function selectDynamicReplyActionKinds(sourcePrompt, body, options = {{}}) {{
      const actionCount = Math.max(1, Number(options.actionCount || 5));
      const includeUnwind = Boolean(options.includeUnwind);
      const stable = STABLE_REPLY_ACTION_KINDS.filter((kind) => kind !== "unwind" || includeUnwind);
      const scored = Object.keys(REPLY_ACTIONS)
        .filter((kind) => kind !== "unwind" || includeUnwind)
        .map((kind) => ({{
          kind,
          score: scoreReplyActionKind(kind, sourcePrompt, body),
        }}))
        .sort((a, b) => b.score - a.score || a.kind.localeCompare(b.kind));
      const selected = [];
      const push = (kind) => {{
        if (REPLY_ACTIONS[kind] && !selected.includes(kind) && selected.length < actionCount) {{
          selected.push(kind);
        }}
      }};
      stable.forEach(push);
      scored.forEach((item) => push(item.kind));
      return selected;
    }}

    function applyPromptSuggestion(prompt) {{
      el.promptInput.value = String(prompt || "");
      autoresize(el.promptInput);
      updateComposerToolbar(state.snapshot);
      renderSuggestions(state.snapshot);
      persistPromptDraft(el.promptInput.value);
      focusPromptInputAtEnd();
    }}

    function submitPromptSuggestion(prompt) {{
      applyPromptSuggestion(prompt);
      if (!promptHasSubmissionPayload()) {{
        return;
      }}
      void submitAsk({{
        preventDefault() {{}},
      }});
    }}

    function buildContextSavePrompt(context) {{
      const tone = String(context?.tone || "ok");
      const urgency = tone === "danger"
        ? "Do this now before the thread gets any heavier."
        : "Do this before the thread sprawls further.";
      return [
        "Save/compact our work so far into a concise working handoff I can continue from cleanly.",
        "Preserve the active goal, current state, key decisions, important files or links, open questions, and the exact next actions.",
        urgency,
      ].join(" ");
    }}

    function handleContextSaveAction(button) {{
      const prompt = button?.dataset?.suggestion || "";
      if (!prompt) {{
        return;
      }}
      applyPromptSuggestion(prompt);
      if (document.body.classList.contains("topbar-menu-open")) {{
        setTopbarMenuOpen(false);
      }}
    }}

    function isConsoleLineKillShortcut(event) {{
      return Boolean(
        event
        && event.ctrlKey
        && !event.metaKey
        && !event.altKey
        && String(event.key || "").toLowerCase() === "u"
      );
    }}

    function clearTextareaLikeConsole(textarea) {{
      if (!textarea) {{
        return false;
      }}
      textarea.value = "";
      textarea.dispatchEvent(new Event("input", {{ bubbles: true }}));
      try {{
        textarea.setSelectionRange(0, 0);
      }} catch (_) {{
        // Some mobile keyboards do not expose selection APIs after input mutation.
      }}
      return true;
    }}

    function maybeKillInputLine(event) {{
      if (!isConsoleLineKillShortcut(event)) {{
        return false;
      }}
      const active = document.activeElement;
      const target = event ? event.target : null;
      const textarea = active === el.promptInput || target === el.promptInput
        ? el.promptInput
        : active === el.tmuxInput || target === el.tmuxInput
          ? el.tmuxInput
          : null;
      if (!textarea) {{
        return false;
      }}
      event.preventDefault();
      event.stopPropagation();
      return clearTextareaLikeConsole(textarea);
    }}

    function replyShortcutDescriptors(sourcePrompt, body, options = {{}}) {{
      const seed = messageVariantSeed(`${{sourcePrompt || ""}}\\n${{body || ""}}`);
      const kinds = Array.isArray(options.kinds) && options.kinds.length
        ? options.kinds
        : selectDynamicReplyActionKinds(sourcePrompt, body, options);
      return kinds.map((kind, index) => replyShortcutDescriptor(kind, seed, index))
        .filter((item) => item && item.label && (item.prompt || item.mode === "invoke"));
    }}

    function buildReplyShortcutGroup(sourcePrompt, body, options = {{}}) {{
      const descriptors = replyShortcutDescriptors(
        sourcePrompt,
        body,
        options
      );
      if (!descriptors.length) {{
        return null;
      }}
      const group = document.createElement("div");
      group.className = String(options.className || "reply-shortcuts");
      const buttonClass = String(options.buttonClass || "ghost inline-action reply-shortcut");
      for (const descriptor of descriptors) {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = buttonClass;
        button.dataset.icon = descriptor.icon;
        button.dataset.actionKind = descriptor.kind || "";
        button.dataset.suggestion = descriptor.prompt || "";
        button.textContent = descriptor.label;
        button.title = descriptor.prompt || descriptor.label;
        button.addEventListener("click", () => {{
          if (descriptor.mode === "invoke" && descriptor.action === "unwind_latest_turn") {{
            void unwindLatestTurn(button);
          }} else if (options.submitImmediately) {{
            submitPromptSuggestion(descriptor.prompt);
          }} else {{
            applyPromptSuggestion(button.dataset.suggestion || "");
          }}
          if (options.closeMenus !== false) {{
            closeMessageActionMenus();
          }}
        }});
        group.appendChild(button);
      }}
      return group;
    }}

    function isConsoleAction(snapshot) {{
      return /^(tmux|relay)-/.test(String(snapshot.last_action || ""));
    }}

    function summarizeServices(services) {{
      const items = Array.isArray(services) ? services : [];
      if (!items.length) return "Runtime state unavailable";
      const problems = items.filter((item) => String(item.state || "").toLowerCase() !== "active");
      if (!problems.length) return "All services healthy";
      if (problems.length === 1) {{
        return `${{problems[0].name}} ${{problems[0].state}}`;
      }}
      return `${{problems.length}} runtime issues`;
    }}

    function contextMeterState(snapshot) {{
      const usage = snapshot && typeof snapshot === "object" ? snapshot.usage || {{}} : {{}};
      const currentThread = usage && typeof usage === "object" ? usage.current_thread || {{}} : {{}};
      const totals = usage && typeof usage === "object" ? usage.totals || {{}} : {{}};
      const recent = usage && typeof usage === "object" ? usage.last_24h || {{}} : {{}};
      const threadScoped = Number(currentThread.turns || 0) > 0 || Number(currentThread.total_tokens || 0) > 0;
      const primary = threadScoped ? currentThread : totals;
      const historyTurns = Array.isArray(snapshot?.history) ? snapshot.history.length : 0;
      const pendingTurn = snapshot?.pending && snapshot?.running_prompt ? 1 : 0;
      const rawTurnCount = Number(primary.turns || 0);
      const trackedTurns = Number.isFinite(rawTurnCount) && rawTurnCount > 0 ? rawTurnCount : 0;
      const totalTurns = Math.max(trackedTurns, historyTurns + pendingTurn);
      const rawTokenCount = Number(primary.total_tokens || 0);
      const totalTokens = Number.isFinite(rawTokenCount) && rawTokenCount > 0 ? rawTokenCount : 0;
      const rawRecentTokens = Number(recent.total_tokens || 0);
      const recentTokens = Number.isFinite(rawRecentTokens) && rawRecentTokens > 0 ? rawRecentTokens : 0;
      const rawQueueDepth = Number(snapshot?.queue_depth || 0);
      const queueDepth = Number.isFinite(rawQueueDepth) && rawQueueDepth > 0 ? Math.round(rawQueueDepth) : 0;
      const hidden = totalTurns <= 0 && totalTokens <= 0 && queueDepth <= 0;

      const tokenLoad = totalTokens > 0 ? totalTokens / 90000 : 0;
      const turnLoad = totalTurns > 0 ? totalTurns / 26 : 0;
      const queueLoad = queueDepth > 0 ? Math.min(1, 0.18 + (queueDepth * 0.18)) : 0;
      const load = Math.max(tokenLoad, turnLoad, queueLoad);

      let tone = "ok";
      let status = "Fresh";
      let hint = "Plenty of room before a compact/save is likely useful.";
      if (load >= 0.92) {{
        tone = "danger";
        status = "Save soon";
        hint = "Good point to compact/save before the thread gets unwieldy.";
      }} else if (load >= 0.55) {{
        tone = "warn";
        status = "Watch";
        hint = "Session is getting heavier; compact soon if the thread starts to sprawl.";
      }}

      const parts = [];
      if (totalTurns > 0) parts.push(`${{formatCount(totalTurns)}}t`);
      if (totalTokens > 0) parts.push(`${{formatCompactMetric(totalTokens)}} tok`);
      if (queueDepth > 0) parts.push(`+${{queueDepth}}`);
      const value = parts.join(" · ") || "Fresh";

      const titleParts = [`${{status}} context load`];
      titleParts.push(
        totalTurns > 0
          ? `${{formatCount(totalTurns)}} ${{threadScoped ? "current-thread" : "tracked"}} turn${{totalTurns === 1 ? "" : "s"}}`
          : "No tracked turns yet"
      );
      if (totalTokens > 0) {{
        titleParts.push(`${{formatCount(totalTokens)}} ${{threadScoped ? "current-thread" : "tracked"}} tokens`);
      }}
      if (recentTokens > 0 && recentTokens !== totalTokens) {{
        titleParts.push(`${{formatCount(recentTokens)}} tokens in the last 24h`);
      }}
      if (queueDepth > 0) {{
        titleParts.push(`${{queueDepth}} queued`);
      }}
      titleParts.push("Heuristic only; use it as a save/compact hint, not an exact context ceiling.");
      titleParts.push(hint);

      return {{
        hidden,
        tone,
        status,
        value,
        fill: hidden ? 0 : Math.max(6, Math.min(100, Math.round(load * 100))),
        title: titleParts.join(" · "),
      }};
    }}

    function renderContextMeter(snapshot) {{
      if (!el.contextMeterChip || !el.contextMeterStatus || !el.contextMeterValue) {{
        return;
      }}
      const context = contextMeterState(snapshot);
      const renderKey = JSON.stringify({{
        hidden: Boolean(context.hidden),
        tone: String(context.tone || ""),
        status: String(context.status || ""),
        value: String(context.value || ""),
        fill: Number(context.fill || 0),
        title: String(context.title || ""),
        pending: Boolean(snapshot?.pending),
      }});
      if (state.renderCache.contextMeter === renderKey) {{
        return;
      }}
      state.renderCache.contextMeter = renderKey;
      el.contextMeterChip.hidden = context.hidden;
      el.contextMeterChip.dataset.loadTone = context.tone;
      el.contextMeterChip.title = context.title;
      el.contextMeterChip.style.setProperty("--context-load", `${{context.fill}}%`);
      el.contextMeterStatus.textContent = context.status;
      el.contextMeterValue.textContent = context.value;
      el.contextMeterChip.setAttribute("aria-label", context.title);
      const showSaveAction = !context.hidden && !snapshot?.pending && (context.tone === "warn" || context.tone === "danger");
      const saveLabel = context.tone === "danger" ? "Save now" : "Save";
      const savePrompt = buildContextSavePrompt(context);
      for (const button of [el.contextSaveButton, el.contextSaveMenuButton]) {{
        if (!button) {{
          continue;
        }}
        button.hidden = !showSaveAction;
        button.textContent = saveLabel;
        button.dataset.saveTone = showSaveAction ? context.tone : "";
        button.dataset.suggestion = savePrompt;
        button.title = showSaveAction
          ? `${{context.title}} · Ask the agent to compact/save this thread.`
          : "Save/compact this thread";
        button.setAttribute("aria-label", button.title);
      }}
    }}

    function usageCapsuleState(snapshot) {{
      const usage = snapshot && typeof snapshot === "object" ? snapshot.usage || {{}} : {{}};
      const recent = usage && typeof usage === "object" ? usage.last_24h || {{}} : {{}};
      const currentThread = usage && typeof usage === "object" ? usage.current_thread || {{}} : {{}};
      const recentTokens = Math.max(0, Number(recent.total_tokens || 0));
      const recentTurns = Math.max(0, Number(recent.turns || 0));
      const threadTokens = Math.max(0, Number(currentThread.total_tokens || 0));
      const threadTurns = Math.max(0, Number(currentThread.turns || 0));
      let tone = "ok";
      if (recentTokens >= 220000) {{
        tone = "alert";
      }} else if (recentTokens >= 90000) {{
        tone = "warn";
      }}
      return {{
        tone,
        value: recentTokens > 0 ? `${{formatCompactMetric(recentTokens)}} tok` : "Quiet",
        meta: recentTurns > 0 ? `24h · ${{formatCount(recentTurns)}}t` : "24h · no turns",
        title: [
          recentTokens > 0
            ? `${{formatCount(recentTokens)}} tokens in the last 24h`
            : "No tracked usage in the last 24h",
          threadTokens > 0
            ? `${{formatCount(threadTokens)}} tokens across ${{formatCount(threadTurns || 0)}} current-thread turns`
            : "No tracked usage in this thread yet",
        ].join(" · "),
      }};
    }}

    function normalizeTransportLabel(label) {{
      const text = String(label || "").trim();
      if (text) {{
        return text;
      }}
      return state.streamConnected ? "Live" : "Polling";
    }}

    function backgroundWorkState(snapshot) {{
      const issue = runtimeIssue(snapshot);
      const queueDepth = Math.max(0, Number(snapshot?.queue_depth || 0));
      const pending = Boolean(snapshot?.pending);
      const hiddenTab = Boolean(document.hidden);
      const launchedTask = inferBackgroundTask(snapshot);
      const transportLabel = normalizeTransportLabel(
        state.transportLabel || el.transportStateMenu?.textContent || ""
      );
      const transportLower = transportLabel.toLowerCase();
      const waitingTransport = transportLower.includes("waiting");
      const transportShort = hiddenTab
        ? (waitingTransport ? "offscreen · waiting" : "offscreen")
        : transportLower.startsWith("live")
          ? (waitingTransport ? "live · waiting" : "live")
          : transportLower.startsWith("polling")
            ? (waitingTransport ? "polling · waiting" : "polling")
            : transportLower.startsWith("background")
              ? (waitingTransport ? "background · waiting" : "background")
              : transportLower.startsWith("reconnecting")
                ? "reconnecting"
                : transportLower.startsWith("offline")
                  ? "offline"
              : transportLower.startsWith("auth")
                    ? "auth"
                    : transportLabel;
      if (issue) {{
        return {{
          hidden: false,
          tone: issue.tone,
          value: issue.label,
          meta: transportShort,
          title: [issue.summary, `Transport · ${{transportLabel}}`]
            .filter(Boolean)
            .join(" · "),
          monitor: null,
        }};
      }}
      const recentConsole = recentConsoleAction(snapshot);
      if (pending) {{
        const stage = inferWorkingStage(snapshot);
        const elapsed = activityElapsed(snapshot);
        const metaParts = [
          stage.step || "Reply",
          elapsed > 0 ? formatElapsedCompact(elapsed) : "",
          queueDepth > 0 ? `+${{queueDepth}} queued` : "",
          transportShort,
        ].filter(Boolean);
        return {{
          hidden: false,
          tone: "active",
          value: "1 running",
          meta: metaParts.join(" · "),
          title: [
            "Background worker is actively handling a turn.",
            stage.note || "Codex is in the middle of the reply.",
            elapsed > 0 ? `${{formatElapsedCompact(elapsed)}} in flight` : "",
            queueDepth > 0
              ? `${{queueDepth}} queued behind the current turn`
              : "",
            `Transport · ${{transportLabel}}`,
          ]
            .filter(Boolean)
            .join(" · "),
        }};
      }}
      if (queueDepth > 0) {{
        return {{
          hidden: false,
          tone: "warn",
          value: queueDepth === 1 ? "1 queued" : `${{formatCount(queueDepth)}} queued`,
          meta: [transportShort, "waiting next"].filter(Boolean).join(" · "),
          title: [
            queueDepth === 1
              ? "One prompt is waiting behind the current turn."
              : `${{queueDepth}} prompts are waiting behind the current turn.`,
            `Transport · ${{transportLabel}}`,
          ].join(" · "),
        }};
      }}
      if (launchedTask) {{
        return {{
          hidden: false,
          tone: "active",
          value: "Job live",
          meta: launchedTask.meta,
          title: [
            launchedTask.title,
            launchedTask.detail,
            `Transport · ${{transportLabel}}`,
          ].filter(Boolean).join(" · "),
          monitor: {{
            title: "Background run active",
            detail: [launchedTask.title, launchedTask.detail].filter(Boolean).join(" · "),
            key: launchedTask.key,
            action: "peek",
          }},
        }};
      }}
      if (recentConsole) {{
        return {{
          hidden: false,
          tone: "warn",
          value: "Console",
          meta: [snapshot.last_action_detail || "Recent operator action", transportShort]
            .filter(Boolean)
            .join(" · "),
          title: [
            snapshot.last_action_detail || "Recent operator action completed.",
            snapshot.last_action_at ? `Last touched ${{formatTs(snapshot.last_action_at)}}` : "",
            `Transport · ${{transportLabel}}`,
          ]
            .filter(Boolean)
            .join(" · "),
        }};
      }}
      if (
        hiddenTab
        || transportLower.startsWith("polling")
        || transportLower.startsWith("background")
        || transportLower.startsWith("reconnecting")
        || transportLower.startsWith("offline")
      ) {{
        const tone = transportLower.startsWith("offline")
          ? "alert"
          : transportLower.startsWith("reconnecting")
            ? "warn"
            : hiddenTab
              ? "warn"
              : "ok";
        const value = hiddenTab
          ? "Offscreen"
          : transportLower.startsWith("polling")
            ? "Polling"
            : transportLower.startsWith("background")
              ? "Background"
              : transportLower.startsWith("reconnecting")
                ? "Reconnecting"
                : "Offline";
        const meta = hiddenTab
          ? (waitingTransport ? "watching · waiting" : "watching")
          : transportShort;
        return {{
          hidden: false,
          tone,
          value,
          meta,
          title: [
            hiddenTab
              ? "This tab is in the background; live updates are backed off."
              : "The console is using a lighter background transport path.",
            `Transport · ${{transportLabel}}`,
          ]
            .filter(Boolean)
            .join(" · "),
        }};
      }}
      return {{
        hidden: true,
        tone: "ok",
        value: "Quiet",
        meta: "No background work",
        title: "No background work is active right now.",
        monitor: null,
      }};
    }}

    function normalizeKpiTone(value) {{
      const clean = String(value || "").trim().toLowerCase();
      if (clean === "danger" || clean === "alert") return "alert";
      if (clean === "watch") return "warn";
      if (["ok", "warn", "active"].includes(clean)) return clean;
      return "ok";
    }}

    function parseKpiTimestampSeconds(value) {{
      if (value === null || value === undefined || value === "") return 0;
      const numeric = Number(value);
      if (Number.isFinite(numeric) && numeric > 0) {{
        return numeric > 100000000000 ? Math.round(numeric / 1000) : Math.round(numeric);
      }}
      const parsed = Date.parse(String(value));
      if (Number.isFinite(parsed) && parsed > 0) {{
        return Math.round(parsed / 1000);
      }}
      return 0;
    }}

    function normalizeResourceKpiMeters(snapshot) {{
      const resource = snapshot && typeof snapshot === "object" ? snapshot.resource_meter || {{}} : {{}};
      const rawMeters = Array.isArray(resource?.kpi_meters) ? resource.kpi_meters : [];
      const nowSeconds = Date.now() / 1000;
      return rawMeters
        .map((item, index) => {{
          if (!item || typeof item !== "object") return null;
          const label = String(item.label || "").trim();
          if (!label) return null;
          const unit = String(item.unit || "").trim();
          const source = String(item.source || "").trim();
          const detail = String(item.detail || "").trim();
          const updatedAt = parseKpiTimestampSeconds(item.updated_at);
          const staleAfter = Math.max(0, Number(item.stale_after_seconds || 0));
          const stale = updatedAt > 0 && staleAfter > 0 && nowSeconds - updatedAt > staleAfter;
          let tone = normalizeKpiTone(item.tone);
          if (stale && (tone === "ok" || tone === "active")) {{
            tone = "warn";
          }}
          const rawValue = item.value === null || item.value === undefined || item.value === ""
            ? "n/a"
            : String(item.value);
          const metaParts = [];
          if (unit) metaParts.push(unit);
          if (source) metaParts.push(source);
          if (stale) {{
            metaParts.push("stale");
          }} else if (updatedAt > 0 && staleAfter > 0) {{
            metaParts.push("fresh");
          }}
          const titleParts = [
            detail || `${{label}}: ${{rawValue}}`,
            unit ? `Unit · ${{unit}}` : "",
            source ? `Source · ${{source}}` : "",
            updatedAt > 0 ? `Updated · ${{formatTs(updatedAt)}}` : "",
            stale ? "Source data is stale." : "",
          ].filter(Boolean);
          return {{
            id: String(item.id || `kpi-${{index}}`),
            label,
            value: rawValue,
            meta: metaParts.join(" · "),
            tone,
            title: titleParts.join(" · "),
            action: "system",
          }};
        }})
        .filter(Boolean)
        .slice(0, 4);
    }}

    function buildStatusCapsules(snapshot) {{
      const services = Array.isArray(snapshot?.services) ? snapshot.services : [];
      const failedServices = services.filter((item) => {{
        const clean = String(item?.state || "").toLowerCase();
        return clean && clean !== "active";
      }});
      const transitioning = failedServices.filter((item) => {{
        const clean = String(item?.state || "").toLowerCase();
        return clean === "activating" || clean === "deactivating";
      }});
      const hostTone = failedServices.length
        ? (failedServices.length === transitioning.length ? "warn" : "alert")
        : "ok";
      const hostValue = failedServices.length
        ? `${{formatCount(failedServices.length)}} issue${{failedServices.length === 1 ? "" : "s"}}`
        : services.length
          ? `${{services.length}}/${{services.length}} up`
          : "No data";
      const hostMeta = failedServices.length
        ? summarizeServices(services)
        : services.length
          ? "Host services healthy"
          : "Host service state unavailable";

      const issue = runtimeIssue(snapshot);
      let runtimeTone = "ok";
      let runtimeValue = "Ready";
      let runtimeMeta = responseProfileText(snapshot?.last_speed, snapshot?.last_detail);
      if (issue) {{
        runtimeTone = issue.tone === "queue" ? "warn" : "alert";
        runtimeValue = issue.label || issue.title || "Attention";
        runtimeMeta = issue.summary || "Runtime needs operator attention.";
      }} else if (snapshot?.pending) {{
        runtimeTone = "active";
        runtimeValue = "Working";
        runtimeMeta = responseProfileText(snapshot?.running_speed, snapshot?.running_detail);
      }} else if (Number(snapshot?.queue_depth || 0) > 0) {{
        runtimeTone = "warn";
        runtimeValue = "Queued";
        runtimeMeta = Number(snapshot?.queue_depth || 0) === 1
          ? "1 prompt waiting"
          : `${{formatCount(snapshot?.queue_depth || 0)}} prompts waiting`;
      }} else if (snapshot?.last_finished_at) {{
        runtimeValue = "Ready";
        runtimeMeta = `Last · ${{formatTs(snapshot.last_finished_at)}}`;
      }}

      const unread = unreadNoticeCount();
      const alertTone = issue ? "alert" : unread > 0 ? "warn" : "ok";
      const alertValue = issue
        ? (issue.title || "Attention")
        : unread > 0
          ? `${{formatCount(unread)}} unread`
          : "Clear";
      const alertMeta = issue
        ? (issue.summary || "Open alerts or system for details.")
        : unread > 0
          ? "Recent notices waiting"
          : "No fresh notices";

      const background = backgroundWorkState(snapshot);

      const capsules = [
        {{
          id: "host",
          label: "Host",
          value: hostValue,
          meta: hostMeta,
          tone: hostTone,
          title: `${{hostValue}} · ${{hostMeta}}`,
          action: "system",
        }},
        {{
          id: "runtime",
          label: "Runtime",
          value: runtimeValue,
          meta: runtimeMeta,
          tone: runtimeTone,
          title: `${{runtimeValue}} · ${{runtimeMeta}}`,
          action: "system",
        }},
      ];

      if (!background.hidden) {{
        const backgroundAction = (
          snapshot?.pending
          || Number(snapshot?.queue_depth || 0) > 0
          || recentConsoleAction(snapshot)
        )
          ? "peek"
          : "system";
        capsules.push({{
          id: "background",
          label: "Background",
          value: background.value,
          meta: background.meta,
          tone: background.tone,
          title: background.title,
          action: background.tone === "alert" ? "system" : backgroundAction,
        }});
      }}

      capsules.push({{
        id: "alerts",
        label: "Alerts",
        value: alertValue,
        meta: alertMeta,
        tone: alertTone,
        title: `${{alertValue}} · ${{alertMeta}}`,
        action: issue ? "system" : "notices",
      }});

      const adapterCapsules = normalizeResourceKpiMeters(snapshot);
      if (adapterCapsules.length) {{
        const adapterIds = new Set(adapterCapsules.map((item) => String(item.id || "")));
        const fallbackCapsules = capsules.filter((item) => !adapterIds.has(String(item.id || "")));
        return [...adapterCapsules, ...fallbackCapsules].slice(0, 4);
      }}
      return capsules.slice(0, 4);
    }}

    function renderStatusCapsules(snapshot) {{
      if (!el.kpiStrip) {{
        return;
      }}
      const capsules = buildStatusCapsules(snapshot);
      const renderKey = JSON.stringify(capsules);
      if (state.renderCache.capsules === renderKey) {{
        return;
      }}
      state.renderCache.capsules = renderKey;
      el.kpiStrip.hidden = !capsules.length;
      if (el.chatActivityChip) {{
        const activityText = String(el.chatActivityChip.textContent || "").trim();
        el.chatActivityChip.hidden = capsules.length > 0 || !activityText;
      }}
      el.kpiStrip.innerHTML = "";
      for (const item of capsules) {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ghost kpi-capsule";
        button.dataset.tone = String(item.tone || "ok");
        button.dataset.kpiAction = String(item.action || "system");
        button.dataset.kpiId = String(item.id || "");
        button.title = String(item.title || "");
        button.setAttribute("aria-label", String(item.title || item.value || item.label || "Status"));
        button.innerHTML = `
          <span class="kpi-capsule-label">${{escapeHtml(String(item.label || ""))}}</span>
          <span class="kpi-capsule-value">${{escapeHtml(String(item.value || ""))}}</span>
          <span class="kpi-capsule-meta">${{escapeHtml(String(item.meta || ""))}}</span>
        `;
        el.kpiStrip.appendChild(button);
      }}
    }}

    function renderSystemRuntimeMetrics(snapshot) {{
      if (!el.systemRuntimeMetrics) {{
        return;
      }}
      const usage = snapshot && typeof snapshot === "object" ? snapshot.usage || {{}} : {{}};
      const recent = usage && typeof usage === "object" ? usage.last_24h || {{}} : {{}};
      const currentThread = usage && typeof usage === "object" ? usage.current_thread || {{}} : {{}};
      const unread = unreadNoticeCount();
      const issue = runtimeIssue(snapshot);
      const background = backgroundWorkState(snapshot);
      const metrics = [
        {{
          label: "Thread",
          value: Math.max(0, Number(currentThread.total_tokens || 0)) > 0
            ? `${{formatCompactMetric(currentThread.total_tokens || 0)}} tok`
            : "Fresh",
          meta: Math.max(0, Number(currentThread.turns || 0)) > 0
            ? `${{formatCount(currentThread.turns || 0)}} turn${{Number(currentThread.turns || 0) === 1 ? "" : "s"}}`
            : "No thread turns",
        }},
        {{
          label: "24h burn",
          value: Math.max(0, Number(recent.total_tokens || 0)) > 0
            ? `${{formatCompactMetric(recent.total_tokens || 0)}} tok`
            : "Quiet",
          meta: Math.max(0, Number(recent.turns || 0)) > 0
            ? `${{formatCount(recent.turns || 0)}} turn${{Number(recent.turns || 0) === 1 ? "" : "s"}}`
            : "No 24h turns",
        }},
        {{
          label: background.hidden ? "Queue" : "Background",
          value: background.hidden
            ? Number(snapshot?.queue_depth || 0) > 0
              ? `${{formatCount(snapshot.queue_depth || 0)}} queued`
              : snapshot?.pending
                ? "Running"
                : "Clear"
            : background.value,
          meta: background.hidden
            ? snapshot?.pending
              ? responseProfileText(snapshot?.running_speed, snapshot?.running_detail)
              : "No backlog"
            : background.meta,
        }},
        {{
          label: "Alerts",
          value: issue
            ? (issue.title || "Attention")
            : unread > 0
              ? `${{formatCount(unread)}} unread`
              : "Clear",
          meta: issue
            ? (issue.summary || "Needs operator attention")
            : "Notifications and notices",
        }},
      ];
      const renderKey = JSON.stringify(metrics);
      if (state.renderCache.systemMetrics === renderKey) {{
        return;
      }}
      state.renderCache.systemMetrics = renderKey;
      el.systemRuntimeMetrics.innerHTML = metrics.map((item) => `
        <div class="system-runtime-metric">
          <div class="system-runtime-metric-label">${{escapeHtml(String(item.label || ""))}}</div>
          <div class="system-runtime-metric-value">${{escapeHtml(String(item.value || ""))}}</div>
          <div class="system-runtime-metric-meta">${{escapeHtml(String(item.meta || ""))}}</div>
        </div>
      `).join("");
    }}

    function messageRoleIcon(role, label) {{
      const cleanRole = String(role || "").toLowerCase();
      if (cleanRole.includes("pending")) return "…";
      if (cleanRole.includes("queued")) return "Q";
      if (cleanRole.includes("error")) return "!";
      if (cleanRole.includes("assistant")) return AGENT_MARK;
      if (cleanRole.includes("user")) return "ME";
      return entityMarkForLabel(label || role || "Console");
    }}

    function nodeInUi(node) {{
      if (!node) return false;
      const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
      return Boolean(
        element && element.closest("#conversation, .raw-view, pre, textarea")
      );
    }}

    function selectionActiveInUi() {{
      const selection = window.getSelection ? window.getSelection() : null;
      if (!selection || selection.isCollapsed) {{
        return false;
      }}
      return nodeInUi(selection.anchorNode) || nodeInUi(selection.focusNode);
    }}

    function focusPromptInputAtEnd() {{
      el.promptInput.focus({{ preventScroll: true }});
      const length = el.promptInput.value.length;
      try {{
        el.promptInput.setSelectionRange(length, length);
      }} catch (_) {{
        // Some mobile keyboards do not expose selection APIs after focus.
      }}
    }}

    function insertTextIntoPrompt(text, options = {{}}) {{
      const value = String(text ?? "");
      if (!value) {{
        return false;
      }}
      const placeAtEnd = Boolean(options.placeAtEnd);
      el.promptInput.focus({{ preventScroll: true }});
      let start = el.promptInput.value.length;
      let end = el.promptInput.value.length;
      try {{
        if (!placeAtEnd) {{
          start = Number.isInteger(el.promptInput.selectionStart)
            ? el.promptInput.selectionStart
            : el.promptInput.value.length;
          end = Number.isInteger(el.promptInput.selectionEnd)
            ? el.promptInput.selectionEnd
            : start;
        }}
        el.promptInput.setRangeText(value, start, end, "end");
      }} catch (_) {{
        const prefix = el.promptInput.value.slice(0, start);
        const suffix = el.promptInput.value.slice(end);
        el.promptInput.value = `${{prefix}}${{value}}${{suffix}}`;
        try {{
          const cursor = prefix.length + value.length;
          el.promptInput.setSelectionRange(cursor, cursor);
        }} catch (_) {{
          // Ignore selection repair failures on constrained keyboards.
        }}
      }}
      el.promptInput.dispatchEvent(new Event("input", {{ bubbles: true }}));
      return true;
    }}

    async function copyText(value, button) {{
      const original = button.textContent;
      try {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          await navigator.clipboard.writeText(value);
        }} else {{
          const helper = document.createElement("textarea");
          helper.value = value;
          helper.setAttribute("readonly", "");
          helper.style.position = "fixed";
          helper.style.opacity = "0";
          document.body.appendChild(helper);
          helper.select();
          document.execCommand("copy");
          helper.remove();
        }}
        button.textContent = "Copied";
      }} catch (_) {{
        button.textContent = "Press Ctrl+C";
      }}
      window.setTimeout(() => {{
        button.textContent = original;
      }}, 1200);
    }}

    function normalizeCopiedText(value) {{
      return String(value ?? "")
        .replace(/\u00a0/g, " ")
        .replace(/\\r\\n?/g, "\\n");
    }}

    function plainTextFromNode(node) {{
      if (!node || !(node instanceof HTMLElement)) {{
        return "";
      }}
      const value = typeof node.innerText === "string"
        ? node.innerText
        : (node.textContent || "");
      return normalizeCopiedText(value);
    }}

    function plainTextFromRenderedMessage(article, fallback = "") {{
      if (!article || !(article instanceof HTMLElement)) {{
        return normalizeCopiedText(fallback);
      }}
      const parts = [];
      const bodyNode = article.querySelector(".message-body");
      const collapsedDetail = bodyNode
        ? bodyNode.querySelector(".collapsed-prompt-body")
        : null;
      if (collapsedDetail && collapsedDetail.hidden) {{
        return normalizeCopiedText(fallback);
      }}
      const bodyText = plainTextFromNode(bodyNode);
      if (bodyText) {{
        parts.push(bodyText);
      }}
      article.querySelectorAll(".inline-file-preview-text").forEach((node) => {{
        const text = plainTextFromNode(node);
        if (text) {{
          parts.push(text);
        }}
      }});
      if (!parts.length) {{
        return normalizeCopiedText(fallback);
      }}
      return parts.join("\\n\\n");
    }}

    function selectionPlainTextFromUi() {{
      const selection = window.getSelection ? window.getSelection() : null;
      if (!selection || selection.isCollapsed) {{
        return "";
      }}
      if (!(nodeInUi(selection.anchorNode) || nodeInUi(selection.focusNode))) {{
        return "";
      }}
      return normalizeCopiedText(selection.toString());
    }}

    function canConsumeScroll(node, deltaY) {{
      if (!node || !(node instanceof HTMLElement)) {{
        return false;
      }}
      const limit = node.scrollHeight - node.clientHeight;
      if (limit <= 1) {{
        return false;
      }}
      if (deltaY < 0) {{
        return node.scrollTop > 0;
      }}
      return node.scrollTop < limit - 1;
    }}

    function chatScrollRoot() {{
      return el.workspace || el.chatMain;
    }}

    function latestConversationNode() {{
      if (!el.conversation) {{
        return null;
      }}
      const items = el.conversation.querySelectorAll(".message:not(.empty)");
      return items.length ? items[items.length - 1] : null;
    }}

    function isNearConversationBottom() {{
      const scroller = chatScrollRoot();
      return scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 96;
    }}

    function updateScrollChrome() {{
      const scroller = chatScrollRoot();
      document.body.classList.toggle("chat-scrolled", scroller.scrollTop > 28);
    }}

    function scrollConversationToBottom(force = false) {{
      if (!force && state.historyExpanded) {{
        return;
      }}
      window.requestAnimationFrame(() => {{
        const scroller = chatScrollRoot();
        const latest = latestConversationNode();
        if (state.keyboardOpen && scroller) {{
          stickConversationToBottom();
        }} else if (latest && typeof latest.scrollIntoView === "function") {{
          latest.scrollIntoView({{ block: "end", inline: "nearest" }});
        }} else {{
          scroller.scrollTop = scroller.scrollHeight;
        }}
        state.userPinnedHistory = false;
        updateScrollChrome();
        el.jumpLatestButton.classList.remove("visible");
      }});
    }}

    function restoreConversationViewport(scrollTop, showJump = false) {{
      window.requestAnimationFrame(() => {{
        const scroller = chatScrollRoot();
        if (!scroller) {{
          return;
        }}
        const maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
        scroller.scrollTop = Math.max(0, Math.min(Number(scrollTop || 0), maxTop));
        state.userPinnedHistory = !isNearConversationBottom();
        updateScrollChrome();
        el.jumpLatestButton.classList.toggle(
          "visible",
          !state.historyExpanded && Boolean(showJump || state.userPinnedHistory)
        );
      }});
    }}

    function settleViewportToLiveEdge(force = false) {{
      if (!force && state.initialViewportSettleDone) {{
        return;
      }}
      window.requestAnimationFrame(() => {{
        const scroller = chatScrollRoot();
        const latest = latestConversationNode();
        if (state.keyboardOpen && scroller) {{
          stickConversationToBottom();
        }} else if (latest && typeof latest.scrollIntoView === "function") {{
          latest.scrollIntoView({{ block: "end", inline: "nearest" }});
        }} else if (scroller) {{
          const maxTop = scroller.scrollHeight - scroller.clientHeight;
          if (maxTop > 0) {{
            scroller.scrollTop = maxTop;
          }}
        }}
        state.initialViewportSettleDone = true;
      }});
    }}

    function expandHistoryFromScroll() {{
      if (state.historyExpanded || state.hiddenHistoryTurns <= 0) {{
        return false;
      }}
      const scroller = chatScrollRoot();
      const previousHeight = scroller.scrollHeight;
      state.historyExpanded = true;
      render(state.snapshot);
      const newHeight = scroller.scrollHeight;
      scroller.scrollTop = Math.max(0, newHeight - previousHeight + 28);
      return true;
    }}

    function renderLinkStrip(container, urls) {{
      container.innerHTML = "";
      if (!urls.length) {{
        container.hidden = true;
        return;
      }}
      container.hidden = false;
      for (const entry of urls) {{
        const url = typeof entry === "string" ? entry : String(entry?.url || "");
        if (!url) {{
          continue;
        }}
        const label = typeof entry === "string"
          ? formatUrlLabel(url)
          : String(entry?.label || formatUrlLabel(url));
        const row = document.createElement("div");
        row.className = "link-chip-row";

        const link = document.createElement("a");
        link.className = "link-chip";
        link.href = url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = label;
        link.title = url;
        row.appendChild(link);

        const copyButton = document.createElement("button");
        copyButton.type = "button";
        copyButton.className = "ghost link-copy-button";
        copyButton.dataset.icon = "⎘";
        copyButton.textContent = "Copy";
        copyButton.addEventListener("click", () => copyText(url, copyButton));
        row.appendChild(copyButton);

        container.appendChild(row);
      }}
    }}

    function runtimeSupportLinks(value) {{
      if (!containsUsageLimitError(value)) {{
        return [];
      }}
      return [
        {{
          label: "Billing",
          url: "https://platform.openai.com/settings/organization/billing/overview",
        }},
        {{
          label: "Limits",
          url: "https://platform.openai.com/settings/organization/limits",
        }},
      ];
    }}

    function noticeToneIcon(tone) {{
      if (tone === "active") return "◎";
      if (tone === "alert") return "!";
      if (tone === "queue") return "◔";
      if (tone === "console") return "⌘";
      return "⇄";
    }}

    function noticeToneLabel(tone) {{
      if (tone === "active") return "Background";
      if (tone === "alert") return "Attention";
      if (tone === "queue") return "Queue";
      if (tone === "console") return "Console";
      return "Info";
    }}

    function noticeActionForItem(item) {{
      const explicit = String(item?.action || "").trim();
      if (explicit) {{
        return explicit;
      }}
      const tone = String(item?.tone || "").trim();
      const title = String(item?.title || item?.label || "").toLowerCase();
      if (tone === "alert") return "system";
      if (tone === "queue" || tone === "active") return "peek";
      if (tone === "console") return "system";
      if (title.includes("reply")) return "latest";
      return "notices";
    }}

    function noticeActionLabel(action) {{
      if (action === "system") return "Open system details";
      if (action === "peek") return "Open activity details";
      if (action === "latest") return "Jump to latest reply";
      if (action === "prompt") return "Focus the prompt";
      if (action === "relay") return "Open relay targets";
      return "Open notifications";
    }}

    function noticeActivationLabel(item) {{
      const title = String(item?.title || item?.label || "Notification").trim();
      const action = noticeActionForItem(item);
      return `${{title}}. ${{noticeActionLabel(action)}}.`;
    }}

    function eventStartedInsideInteractiveTarget(event, container) {{
      const target = event?.target;
      if (!target || target === container) {{
        return false;
      }}
      return Boolean(target.closest("a, button, input, select, textarea, summary, [data-action]"));
    }}

    function performNoticeAction(action) {{
      const clean = String(action || "notices").trim();
      if (clean === "system") {{
        setSystemOpen(true);
        return;
      }}
      if (clean === "peek") {{
        setNoticesOpen(false);
        if (buildActivityInsight(state.snapshot)) {{
          state.activityPeekOpen = true;
          renderActivityStrip(state.snapshot);
        }} else {{
          setSystemOpen(true);
        }}
        return;
      }}
      if (clean === "latest") {{
        setNoticesOpen(false);
        jumpToLatestConversation();
        return;
      }}
      if (clean === "prompt") {{
        setNoticesOpen(false);
        focusPromptInputAtEnd();
        return;
      }}
      if (clean === "relay") {{
        if (openLatestRelayTargets()) {{
          setNoticesOpen(false);
          return;
        }}
        el.statusMessage.textContent = "No linked-bot handoff is available in this reply yet.";
        return;
      }}
      setNoticesOpen(true);
    }}

    function attachNoticeActivation(node, item) {{
      if (!node) {{
        return;
      }}
      const action = noticeActionForItem(item);
      node.dataset.noticeAction = action;
      node.setAttribute("role", "button");
      node.tabIndex = 0;
      node.setAttribute("aria-label", noticeActivationLabel(item));
      node.title = noticeActionLabel(action);
      node.addEventListener("click", (event) => {{
        if (eventStartedInsideInteractiveTarget(event, node)) {{
          return;
        }}
        performNoticeAction(action);
      }});
      node.addEventListener("keydown", (event) => {{
        if (eventStartedInsideInteractiveTarget(event, node)) {{
          return;
        }}
        if (event.key !== "Enter" && event.key !== " ") {{
          return;
        }}
        event.preventDefault();
        performNoticeAction(action);
      }});
    }}

    function backgroundMonitorNotice(snapshot = state.snapshot) {{
      const background = backgroundWorkState(snapshot);
      if (background.hidden) {{
        return null;
      }}
      if (background.monitor) {{
        return {{
          tone: background.tone || "active",
          title: background.monitor.title || "Background run active",
          detail: background.monitor.detail || background.title || background.meta || "Background work is still running.",
          action: String(background.monitor.action || "peek"),
          key: String(background.monitor.key || ""),
        }};
      }}
      if (snapshot?.pending) {{
        return {{
          tone: "active",
          title: "Working in background",
          detail: background.title || background.meta || "Codex is still handling the active turn.",
          action: "peek",
          key: `pending:${{Number(snapshot?.last_started_at || 0)}}:${{Number(snapshot?.queue_depth || 0)}}`,
        }};
      }}
      if (Number(snapshot?.queue_depth || 0) > 0) {{
        return {{
          tone: "queue",
          title: Number(snapshot?.queue_depth || 0) === 1 ? "Prompt queued" : "Background queue active",
          detail: background.title || background.meta || "Queued work is still waiting behind the current turn.",
          action: "peek",
          key: `queue:${{Number(snapshot?.queue_depth || 0)}}:${{Number(snapshot?.last_action_at || 0)}}`,
        }};
      }}
      return null;
    }}

    function pushNotice(tone, title, detail, key = "", action = "") {{
      const cleanTitle = String(title || "").trim();
      const cleanDetail = String(detail || "").trim();
      if (!cleanTitle && !cleanDetail) {{
        return;
      }}
      const dedupeKey = key || `${{tone}}:${{cleanTitle}}:${{cleanDetail}}`;
      const now = Date.now();
      const existing = state.notices.find((item) => item.key === dedupeKey && now - item.createdAt < 12000);
      if (existing) {{
        existing.createdAt = now;
        existing.unread = true;
        return;
      }}
      state.noticeSerial += 1;
      state.notices.unshift({{
        id: state.noticeSerial,
        key: dedupeKey,
        tone,
        title: cleanTitle,
        detail: cleanDetail,
        createdAt: now,
        unread: true,
        action: String(action || "").trim(),
      }});
      state.notices = state.notices.slice(0, 24);
    }}

    function unreadNoticeCount() {{
      return state.notices.filter((item) => item.unread).length;
    }}

    function dismissNoticeById(id) {{
      const targetId = Number(id);
      if (!Number.isFinite(targetId)) {{
        return;
      }}
      state.notices = state.notices.filter((item) => item.id !== targetId);
      renderNotifications();
    }}

    function attachToastDismissHandlers(toast, item) {{
      let pointerId = null;
      let startX = 0;
      let startY = 0;
      let deltaX = 0;
      let dragging = false;
      const swipeThreshold = 72;

      const reset = () => {{
        pointerId = null;
        deltaX = 0;
        dragging = false;
        toast.classList.remove("swiping");
        toast.style.transform = "";
        toast.style.opacity = "";
      }};

      toast.addEventListener("pointerdown", (event) => {{
        if (event.pointerType === "mouse" && event.button !== 0) {{
          return;
        }}
        pointerId = event.pointerId;
        startX = event.clientX;
        startY = event.clientY;
        deltaX = 0;
        dragging = false;
      }});

      toast.addEventListener("pointermove", (event) => {{
        if (pointerId !== event.pointerId) {{
          return;
        }}
        const nextDeltaX = event.clientX - startX;
        const deltaY = event.clientY - startY;
        if (!dragging) {{
          if (Math.abs(nextDeltaX) < 12 || Math.abs(nextDeltaX) <= Math.abs(deltaY)) {{
            return;
          }}
          dragging = true;
          toast.classList.add("swiping");
        }}
        deltaX = nextDeltaX;
        const clamped = Math.max(-160, Math.min(160, deltaX));
        const opacity = Math.max(0.26, 1 - Math.min(Math.abs(clamped) / 160, 0.74));
        toast.style.transform = `translateX(${{clamped}}px)`;
        toast.style.opacity = String(opacity);
      }});

      const finish = (event) => {{
        if (pointerId !== null && event.pointerId !== pointerId) {{
          return;
        }}
        if (dragging && Math.abs(deltaX) >= swipeThreshold) {{
          toast.classList.remove("swiping");
          toast.classList.add("dismissing");
          toast.style.transform = `translateX(${{deltaX > 0 ? 130 : -130}}%)`;
          toast.style.opacity = "0";
          window.setTimeout(() => dismissNoticeById(item.id), 170);
          reset();
          return;
        }}
        const wasDragging = dragging;
        reset();
        if (!wasDragging) {{
          setNoticesOpen(true);
        }}
      }};

      toast.addEventListener("pointerup", finish);
      toast.addEventListener("pointercancel", () => reset());
      toast.addEventListener("lostpointercapture", () => reset());
    }}

    function renderNotifications() {{
      const unreadCount = unreadNoticeCount();
      el.topbarMenuButton.classList.toggle("has-unread", unreadCount > 0);
      el.topbarMenuCount.hidden = unreadCount === 0;
      el.topbarMenuCount.textContent = String(unreadCount);
      el.noticeToggleButton.classList.toggle("has-unread", unreadCount > 0);
      el.noticeCount.hidden = unreadCount === 0;
      el.noticeCount.textContent = String(unreadCount);

      el.notificationsList.innerHTML = "";
      if (!state.notices.length) {{
        const empty = document.createElement("div");
        empty.className = "notification-empty";
        empty.textContent = "No notifications yet.";
        el.notificationsList.appendChild(empty);
      }} else {{
        for (const item of state.notices) {{
          const card = document.createElement("div");
          card.className = `notification-item ${{item.tone}}${{item.unread ? " unread" : ""}}`;
          card.innerHTML = `
            <div class="notification-meta">
              <span class="notification-tone" data-icon="${{noticeToneIcon(item.tone)}}">${{escapeHtml(noticeToneLabel(item.tone))}}</span>
              <span>${{escapeHtml(new Date(item.createdAt).toLocaleTimeString([], {{ hour: "numeric", minute: "2-digit" }}))}}</span>
            </div>
            <div class="notification-title">${{escapeHtml(item.title)}}</div>
            <div class="notification-detail">${{escapeHtml(item.detail)}}</div>
          `;
          attachNoticeActivation(card, item);
          el.notificationsList.appendChild(card);
        }}
      }}

      el.toastStack.innerHTML = "";
      const persistentBackground = backgroundMonitorNotice(state.snapshot);
      if (persistentBackground) {{
        const monitor = document.createElement("button");
        monitor.type = "button";
        monitor.className = `toast monitor ${{persistentBackground.tone || "active"}}`;
        monitor.dataset.noticeId = String(persistentBackground.key || "background-monitor");
        monitor.dataset.monitorAction = String(persistentBackground.action || "peek");
        monitor.innerHTML = `
          <div class="toast-head">
            <div class="toast-title-wrap" data-icon="${{noticeToneIcon(persistentBackground.tone || "active")}}">
              <div class="toast-title">${{escapeHtml(String(persistentBackground.title || "Background run active"))}}</div>
            </div>
            <div class="toast-time">live</div>
          </div>
          <div class="toast-detail">${{escapeHtml(String(persistentBackground.detail || "Background work is still running."))}}</div>
        `;
        monitor.addEventListener("click", () => {{
          const action = String(monitor.dataset.monitorAction || "peek");
          if (action === "system") {{
            setSystemOpen(true);
            return;
          }}
          setActivityPeekOpen(true);
        }});
        el.toastStack.appendChild(monitor);
      }}
      const toastCutoff = Date.now() - 12000;
      for (const item of state.notices.filter((entry) => entry.createdAt >= toastCutoff).slice(0, 3).reverse()) {{
        const toast = document.createElement("div");
        toast.className = `toast ${{item.tone}}`;
        toast.dataset.noticeId = String(item.id);
        toast.innerHTML = `
          <div class="toast-head">
            <div class="toast-title-wrap" data-icon="${{noticeToneIcon(item.tone)}}">
              <div class="toast-title">${{escapeHtml(item.title)}}</div>
            </div>
            <div class="toast-time">${{escapeHtml(new Date(item.createdAt).toLocaleTimeString([], {{ hour: "numeric", minute: "2-digit" }}))}}</div>
          </div>
          <div class="toast-detail">${{escapeHtml(item.detail)}}</div>
        `;
        attachToastDismissHandlers(toast, item);
        el.toastStack.appendChild(toast);
      }}
    }}

    function syncNotifications(snapshot) {{
      const prev = state.previousSnapshot;
      if (!prev || !prev.updated_at) {{
        state.previousSnapshot = snapshot;
        renderNotifications();
        return;
      }}
      const issue = runtimeIssue(snapshot);
      const prevIssue = runtimeIssue(prev);
      const finishedWithRealReply = Boolean(String(snapshot.last_response || "").trim())
        && !isPlaceholderAssistantResponse(snapshot.last_response)
        && !String(snapshot.last_error || "").trim();
      if (
        prev.pending
        && !snapshot.pending
        && snapshot.last_finished_at > (prev.last_finished_at || 0)
        && finishedWithRealReply
      ) {{
        pushNotice(
          "info",
          "Reply ready",
          summarizePrompt(snapshot.last_response || "The latest reply is ready.", 96),
          `reply:${{snapshot.last_finished_at}}`
        );
        playCompletionBell();
      }}
      if (issue && (!prevIssue || issue.code !== prevIssue.code || issue.summary !== prevIssue.summary)) {{
        pushNotice(
          issue.tone,
          issue.title,
          issue.summary,
          `issue:${{issue.code}}:${{snapshot.updated_at}}`,
          issue.tone === "queue" ? "peek" : "system"
        );
      }} else if (snapshot.last_error && snapshot.last_error !== prev.last_error) {{
        pushNotice(
          "alert",
          "Needs attention",
          summarizeErrorText(snapshot.last_error),
          `error:${{snapshot.last_error}}`,
          "system"
        );
      }}
      if (Number(snapshot.queue_depth || 0) > Number(prev.queue_depth || 0)) {{
        const queued = queuedEntries(snapshot);
        const newestQueued = queued[queued.length - 1] || {{}};
        const attachmentPhrase = attachmentCountPhrase(newestQueued.attachments);
        const queueDepth = Number(snapshot.queue_depth || 0);
        pushNotice(
          "queue",
          queueDepth === 1 ? "Prompt queued" : "Queue updated",
          queueDepth === 1
            ? attachmentPhrase
              ? `A follow-up with ${{attachmentPhrase}} is queued behind the current run.`
              : "A follow-up is queued behind the current run."
            : attachmentPhrase
              ? `${{queueDepth}} prompts are queued. Latest has ${{attachmentPhrase}}.`
              : `${{queueDepth}} prompts are queued.`,
          `queue:${{queueDepth}}:${{snapshot.updated_at}}`,
          "peek"
        );
      }}
      if (Number(snapshot.last_action_at || 0) > Number(prev.last_action_at || 0)) {{
        const authNotice = authActionNotice(
          snapshot.last_action,
          snapshot.last_action_detail
        );
        pushNotice(
          authNotice
            ? authNotice.tone
            : String(snapshot.last_action || "").startsWith("relay-")
              ? "info"
              : "console",
          authNotice
            ? authNotice.title
            : String(snapshot.last_action || "").startsWith("relay-")
              ? "Handoff sent"
              : "Operator action",
          authNotice
            ? authNotice.detail
            : summarizePrompt(snapshot.last_action_detail || "Recent operator action completed.", 96),
          `action:${{snapshot.last_action_at}}`,
          "system"
        );
      }}
      state.previousSnapshot = snapshot;
      renderNotifications();
    }}

    function decodeJsonStringFragment(value) {{
      const raw = String(value || "");
      if (!raw) {{
        return "";
      }}
      try {{
        return JSON.parse('"' + raw + '"');
      }} catch (_) {{
        return raw
          .replace(/\\\\n/g, " ")
          .replace(/\\\\r/g, " ")
          .replace(/\\\\t/g, " ")
          .replace(/\\\\"/g, '"')
          .replace(/\\s+/g, " ")
          .trim();
      }}
    }}

    function extractStructuredErrorOutput(value) {{
      const text = String(value || "").trim();
      if (!text) {{
        return "";
      }}
      const outputMatch = text.match(/"output"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"/);
      if (outputMatch) {{
        const decoded = decodeJsonStringFragment(outputMatch[1]);
        if (decoded) {{
          return decoded;
        }}
      }}
      const payloadMatch = text.match(/\\berror=(\\x7b[\\s\\S]*\\x7d)\\s*$/);
      if (payloadMatch) {{
        try {{
          const parsed = JSON.parse(payloadMatch[1]);
          const candidates = [parsed.output, parsed.message, parsed.error, parsed.stderr];
          for (const candidate of candidates) {{
            if (typeof candidate === "string" && candidate.trim()) {{
              return candidate.trim();
            }}
          }}
        }} catch (_) {{}}
      }}
      const loggerMatch = text.match(/\\bERROR\\s+[A-Za-z0-9_:.-]+:\\s*(.*)$/);
      if (loggerMatch && loggerMatch[1]) {{
        return loggerMatch[1].replace(/^error=/i, "").trim();
      }}
      return "";
    }}

    function summarizeErrorText(value) {{
      const text = String(value || "").trim();
      if (!text) {{
        return "Check the latest warning details.";
      }}
      if (containsUsageLimitError(text)) {{
        return "Usage limit reached. Open billing or limits, or switch this bot to the right account.";
      }}
      if (containsCodexAuthFailure(text)) {{
        return "Codex needs a fresh sign-in. Reauthenticate this bot home.";
      }}
      if (containsCodexCliUpgradeError(text)) {{
        return "Codex CLI was stale for this turn. Upgrade/restart the bot, then retry.";
      }}
      if (containsCertWorkflowError(text)) {{
        return "Certificate/TLS workflow failed. Use the right host family, then retry or inspect the raw details.";
      }}
      if (containsOpenAITransportError(text)) {{
        return "OpenAI's responses websocket failed during this turn. Retry when the API settles.";
      }}
      const structured = extractStructuredErrorOutput(text).replace(/\\s+/g, " ").trim();
      if (structured) {{
        return summarizePrompt(structured, 108);
      }}
      const firstLine = text.split(/\\r?\\n/, 1)[0].trim();
      return summarizePrompt(firstLine || text, 92);
    }}

    function shouldCollapseErrorDetails(value) {{
      const text = String(value || "").trim();
      if (!text) {{
        return false;
      }}
      return text.length > 220 || /\\r?\\n/.test(text);
    }}

    function renderErrorMarkup(value) {{
      const text = String(value || "").trim();
      if (!text) {{
        return `<div class="error-inline-summary">${{escapeHtml(summarizeErrorText(value))}}</div>`;
      }}
      const structured = extractStructuredErrorOutput(text).replace(/\\s+/g, " ").trim();
      if (!shouldCollapseErrorDetails(text)) {{
        if (structured) {{
          return `<div class="error-inline-summary">${{escapeHtml(summarizeErrorText(text))}}</div>`;
        }}
        return renderRichText(text);
      }}
      return `
        <div class="error-inline-summary">${{escapeHtml(summarizeErrorText(text))}}</div>
        <details class="error-details">
          <summary>Raw</summary>
          <pre>${{escapeHtml(text)}}</pre>
        </details>
      `;
    }}

    function authActionNotice(action, detail) {{
      const value = String(action || "").trim();
      const summary = summarizePrompt(
        detail || "Browser sign-in finished and the bot is ready.",
        96
      );
      if (value === "auth-browser-self-check") {{
        return {{
          tone: "info",
          title: "Sign-in complete",
          detail: summary,
        }};
      }}
      if (value === "auth-browser-callback") {{
        return {{
          tone: "info",
          title: "Sign-in delivered",
          detail: summary,
        }};
      }}
      return null;
    }}

    function openLatestRelayTargets() {{
      const relayGroups = Array.from(el.conversation.querySelectorAll(".relay-group"));
      const group = relayGroups.length ? relayGroups[relayGroups.length - 1] : null;
      if (!group) {{
        return false;
      }}
      const footer = group.closest(".message-footer");
      const message = group.closest(".message");
      const toolsToggle = message ? message.querySelector(".message-tools-toggle") : null;
      if (footer?.classList.contains("collapsed") && toolsToggle) {{
        toolsToggle.click();
      }}
      const targets = group.querySelector(".relay-targets");
      const relayToggle = group.querySelector(".relay-toggle");
      if (targets?.hidden && relayToggle) {{
        relayToggle.click();
      }}
      if (typeof group.scrollIntoView === "function") {{
        group.scrollIntoView({{ block: "nearest", inline: "nearest" }});
      }}
      return true;
    }}

    function noticeActionDescriptors(kind = "broker") {{
      const actions = [
        {{
          type: "link",
          label: "Prime",
          href: el.primeHomeButton?.href || {json.dumps(norman_prime_href)},
        }},
        {{
          type: "link",
          label: "Dir",
          href: el.directoryHomeButton?.href || {json.dumps(norman_directory_href)},
        }},
      ];
      if (kind === "broker" && RELAY_TARGETS.length) {{
        actions.unshift({{
          type: "button",
          label: "Ask another",
          action: "relay",
        }});
      }}
      return actions;
    }}

    function buildInlineAction(action, className = "notice-chip-action") {{
      if (action?.type === "button") {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = `ghost ${{className}}`;
        button.textContent = String(action.label || "Action");
        button.dataset.action = String(action.action || "");
        return button;
      }}
      const link = document.createElement("a");
      link.className = `ghost button-link ${{className}}`;
      link.textContent = String(action?.label || "Open");
      link.href = String(action?.href || "#");
      return link;
    }}

    function renderNoticeRail(snapshot) {{
      const notices = [];
      const queueDepth = Number(snapshot.queue_depth || 0);
      const draftAttachmentCount = Array.isArray(snapshot.draft_attachments)
        ? snapshot.draft_attachments.length
        : 0;
      const issue = runtimeIssue(snapshot);
      const broker = brokerInsight(snapshot);

      if (issue) {{
        notices.push({{
          tone: issue.tone,
          icon: issue.code === "needs_reauth" ? "!" : "◉",
          label: issue.label,
          copy: issue.summary,
          action: issue.tone === "queue" ? "peek" : "system",
        }});
      }} else if (snapshot.last_error) {{
        notices.push({{
          tone: "alert",
          icon: "!",
          label: "Attention",
          copy: summarizeErrorText(snapshot.last_error),
          action: "system",
        }});
      }}
      if (snapshot.pending) {{
        notices.push({{
          tone: "queue",
          icon: "◔",
          label: queueDepth > 0 ? `Running +${{queueDepth}}` : "Running",
          copy: responseProfileText(snapshot.running_speed, snapshot.running_detail),
          action: "peek",
        }});
      }} else if (queueDepth > 0) {{
        notices.push({{
          tone: "queue",
          icon: "◷",
          label: queueDepth === 1 ? "1 queued" : `${{queueDepth}} queued`,
          copy: "Queued prompts will run in order.",
          action: "peek",
        }});
      }}
      if (recentConsoleAction(snapshot)) {{
        notices.push({{
          tone: "console",
          icon: "⌘",
          label: "Operator",
          copy: summarizePrompt(snapshot.last_action_detail || "Recent operator action.", 92),
          action: "system",
        }});
      }}
      if (draftAttachmentCount > 0) {{
        notices.push({{
          tone: "info",
          icon: "⊕",
          label: draftAttachmentCount === 1 ? "1 staged" : `${{draftAttachmentCount}} staged`,
          copy: "Attachments are ready to send.",
          action: "prompt",
        }});
      }}
      if (broker) {{
        notices.push({{
          tone: "info",
          icon: "⇄",
          label: broker.label,
          copy: broker.copy,
          action: "relay",
          actions: noticeActionDescriptors("broker"),
        }});
      }}

      const renderKey = JSON.stringify(notices);
      if (state.renderCache.noticeRail === renderKey) {{
        return;
      }}
      state.renderCache.noticeRail = renderKey;

      el.noticeRail.innerHTML = "";
      el.noticeRail.hidden = notices.length === 0;
      el.noticeRail.classList.toggle("visible", notices.length > 0);
      for (const item of notices) {{
        const chip = document.createElement("div");
        chip.className = `notice-chip ${{item.tone}}`;
        const hasInlineActions = Array.isArray(item.actions) && item.actions.length;
        if (hasInlineActions) {{
          chip.classList.add("has-actions");
        }}
        chip.dataset.icon = item.icon;
        const body = document.createElement("div");
        body.className = "notice-chip-body";
        body.innerHTML = `<span class="notice-label">${{escapeHtml(item.label)}}</span><span class="notice-copy">${{escapeHtml(item.copy)}}</span>`;
        chip.appendChild(body);
        if (hasInlineActions) {{
          const actions = document.createElement("div");
          actions.className = "notice-chip-actions";
          for (const descriptor of item.actions) {{
            actions.appendChild(buildInlineAction(descriptor));
          }}
          chip.appendChild(actions);
        }}
        attachNoticeActivation(hasInlineActions ? body : chip, item);
        el.noticeRail.appendChild(chip);
      }}
    }}

    async function unwindLatestTurn(button) {{
      if (!button) {{
        return;
      }}
      const confirmed = window.confirm(
        "Remove the latest turn and start the next prompt fresh?"
      );
      if (!confirmed) {{
        return;
      }}
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "Unwinding…";
      closeMessageActionMenus();
      el.statusMessage.textContent = "Unwinding the latest turn…";
      try {{
        const result = await postForm("/api/history/unwind", {{}});
        state.transientOperatorBanner = "Latest turn unwound.";
        if (result.snapshot) {{
          render(result.snapshot);
        }} else {{
          renderActivityStrip(state.snapshot);
        }}
        el.statusMessage.textContent = "Latest turn removed. The next prompt will start fresh.";
      }} catch (err) {{
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Unwind failed: ${{err.message}}`;
      }} finally {{
        button.disabled = false;
        button.textContent = original;
        schedulePoll(1000);
      }}
    }}

    function relayEtaLabel(queuePosition, pending) {{
      if (pending && queuePosition <= 0) {{
        return "running now";
      }}
      if (queuePosition <= 0) {{
        return "ETA unknown";
      }}
      const minutes = Math.max(5, Math.min(120, queuePosition * 10));
      return `rough ETA ${{minutes}} min`;
    }}

    function relayPickupState(result, target) {{
      const ack = result?.relay_ack && typeof result.relay_ack === "object"
        ? result.relay_ack
        : {{}};
      const downstream = result?.downstream && typeof result.downstream === "object"
        ? result.downstream
        : {{}};
      const targetSnapshot = downstream.snapshot && typeof downstream.snapshot === "object"
        ? downstream.snapshot
        : {{}};
      const targetLabel = String(ack.target || result?.target || target?.label || "BBS").trim() || "BBS";
      const queueDepth = Number(ack.queue_depth ?? targetSnapshot.queue_depth ?? 0);
      const queuePosition = Number(
        ack.queue_position ?? (queueDepth > 0 ? queueDepth : 0)
      );
      const pending = Boolean(ack.pending ?? targetSnapshot.pending);
      const modelAlive = Boolean(
        ack.model_alive ?? targetSnapshot.model_process_alive ?? targetSnapshot.web_worker_alive
      );
      let relayState = String(ack.state || "").trim();
      if (!relayState) {{
        relayState = queuePosition > 0 ? "queued" : pending ? "running" : "picked-up";
      }}
      const label = String(
        ack.label || (relayState === "queued" ? "Queued" : "Picked up")
      ).trim();
      const etaLabel = String(ack.eta_label || relayEtaLabel(queuePosition, pending)).trim();
      const detail = String(ack.detail || "").trim();
      return {{
        state: relayState,
        label,
        targetLabel,
        queueDepth,
        queuePosition,
        pending,
        modelAlive,
        etaLabel,
        detail,
      }};
    }}

    function relayStatusLine(ack) {{
      const label = ack.state === "queued"
        ? `Picked up by ${{ack.targetLabel}} · queued at position ${{ack.queuePosition}}`
        : `${{ack.label}} by ${{ack.targetLabel}}`;
      const worker = ack.state === "running"
        ? (ack.modelAlive ? "worker alive" : "waiting for worker")
        : "";
      return [label, ack.etaLabel, worker, ack.detail].filter(Boolean).join(" · ");
    }}

    function applyRelayButtonState(button, ack) {{
      const icon = ack.state === "queued" ? "◔" : "✓";
      button.dataset.relayState = ack.state;
      button.dataset.icon = icon;
      const status = ack.state === "queued"
        ? `Queued #${{ack.queuePosition}} ·`
        : `${{ack.label}} ·`;
      button.innerHTML = `<span class="relay-target-status">${{escapeHtml(status)}}</span> ${{renderNameCartouche(ack.targetLabel)}}`;
      const line = relayStatusLine(ack);
      button.title = line;
      button.setAttribute("aria-label", line);
    }}

    function setRelayButtonBusy(button, busy) {{
      if (!button) {{
        return;
      }}
      if ("disabled" in button) {{
        button.disabled = Boolean(busy);
      }}
      button.setAttribute("aria-disabled", busy ? "true" : "false");
      button.classList.toggle("is-busy", Boolean(busy));
    }}

    async function relayMessage(target, sourcePrompt, sourceResponse, button) {{
      if (!target || !target.label) {{
        return;
      }}
      setRelayButtonBusy(button, true);
      button.dataset.relayState = "sending";
      button.dataset.icon = "⇄";
      button.innerHTML = `<span class="relay-target-status">Sending ·</span> ${{renderNameCartouche(target.label)}}`;
      el.statusMessage.textContent = `Handing off to ${{target.label}}…`;
      try {{
        const result = await postForm("/api/relay", {{
          target_label: target.label,
          source_prompt: sourcePrompt || "",
          source_response: sourceResponse || "",
          speed: normalizeResponseSpeed(state.preferences.responseSpeed),
          detail: String(normalizeResponseDetail(state.preferences.responseDetail)),
        }});
        state.transientOperatorBanner = `Handoff sent to ${{target.label}}`;
        if (result.snapshot) {{
          render(result.snapshot);
        }} else {{
          renderActivityStrip(state.snapshot);
        }}
        const ack = relayPickupState(result, target);
        applyRelayButtonState(button, ack);
        const statusLine = relayStatusLine(ack);
        el.statusMessage.textContent = statusLine;
        pushNotice(
          ack.state === "queued" ? "queue" : "info",
          ack.state === "queued" ? "BBS handoff queued" : "BBS picked up",
          statusLine,
          `relay:${{ack.targetLabel}}:${{Date.now()}}`
        );
      }} catch (err) {{
        button.dataset.relayState = "error";
        button.dataset.icon = "!";
        button.innerHTML = `<span class="relay-target-status">Retry ·</span> ${{renderNameCartouche(target.label)}}`;
        button.title = `Handoff failed: ${{err.message}}`;
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Handoff failed: ${{err.message}}`;
      }} finally {{
        setRelayButtonBusy(button, false);
        schedulePoll(1000);
      }}
    }}

    function buildRelayGroup(sourcePrompt, sourceResponse) {{
      if (!RELAY_TARGETS.length) {{
        return null;
      }}
      const group = document.createElement("div");
      group.className = "relay-group";

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "ghost copy-button inline-action relay-toggle";
      toggle.dataset.icon = "⇄";
      toggle.textContent = "Ask another";
      group.appendChild(toggle);

      const targets = document.createElement("div");
      targets.className = "relay-targets";
      targets.hidden = true;

      for (const target of RELAY_TARGETS) {{
        const button = document.createElement("a");
        button.href = target.url || "#";
        button.target = "_blank";
        button.rel = "noreferrer";
        button.className = "ghost relay-target";
        button.dataset.icon = "⇄";
        button.setAttribute("aria-label", target.label);
        button.innerHTML = renderNameCartouche(target.label);
        button.addEventListener("click", (event) => {{
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {{
            return;
          }}
          event.preventDefault();
          if (button.getAttribute("aria-disabled") === "true") {{
            return;
          }}
          relayMessage(target, sourcePrompt, sourceResponse, button);
        }});
        targets.appendChild(button);
      }}

      toggle.addEventListener("click", () => {{
        targets.hidden = !targets.hidden;
      }});

      group.appendChild(targets);
      return group;
    }}

    function closeMessageActionMenus(exceptFooter = null) {{
      for (const article of el.conversation.querySelectorAll(".message")) {{
        const footer = article.querySelector(".message-footer[data-collapsible='true']");
        const toggle = article.querySelector(".message-tools-toggle");
        if (!footer || footer === exceptFooter) {{
          continue;
        }}
        footer.classList.add("collapsed");
        if (toggle) {{
          toggle.classList.remove("active");
          toggle.setAttribute("aria-expanded", "false");
        }}
      }}
    }}

    function conversationGroupKey(role) {{
      const clean = String(role || "").trim().toLowerCase();
      if (clean.includes("pending") || clean.includes("queued") || clean.includes("error")) {{
        return "";
      }}
      if (clean.includes("assistant")) {{
        return "assistant";
      }}
      if (clean.includes("user")) {{
        return "user";
      }}
      return "";
    }}

    function applyConversationGrouping() {{
      const messages = Array.from(el.conversation.querySelectorAll(".message"));
      for (const message of messages) {{
        message.classList.remove("continuation", "group-start", "group-end");
      }}
      for (let index = 0; index < messages.length; index += 1) {{
        const current = messages[index];
        const currentKey = current.dataset.groupKey || "";
        if (!currentKey) {{
          continue;
        }}
        const previous = messages[index - 1];
        const next = messages[index + 1];
        const previousKey = previous ? (previous.dataset.groupKey || "") : "";
        const nextKey = next ? (next.dataset.groupKey || "") : "";
        if (previousKey === currentKey) {{
          current.classList.add("continuation", "group-end");
        }}
        if (nextKey === currentKey) {{
          current.classList.add("group-start");
        }}
      }}
    }}

    function appendMessage(role, label, body, metaText, options = {{}}) {{
      const cleanRole = String(role || "").trim().toLowerCase();
      const article = document.createElement("article");
      article.className = `message ${{role}}`;
      article.dataset.groupKey = conversationGroupKey(role);
      if (cleanRole.includes("pending")) {{
        article.classList.add("live-status");
      }}
      const relayCallback = options.relayCallback || null;
      if (relayCallback) {{
        article.classList.add("relay-queued");
      }}

      const head = document.createElement("div");
      head.className = "message-head";

      const metaWrap = document.createElement("div");
      metaWrap.className = "meta-block";

      const labelNode = document.createElement("span");
      labelNode.className = "message-role";
      labelNode.dataset.icon = messageRoleIcon(role, label);
      labelNode.setAttribute("aria-label", label);
      labelNode.innerHTML = renderLinkedNameCartouche(label);
      metaWrap.appendChild(labelNode);

      if (metaText) {{
        const metaNode = document.createElement("span");
        metaNode.className = "message-meta";
        metaNode.textContent = metaText;
        metaWrap.appendChild(metaNode);
      }}
      if (cleanRole.includes("queued")) {{
        const queueBadge = document.createElement("span");
        queueBadge.className = "message-state-badge";
        queueBadge.textContent = "queued";
        metaWrap.appendChild(queueBadge);
      }}
      if (relayCallback) {{
        const relayBadge = document.createElement("span");
        relayBadge.className = "message-state-badge relay";
        const relayLabel = relayQueueLabel(relayCallback);
        relayBadge.setAttribute("aria-label", relayLabel);
        relayBadge.innerHTML = renderLinkedNameCartouche(relayLabel);
        metaWrap.appendChild(relayBadge);
      }}

      head.appendChild(metaWrap);

      let footer = null;
      const urls = extractUrls(body);
      const footerLinks = [...urls, ...runtimeSupportLinks(body)];
      const hasAssistantActions =
        (cleanRole.includes("assistant") || cleanRole.includes("error")) && !cleanRole.includes("pending");
      const hasFooterContent = hasAssistantActions || footerLinks.length;
      if (hasFooterContent) {{
        const tools = document.createElement("div");
        tools.className = "message-tools";

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "ghost message-tools-toggle";
        toggle.dataset.icon = "⋯";
        toggle.textContent = "";
        toggle.setAttribute("aria-label", "Message actions");
        toggle.title = "Message actions";
        toggle.setAttribute("aria-expanded", "false");
        tools.appendChild(toggle);
        head.appendChild(tools);

        footer = document.createElement("div");
        footer.className = "message-footer collapsed";
        footer.dataset.collapsible = "true";

        toggle.addEventListener("click", (event) => {{
          event.stopPropagation();
          const opening = footer.classList.contains("collapsed");
          closeMessageActionMenus(opening ? footer : null);
          footer.classList.toggle("collapsed", !opening);
          toggle.classList.toggle("active", opening);
          toggle.setAttribute("aria-expanded", opening ? "true" : "false");
        }});
      }}

      const text = document.createElement("div");
      text.className = "message-body";
      const collapsedPrompt = collapsedPromptDescriptor(cleanRole, body, options);
      if (collapsedPrompt) {{
        text.innerHTML = `
          <button type="button" class="collapsed-prompt-toggle" aria-expanded="false">
            <span class="collapsed-prompt-badge">${{escapeHtml(collapsedPrompt.badge || "Text")}}</span>
            <span class="collapsed-prompt-title">${{escapeHtml(collapsedPrompt.title)}}</span>
            <span class="collapsed-prompt-meta">${{escapeHtml(collapsedPrompt.meta)}}</span>
            <span class="collapsed-prompt-preview">${{escapeHtml(collapsedPrompt.preview || "")}}</span>
          </button>
          <div class="collapsed-prompt-body" hidden></div>
        `;
        const toggle = text.querySelector(".collapsed-prompt-toggle");
        const detail = text.querySelector(".collapsed-prompt-body");
        if (toggle && detail) {{
          let detailRendered = false;
          const renderCollapsedDetail = () => {{
            if (detailRendered) {{
              return;
            }}
            detail.innerHTML = cleanRole.includes("error")
              ? renderErrorMarkup(body)
              : renderRichText(body);
            detailRendered = true;
          }};
          toggle.addEventListener("click", () => {{
            const opening = detail.hidden;
            if (opening) {{
              renderCollapsedDetail();
            }}
            detail.hidden = !opening;
            toggle.setAttribute("aria-expanded", opening ? "true" : "false");
          }});
        }}
      }} else {{
        text.innerHTML = cleanRole.includes("error")
          ? renderErrorMarkup(body)
          : renderRichText(body);
      }}

      article.appendChild(head);
      article.appendChild(text);
      const attachmentPaths = new Set(
        (Array.isArray(options.attachments) ? options.attachments : [])
          .map((entry) => splitFileTarget(entry?.path || "").path)
          .filter(Boolean)
      );
      const shouldScanInlinePreviews = options.inlinePreviews !== false
        && !cleanRole.includes("pending")
        && !cleanRole.includes("queued")
        && (cleanRole.includes("assistant") || cleanRole.includes("error") || options.forceInlinePreviews);
      const previewLimit = Math.max(0, Number(options.inlinePreviewLimit || INLINE_FILE_TARGET_LIMIT));
      const previewTargets = shouldScanInlinePreviews
        ? extractInlineFileTargets(body, previewLimit).filter((entry) => !attachmentPaths.has(entry.path))
        : [];
      if (previewTargets.length) {{
        const previews = document.createElement("div");
        previews.className = "message-file-previews";
        article.appendChild(previews);
        renderInlineFilePreviews(previews, previewTargets);
      }}
      if (Array.isArray(options.attachments) && options.attachments.length) {{
        const attachments = document.createElement("div");
        attachments.className = "message-attachments";
        renderAttachmentChips(attachments, options.attachments, {{ removable: false, gallery: true }});
        article.appendChild(attachments);
      }}
      const visibleShortcutGroup = cleanRole.includes("assistant") && !cleanRole.includes("pending")
        ? buildReplyShortcutGroup(options.sourcePrompt || "", body, {{
            actionCount: 5,
            includeUnwind: options.canUnwindLatestTurn,
            className: "reply-tail-actions",
            buttonClass: "ghost inline-action reply-tail-action",
            closeMenus: false,
            submitImmediately: true,
          }})
        : null;
      if (visibleShortcutGroup) {{
        const copyQuick = document.createElement("button");
        copyQuick.type = "button";
        copyQuick.className = "ghost inline-action reply-tail-action";
        copyQuick.textContent = "Copy";
        copyQuick.title = "Copy plain text";
        copyQuick.addEventListener("click", () => {{
          copyText(plainTextFromRenderedMessage(article, body), copyQuick);
        }});
        visibleShortcutGroup.appendChild(copyQuick);
        if (options.canUnwindLatestTurn) {{
          const unwindQuick = document.createElement("button");
          unwindQuick.type = "button";
          unwindQuick.className = "ghost inline-action reply-tail-action";
          unwindQuick.textContent = "Unwind";
          unwindQuick.title = "Remove the latest turn and start the next prompt fresh";
          unwindQuick.addEventListener("click", () => {{
            void unwindLatestTurn(unwindQuick);
          }});
          visibleShortcutGroup.appendChild(unwindQuick);
        }}
        article.appendChild(visibleShortcutGroup);
      }}
      if (hasAssistantActions && footer) {{
        if (options.canUnwindLatestTurn) {{
          const unwindButton = document.createElement("button");
          unwindButton.type = "button";
          unwindButton.className = "ghost inline-action";
          unwindButton.dataset.icon = "↺";
          unwindButton.textContent = "Unwind";
          unwindButton.title = "Remove the latest turn and start the next prompt fresh";
          unwindButton.addEventListener("click", () => {{
            void unwindLatestTurn(unwindButton);
          }});
          footer.appendChild(unwindButton);
        }}

        const copyButton = document.createElement("button");
        copyButton.type = "button";
        copyButton.className = "ghost copy-button inline-action";
        copyButton.dataset.icon = "⎘";
        copyButton.textContent = "Copy";
        copyButton.title = "Copy plain text";
        copyButton.addEventListener("click", () => copyText(plainTextFromRenderedMessage(article, body), copyButton));
        footer.appendChild(copyButton);

        const relayGroup = buildRelayGroup(options.sourcePrompt || "", body);
        if (relayGroup) {{
          footer.appendChild(relayGroup);
        }}

        if (footerLinks.length) {{
          const links = document.createElement("div");
          links.className = "message-links";
          renderLinkStrip(links, footerLinks);
          footer.appendChild(links);
        }}
        article.appendChild(footer);
      }} else if (footerLinks.length && footer) {{
        const linkStrip = document.createElement("div");
        linkStrip.className = "message-links";
        renderLinkStrip(linkStrip, footerLinks);
        footer.appendChild(linkStrip);
        article.appendChild(footer);
      }}
      if (options.latest) {{
        article.classList.add("latest-message");
      }}
      el.conversation.appendChild(article);
      return article;
    }}

    function renderHistoryToolbar(totalTurns) {{
      const windowSize = recentHistoryWindow();
      if (totalTurns <= windowSize) {{
        el.historyToolbar.classList.remove("visible");
        el.historyWindowNote.textContent = "";
        el.historyToggleButton.textContent = "Timeline";
        return;
      }}
      const hiddenTurns = Math.max(0, totalTurns - windowSize);
      el.historyToolbar.classList.add("visible");
      if (state.historyExpanded) {{
        el.historyWindowNote.textContent = `${{formatCount(totalTurns)}} turns visible`;
        el.historyToggleButton.textContent = "Recent";
      }} else {{
        el.historyWindowNote.textContent = `Latest ${{windowSize}}/${{totalTurns}}`;
        el.historyToggleButton.textContent = hiddenTurns
          ? `${{hiddenTurns}} older`
          : "Timeline";
      }}
    }}

    function renderConversation(snapshot) {{
      const renderKey = conversationRenderSignature(snapshot);
      if (state.renderCache.conversation === renderKey) {{
        return;
      }}
      state.renderCache.conversation = renderKey;
      const scroller = chatScrollRoot();
      const previousScrollTop = scroller ? scroller.scrollTop : 0;
      const shouldStick = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 96;
      const previousTailKey = String(state.lastConversationTailKey || "");
      const nextTailKey = conversationTailKey(snapshot);
      const tailChanged = Boolean(previousTailKey) && previousTailKey !== nextTailKey;
      const items = historyEntries(snapshot);
      const queued = queuedEntries(snapshot);
      const totalTurns = items.length + (snapshot.pending ? 1 : 0);
      const windowSize = recentHistoryWindow();
      const hiddenTurns = Math.max(0, items.length - windowSize);
      const visibleItems = state.historyExpanded ? items : items.slice(-windowSize);
      state.hiddenHistoryTurns = hiddenTurns;
      const recentStartIndex = Math.max(0, items.length - windowSize);

      el.conversation.innerHTML = "";
      let latestNode = null;
      if (!items.length && !snapshot.pending) {{
        const empty = document.createElement("div");
        empty.className = "message empty";
        empty.textContent = {json.dumps(PROMPT_PLACEHOLDER)};
        el.conversation.appendChild(empty);
      }}
      for (const [index, item] of visibleItems.entries()) {{
        if (state.historyExpanded && items.length > windowSize) {{
          if (index === 0) {{
            const earlier = document.createElement("div");
            earlier.className = "timeline-divider";
            earlier.textContent = "Earlier session";
            el.conversation.appendChild(earlier);
          }}
          if (index === recentStartIndex) {{
            const recent = document.createElement("div");
            recent.className = "timeline-divider";
            recent.textContent = "Recent";
            el.conversation.appendChild(recent);
          }}
        }}
        const promptTs = item.started_at || item.finished_at || 0;
        const replyTs = item.finished_at || item.started_at || 0;
        const responseProfile = responseProfileText(item.speed, item.detail);
        const promptMeta = promptTs ? `${{formatTs(promptTs)}} · ${{responseProfile}}` : responseProfile;
        const replyMeta = replyTs ? `${{formatTs(replyTs)}} · ${{responseProfile}}` : responseProfile;
        const canUnwindLatestTurn = index === visibleItems.length - 1
          && !snapshot.pending
          && queued.length === 0;
        const turnDistanceFromLatest = visibleItems.length - index;
        const allowInlinePreviews = turnDistanceFromLatest <= INLINE_PREVIEW_VISIBLE_MESSAGE_LIMIT;
        appendMessage(
          "user",
          "You",
          item.prompt || "[empty prompt]",
          promptMeta,
          {{
            attachments: Array.isArray(item.attachments) ? item.attachments : [],
            inlinePreviews: false,
          }}
        );
        if (item.response && !(isPlaceholderAssistantResponse(item.response) && String(item.error || "").trim())) {{
          latestNode = appendMessage("assistant", AGENT_LABEL, item.response, replyMeta, {{
            sourcePrompt: item.prompt || "",
            canUnwindLatestTurn: canUnwindLatestTurn && !String(item.error || "").trim(),
            inlinePreviews: allowInlinePreviews,
            inlinePreviewLimit: INLINE_FILE_TARGET_LIMIT,
          }});
        }}
        if (item.error) {{
          latestNode = appendMessage("error", "Error", item.error, replyMeta, {{
            sourcePrompt: item.prompt || "",
            canUnwindLatestTurn,
            inlinePreviews: allowInlinePreviews,
            inlinePreviewLimit: INLINE_FILE_TARGET_LIMIT,
          }});
        }}
      }}

      if (snapshot.pending && snapshot.running_prompt) {{
        const liveProfile = responseProfileText(snapshot.running_speed, snapshot.running_detail);
        const liveMeta = snapshot.last_started_at
          ? `${{formatTs(snapshot.last_started_at)}} · ${{liveProfile}}`
          : liveProfile;
        const liveAgentLabel = String(AGENT_LABEL || "Assistant").trim() || "Assistant";
        const elapsed = activityElapsed(snapshot);
        const modelState = snapshot.model_process_alive ? "model process alive" : "waiting for model process";
        const liveStatusBody = `Working on: ${{summarizePrompt(snapshot.running_prompt, 140)}}. New messages will be queued. ${{elapsed > 0 ? formatElapsedCompact(elapsed) + " elapsed. " : ""}}${{modelState}}.`;
        appendMessage(
          "user",
          "You",
          snapshot.running_prompt,
          liveMeta,
          {{
            attachments: Array.isArray(snapshot.running_attachments)
              ? snapshot.running_attachments
              : [],
            inlinePreviews: false,
          }}
        );
        latestNode = appendMessage(
          "assistant pending",
          AGENT_LABEL,
          liveStatusBody,
          `Running · ${{liveProfile}}`,
          {{
            latest: true,
            sourcePrompt: snapshot.running_prompt || "",
            inlinePreviews: false,
          }}
        );
      }}

      for (const item of queued) {{
        const relayCallback = queueRelayCallback(item);
        const queuedProfile = responseProfileText(item.speed, item.detail);
        const queueSource = String(item.source || "").toLowerCase();
        let queueLabel = relayCallback ? "BBS" : "You";
        if (!relayCallback && (queueSource === "passive" || queueSource === "relay")) {{
          queueLabel = "BBS / passive";
        }} else if (!relayCallback && queueSource === "recovered") {{
          queueLabel = "Recovered";
        }}
        const queueRole = relayCallback ? "user queued relay" : "user queued";
        const queuedAttachmentText = attachmentCountPhrase(item.attachments);
        // Produces the visible "Queued · ..." metadata line without hiding attachments.
        const queuedMeta = [
          "Queued",
          queuedAttachmentText,
          item.queued_at ? formatTs(item.queued_at) : "",
          queuedProfile,
        ].filter(Boolean).join(" · ");
        appendMessage(
          queueSource === "passive" && !relayCallback ? "user queued relay" : queueRole,
          queueLabel,
          item.prompt || "[empty prompt]",
          queuedMeta,
          {{
            attachments: Array.isArray(item.attachments) ? item.attachments : [],
            inlinePreviews: false,
            relayCallback,
          }}
        );
      }}

      const visibleTurns = visibleItems.length + (snapshot.pending ? 1 : 0);
      const queueCount = queued.length;
      applyConversationGrouping();
      renderHistoryToolbar(totalTurns);
      if (!totalTurns && !queueCount) {{
        el.historySummary.textContent = "No conversation yet.";
      }} else if (hiddenTurns && !state.historyExpanded) {{
        el.historySummary.textContent = `${{visibleTurns}} recent of ${{totalTurns}} turns${{queueCount ? ` · ${{queueCount}} queued` : ""}}`;
      }} else if (queueCount) {{
        el.historySummary.textContent = `${{totalTurns}} turn${{totalTurns === 1 ? "" : "s"}} · ${{queueCount}} queued`;
      }} else {{
        el.historySummary.textContent = `${{totalTurns}} turn${{totalTurns === 1 ? "" : "s"}}`;
      }}

      state.lastConversationTailKey = nextTailKey;
      const shouldPreserveViewport = !state.historyExpanded && !shouldStick;
      const shouldSnapToBottom = !state.historyExpanded && totalTurns > 0 && (!state.initialBottomSnapDone || shouldStick);
      if (shouldSnapToBottom) {{
        scrollConversationToBottom(!state.initialBottomSnapDone);
        settleViewportToLiveEdge(!state.initialViewportSettleDone);
        state.initialBottomSnapDone = true;
      }} else if (shouldPreserveViewport) {{
        restoreConversationViewport(previousScrollTop, tailChanged);
      }}
      updateScrollChrome();
      if (!shouldPreserveViewport) {{
        el.jumpLatestButton.classList.toggle("visible", false);
      }}
      if (latestNode && !snapshot.pending && !state.historyExpanded && (shouldStick || !state.userPinnedHistory)) {{
        latestNode.classList.add("latest-message");
      }}
    }}

    function recentConsoleAction(snapshot) {{
      return (
        isConsoleAction(snapshot)
        && Number(snapshot.last_action_at || 0) > 0
        && ((Date.now() / 1000) - Number(snapshot.last_action_at || 0)) < 900
      );
    }}

    function trimConsoleLine(value) {{
      return String(value || "")
        .replace(/\u001b\[[0-9;]*m/g, "")
        .replace(/\s+/g, " ")
        .trim();
    }}

    function activitySignalLines(value, limit = 6) {{
      const rawLines = String(value || "")
        .replace(/\\r\\n/g, "\\n")
        .split("\\n")
        .map(trimConsoleLine)
        .filter(Boolean);
      const lines = [];
      for (let index = rawLines.length - 1; index >= 0; index -= 1) {{
        const line = rawLines[index];
        const lower = line.toLowerCase();
        if (
          lower === "ready."
          || lower === "web prompt completed."
          || lower === "[waiting for reply]"
          || lower === "[no response returned]"
          || lower.includes("healthz")
        ) {{
          continue;
        }}
        if (lines[0] === line) {{
          continue;
        }}
        lines.unshift(line);
        if (lines.length >= limit) {{
          break;
        }}
      }}
      return lines;
    }}

    function activityElapsed(snapshot) {{
      const started = Number(snapshot.last_started_at || 0);
      if (!started) {{
        return 0;
      }}
      return Math.max(0, Math.round((Date.now() / 1000) - started));
    }}

    function formatElapsedCompact(seconds) {{
      const clean = Math.max(0, Number(seconds || 0));
      if (!clean) {{
        return "just now";
      }}
      if (clean < 60) {{
        return `${{clean}}s`;
      }}
      const minutes = Math.floor(clean / 60);
      const remain = clean % 60;
      if (!remain) {{
        return `${{minutes}}m`;
      }}
      return `${{minutes}}m ${{remain}}s`;
    }}

    function inferWorkingStage(snapshot) {{
      const elapsed = activityElapsed(snapshot);
      const attachmentCount = Array.isArray(snapshot.running_attachments)
        ? snapshot.running_attachments.length
        : 0;
      const paneSignals = activitySignalLines(snapshot.pane, 6);
      const logSignals = activitySignalLines(snapshot.logs, 6);
      const signal = paneSignals[paneSignals.length - 1] || logSignals[logSignals.length - 1] || "";
      const lower = signal.toLowerCase();
      if (lower.includes("sign in") || lower.includes("device code")) {{
        return {{
          line: "Waiting on sign-in",
          note: signal || "The runtime is blocked on authentication.",
          step: "Finish auth",
        }};
      }}
      if (/(apply_patch|updating file|move to:|added file|deleted file)/i.test(signal)) {{
        return {{
          line: "Applying edits",
          note: signal,
          step: "Write changes",
        }};
      }}
      if (/\b(pytest|make test|npm test|make lint|make format|ruff|black|eslint|journalctl|systemctl|git|rg|grep|sed|ssh|scp|rsync|curl)\b/i.test(signal)) {{
        return {{
          line: "Running tools",
          note: signal,
          step: "Run checks",
        }};
      }}
      if (/(capture|screenshot|snapshot|attachment|upload|clipboard|paste|image)/i.test(signal)) {{
        return {{
          line: "Staging context",
          note: signal,
          step: "Read context",
        }};
      }}
      if (attachmentCount > 0 && elapsed < 8) {{
        return {{
          line: attachmentCount === 1 ? "Reading staged context" : `Reading ${{attachmentCount}} staged items`,
          note: attachmentCount === 1 ? "One attachment is being folded into the turn." : `${{attachmentCount}} staged items are being folded into the turn.`,
          step: "Read context",
        }};
      }}
      if (elapsed <= 3) {{
        return {{
          line: "Sending to worker",
          note: "The bridge is handing the turn into the live worker session.",
          step: "Send",
        }};
      }}
      if (elapsed <= 18) {{
        return {{
          line: "Thinking",
          note: signal || "Codex is reasoning before it starts writing back.",
          step: "Think",
        }};
      }}
      if (elapsed <= 75) {{
        return {{
          line: "Building reply",
          note: signal || "The worker is still in the middle of the turn.",
          step: "Reply",
        }};
      }}
      return {{
        line: "Still running",
        note: signal || "Longer-running turn. Open the live tail if you want the raw feed.",
        step: "Reply",
      }};
    }}

    function buildActivityInsight(snapshot) {{
      const queueDepth = Number(snapshot.queue_depth || 0);
      const queued = queuedEntries(snapshot);
      if (snapshot.pending) {{
        const stage = inferWorkingStage(snapshot);
        const elapsed = activityElapsed(snapshot);
        const startedParts = [];
        if (snapshot.last_started_at) {{
          startedParts.push(`started ${{formatTs(snapshot.last_started_at)}}`);
        }}
        if (elapsed > 0) {{
          startedParts.push(`${{formatElapsedCompact(elapsed)}} in flight`);
        }}
        if (queueDepth > 0) {{
          startedParts.push(queueDepth === 1 ? "1 queued next" : `${{queueDepth}} queued next`);
        }}
        startedParts.push(snapshot.model_process_alive ? "model process alive" : "waiting for model process");
        const queuePreview = queued.slice(0, 3).map((item, index) => {{
          const source = String(item?.source || "operator").toLowerCase();
          const sourceLabel = source === "passive" || source === "relay" ? "passive/BBS" : source === "recovered" ? "recovered" : "operator";
          return `${{index + 1}}. ${{sourceLabel}} · ${{summarizePrompt(item?.prompt || "", 72)}}`;
        }});
        const attachments = Array.isArray(snapshot.running_attachments)
          ? snapshot.running_attachments.length
          : 0;
        const steps = [
          {{
            label: "Accepted",
            note: "The web bridge handed the turn into the live tmux session.",
            state: "done",
          }},
          {{
            label: attachments > 0 ? `Read ${{attachments}} item${{attachments === 1 ? "" : "s"}}` : "Read prompt",
            note: attachments > 0 ? "Attachments are folded into the turn before the reply comes back." : "No extra staged context on this turn.",
            state: elapsed >= 2 ? "done" : "active",
          }},
          {{
            label: stage.step,
            note: stage.note,
            state: "active",
          }},
          {{
            label: "Return reply",
            note: "The response lands here as soon as the worker finishes.",
            state: "upnext",
          }},
        ];
        return {{
          mode: "working",
          stripTitle: stage.line,
          stripDetail: [
            responseProfileText(snapshot.running_speed, snapshot.running_detail),
            startedParts.find((item) => item.includes("in flight")) || "",
            attachments > 0 ? `+${{attachments}} item${{attachments === 1 ? "" : "s"}}` : "",
            queueDepth > 0 ? `+${{queueDepth}} queued` : "",
            snapshot.model_process_alive ? "model alive" : "model pending",
            !elapsed && snapshot.last_started_at ? `started ${{formatTs(snapshot.last_started_at)}}` : "",
          ].filter(Boolean).join(" · "),
          peekTitle: "Background",
          simLine: `Running: ${{summarizePrompt(snapshot.running_prompt || "", 120)}}`,
          simMeta: [...startedParts, ...queuePreview],
          steps,
          logText: activitySignalLines(snapshot.logs, 10).join("\\n") || "[no log tail yet]",
          paneText: activitySignalLines(snapshot.pane, 12).join("\\n") || "[no live pane lines yet]",
          logSummary: "Open the live tail only if you want the raw feed.",
        }};
      }}
      if (recentConsoleAction(snapshot)) {{
        return {{
          mode: "console",
          stripTitle: "Console action",
          stripDetail: [snapshot.last_action_detail || "Recent console action completed.", snapshot.last_action_at ? formatTs(snapshot.last_action_at) : ""].filter(Boolean).join(" · "),
          peekTitle: "Console",
          simLine: snapshot.last_action_detail || "Recent operator action completed.",
          simMeta: snapshot.last_action_at ? [`last touched ${{formatTs(snapshot.last_action_at)}}`] : [],
          steps: [
            {{
              label: snapshot.last_action || "console action",
              note: snapshot.last_action_detail || "Recent operator action completed.",
              state: "done",
            }},
          ],
          logText: activitySignalLines(snapshot.logs, 8).join("\\n") || "[no log tail yet]",
          paneText: activitySignalLines(snapshot.pane, 8).join("\\n") || "[no live pane lines yet]",
          logSummary: "The raw tail is here if you want to verify the operator action.",
        }};
      }}
      if (queueDepth > 0) {{
        const queuePreview = queued.slice(0, 4).map((item, index) => {{
          const source = String(item?.source || "operator").toLowerCase();
          const sourceLabel = source === "passive" || source === "relay" ? "passive/BBS" : source === "recovered" ? "recovered" : "operator";
          return `${{index + 1}}. ${{sourceLabel}} · ${{summarizePrompt(item?.prompt || "", 82)}}`;
        }});
        return {{
          mode: "queue",
          stripTitle: "Queued",
          stripDetail: queueDepth === 1 ? "1 prompt is waiting to run next." : `${{queueDepth}} prompts are waiting to run next.`,
          peekTitle: "Queue",
          simLine: queueDepth === 1 ? "One prompt is parked behind the active turn." : `${{queueDepth}} prompts are parked behind the active turn.`,
          simMeta: ["They will run in order as the worker frees up.", ...queuePreview],
          steps: [
            {{
              label: "Current turn finishes first",
              note: "Queued work only moves once the running turn clears.",
              state: "active",
            }},
            {{
              label: queueDepth === 1 ? "Run the queued follow-up" : `Run ${{queueDepth}} queued follow-ups`,
              note: "The queue is preserved by the bridge.",
              state: "upnext",
            }},
          ],
          logText: activitySignalLines(snapshot.logs, 6).join("\\n") || "[no log tail yet]",
          paneText: activitySignalLines(snapshot.pane, 6).join("\\n") || "[no live pane lines yet]",
          logSummary: "You can inspect the raw tail, but most of the time the queue note above is enough.",
        }};
      }}
      const broker = brokerInsight(snapshot);
      if (broker) {{
        const steps = [
          {{
            label: "Keep the current read narrow",
            note: "This bot has enough context to know it needs another surface, but not enough to safely pull it itself.",
            state: "done",
          }},
          {{
            label: "Broker through Norman Prime",
            note: "Use Norman Prime and the Switchboard to decide whether this should become a Switchboard handoff, a direct peer request, or a blocked cross-lane jump.",
            state: "active",
          }},
          {{
            label: RELAY_TARGETS.length ? "Open a linked bot if needed" : "Bring the other surface in deliberately",
            note: broker.linkedSummary,
            state: "upnext",
          }},
        ];
        return {{
          mode: "broker",
          stripTitle: "Broker through Norman",
          stripDetail: broker.detail,
          peekTitle: "Handoff",
          simLine: broker.copy,
          simMeta: [broker.linkedSummary],
          steps,
          logText: activitySignalLines(snapshot.logs, 6).join("\\n") || "[no log tail yet]",
          paneText: activitySignalLines(snapshot.pane, 6).join("\\n") || "[no live pane lines yet]",
          logSummary: "Use the raw tail only if you need to verify the broker path or latest pane state.",
          actions: noticeActionDescriptors("broker"),
        }};
      }}
      return null;
    }}

    function compactActivityStepLabel(label) {{
      const text = String(label || "").trim().replace(/\s+/g, " ");
      if (!text) {{
        return "";
      }}
      const seed = text.split(" ").slice(0, 4).join(" ");
      return summarizePrompt(seed, 24);
    }}

    function activityStepProgress(steps) {{
      const items = Array.isArray(steps) ? steps : [];
      if (!items.length) {{
        return 0;
      }}
      let score = 0;
      for (const step of items) {{
        const stateName = String(step.state || "upnext");
        if (stateName === "done") {{
          score += 1;
        }} else if (stateName === "active") {{
          score += 0.55;
        }}
      }}
      const ratio = Math.max(0.08, Math.min(1, score / items.length));
      return Math.round(ratio * 100);
    }}

    function activityTrackSummary(steps) {{
      const items = Array.isArray(steps) ? steps : [];
      if (!items.length) {{
        return "";
      }}
      const active = items.find((step) => String(step.state || "") === "active");
      const doneCount = items.filter((step) => String(step.state || "") === "done").length;
      const lead = active || items[items.length - 1];
      const currentCount = Math.max(doneCount + (active ? 1 : 0), items.length && !active ? items.length : 0);
      return `${{currentCount}}/${{items.length}} · ${{compactActivityStepLabel(lead.label || "") || "Working"}}`;
    }}

    function renderActivityPeek(snapshot, insight) {{
      const activeInsight = insight || buildActivityInsight(snapshot);
      const shouldShow = Boolean(activeInsight) && state.activityPeekOpen;
      el.activityPeek.classList.toggle("visible", shouldShow);
      el.activityPeek.hidden = !shouldShow;
      el.activityPeekToggle.hidden = !activeInsight;
      el.activityPeekToggle.textContent = shouldShow ? "Hide" : "Peek";
      if (!activeInsight) {{
        el.activityPeekTitle.textContent = "Background";
        el.activitySimLine.textContent = "";
        el.activitySimMeta.textContent = "";
        el.activitySteps.innerHTML = "";
        el.activityLogOutput.textContent = "";
        el.activityPaneOutput.textContent = "";
        return;
      }}
      el.activityPeekTitle.textContent = activeInsight.peekTitle || "Background";
      el.activitySimLine.textContent = activeInsight.simLine || "";
      el.activitySimMeta.innerHTML = (Array.isArray(activeInsight.simMeta) ? activeInsight.simMeta : [])
        .filter(Boolean)
        .map((item) => `<span>${{escapeHtml(String(item))}}</span>`)
        .join("");
      el.activitySteps.innerHTML = (Array.isArray(activeInsight.steps) ? activeInsight.steps : []).map((step) => `
        <div class="activity-step is-${{escapeHtml(String(step.state || "upnext"))}}">
          <span class="activity-step-dot"></span>
          <div class="activity-step-copy">
            <div class="activity-step-label">${{escapeHtml(String(step.label || ""))}}</div>
            <div class="activity-step-note">${{renderInlineMarkup(String(step.note || ""))}}</div>
          </div>
        </div>
      `).join("");
      el.activityLogOutput.textContent = activeInsight.logText || "[no log tail yet]";
      el.activityPaneOutput.textContent = activeInsight.paneText || "[no live pane lines yet]";
    }}

    function renderActivityStrip(snapshot) {{
      const insight = buildActivityInsight(snapshot);
      const renderKey = insight ? JSON.stringify(insight) : "none";
      if (state.renderCache.activity === renderKey) {{
        return;
      }}
      state.renderCache.activity = renderKey;
      if (!insight) {{
        el.activityStrip.className = "activity-strip";
        el.activityStrip.classList.remove("visible");
        el.activityTitle.textContent = "";
        el.activityDetail.textContent = "";
        if (el.activityTrack) {{
          el.activityTrack.hidden = true;
          el.activityTrack.innerHTML = "";
        }}
        if (el.activityActions) {{
          el.activityActions.querySelectorAll(".activity-inline-action").forEach((node) => node.remove());
        }}
        state.activityPeekOpen = false;
        renderActivityPeek(snapshot, null);
        scheduleComposerReserve({{ preserveLiveEdge: true }});
        return;
      }}
      el.activityStrip.className = `activity-strip visible ${{insight.mode}}`;
      el.activityTitle.textContent = insight.stripTitle || "";
      el.activityDetail.textContent = insight.stripDetail || "";
      if (el.activityTrack) {{
        const trackSteps = Array.isArray(insight.steps) ? insight.steps.slice(0, 4) : [];
        el.activityTrack.hidden = trackSteps.length === 0;
        if (trackSteps.length) {{
          const progress = activityStepProgress(trackSteps);
          const summary = activityTrackSummary(trackSteps);
          const title = trackSteps.map((step) => compactActivityStepLabel(step.label || "")).filter(Boolean).join(" → ");
          el.activityTrack.innerHTML = `
            <span class="activity-track-bar" aria-hidden="true">
              <span class="activity-track-fill" style="width: ${{progress}}%"></span>
            </span>
            <span class="activity-track-summary" title="${{escapeHtml(title)}}">${{escapeHtml(summary)}}</span>
          `;
        }} else {{
          el.activityTrack.innerHTML = "";
        }}
      }}
      if (el.activityActions) {{
        el.activityActions.querySelectorAll(".activity-inline-action").forEach((node) => node.remove());
        const actions = Array.isArray(insight.actions) ? insight.actions : [];
        if (state.activityPeekOpen) {{
          for (const descriptor of actions) {{
            const control = buildInlineAction(descriptor, "activity-peek-toggle activity-inline-action");
            el.activityActions.insertBefore(control, el.activityPeekToggle);
          }}
        }}
      }}
      renderActivityPeek(snapshot, insight);
      scheduleComposerReserve({{ preserveLiveEdge: true }});
    }}

    function renderSuggestions(snapshot) {{
      const activeCount = historyEntries(snapshot).length + queuedEntries(snapshot).length + (snapshot.pending ? 1 : 0);
      const draftAttachmentCount = Array.isArray(snapshot?.draft_attachments) ? snapshot.draft_attachments.length : 0;
      const promptHasText = Boolean(el.promptInput.value.trim());
      const samplePromptsHidden = (
        activeCount > 0
        || draftAttachmentCount > 0
        || state.preferences.viewMode === "stage"
        || state.toolbarExpanded
        || promptHasText
      );
      const hidden = (
        activeCount > 0
        || draftAttachmentCount > 0
        || state.preferences.viewMode === "stage"
        || !state.promptFocused
        || promptHasText
      );
      const renderKey = JSON.stringify({{
        hidden,
        activeCount,
        draftAttachmentCount,
        viewMode: String(state.preferences?.viewMode || ""),
        promptFocused: Boolean(state.promptFocused),
        samplePromptsHidden,
        toolbarExpanded: Boolean(state.toolbarExpanded),
        promptHasText,
      }});
      if (state.renderCache.suggestions === renderKey) {{
        return;
      }}
      state.renderCache.suggestions = renderKey;
      el.promptSuggestions.hidden = hidden;
      if (el.samplePromptStrip) {{
        el.samplePromptStrip.hidden = samplePromptsHidden;
      }}
    }}

    function renderDraftAttachments(snapshot) {{
      const attachments = Array.isArray(snapshot.draft_attachments) ? snapshot.draft_attachments : [];
      const renderKey = attachmentSignature(attachments);
      if (state.renderCache.draftAttachments === renderKey) {{
        return;
      }}
      state.renderCache.draftAttachments = renderKey;
      renderAttachmentChips(
        el.draftAttachments,
        attachments,
        {{ removable: true }}
      );
    }}

    function setBusyButtons(isBusy) {{
      const busy = Boolean(isBusy) || state.attachmentBusy;
      el.askButton.disabled = busy;
      if (state.attachmentBusy) {{
        setAskButtonState("Attaching files…", "…");
      }} else if (isBusy) {{
        setAskButtonState(
          state.snapshot.pending ? "Queue next prompt…" : "Sending prompt…",
          "…"
        );
      }} else {{
        setAskButtonState(
          state.snapshot.pending ? "Queue" : "Next",
          state.snapshot.pending ? "+" : "→"
        );
      }}
      el.askButton.classList.toggle("pending", busy);
      el.tmuxSendButton.disabled = busy;
      const queueDepth = Number(state.snapshot.queue_depth || 0);
      el.cancelWebButton.disabled = busy || !state.snapshot.pending;
      el.clearQueueButton.disabled = busy || queueDepth <= 0;
      el.cancelAllButton.disabled = busy || (!state.snapshot.pending && queueDepth <= 0);
      el.promoteLatestButton.disabled = busy || queueDepth <= 1;
      el.interruptButton.disabled = busy;
      el.restartButton.disabled = busy;
      el.refreshButton.disabled = busy;
    }}

    function autoresize(textarea) {{
      textarea.style.height = "auto";
      const minimum = window.innerWidth <= 640 ? 52 : 54;
      const maximum = window.innerWidth <= 640
        ? (state.keyboardOpen ? 128 : 160)
        : 176;
      const target = Math.min(Math.max(textarea.scrollHeight, minimum), maximum);
      textarea.style.height = `${{target}}px`;
      scheduleComposerReserve();
    }}

    function render(snapshot) {{
      const nextThreadId = String(snapshot.thread_id || "");
      if (nextThreadId !== String(state.activeThreadId || "")) {{
        state.activeThreadId = nextThreadId;
        state.initialBottomSnapDone = false;
        state.initialViewportSettleDone = false;
        state.historyExpanded = false;
        state.userPinnedHistory = false;
      }}
      syncNotifications(snapshot);
      state.snapshot = snapshot;
      const auth = currentAuthState(snapshot);
      const [tone, label] = stateTone(snapshot);
      el.runState.className = `pill ${{tone}}`;
      el.runState.textContent = label;
      renderStatusActionPanel(snapshot);
      updateTabChrome(snapshot);
      const queueDepth = Number(snapshot.queue_depth || 0);
      const consoleActionActive = recentConsoleAction(snapshot);
      const draftAttachmentCount = Array.isArray(snapshot.draft_attachments)
        ? snapshot.draft_attachments.length
        : 0;
      let statusText = snapshot.status_message || "Ready.";
      if (snapshot.pending && snapshot.running_prompt) {{
        const elapsed = activityElapsed(snapshot);
        statusText = [
          `Running: ${{summarizePrompt(snapshot.running_prompt, 88)}}`,
          elapsed > 0 ? `${{formatElapsedCompact(elapsed)}} elapsed` : "",
          responseProfileText(snapshot.running_speed, snapshot.running_detail),
          snapshot.model_process_alive ? "model process alive" : "waiting for model process",
          "new messages queue",
        ].filter(Boolean).join(" · ");
      }} else if (snapshot.stale_queue) {{
        statusText = "Recovered queued work after restart. Review the queue before resuming or clearing it.";
      }} else if (auth.required) {{
        statusText = auth.summary || "Sign in is required for this console.";
      }} else if (consoleActionActive) {{
        statusText = snapshot.last_action_detail
          ? `Console: ${{snapshot.last_action_detail}}`
          : "Recent console action completed.";
      }} else if (draftAttachmentCount > 0) {{
        statusText = draftAttachmentCount === 1
          ? "Ready. 1 attachment staged."
          : `Ready. ${{draftAttachmentCount}} attachments staged.`;
      }} else if (snapshot.last_finished_at) {{
        statusText = `Ready. Last reply ${{formatTs(snapshot.last_finished_at)}} · ${{responseProfileText(snapshot.last_speed, snapshot.last_detail)}}`;
      }}
      if (snapshot.pending && queueDepth > 0) {{
        statusText += ` ${{
          queueDepth === 1 ? "1 queued." : `${{queueDepth}} queued.`
        }}`;
      }}
      el.statusMessage.textContent = statusText;
      document.body.classList.toggle(
        "quiet-status",
        Boolean(snapshot.thread_id)
          && !snapshot.pending
          && !consoleActionActive
          && draftAttachmentCount === 0
          && queueDepth === 0
          && !snapshot.last_error
      );

      el.threadIdHead.textContent = snapshot.thread_id || "thread not started";
      el.lastUpdatedHead.textContent = snapshot.updated_at ? `updated ${{formatTs(snapshot.updated_at)}}` : "waiting for first update";
      el.systemSummary.textContent = summarizeServices(snapshot.services);
      const sessionProfile = snapshot.pending
        ? responseProfileText(snapshot.running_speed, snapshot.running_detail)
        : responseProfileText(state.preferences.responseSpeed, state.preferences.responseDetail);
      el.chatSessionChip.textContent = snapshot.thread_id
        ? `${{CHAT_MODEL}} · ${{snapshot.thread_id.slice(0, 8)}}…`
        : `${{CHAT_MODEL}} · ${{ACTIVE_PROFILE_LABEL}}`;
      if (snapshot.pending) {{
        el.chatActivityChip.textContent = queueDepth > 0
          ? `Working · ${{responseProfileText(snapshot.running_speed, snapshot.running_detail)}} · +${{queueDepth}}`
          : `Working · ${{responseProfileText(snapshot.running_speed, snapshot.running_detail)}}`;
      }} else if (auth.required) {{
        el.chatActivityChip.textContent = auth.mode === "device_code" ? "Device code" : "Needs sign-in";
      }} else if (consoleActionActive) {{
        el.chatActivityChip.textContent = snapshot.last_action_at
          ? `Console action · ${{formatTs(snapshot.last_action_at)}}`
          : "Recent console action";
      }} else if (draftAttachmentCount > 0) {{
        el.chatActivityChip.textContent = draftAttachmentCount === 1
          ? "Ready · 1 staged"
          : `Ready · ${{draftAttachmentCount}} staged`;
      }} else if (snapshot.last_finished_at) {{
        el.chatActivityChip.textContent = `Idle · ${{responseProfileText(snapshot.last_speed, snapshot.last_detail)}}`;
      }} else {{
        el.chatActivityChip.textContent = `Ready · next ${{responseProfileText(state.preferences.responseSpeed, state.preferences.responseDetail)}}`;
      }}
      el.chatActivityChip.hidden = !snapshot.pending && !consoleActionActive && draftAttachmentCount === 0;
      renderContextMeter(snapshot);
      renderStatusCapsules(snapshot);
      if (el.chatSummaryBar) {{
        const contextHidden = !el.contextMeterChip || el.contextMeterChip.hidden;
        const saveHidden = !el.contextSaveButton || el.contextSaveButton.hidden;
        el.chatSummaryBar.hidden = el.chatActivityChip.hidden && contextHidden && saveHidden;
      }}

      el.lastError.innerHTML = renderPreformattedText(snapshot.last_error || "[none]");
      el.copyPromptButton.disabled = !snapshot.last_prompt || snapshot.last_prompt === "[no prompt yet]";
      el.copyResponseButton.disabled = !snapshot.last_response || snapshot.last_response === "[no response yet]";
      el.errorDetails.open = Boolean(snapshot.last_error);

      const preserveSelection = selectionActiveInUi();
      if (!preserveSelection) {{
        const promptResponseKey = JSON.stringify({{
          last_prompt: textBlockSignature(snapshot.last_prompt || "[no prompt yet]"),
          last_response: textBlockSignature(snapshot.last_response || "[no response yet]"),
          last_error: textBlockSignature(snapshot.last_error || "[none]"),
          pane: textBlockSignature(snapshot.pane || "[pane unavailable]"),
          logs: textBlockSignature(snapshot.logs || "[no journal output]"),
        }});
        if (state.renderCache.promptResponse !== promptResponseKey) {{
          state.renderCache.promptResponse = promptResponseKey;
          el.lastPrompt.dataset.raw = snapshot.last_prompt || "[no prompt yet]";
          el.lastResponse.dataset.raw = snapshot.last_response || "[no response yet]";
          el.lastPrompt.innerHTML = renderPlainTextWithSecrets(el.lastPrompt.dataset.raw);
          el.lastResponse.innerHTML = renderPlainTextWithSecrets(el.lastResponse.dataset.raw);
          renderLinkStrip(el.lastPromptLinks, extractUrls(el.lastPrompt.dataset.raw));
          renderLinkStrip(el.lastResponseLinks, extractUrls(el.lastResponse.dataset.raw));
          el.lastError.innerHTML = renderPreformattedText(snapshot.last_error || "[none]");
          el.paneOutput.innerHTML = renderPreformattedText(snapshot.pane || "[pane unavailable]");
          el.journalOutput.innerHTML = renderPreformattedText(snapshot.logs || "[no journal output]");
        }}
        renderConversation(snapshot);
        state.deferredSnapshot = null;
      }} else {{
        state.deferredSnapshot = snapshot;
      }}
      renderNoticeRail(snapshot);
      renderActivityStrip(snapshot);
      renderSuggestions(snapshot);
      renderDraftAttachments(snapshot);
      updateAuthActions(snapshot);
      applyPreferences();

      const servicesKey = JSON.stringify(
        Array.isArray(snapshot.services)
          ? snapshot.services.map((item) => [String(item?.name || ""), String(item?.state || "")])
          : []
      );
      if (state.renderCache.services !== servicesKey) {{
        state.renderCache.services = servicesKey;
        el.services.innerHTML = "";
        for (const item of snapshot.services || []) {{
          const chip = document.createElement("span");
          chip.className = `service-chip ${{serviceTone(item.state)}}`;
          chip.textContent = `${{item.name}}: ${{item.state}}`;
          el.services.appendChild(chip);
        }}
      }}
      renderSystemRuntimeMetrics(snapshot);

      scheduleComposerReserve();
      setBusyButtons(false);
    }}

    async function fetchStatus() {{
      const res = await fetch(`${{clientPath("/api/status")}}?token=${{encodeURIComponent(TOKEN)}}`, {{ cache: "no-store" }});
      if (res.status === 401 || res.status === 403) {{
        triggerAuthRefresh("Authentication expired. Reloading console…");
        throw new Error("authentication required");
      }}
      if (!res.ok) {{
        throw new Error(`status ${{res.status}}`);
      }}
      return await res.json();
    }}

    async function fetchKpis() {{
      const res = await fetch(`${{clientPath("/api/kpis")}}?token=${{encodeURIComponent(TOKEN)}}`, {{ cache: "no-store" }});
      if (res.status === 404) {{
        return state.snapshot?.kpis || {{}};
      }}
      if (res.status === 401 || res.status === 403) {{
        triggerAuthRefresh("Authentication expired. Reloading console…");
        throw new Error("authentication required");
      }}
      if (!res.ok) {{
        throw new Error(`kpis ${{res.status}}`);
      }}
      return await res.json();
    }}

    async function refreshStatusActions(options = {{}}) {{
      state.statusActionBusy = true;
      renderStatusActionPanel(state.snapshot);
      try {{
        const statusPromise = fetchStatus().catch(() => state.snapshot);
        const kpiPromise = fetchKpis().catch(() => state.snapshot?.kpis || {{}});
        const [snapshot, kpis] = await Promise.all([statusPromise, kpiPromise]);
        if (kpis && typeof kpis === "object" && Object.keys(kpis).length) {{
          state.statusKpis = kpis;
        }}
        if (snapshot && typeof snapshot === "object") {{
          render(snapshot);
        }} else {{
          renderStatusActionPanel(state.snapshot);
        }}
      }} catch (err) {{
        el.statusMessage.textContent = `Status check failed: ${{err.message}}`;
      }} finally {{
        state.statusActionBusy = false;
        if (options.keepOpen) {{
          state.statusPanelOpen = true;
        }}
        renderStatusActionPanel(state.snapshot);
      }}
    }}

    function statusActionContextText(kind, descriptor) {{
      const signals = descriptor.signals.length
        ? descriptor.signals.map((signal) => `${{signal.code || signal.severity || "signal"}}: ${{signal.summary || signal.detail || ""}}`).join("\\n")
        : "none";
      const services = descriptor.badServices.length
        ? descriptor.badServices.join(", ")
        : "none";
      const base = [
        `Agent: ${{AGENT_LABEL}}`,
        `Bridge state: ${{descriptor.stateName}}`,
        `Summary: ${{descriptor.summary}}`,
        `Queue depth: ${{descriptor.queueDepth}}`,
        `Signals:\\n${{signals}}`,
        `Service issues: ${{services}}`,
      ].join("\\n");
      if (kind === "handle") {{
        return [
          `Handle the current TUI status for ${{AGENT_LABEL}}.`,
          "",
          base,
          "",
          "Take the next concrete safe action. If this is blocked by auth, credentials, approvals, or missing operator context, say exactly what is needed. Otherwise recover or fix what you can, then report the result briefly.",
        ].join("\\n");
      }}
      return [
        `Give operator status for ${{AGENT_LABEL}}.`,
        "",
        base,
        "",
        "Return: current state, whether anything is wedged or blocked, what is running in the background, and the next useful action. Keep it concise.",
      ].join("\\n");
    }}

    async function submitStatusAction(kind) {{
      const descriptor = statusActionDescriptor(state.snapshot);
      const message = statusActionContextText(kind, descriptor);
      const speed = normalizeResponseSpeed(state.preferences.responseSpeed);
      const detail = normalizeResponseDetail(state.preferences.responseDetail);
      state.statusActionBusy = true;
      setStatusActionOpen(false);
      setBusyButtons(false);
      el.statusMessage.textContent = kind === "handle"
        ? "Sending status recovery prompt…"
        : "Asking for operator status…";
      try {{
        const result = await postForm("/api/ask", {{ message, speed, detail: String(detail) }});
        if (result.snapshot) {{
          render(result.snapshot);
        }}
        if (!result.accepted) {{
          el.statusMessage.textContent = result.error || "Status prompt could not be accepted.";
        }}
      }} catch (err) {{
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Status action failed: ${{err.message}}`;
      }} finally {{
        state.statusActionBusy = false;
        renderStatusActionPanel(state.snapshot);
        schedulePoll(1200);
      }}
    }}

    async function postForm(path, payload) {{
      const body = new URLSearchParams({{ token: TOKEN, ...payload }});
      const res = await fetch(clientPath(path), {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }},
        body,
      }});
      let data = {{}};
      const contentType = res.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {{
        data = await res.json();
      }}
      if (res.status === 401 || res.status === 403) {{
        triggerAuthRefresh("Authentication expired. Reloading console…");
        throw new Error("authentication required");
      }}
      if (!res.ok) {{
        throw new Error(data.error || `request failed (${{res.status}})`);
      }}
      return data;
    }}

    async function postJson(path, payload) {{
      const res = await fetch(clientPath(path), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json;charset=UTF-8" }},
        body: JSON.stringify({{ token: TOKEN, ...payload }}),
      }});
      const contentType = res.headers.get("content-type") || "";
      let data = {{}};
      if (contentType.includes("application/json")) {{
        data = await res.json();
      }}
      if (res.status === 401 || res.status === 403) {{
        triggerAuthRefresh("Authentication expired. Reloading console…");
        throw new Error("authentication required");
      }}
      if (!res.ok) {{
        throw new Error(data.error || `request failed (${{res.status}})`);
      }}
      return data;
    }}

    function fileToBase64(file) {{
      return new Promise((resolve, reject) => {{
        const reader = new FileReader();
        reader.onload = () => {{
          const result = String(reader.result || "");
          const parts = result.split(",", 2);
          resolve(parts.length === 2 ? parts[1] : "");
        }};
        reader.onerror = () => reject(new Error("file read failed"));
        reader.readAsDataURL(file);
      }});
    }}

    async function uploadAttachment(payload, waitingText, path = "/api/attachment") {{
      state.attachmentBusy = true;
      setBusyButtons(false);
      if (waitingText) {{
        el.statusMessage.textContent = waitingText;
      }}
      try {{
        const result = await postJson(path, payload);
        if (result.snapshot) {{
          render(result.snapshot);
          if (state.snapshot.pending && Number(result.snapshot.queue_depth || 0) > 0) {{
            const position = Number(result.snapshot.queue_depth || 0);
            el.statusMessage.textContent = `Queued at position ${{position}}. Current web reply is still running.`;
          }}
        }}
        if (result.attachment) {{
          el.statusMessage.textContent = `Staged ${{attachmentDisplayName(result.attachment)}} · ready to send.`;
        }}
      }} catch (err) {{
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Attachment failed: ${{err.message}}`;
      }} finally {{
        state.attachmentBusy = false;
        setBusyButtons(false);
        schedulePoll(1200);
      }}
    }}

    async function uploadTextAttachment(text, options = {{}}) {{
      const body = String(text || "");
      if (!body.trim()) {{
        return;
      }}
      const fileName = options.name || "Clipboard paste";
      const kind = options.kind || "text";
      await uploadAttachment(
        {{
          name: fileName,
          content_type: options.contentType || "text/plain; charset=utf-8",
          kind,
          source: options.source || "paste-block",
          text: body,
        }},
        "Staging pasted text…"
      );
    }}

    function historyExportText(snapshot = state.snapshot) {{
      const lines = [
        `${{AGENT_LABEL}} session history`,
        `Generated: ${{new Date().toLocaleString()}}`,
        `Thread: ${{snapshot.thread_id || "not started"}}`,
        `State: ${{snapshot.state || "idle"}}`,
      ];
      const items = historyEntries(snapshot);
      if (!items.length) {{
        lines.push("", "[no history yet]");
        return lines.join("\\n");
      }}
      items.forEach((item, index) => {{
        lines.push("");
        lines.push(`Turn ${{index + 1}} · ${{formatTs(item.finished_at || item.started_at || 0) || "no timestamp"}} · ${{responseProfileText(item.speed, item.detail)}}`);
        lines.push("User:");
        lines.push(item.prompt || "[empty prompt]");
        if (Array.isArray(item.attachments) && item.attachments.length) {{
          lines.push("Attachments:");
          item.attachments.forEach((entry) => {{
            lines.push(`- ${{attachmentSummary(entry)}}`);
          }});
        }}
        if (item.response) {{
          lines.push("Reply:");
          lines.push(item.response);
        }}
        if (item.error) {{
          lines.push("Error:");
          lines.push(item.error);
        }}
      }});
      return lines.join("\\n");
    }}

    function captureUrlCandidates() {{
      const items = [];
      const seen = new Set();
      const push = (label, url) => {{
        const clean = normalizeUrlCandidate(url);
        if (!/^https?:\\/\\//i.test(clean) || seen.has(clean)) {{
          return;
        }}
        seen.add(clean);
        items.push({{ label: label || "Linked page", url: clean }});
      }};
      push(`${{AGENT_LABEL}} console`, window.location.href);
      document.querySelectorAll(".console-nav .quick-link, .settings-card .quick-link").forEach((link) => {{
        push(link.dataset.label || link.textContent.trim(), link.href);
      }});
      extractUrls(el.lastResponse?.dataset?.raw || "").forEach((url, index) => {{
        push(`Reply link ${{index + 1}}`, url);
      }});
      extractUrls(el.lastPrompt?.dataset?.raw || "").forEach((url, index) => {{
        push(`Prompt link ${{index + 1}}`, url);
      }});
      return items;
    }}

    async function captureUrlAttachment(url, label, waitingText) {{
      const clean = normalizeUrlCandidate(url);
      if (!/^https?:\\/\\//i.test(clean)) {{
        throw new Error("capture URL must start with http:// or https://");
      }}
      await uploadAttachment(
        {{
          url: clean,
          label: label || "Web capture",
        }},
        waitingText || `Capturing ${{label || "web page"}}…`,
        "/api/attachment/capture"
      );
    }}

    async function attachSnapshotText(kind) {{
      if (kind === "logs") {{
        await uploadTextAttachment(state.snapshot.logs || "", {{
          name: `${{AGENT_LABEL}} log tail.log`,
          source: "log-tail",
        }});
        return;
      }}
      if (kind === "history") {{
        await uploadTextAttachment(historyExportText(state.snapshot), {{
          name: `${{AGENT_LABEL}} history.txt`,
          source: "history-export",
        }});
        return;
      }}
      if (kind === "pane") {{
        await uploadTextAttachment(state.snapshot.pane || "", {{
          name: `${{AGENT_LABEL}} live pane.txt`,
          source: "pane-capture",
        }});
      }}
    }}

    async function uploadFiles(files, source) {{
      const list = Array.from(files || []);
      for (const file of list) {{
        const encoded = await fileToBase64(file);
        await uploadAttachment(
          {{
            name: file.name || "attachment",
            content_type: file.type || "application/octet-stream",
            source: source || "paste-file",
            data_b64: encoded,
          }},
          `Staging ${{file.name || "file"}}…`
        );
      }}
    }}

    function clipboardImageExtension(contentType) {{
      const mime = String(contentType || "").split(";", 1)[0].trim().toLowerCase();
      if (mime === "image/jpeg") {{
        return ".jpg";
      }}
      if (mime === "image/svg+xml") {{
        return ".svg";
      }}
      if (mime === "image/heic") {{
        return ".heic";
      }}
      if (mime === "image/heif") {{
        return ".heif";
      }}
      if (mime.startsWith("image/")) {{
        const suffix = mime.slice("image/".length).replace(/[^a-z0-9]+/g, "");
        return suffix ? `.${{suffix}}` : ".png";
      }}
      return ".png";
    }}

    function dedupeFiles(files) {{
      const seen = new Set();
      return Array.from(files || []).filter((file) => {{
        if (!file) {{
          return false;
        }}
        const signature = [
          file.name || "",
          String(file.size || 0),
          file.type || "",
          String(file.lastModified || 0),
        ].join("::");
        if (seen.has(signature)) {{
          return false;
        }}
        seen.add(signature);
        return true;
      }});
    }}

    function clipboardFilesFromEvent(event) {{
      const clipboard = event?.clipboardData;
      if (!clipboard) {{
        return [];
      }}
      const files = [];
      Array.from(clipboard.files || []).forEach((file) => {{
        if (file) {{
          files.push(file);
        }}
      }});
      if (files.length) {{
        return dedupeFiles(files);
      }}
      Array.from(clipboard.items || []).forEach((item) => {{
        if (!item || item.kind !== "file") {{
          return;
        }}
        const file = item.getAsFile();
        if (file) {{
          files.push(file);
        }}
      }});
      return dedupeFiles(files);
    }}

    async function readClipboardImageFiles() {{
      if (!navigator.clipboard || typeof navigator.clipboard.read !== "function") {{
        return [];
      }}
      try {{
        const items = await navigator.clipboard.read();
        const files = [];
        let fallbackIndex = 0;
        for (const item of items || []) {{
          const types = Array.from(item?.types || []);
          for (const type of types) {{
            const mime = String(type || "").trim().toLowerCase();
            if (!mime.startsWith("image/")) {{
              continue;
            }}
            const blob = await item.getType(type);
            if (!blob) {{
              continue;
            }}
            fallbackIndex += 1;
            files.push(new File(
              [blob],
              `Clipboard image ${{fallbackIndex}}${{clipboardImageExtension(mime)}}`,
              {{
                type: mime,
                lastModified: Date.now(),
              }}
            ));
          }}
        }}
        return dedupeFiles(files);
      }} catch (_) {{
        return [];
      }}
    }}

    async function readClipboardPlainText() {{
      if (!navigator.clipboard || typeof navigator.clipboard.readText !== "function") {{
        return "";
      }}
      try {{
        return String(await navigator.clipboard.readText() || "");
      }} catch (_) {{
        return "";
      }}
    }}

    async function removeAttachment(token) {{
      if (!token) {{
        return;
      }}
      state.attachmentBusy = true;
      setBusyButtons(false);
      el.statusMessage.textContent = `Removing [${{token}}]…`;
      try {{
        const result = await postForm("/api/attachment/remove", {{ attachment_token: token }});
        if (result.snapshot) {{
          render(result.snapshot);
        }}
      }} catch (err) {{
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Remove failed: ${{err.message}}`;
      }} finally {{
        state.attachmentBusy = false;
        setBusyButtons(false);
      }}
    }}

    function schedulePoll(delayMs) {{
      if (state.streamConnected && !document.hidden) {{
        clearTimeout(state.pollTimer);
        return;
      }}
      clearTimeout(state.pollTimer);
      const nextDelay = delayMs || (
        document.hidden
          ? (state.snapshot.pending ? 12000 : 30000)
          : (state.snapshot.pending ? VISIBLE_PENDING_STATUS_POLL_MS : VISIBLE_IDLE_STATUS_POLL_MS)
      );
      state.pollTimer = window.setTimeout(refreshStatus, nextDelay);
    }}

    function disconnectStream() {{
      clearTimeout(state.streamReconnectTimer);
      state.streamReconnectTimer = 0;
      if (state.stream) {{
        state.stream.close();
      }}
      state.stream = null;
      state.streamConnected = false;
    }}

    function scheduleStreamReconnect(delayMs = 1800) {{
      clearTimeout(state.streamReconnectTimer);
      if (document.hidden) {{
        return;
      }}
      state.streamReconnectTimer = window.setTimeout(() => {{
        state.streamReconnectTimer = 0;
        connectStream();
      }}, delayMs);
    }}

    function syncLiveTransport() {{
      if (document.hidden) {{
        disconnectStream();
        setTransportState(state.snapshot.pending ? "Background · waiting" : "Background", false);
        schedulePoll();
        return;
      }}
      connectStream();
      schedulePoll(1200);
    }}

    function connectStream() {{
      if (!window.EventSource) {{
        setTransportState("Polling", false);
        return;
      }}
      if (document.hidden) {{
        return;
      }}
      if (state.stream) {{
        return;
      }}
      clearTimeout(state.streamReconnectTimer);
      state.streamReconnectTimer = 0;
      const stream = new EventSource(`${{clientPath("/api/stream")}}?token=${{encodeURIComponent(TOKEN)}}`);
      state.stream = stream;
      setTransportState("Connecting…", false);

      stream.addEventListener("snapshot", (event) => {{
        try {{
          const snapshot = JSON.parse(event.data);
          state.streamConnected = true;
          setTransportState(snapshot.pending ? "Live · waiting" : "Live", true);
          clearTimeout(state.pollTimer);
          render(snapshot);
        }} catch (_) {{
          // Ignore malformed event payloads and let the fallback polling recover.
        }}
      }});

      stream.onerror = () => {{
        disconnectStream();
        setTransportState(document.hidden ? "Background" : "Reconnecting…", false);
        schedulePoll(900);
        scheduleStreamReconnect(1800);
      }};
    }}

    async function refreshStatus() {{
      try {{
        const snapshot = await fetchStatus();
        state.streamConnected = false;
        setTransportState(snapshot.pending ? "Polling · waiting" : "Polling", false);
        render(snapshot);
      }} catch (err) {{
        el.runState.className = "pill error";
        el.runState.textContent = "Offline";
        el.statusMessage.textContent = `Status refresh failed: ${{err.message}}`;
        setTransportState("Offline", false);
      }} finally {{
        schedulePoll();
      }}
    }}

    async function submitAsk(event) {{
      event.preventDefault();
      const message = el.promptInput.value.trim();
      const draftAttachments = Array.isArray(state.snapshot.draft_attachments)
        ? state.snapshot.draft_attachments
        : [];
      if (!message && !draftAttachments.length) return;
      const speed = normalizeResponseSpeed(state.preferences.responseSpeed);
      const detail = normalizeResponseDetail(state.preferences.responseDetail);
      const responseProfile = responseProfileText(speed, detail);
      state.transientOperatorBanner = "";
      setSystemOpen(false);
      el.askButton.disabled = true;
      setAskButtonState(
        state.snapshot.pending ? "Queueing next prompt…" : "Sending prompt…",
        "…"
      );
      el.statusMessage.textContent = state.snapshot.pending
        ? `Queueing follow-up prompt · ${{responseProfile}}…`
        : `Submitting prompt to ${{AGENT_LABEL}} · ${{responseProfile}}…`;
      try {{
        const result = await postForm("/api/ask", {{ message, speed, detail: String(detail) }});
        if (result.accepted) {{
          el.promptInput.value = "";
          autoresize(el.promptInput);
          state.toolbarExpanded = false;
          clearPromptDraft();
        }}
        if (result.snapshot) {{
          render(result.snapshot);
        }}
        if (!result.accepted) {{
          el.statusMessage.textContent = result.error || "A web prompt is already running.";
        }}
      }} catch (err) {{
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Send failed: ${{err.message}}`;
        setBusyButtons(false);
      }} finally {{
        schedulePoll(1200);
      }}
    }}

    function promptHasSubmissionPayload() {{
      if (el.promptInput.value.trim()) {{
        return true;
      }}
      const draftAttachments = Array.isArray(state.snapshot.draft_attachments)
        ? state.snapshot.draft_attachments
        : [];
      return draftAttachments.length > 0;
    }}

    function isEnterLikeKey(event) {{
      const key = String(event?.key || "");
      const code = String(event?.code || "");
      const keyCode = Number(event?.keyCode || event?.which || 0);
      return (
        key === "Enter"
        || key === "LineFeed"
        || code === "Enter"
        || code === "NumpadEnter"
        || keyCode === 13
      );
    }}

    function rememberPromptEnterMeta(event) {{
      if (!isEnterLikeKey(event)) {{
        return;
      }}
      state.promptEnterMeta = {{
        at: Date.now(),
        shiftKey: Boolean(event.shiftKey),
        altKey: Boolean(event.altKey),
        ctrlKey: Boolean(event.ctrlKey),
        metaKey: Boolean(event.metaKey),
        isComposing: Boolean(event.isComposing),
      }};
    }}

    function shouldSubmitPromptOnKeydown(event) {{
      if (!isEnterLikeKey(event)) {{
        return false;
      }}
      return !event.shiftKey
        && !event.altKey
        && !event.ctrlKey
        && !event.metaKey;
    }}

    function shouldSubmitPromptOnBeforeInput(event) {{
      const inputType = String(event?.inputType || "");
      if (inputType !== "insertLineBreak" && inputType !== "insertParagraph") {{
        return false;
      }}
      if (document.activeElement !== el.promptInput) {{
        return false;
      }}
      const meta = state.promptEnterMeta;
      if (!meta || Date.now() - meta.at > 450) {{
        return false;
      }}
      return !meta.shiftKey
        && !meta.altKey
        && !meta.ctrlKey
        && !meta.metaKey;
    }}

    function submitPromptFromKeyboard(event) {{
      if (el.askButton.disabled) {{
        event.preventDefault();
        return true;
      }}
      if (!promptHasSubmissionPayload()) {{
        return false;
      }}
      event.preventDefault();
      if (Date.now() - state.lastPromptSubmitAt < 300) {{
        return true;
      }}
      state.lastPromptSubmitAt = Date.now();
      event.stopPropagation();
      void submitAsk({{
        preventDefault() {{}},
      }});
      return true;
    }}

    async function submitTmux(event) {{
      event.preventDefault();
      const message = el.tmuxInput.value.trim();
      if (!message) return;
      state.transientOperatorBanner = `Console send in progress: ${{summarizePrompt(message, 88)}}`;
      renderActivityStrip(state.snapshot);
      el.statusMessage.textContent = "Sending raw text into tmux…";
      setBusyButtons(true);
      try {{
        const result = await postForm("/api/send", {{ message }});
        el.tmuxInput.value = "";
        autoresize(el.tmuxInput);
        if (result.snapshot) {{
          state.transientOperatorBanner = "";
          render(result.snapshot);
        }}
      }} catch (err) {{
        state.transientOperatorBanner = "Console action failed.";
        renderActivityStrip(state.snapshot);
        el.statusMessage.textContent = `tmux send failed: ${{err.message}}`;
        setBusyButtons(false);
      }} finally {{
        schedulePoll(1000);
      }}
    }}

    async function fireAction(path, label) {{
      state.transientOperatorBanner = label;
      renderActivityStrip(state.snapshot);
      el.statusMessage.textContent = label;
      setBusyButtons(true);
      try {{
        const result = await postForm(path, {{}});
        if (result.snapshot) {{
          state.transientOperatorBanner = "";
          render(result.snapshot);
        }}
      }} catch (err) {{
        state.transientOperatorBanner = "Console action failed.";
        renderActivityStrip(state.snapshot);
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `${{label}} failed: ${{err.message}}`;
        setBusyButtons(false);
      }} finally {{
        schedulePoll(1000);
      }}
    }}

    function startBrowserAuthFromConsole() {{
      if (!BROWSER_AUTH_BRIDGE_ALLOWED) {{
        el.statusMessage.textContent = "Browser sign-in is only available from Hal or the Plasma phone right now.";
        return;
      }}
      state.transientOperatorBanner = "Opening browser sign-in…";
      renderActivityStrip(state.snapshot);
      el.statusMessage.textContent = "Opening browser sign-in…";
      (async () => {{
        try {{
          const result = await postJson("/api/auth/browser", {{}});
          if (result.snapshot) {{
            state.transientOperatorBanner = "";
            render(result.snapshot);
          }}
          const snapshot = result.snapshot || state.snapshot;
          const auth = currentAuthState(snapshot);
          const snapshotState = String(snapshot?.state || "").trim().toLowerCase();
          if (!auth.required && snapshotState === "ok") {{
            el.statusMessage.textContent = "Already signed in.";
            return;
          }}
          const verificationUrl = String(auth.verification_url || "").trim();
          if (verificationUrl) {{
            const launchHref = browserAuthBridgeLaunchHref(verificationUrl);
            let popup = null;
            try {{
              popup = window.open("", "_blank", "noopener,noreferrer");
            }} catch (_) {{
              popup = null;
            }}
            el.statusMessage.textContent = launchHref.startsWith(browserAuthBridgeApiBase())
              ? "Browser sign-in opened. Local auth bridge armed."
              : "Browser sign-in opened.";
            if (popup) {{
              popup.location.replace(launchHref);
            }} else {{
              window.location.assign(launchHref);
            }}
          }} else {{
            el.statusMessage.textContent = auth.required
              ? "Browser sign-in was prepared, but no auth URL was returned. Refresh and retry."
              : "No browser sign-in was needed.";
          }}
        }} catch (err) {{
          state.transientOperatorBanner = "Auth action failed.";
          renderActivityStrip(state.snapshot);
          el.runState.className = "pill error";
          el.runState.textContent = "Error";
          el.statusMessage.textContent = `Browser sign-in failed: ${{err.message}}`;
          setBusyButtons(false);
        }} finally {{
          schedulePoll(1000);
        }}
      }})();
    }}

    async function startDeviceAuthFromConsole() {{
      state.transientOperatorBanner = "Preparing device code…";
      renderActivityStrip(state.snapshot);
      el.statusMessage.textContent = "Preparing device code…";
      setBusyButtons(true);
      try {{
        const result = await postJson("/api/auth/device", {{}});
        if (result.snapshot) {{
          state.transientOperatorBanner = "";
          render(result.snapshot);
        }}
        const auth = currentAuthState(result.snapshot || state.snapshot);
        if (auth.verification_url) {{
          window.open(auth.verification_url, "_blank", "noopener,noreferrer");
        }}
        el.statusMessage.textContent = auth.device_code
          ? `Device code ready: ${{auth.device_code}}`
          : "Device code sign-in is ready.";
      }} catch (err) {{
        state.transientOperatorBanner = "Auth action failed.";
        renderActivityStrip(state.snapshot);
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Device code failed: ${{err.message}}`;
        setBusyButtons(false);
      }} finally {{
        schedulePoll(1000);
      }}
    }}

    async function handlePromptPaste(event) {{
      const clipboard = event.clipboardData;
      const canReadClipboard =
        navigator.clipboard
        && (
          typeof navigator.clipboard.read === "function"
          || typeof navigator.clipboard.readText === "function"
        );
      if (!clipboard && !canReadClipboard) {{
        return;
      }}
      const reroutedPaste = Boolean(event && event.target && event.target !== el.promptInput);
      let files = clipboardFilesFromEvent(event);
      if (!files.length) {{
        files = await readClipboardImageFiles();
      }}
      if (files.length) {{
        event.preventDefault();
        await uploadFiles(files, "paste-file");
        return;
      }}
      let pastedText = clipboard ? clipboard.getData("text/plain") : "";
      if (!pastedText) {{
        pastedText = await readClipboardPlainText();
      }}
      if (reroutedPaste && pastedText) {{
        event.preventDefault();
        if (!looksLikeLargePaste(pastedText)) {{
          insertTextIntoPrompt(pastedText, {{ placeAtEnd: true }});
          return;
        }}
      }}
      if (!looksLikeLargePaste(pastedText)) {{
        return;
      }}
      event.preventDefault();
      await uploadTextAttachment(pastedText, {{
        name: "Clipboard paste",
        contentType: "text/plain; charset=utf-8",
        source: "paste-block",
      }});
    }}

    function editablePasteTarget(target) {{
      if (!target || !(target instanceof Element)) {{
        return false;
      }}
      if (target === el.promptInput || el.promptInput.contains(target)) {{
        return false;
      }}
      if (target.closest("#tmux-form")) {{
        return true;
      }}
      if (target.closest("input, textarea, [contenteditable='true'], [contenteditable=''], [role='textbox']")) {{
        return true;
      }}
      return false;
    }}

    function editableShortcutTarget(target = document.activeElement) {{
      if (!target || !(target instanceof Element)) {{
        return false;
      }}
      return Boolean(
        target.closest("input, textarea, [contenteditable='true'], [contenteditable=''], [role='textbox']")
      );
    }}

    function jumpToLatestConversation() {{
      if (state.historyExpanded) {{
        state.historyExpanded = false;
        render(state.snapshot);
      }}
      scrollConversationToBottom(true);
      settleViewportToLiveEdge(true);
    }}

    function shortcutEligibleTarget(event) {{
      if (!event || editableShortcutTarget(event.target) || selectionActiveInUi()) {{
        return false;
      }}
      return true;
    }}

    function openShortcutGuide() {{
      setTopbarMenuOpen(true);
      if (el.topbarMenu && typeof el.topbarMenu.scrollTo === "function") {{
        el.topbarMenu.scrollTo({{ top: 0, behavior: "smooth" }});
      }}
    }}

    function handleGlobalConsoleShortcut(event) {{
      if (!event || event.defaultPrevented || event.isComposing || event.repeat) {{
        return false;
      }}
      const key = String(event.key || "");
      const lowerKey = key.toLowerCase();
      const hasPrimaryModifier = Boolean(event.metaKey || event.ctrlKey);

      if (
        key === "/"
        && !hasPrimaryModifier
        && !event.altKey
        && !event.shiftKey
        && shortcutEligibleTarget(event)
      ) {{
        event.preventDefault();
        dismissTransientChrome();
        focusPromptInputAtEnd();
        return true;
      }}

      if (
        (key === "?" || (key === "/" && event.shiftKey))
        && !hasPrimaryModifier
        && !event.altKey
        && shortcutEligibleTarget(event)
      ) {{
        event.preventDefault();
        dismissTransientChrome();
        openShortcutGuide();
        return true;
      }}

      if (
        lowerKey === "k"
        && hasPrimaryModifier
        && !event.altKey
        && !editableShortcutTarget(event.target)
      ) {{
        event.preventDefault();
        setSwitcherOpen(true);
        return true;
      }}

      if (
        key === "End"
        && !hasPrimaryModifier
        && !event.altKey
        && !event.shiftKey
        && !editableShortcutTarget(event.target)
        && !selectionActiveInUi()
      ) {{
        event.preventDefault();
        jumpToLatestConversation();
        return true;
      }}

      return false;
    }}

    function isPasteShortcut(event) {{
      if (!event || event.defaultPrevented || event.repeat || event.isComposing) {{
        return false;
      }}
      const key = String(event.key || "").toLowerCase();
      if (key !== "v") {{
        return false;
      }}
      return Boolean(event.metaKey || event.ctrlKey);
    }}

    function primePromptForPasteShortcut(event) {{
      if (!isPasteShortcut(event)) {{
        return;
      }}
      if (editablePasteTarget(event.target)) {{
        return;
      }}
      if (document.activeElement === el.promptInput) {{
        return;
      }}
      el.promptInput.focus({{ preventScroll: true }});
      const length = el.promptInput.value.length;
      try {{
        el.promptInput.setSelectionRange(length, length);
      }} catch (_) {{
        // Selection APIs can fail on some mobile keyboards; focus is enough.
      }}
    }}

    function routePasteToPrompt(event) {{
      if (event && event.__normanPromptPasteRouted) {{
        return;
      }}
      if (event) {{
        event.__normanPromptPasteRouted = true;
      }}
      handlePromptPaste(event).catch((err) => {{
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Paste failed: ${{err.message}}`;
      }});
    }}

    function shouldFocusPromptFromCanvasClick(event) {{
      if (!event || event.defaultPrevented || event.button !== 0) {{
        return false;
      }}
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) {{
        return false;
      }}
      if (selectionActiveInUi()) {{
        return false;
      }}
      const target = event.target;
      if (!(target instanceof Element)) {{
        return false;
      }}
      return (
        target === el.workspace
        || target === el.chatShell
        || target === el.chatMain
        || target === el.conversation
      );
    }}

    function setComposerDragActive(active) {{
      el.askForm.classList.toggle("dragover", Boolean(active));
      const shell = el.askForm.querySelector(".composer-input-shell");
      if (shell) {{
        shell.classList.toggle("dragover", Boolean(active));
      }}
    }}

    function dragHasFiles(event) {{
      const types = event.dataTransfer && event.dataTransfer.types
        ? Array.from(event.dataTransfer.types)
        : [];
      return types.includes("Files");
    }}

    async function handlePromptDrop(event) {{
      if (!dragHasFiles(event)) {{
        return;
      }}
      event.preventDefault();
      setComposerDragActive(false);
      const files = Array.from(event.dataTransfer.files || []);
      if (!files.length) {{
        return;
      }}
      await uploadFiles(files, "drop-file");
    }}

    el.askForm.addEventListener("submit", submitAsk);
    el.composerUploadButton.addEventListener("click", () => {{
      setUploadMenuOpen(!state.uploadMenuOpen);
    }});
    if (el.composerUploadMenu) {{
      el.composerUploadMenu.addEventListener("click", (event) => {{
        const button = event.target.closest("[data-upload-action]");
        if (!button) {{
          return;
        }}
        const action = button.dataset.uploadAction || "";
        setUploadMenuOpen(false);
        if (action === "file") {{
          el.promptFileInput.click();
          return;
        }}
        if (action === "capture-console") {{
          captureUrlAttachment(window.location.href, `${{AGENT_LABEL}} console`, "Capturing console…").catch((err) => {{
            el.runState.className = "pill error";
            el.runState.textContent = "Error";
            el.statusMessage.textContent = `Capture failed: ${{err.message}}`;
          }});
          return;
        }}
        if (action === "capture-link") {{
          const candidates = captureUrlCandidates().filter((item) => item.url !== window.location.href);
          const preferred = candidates[0] || captureUrlCandidates()[0];
          const raw = window.prompt("Capture which URL?", preferred ? preferred.url : "");
          if (!raw) {{
            return;
          }}
          const clean = normalizeUrlCandidate(raw);
          const match = captureUrlCandidates().find((item) => item.url === clean);
          captureUrlAttachment(clean, match ? match.label : "Linked page", "Capturing linked page…").catch((err) => {{
            el.runState.className = "pill error";
            el.runState.textContent = "Error";
            el.statusMessage.textContent = `Capture failed: ${{err.message}}`;
          }});
          return;
        }}
        if (["logs", "history", "pane"].includes(action)) {{
          attachSnapshotText(action).catch((err) => {{
            el.runState.className = "pill error";
            el.runState.textContent = "Error";
            el.statusMessage.textContent = `Attach failed: ${{err.message}}`;
          }});
        }}
      }});
    }}
    el.promptFileInput.addEventListener("change", async () => {{
      const files = Array.from(el.promptFileInput.files || []);
      if (!files.length) {{
        return;
      }}
      await uploadFiles(files, "picker-file");
      el.promptFileInput.value = "";
    }});
    el.tmuxForm.addEventListener("submit", submitTmux);
    el.copyPromptButton.addEventListener("click", () => copyText(el.lastPrompt.dataset.raw || el.lastPrompt.textContent, el.copyPromptButton));
    el.copyResponseButton.addEventListener("click", () => copyText(el.lastResponse.dataset.raw || el.lastResponse.textContent, el.copyResponseButton));
    if (el.contextSaveButton) {{
      el.contextSaveButton.addEventListener("click", () => handleContextSaveAction(el.contextSaveButton));
    }}
    if (el.contextSaveMenuButton) {{
      el.contextSaveMenuButton.addEventListener("click", () => handleContextSaveAction(el.contextSaveMenuButton));
    }}
    el.historyToggleButton.addEventListener("click", () => {{
      const expanding = !state.historyExpanded;
      state.historyExpanded = expanding;
      render(state.snapshot);
      if (expanding) {{
        chatScrollRoot().scrollTop = 0;
      }} else {{
        scrollConversationToBottom(true);
      }}
    }});
    consoleGroupButtons.forEach((button, index) => {{
      button.addEventListener("click", () => {{
        setConsoleNavGroup(button.dataset.group || "");
        if (state.switcher) {{
          state.switcher.activeGroup = button.dataset.group || "all";
          saveSwitcherState();
          renderSwitcher();
        }}
      }});
      button.addEventListener("keydown", (event) => {{
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {{
          return;
        }}
        event.preventDefault();
        let nextIndex = index;
        if (event.key === "ArrowLeft") {{
          nextIndex = (index - 1 + consoleGroupButtons.length) % consoleGroupButtons.length;
        }} else if (event.key === "ArrowRight") {{
          nextIndex = (index + 1) % consoleGroupButtons.length;
        }} else if (event.key === "Home") {{
          nextIndex = 0;
        }} else if (event.key === "End") {{
          nextIndex = consoleGroupButtons.length - 1;
        }}
        const nextButton = consoleGroupButtons[nextIndex];
        if (!nextButton) {{
          return;
        }}
        setConsoleNavGroup(nextButton.dataset.group || "");
        if (state.switcher) {{
          state.switcher.activeGroup = nextButton.dataset.group || "all";
          saveSwitcherState();
          renderSwitcher();
        }}
        nextButton.focus();
      }});
    }});
    state.switcher = loadSwitcherState();
    if (consoleGroupButtons.length) {{
      const initialConsoleGroup = (
        state.switcher?.activeGroup
        && state.switcher.activeGroup !== "all"
        && consoleGroupButtons.some((button) => button.dataset.group === state.switcher.activeGroup)
      )
        ? state.switcher.activeGroup
        : document.querySelector(".console-group-pill.active")?.dataset.group
        || consoleGroupButtons[0]?.dataset.group
        || "";
      setConsoleNavGroup(initialConsoleGroup);
    }}
    renderSwitcher();
    if (el.statusActionButton) {{
      el.statusActionButton.addEventListener("click", (event) => {{
        event.preventDefault();
        event.stopPropagation();
        setStatusActionOpen(!state.statusPanelOpen);
      }});
    }}
    if (el.statusRefreshButton) {{
      el.statusRefreshButton.addEventListener("click", (event) => {{
        event.preventDefault();
        void refreshStatusActions({{ keepOpen: true }});
      }});
    }}
    if (el.statusAskButton) {{
      el.statusAskButton.addEventListener("click", (event) => {{
        event.preventDefault();
        void submitStatusAction("ask");
      }});
    }}
    if (el.statusHandleButton) {{
      el.statusHandleButton.addEventListener("click", (event) => {{
        event.preventDefault();
        void submitStatusAction("handle");
      }});
    }}
    el.topbarMenuButton.addEventListener("click", () => {{
      setSwitcherOpen(false);
      setTopbarMenuOpen(!document.body.classList.contains("topbar-menu-open"));
    }});
    if (el.consoleFocusToggle) {{
      el.consoleFocusToggle.addEventListener("click", () => {{
        setConsoleFocusExpanded(el.consoleFocusPanel.hidden);
      }});
      setConsoleFocusExpanded(false);
    }}
    el.switcherToggleButton.addEventListener("click", () => {{
      setSwitcherOpen(!document.body.classList.contains("switcher-open"));
    }});
    el.topbarMenuBackdrop.addEventListener("click", () => setTopbarMenuOpen(false));
    document.addEventListener("click", (event) => {{
      const target = event.target instanceof Element ? event.target : null;
      if (
        state.statusPanelOpen
        && target
        && !target.closest("#status-action-panel")
        && !target.closest("#status-action-button")
      ) {{
        setStatusActionOpen(false);
      }}
    }});
    el.switcherCloseButton.addEventListener("click", () => setSwitcherOpen(false));
    el.switcherBackdrop.addEventListener("click", () => setSwitcherOpen(false));
    el.switcherSearchInput.addEventListener("input", () => {{
      if (!state.switcher) {{
        return;
      }}
      state.switcher.query = el.switcherSearchInput.value || "";
      renderSwitcher();
    }});
    el.switcherViews.addEventListener("click", (event) => {{
      const button = event.target.closest("[data-switcher-view]");
      if (!button || !state.switcher) {{
        return;
      }}
      state.switcher.activeView = button.dataset.switcherView || "all";
      saveSwitcherState();
      renderSwitcher();
    }});
    el.switcherGroups.addEventListener("click", (event) => {{
      const button = event.target.closest("[data-switcher-group]");
      if (!button || !state.switcher) {{
        return;
      }}
      state.switcher.activeGroup = button.dataset.switcherGroup || "all";
      if (state.switcher.activeGroup !== "all") {{
        setConsoleNavGroup(state.switcher.activeGroup);
      }}
      saveSwitcherState();
      renderSwitcher();
    }});
    el.switcherList.addEventListener("click", (event) => {{
      const pinButton = event.target.closest("[data-switcher-pin]");
      if (pinButton) {{
        event.preventDefault();
        event.stopPropagation();
        togglePinnedSwitcherKey(pinButton.dataset.switcherPin || "");
        return;
      }}
      const link = event.target.closest("[data-switcher-link]");
      if (!link) {{
        return;
      }}
      const key = link.dataset.switcherLink || "";
      recordRecentSwitcherKey(key);
      link.href = buildSwitcherHref(link.href, key);
      setSwitcherOpen(false);
    }});
    consoleNavLinks.forEach((link) => {{
      link.addEventListener("click", () => {{
        const key = link.dataset.switcherKey || "";
        recordRecentSwitcherKey(key);
        link.href = buildSwitcherHref(link.dataset.switcherBase || link.href, key);
      }});
    }});
    el.noticeToggleButton.addEventListener("click", () => setNoticesOpen(!document.body.classList.contains("notices-open")));
    el.noticesCloseButton.addEventListener("click", () => setNoticesOpen(false));
    el.clearNoticesButton.addEventListener("click", () => {{
      state.notices = [];
      renderNotifications();
    }});
    el.settingsToggleButton.addEventListener("click", () => setSettingsOpen(true));
    el.settingsCloseButton.addEventListener("click", () => setSettingsOpen(false));
    el.settingsBackdrop.addEventListener("click", () => {{
      setSettingsOpen(false);
      setNoticesOpen(false);
    }});
    el.systemToggleButton.addEventListener("click", () => setSystemOpen(true));
    el.systemCloseButton.addEventListener("click", () => setSystemOpen(false));
    el.systemBackdrop.addEventListener("click", () => setSystemOpen(false));
    if (el.activityPeekToggle) {{
      el.activityPeekToggle.addEventListener("click", () => {{
        state.activityPeekOpen = !state.activityPeekOpen;
        renderActivityStrip(state.snapshot);
      }});
    }}
    if (el.activityPeekClose) {{
      el.activityPeekClose.addEventListener("click", () => {{
        state.activityPeekOpen = false;
        renderActivityStrip(state.snapshot);
      }});
    }}
    if (el.activityLogLink) {{
      el.activityLogLink.addEventListener("click", () => {{
        state.activityPeekOpen = true;
        renderActivityStrip(state.snapshot);
        setSystemOpen(true);
      }});
    }}
    el.composerToolsToggle.addEventListener("click", () => {{
      state.toolbarExpanded = !composerToolbarShouldExpand(state.snapshot);
      updateComposerToolbar(state.snapshot);
    }});
    el.promptInput.addEventListener("keydown", (event) => {{
      if (maybeKillInputLine(event)) {{
        return;
      }}
      rememberPromptEnterMeta(event);
      if (!shouldSubmitPromptOnKeydown(event)) {{
        return;
      }}
      submitPromptFromKeyboard(event);
    }});
    el.promptInput.addEventListener("beforeinput", (event) => {{
      if (!shouldSubmitPromptOnBeforeInput(event)) {{
        return;
      }}
      submitPromptFromKeyboard(event);
    }});
    el.promptInput.addEventListener("keyup", (event) => {{
      if (!isEnterLikeKey(event)) {{
        return;
      }}
      state.promptEnterMeta = null;
    }});
    el.promptInput.addEventListener("focus", () => {{
      state.promptFocused = true;
      updateComposerToolbar(state.snapshot);
      renderSuggestions(state.snapshot);
      syncMobileComposeMode();
      scheduleComposerReserve({{ preserveLiveEdge: true }});
      window.setTimeout(() => scheduleComposerReserve({{ preserveLiveEdge: true }}), 140);
    }});
    el.promptInput.addEventListener("blur", () => {{
      state.promptFocused = false;
      updateComposerToolbar(state.snapshot);
      renderSuggestions(state.snapshot);
      syncMobileComposeMode();
      scheduleComposerReserve({{ preserveLiveEdge: true }});
      window.setTimeout(() => scheduleComposerReserve({{ preserveLiveEdge: true }}), 140);
    }});
    el.promptInput.addEventListener("paste", routePasteToPrompt);
    document.addEventListener("paste", (event) => {{
      if (event.defaultPrevented) {{
        return;
      }}
      if (event.__normanPromptPasteRouted) {{
        return;
      }}
      if (event.target === el.promptInput) {{
        return;
      }}
      if (editablePasteTarget(event.target)) {{
        return;
      }}
      el.promptInput.focus({{ preventScroll: true }});
      routePasteToPrompt(event);
    }});
    el.askForm.addEventListener("dragenter", (event) => {{
      if (!dragHasFiles(event)) {{
        return;
      }}
      event.preventDefault();
      setComposerDragActive(true);
    }});
    el.askForm.addEventListener("dragover", (event) => {{
      if (!dragHasFiles(event)) {{
        return;
      }}
      event.preventDefault();
      setComposerDragActive(true);
    }});
    el.askForm.addEventListener("dragleave", (event) => {{
      const related = event.relatedTarget;
      if (related && el.askForm.contains(related)) {{
        return;
      }}
      setComposerDragActive(false);
    }});
    el.askForm.addEventListener("drop", (event) => {{
      handlePromptDrop(event).catch((err) => {{
        el.runState.className = "pill error";
        el.runState.textContent = "Error";
        el.statusMessage.textContent = `Drop failed: ${{err.message}}`;
      }});
    }});

    function dismissTransientChrome() {{
      const hadOpenChrome = Boolean(
        (el.consoleFocusPanel && !el.consoleFocusPanel.hidden)
        || state.toolbarExpanded
        || state.uploadMenuOpen
        || document.body.classList.contains("switcher-open")
        || document.body.classList.contains("topbar-menu-open")
        || document.body.classList.contains("settings-open")
        || document.body.classList.contains("notices-open")
        || document.body.classList.contains("system-open")
        || document.querySelector(".message-footer:not(.collapsed)")
      );
      if (!hadOpenChrome) {{
        return false;
      }}
      state.toolbarExpanded = false;
      setConsoleFocusExpanded(false);
      setUploadMenuOpen(false);
      updateComposerToolbar(state.snapshot);
      setSwitcherOpen(false);
      setTopbarMenuOpen(false);
      setSettingsOpen(false);
      setNoticesOpen(false);
      setSystemOpen(false);
      closeMessageActionMenus();
      return true;
    }}

    function maybeInterruptFromEscape(event) {{
      if (event.key !== "Escape") {{
        return false;
      }}
      if (dismissTransientChrome()) {{
        event.preventDefault();
        event.stopPropagation();
        focusPromptInputAtEnd();
        return true;
      }}
      if (!state.snapshot.pending || event.repeat) {{
        return false;
      }}
      const active = document.activeElement;
      if (
        active
        && active.tagName === "TEXTAREA"
        && active !== el.promptInput
        && active !== el.tmuxInput
      ) {{
        return false;
      }}
      if (Date.now() - state.escapeInterruptAt < 900) {{
        event.preventDefault();
        return true;
      }}
      state.escapeInterruptAt = Date.now();
      event.preventDefault();
      event.stopPropagation();
      fireAction("/api/cancel-web", "Cancelling current web reply…");
      return true;
    }}

    function maybeFocusPromptFromEscape(event) {{
      if (
        !event
        || event.defaultPrevented
        || event.key !== "Escape"
        || event.repeat
        || state.snapshot.pending
        || !shortcutEligibleTarget(event)
      ) {{
        return false;
      }}
      event.preventDefault();
      focusPromptInputAtEnd();
      return true;
    }}

    document.addEventListener("click", (event) => {{
      const capsule = event.target.closest("[data-kpi-action]");
      if (capsule) {{
        event.preventDefault();
        const action = String(capsule.dataset.kpiAction || "system");
        if (action === "notices") {{
          setNoticesOpen(true);
        }} else if (action === "peek") {{
          if (buildActivityInsight(state.snapshot)) {{
            state.activityPeekOpen = true;
            renderActivityStrip(state.snapshot);
          }} else {{
            setSystemOpen(true);
          }}
        }} else {{
          setSystemOpen(true);
        }}
        return;
      }}
      const inlineAction = event.target.closest("[data-action]");
      if (inlineAction) {{
        const action = String(inlineAction.dataset.action || "").trim();
        if (action === "relay") {{
          event.preventDefault();
          if (openLatestRelayTargets()) {{
            setNoticesOpen(false);
            return;
          }}
          el.statusMessage.textContent = "No linked-bot handoff is available in this reply yet.";
          return;
        }}
      }}
      const toggle = event.target.closest(".code-toggle-button");
      if (toggle) {{
        const block = toggle.closest(".code-block.compactable");
        if (!block) {{
          return;
        }}
        const collapsed = block.classList.toggle("collapsed");
        toggle.textContent = collapsed ? "View" : "Hide";
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        return;
      }}
      const button = event.target.closest(".code-copy-button");
      if (!button) {{
        return;
      }}
      const block = button.closest(".code-block");
      const code = block ? (block.querySelector(".code-scroll code") || block.querySelector("code")) : null;
      if (!code) {{
        return;
      }}
      copyText(code.textContent || "", button);
    }});
    document.addEventListener("keydown", (event) => {{
      if (handleGlobalConsoleShortcut(event)) {{
        return;
      }}
      primePromptForPasteShortcut(event);
      if (maybeInterruptFromEscape(event)) {{
        return;
      }}
      maybeFocusPromptFromEscape(event);
    }});
    document.addEventListener("copy", (event) => {{
      if (event.defaultPrevented || editableShortcutTarget(event.target)) {{
        return;
      }}
      const value = selectionPlainTextFromUi();
      if (!value) {{
        return;
      }}
      event.preventDefault();
      try {{
        if (event.clipboardData && typeof event.clipboardData.setData === "function") {{
          event.clipboardData.setData("text/plain", value);
          return;
        }}
      }} catch (_) {{
        // Fall back to async clipboard below when direct clipboardData access fails.
      }}
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(value).catch(() => {{}});
      }}
    }});
    el.themeToggleButton.addEventListener("click", () => setTopbarMenuOpen(false));
    if (el.authBrowserButton) {{
      el.authBrowserButton.addEventListener("click", () => {{
        setTopbarMenuOpen(false);
        void startBrowserAuthFromConsole();
      }});
    }}
    if (el.authDeviceButton) {{
      el.authDeviceButton.addEventListener("click", () => {{
        setTopbarMenuOpen(false);
        void startDeviceAuthFromConsole();
      }});
    }}
    if (el.authHelperLink) {{
      el.authHelperLink.addEventListener("click", () => {{
        setTopbarMenuOpen(false);
      }});
    }}
    el.refreshButton.addEventListener("click", () => {{
      setTopbarMenuOpen(false);
      el.statusMessage.textContent = "Refreshing status…";
      refreshStatus();
    }});
    el.cancelWebButton.addEventListener("click", () => fireAction("/api/cancel-web", "Cancelling current web reply…"));
    el.clearQueueButton.addEventListener("click", () => fireAction("/api/queue/clear", "Clearing queued prompts…"));
    el.cancelAllButton.addEventListener("click", () => fireAction("/api/cancel-all", "Cancelling current reply and clearing queue…"));
    el.promoteLatestButton.addEventListener("click", () => fireAction("/api/queue/promote-latest", "Promoting latest operator prompt…"));
    el.interruptButton.addEventListener("click", () => fireAction("/api/interrupt", "Interrupting tmux session…"));
    el.restartButton.addEventListener("click", () => fireAction("/api/restart", "Restarting the interactive session…"));
    el.promptInput.addEventListener("input", () => {{
      autoresize(el.promptInput);
      updateComposerToolbar(state.snapshot);
      renderSuggestions(state.snapshot);
      persistPromptDraft(el.promptInput.value);
    }});
    el.tmuxInput.addEventListener("keydown", (event) => {{
      maybeKillInputLine(event);
    }});
    el.tmuxInput.addEventListener("input", () => autoresize(el.tmuxInput));
    el.tmuxInput.addEventListener("focus", () => {{
      syncMobileComposeMode();
      scheduleComposerReserve({{ preserveLiveEdge: true }});
      window.setTimeout(() => scheduleComposerReserve({{ preserveLiveEdge: true }}), 140);
    }});
    el.tmuxInput.addEventListener("blur", () => {{
      syncMobileComposeMode();
      scheduleComposerReserve({{ preserveLiveEdge: true }});
      window.setTimeout(() => scheduleComposerReserve({{ preserveLiveEdge: true }}), 140);
    }});
    suggestionButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        applyPromptSuggestion(button.dataset.suggestion || "");
      }});
    }});
    settingButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        const key = button.dataset.setting;
        const value = button.dataset.value;
        if (!key || !value) {{
          return;
        }}
        const stringSettings = new Set(["density", "viewMode", "styleVariant", "finish", "responseSpeed", "completionBell"]);
        state.preferences = normalizePreferences({{
          ...state.preferences,
          [key]: stringSettings.has(key) ? value : Number(value),
        }});
        savePreferences();
        applyPreferences();
        render(state.snapshot);
      }});
    }});
    if (el.completionBellTestButton) {{
      el.completionBellTestButton.addEventListener("click", () => {{
        primeCompletionAudio();
        playCompletionBell({{ force: true }});
      }});
    }}
    window.addEventListener("pointerdown", primeCompletionAudio, {{ passive: true, capture: true }});
    window.addEventListener("touchstart", primeCompletionAudio, {{ passive: true, capture: true }});
    window.addEventListener("keydown", primeCompletionAudio, {{ capture: true }});
    el.responseSpeedRange.addEventListener("input", () => {{
      state.preferences = normalizePreferences({{
        ...state.preferences,
        responseSpeed: responseSpeedFromIndex(el.responseSpeedRange.value || 2),
      }});
      applyPreferences();
    }});
    el.responseSpeedRange.addEventListener("change", () => {{
      state.preferences = normalizePreferences({{
        ...state.preferences,
        responseSpeed: responseSpeedFromIndex(el.responseSpeedRange.value || 2),
      }});
      savePreferences();
      applyPreferences();
      render(state.snapshot);
    }});
    el.responseDetailRange.addEventListener("input", () => {{
      state.preferences = normalizePreferences({{
        ...state.preferences,
        responseDetail: Number(el.responseDetailRange.value || DEFAULT_RESPONSE_DETAIL),
      }});
      applyPreferences();
    }});
    el.responseDetailRange.addEventListener("change", () => {{
      state.preferences = normalizePreferences({{
        ...state.preferences,
        responseDetail: Number(el.responseDetailRange.value || DEFAULT_RESPONSE_DETAIL),
      }});
      savePreferences();
      applyPreferences();
      render(state.snapshot);
    }});
    window.addEventListener("keydown", (event) => {{
      if (event.defaultPrevented) {{
        return;
      }}
      if (event.key === "Escape") {{
        dismissTransientChrome();
      }}
    }});
    document.addEventListener("visibilitychange", () => {{
      if (document.visibilityState === "hidden") {{
        persistPromptDraft(el.promptInput.value);
      }}
      syncLiveTransport();
      if (document.visibilityState === "visible") {{
        pingNormanPrime("visible");
        schedulePrimePing(90000);
        refreshStatus();
      }}
    }});
    window.addEventListener("beforeunload", () => {{
      persistPromptDraft(el.promptInput.value);
    }});
    window.addEventListener("focus", () => {{
      pingNormanPrime("focus");
      schedulePrimePing(90000);
      syncLiveTransport();
    }});
    window.addEventListener("online", () => {{
      pingNormanPrime("online");
      schedulePrimePing(15000);
      syncLiveTransport();
    }});
    document.addEventListener("click", (event) => {{
      if (
        !event.target.closest(".composer-upload-shell")
      ) {{
        setUploadMenuOpen(false);
      }}
      if (state.toolbarExpanded && !event.target.closest("#ask-form")) {{
        state.toolbarExpanded = false;
        updateComposerToolbar(state.snapshot);
      }}
      if (
        !event.target.closest("#console-focus-shell")
      ) {{
        setConsoleFocusExpanded(false);
      }}
      if (
        state.activityPeekOpen
        && !event.target.closest("#activity-strip")
        && !event.target.closest("#activity-peek")
      ) {{
        state.activityPeekOpen = false;
        renderActivityStrip(state.snapshot);
      }}
      if (
        !event.target.closest("#topbar-menu")
        && !event.target.closest("#topbar-menu-button")
      ) {{
        setTopbarMenuOpen(false);
      }}
      if (event.target.closest(".message-tools") || event.target.closest(".message-footer")) {{
        return;
      }}
      closeMessageActionMenus();
    }});
    document.addEventListener("selectionchange", () => {{
      if (!selectionActiveInUi() && state.deferredSnapshot) {{
        const snapshot = state.deferredSnapshot;
        state.deferredSnapshot = null;
        render(snapshot);
      }}
    }});
    el.workspace.addEventListener("click", (event) => {{
      if (!shouldFocusPromptFromCanvasClick(event)) {{
        return;
      }}
      focusPromptInputAtEnd();
    }});
    desktopLayout.addEventListener("change", syncSystemPanelMode);
    el.workspace.addEventListener("wheel", (event) => {{
      if (event.ctrlKey || event.deltaY >= 0) {{
        return;
      }}
      if (state.historyExpanded || state.hiddenHistoryTurns <= 0 || chatScrollRoot().scrollTop > 8) {{
        return;
      }}
      if (expandHistoryFromScroll()) {{
        event.preventDefault();
      }}
    }}, {{ passive: false }});
    el.workspace.addEventListener("touchstart", (event) => {{
      const touch = event.touches && event.touches[0];
      if (!touch) {{
        return;
      }}
      state.touchStartY = touch.clientY;
    }}, {{ passive: true }});
    el.workspace.addEventListener("touchmove", (event) => {{
      const touch = event.touches && event.touches[0];
      if (!touch) {{
        return;
      }}
      if (state.historyExpanded || state.hiddenHistoryTurns <= 0 || chatScrollRoot().scrollTop > 8) {{
        return;
      }}
      if (touch.clientY - (state.touchStartY || touch.clientY) < 26) {{
        return;
      }}
      if (expandHistoryFromScroll()) {{
        state.touchStartY = touch.clientY;
      }}
    }}, {{ passive: true }});
    el.workspace.addEventListener("scroll", () => {{
      if (!state.historyExpanded) {{
        state.userPinnedHistory = false;
        el.jumpLatestButton.classList.remove("visible");
        return;
      }}
      state.userPinnedHistory = !isNearConversationBottom();
      updateScrollChrome();
      el.jumpLatestButton.classList.toggle("visible", !state.historyExpanded && state.userPinnedHistory);
    }});
    el.jumpLatestButton.addEventListener("click", () => {{
      state.userPinnedHistory = false;
      scrollConversationToBottom(true);
    }});

    if (typeof ResizeObserver !== "undefined" && el.composerWrap) {{
      const composerObserver = new ResizeObserver(() => {{
        scheduleComposerReserve();
      }});
      composerObserver.observe(el.composerWrap);
    }}
    if (window.visualViewport) {{
      const syncViewportReserve = () => {{
        scheduleComposerReserve({{ preserveLiveEdge: true }});
      }};
      window.visualViewport.addEventListener("resize", syncViewportReserve);
      window.visualViewport.addEventListener("scroll", syncViewportReserve);
    }}
    window.addEventListener("resize", () => {{
      applyPreferences();
      syncTopbarMenuPosition();
      scheduleComposerReserve({{ preserveLiveEdge: true }});
    }});
    window.addEventListener("orientationchange", () => {{
      applyPreferences();
      syncTopbarMenuPosition();
      window.setTimeout(() => scheduleComposerReserve({{ preserveLiveEdge: true }}), 40);
      window.setTimeout(() => scheduleComposerReserve({{ preserveLiveEdge: true }}), 220);
    }});

    try {{
      state.preferences = loadPreferences();
    }} catch (_) {{
      state.preferences = normalizePreferences(DEFAULT_PREFERENCES);
    }}
    render(INITIAL_SNAPSHOT);
    restorePromptDraft();
    try {{
      applyPreferences();
      autoresize(el.promptInput);
      autoresize(el.tmuxInput);
      applyViewportMetrics();
      applyComposerReserve();
      syncSystemPanelMode();
    }} catch (_) {{
      // Keep the first paint usable even if a post-render browser quirk trips.
    }}
    updateScrollChrome();
    syncLiveTransport();
    pingNormanPrime("load");
    schedulePrimePing(45000);
  </script>
</body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.maybe_send_auth_cookie(params)
        self.end_headers()
        self.wfile.write(encoded)

    def render_token_gate(self, params: dict[str, list[str]]) -> None:
        supplied = html.escape((params.get("token") or [""])[0])
        active_profile = normalize_profile_name((params.get("profile") or [""])[0])
        active_route = normalize_route_mode((params.get("route") or [""])[0])
        path_prefix = self.request_path_prefix()
        profile_field = f'<input type="hidden" name="profile" value="{html.escape(active_profile)}">'
        route_field = (
            f'<input type="hidden" name="route" value="{html.escape(active_route)}">'
            if active_route != "auto"
            else ""
        )
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{html.escape(CONSOLE_TAB_TITLE)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Poppins:wght@400;500;600;700&display=swap">
  {favicon_links_html(self.request_path_prefix())}
  <style>
    :root {{
{profile_vars_css(active_profile)}
{agent_theme_vars_css(AGENT_SLUG)}
      --font-ui: "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-body: "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-reading: "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif;
      --font-mono: "SFMono-Regular", "JetBrains Mono", "IBM Plex Mono", Menlo, Consolas, "Liberation Mono", monospace;
      --brand-radius: 16px;
      --chrome-pill-radius: 999px;
      --body-overlay-opacity: 0.42;
      --body-edge-opacity: 0.82;
      --body-accent-angle: 90deg;
      --topbar-glint-opacity: 0.9;
      --topbar-edge-opacity: 1;
      --topbar-saturate: 128%;
      --topbar-blur: 16px;
{style_variant_vars_css(AGENT_SLUG)}
{agent_font_vars_css(AGENT_SLUG)}
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at top right, var(--glow-a), transparent 24%),
        linear-gradient(180deg, var(--body-start) 0%, var(--body-mid) 44%, var(--body-end) 100%);
      color: var(--text);
      font-family: var(--font-body);
      padding: 18px;
      box-sizing: border-box;
    }}
    .box {{
      width: min(100%, 520px);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--brand-radius);
      padding: 20px;
      box-shadow: var(--shadow);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 1.72rem;
    }}
    p {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.45;
    }}
    label {{
      display: block;
      font-size: 0.88rem;
      margin-bottom: 6px;
      color: var(--muted);
    }}
    input {{
      width: 100%;
      border-radius: 16px;
      border: 1px solid var(--border);
      padding: 12px 14px;
      background: var(--surface-2);
      color: var(--text);
      font: inherit;
      box-sizing: border-box;
    }}
    .input-row {{
      display: flex;
      align-items: stretch;
      gap: 10px;
    }}
    .input-row input {{
      flex: 1 1 auto;
    }}
    button {{
      margin-top: 12px;
      min-height: 44px;
      border-radius: 6px;
      border: 1px solid var(--border-strong);
      background: linear-gradient(180deg, var(--surface-3), var(--surface-2));
      color: var(--text);
      font: inherit;
      font-weight: 600;
      padding: 10px 14px;
      cursor: pointer;
    }}
    .reveal-button {{
      margin-top: 0;
      min-width: 76px;
      white-space: nowrap;
    }}
  </style>
</head>
<body>
  <div class="box">
    <h1>{html.escape(CONSOLE_TITLE)}</h1>
    <p>This console is token-protected. Open it with the `?token=` query value, or paste the token below.</p>
    <form method="get" action="{html.escape(prefixed_path('/', path_prefix))}">
      {profile_field}
      {route_field}
      <label for="token">Token</label>
      <div class="input-row">
        <input id="token" name="token" type="password" value="{supplied}" placeholder="Paste the {html.escape(AGENT_NAME)} web token" autocomplete="current-password" autocapitalize="off" spellcheck="false">
        <button id="reveal-token" type="button" class="reveal-button" aria-pressed="false">Show</button>
      </div>
      <button type="submit">Open Console</button>
    </form>
  </div>
  <script>
    (() => {{
      const input = document.getElementById("token");
      const button = document.getElementById("reveal-token");
      if (!input || !button) return;
      button.addEventListener("click", () => {{
        const revealing = input.type === "password";
        input.type = revealing ? "text" : "password";
        button.textContent = revealing ? "Hide" : "Show";
        button.setAttribute("aria-pressed", revealing ? "true" : "false");
      }});
    }})();
  </script>
</body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> int:
    ensure_state_dir()
    start_kpi_collector()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving {AGENT_NAME} Codex bridge on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
