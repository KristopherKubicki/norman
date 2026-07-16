#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.services.codex_role_policy import (
    codex_role_policy_identity,
    codex_role_value,
    codex_switchable_models,
    load_codex_role_policy,
)


SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_ROOT = SCRIPT_DIR / "agent_console_template"
PROMPT_TEMPLATE_ROOT = TEMPLATE_ROOT / "prompts"
SOURCE_FILES = {
    "web": TEMPLATE_ROOT / "agent_console_web.py",
    "norman-switchboard": SCRIPT_DIR / "norman_codex_web.py",
    "launch": TEMPLATE_ROOT / "agent_console_launch.sh",
    "supervisor": TEMPLATE_ROOT / "agent_console_supervisor.sh",
    "vector-preflight": SCRIPT_DIR / "tui_vector_preflight.py",
    "soul-loader": SCRIPT_DIR / "compose_soul_context.py",
    "soul-validator": SCRIPT_DIR / "validate_soul_md.py",
}
WEB_SOURCE_KEYS = frozenset({"web", "norman-switchboard"})
NORMAN_FLEET_DOCTOR_TEMPLATE_PATH = (
    os.environ.get(
        "NORMAN_SYNC_FLEET_DOCTOR_TEMPLATE_PATH",
        "/home/kristopher/code/norman/scripts/agent_console_template/agent_console_web.py",
    ).strip()
    or "/home/kristopher/code/norman/scripts/agent_console_template/agent_console_web.py"
)
PROMPT_TEMPLATES = {
    "compere": PROMPT_TEMPLATE_ROOT / "compere.txt",
    "control-plane": PROMPT_TEMPLATE_ROOT / "control-plane.txt",
    "diamond-roc": PROMPT_TEMPLATE_ROOT / "diamond-roc.txt",
    "dj": PROMPT_TEMPLATE_ROOT / "dj.txt",
    "emerald-canopy": PROMPT_TEMPLATE_ROOT / "emerald-canopy.txt",
    "gold-book": PROMPT_TEMPLATE_ROOT / "gold-book.txt",
    "mls": PROMPT_TEMPLATE_ROOT / "mls.txt",
    "networking": PROMPT_TEMPLATE_ROOT / "networking.txt",
    "parkergale": PROMPT_TEMPLATE_ROOT / "parkergale.txt",
    "platinum-standard": PROMPT_TEMPLATE_ROOT / "platinum-standard.txt",
    "publisher": PROMPT_TEMPLATE_ROOT / "publisher.txt",
    "scout": PROMPT_TEMPLATE_ROOT / "scout.txt",
    "studio": PROMPT_TEMPLATE_ROOT / "studio.txt",
    "tv": PROMPT_TEMPLATE_ROOT / "tv.txt",
    "uplink": PROMPT_TEMPLATE_ROOT / "uplink.txt",
}
INSTANCE_PUBLIC_HOST_OVERRIDES: dict[str, str] = {
    "autocamera": "autocamera.home.arpa",
    "castle": "castle.home.arpa",
    "cloudagent": "cloudagent.home.arpa",
    "compere": "keystone.kris.openbrand.com",
    "control-plane": "cp.kris.openbrand.com",
    "dj": "dj.home.arpa",
    "earlybird": "earlybird.kris.openbrand.com",
    "glimpser": "eyebat.home.arpa",
    "gold-book": "goldbook.kris.openbrand.com",
    "housebot": "housebot.home.arpa",
    "infra": "infra.kris.openbrand.com",
    "leadership-kpis": "kpis.kris.openbrand.com",
    "market-sizing": "market.kris.openbrand.com",
    "mls": "mls.kris.openbrand.com",
    "networking": "networking.home.arpa",
    "panelbot": "panelbot.kris.openbrand.com",
    "parkergale": "pefb.home.arpa",
    "phone-ops": "phone.home.arpa",
    "platinum-standard": "platinum.kris.openbrand.com",
    "publisher": "publisher.kris.openbrand.com",
    "scout": "scout.kris.openbrand.com",
    "studio": "studio.home.arpa",
    "theseus": "theseus.home.arpa",
    "tmi-dashboards": "dashboards.kris.openbrand.com",
    "tv": "tv.home.arpa",
    "uplink": "uplink.home.arpa",
    "uscache": "uscache.home.arpa",
}
DEFAULT_LAUNCHERS = {
    "housebot": "/opt/housebot/scripts/housebot_codex_launch.sh",
}
DISABLED_CODEX_PLUGINS_BY_INSTANCE: dict[str, tuple[str, ...]] = {
    "uplink": ("figma@openai-curated",),
}
RESTART_READINESS_TIMEOUT_SECONDS = int(
    os.environ.get("NORMAN_SYNC_RESTART_READINESS_TIMEOUT_SECONDS", "3")
)
STATUS_PROBE_TIMEOUT_SECONDS = int(
    os.environ.get("NORMAN_SYNC_STATUS_TIMEOUT_SECONDS", "12")
)


def _fetch_restart_readiness_payload(port: str, token: str) -> dict[str, object]:
    readiness_timeout = RESTART_READINESS_TIMEOUT_SECONDS
    status_timeout = STATUS_PROBE_TIMEOUT_SECONDS
    query = "?" + urllib.parse.urlencode({"token": token}) if token else ""
    readiness_url = "http://127.0.0.1:" + port + "/api/restart-readiness" + query
    status_url = "http://127.0.0.1:" + port + "/api/status" + query

    def fetch_json(url, timeout):
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8")
        return json.loads(body or "{}")

    try:
        return fetch_json(readiness_url, readiness_timeout)
    except Exception:
        return fetch_json(status_url, status_timeout)


@dataclass(frozen=True)
class DiscoveryHost:
    name: str
    ssh_target: str
    use_sudo: bool
    env_globs: tuple[str, ...]
    public_host: str
    lan_host: str
    canonical_host: str | None = None
    frontdoor_alias_hosts: tuple[str, ...] = ()
    alias_hosts: tuple[str, ...] = ()
    host_home_path: str | None = None
    local: bool = False
    read_only: bool = False
    root_managed_local: bool = False


@dataclass(frozen=True)
class ConsoleInstance:
    name: str
    host_name: str
    ssh_target: str
    use_sudo: bool
    env_file: str
    web_path: str
    launch_path: str
    supervisor_path: str
    restart_units: tuple[str, ...]
    agent_label: str
    web_port: str
    web_token: str
    prompt_file: str
    codex_home: str

    @property
    def files(self) -> tuple[tuple[str, str], ...]:
        web_source = (
            "norman-switchboard"
            if self.host_name == "norman" and self.name == "norman"
            else "web"
        )
        return (
            (web_source, self.web_path),
            ("launch", self.launch_path),
            ("supervisor", self.supervisor_path),
            ("vector-preflight", f"/opt/{self.name}/tui_vector_preflight.py"),
            ("soul-loader", f"/opt/{self.name}/compose_soul_context.py"),
            ("soul-validator", f"/opt/{self.name}/validate_soul_md.py"),
        )

    @property
    def prompt_template(self) -> Path | None:
        return PROMPT_TEMPLATES.get(self.name)


@dataclass(frozen=True)
class RemoteFileState:
    exists: bool
    sha256: str | None
    mode: str
    owner: str | None
    group: str | None


@dataclass(frozen=True)
class UiVersionStatus:
    version: str
    version_error: str = ""
    readiness_error: str = ""
    status_error: str = ""
    web_restart_required: bool = False
    web_restart_reason: str = ""
    prompt_idle: bool = False
    prompt_done: bool = False
    auto_update_safe: bool = False
    busy: bool = False


HOSTS: dict[str, DiscoveryHost] = {
    "hal": DiscoveryHost(
        name="hal",
        ssh_target="",
        use_sudo=False,
        env_globs=("/etc/*/codex-web.env",),
        public_host="hal.home.arpa",
        lan_host="192.168.2.137",
        alias_hosts=("hal.tail94915.ts.net",),
        host_home_path=None,
        local=True,
        read_only=False,
        root_managed_local=True,
    ),
    "toy-box": DiscoveryHost(
        name="toy-box",
        ssh_target="toy-box",
        use_sudo=True,
        env_globs=("/etc/*/codex-web.env",),
        public_host="toy-box.home.arpa",
        lan_host="192.168.2.146",
        alias_hosts=("toy-box.tail94915.ts.net",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "work-special": DiscoveryHost(
        name="work-special",
        ssh_target="work-special",
        use_sudo=True,
        env_globs=("/etc/*/codex-web.env",),
        public_host="work-special.home.arpa",
        lan_host="192.168.2.147",
        alias_hosts=("work-special.tail94915.ts.net",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "norman": DiscoveryHost(
        name="norman",
        ssh_target="192.168.2.241",
        use_sudo=True,
        env_globs=("/etc/norman/codex-web.env",),
        public_host="norman.home.arpa",
        canonical_host="norman.tail94915.ts.net",
        lan_host="192.168.2.241",
        frontdoor_alias_hosts=("norman.home.lollie.org",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "networking-host": DiscoveryHost(
        name="networking-host",
        ssh_target="debian@192.168.2.242",
        use_sudo=True,
        env_globs=("/etc/net-agents/*.env",),
        public_host="networking-host.home.arpa",
        lan_host="192.168.2.242",
        alias_hosts=("networking.tail94915.ts.net",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "private-host": DiscoveryHost(
        name="private-host",
        ssh_target="root@192.168.2.148",
        use_sudo=False,
        env_globs=("/etc/*/codex-web.env",),
        public_host="private.home.lollie.org",
        lan_host="192.168.2.148",
        host_home_path="/var/www/private/index.html",
    ),
}

HOST_HUBS: dict[str, tuple[str, str]] = {
    "norman": ("norman", "Norman"),
    "hal": ("autocamera", "Hal"),
    "toy-box": ("housebot", "Toy Box"),
    "work-special": ("compere", "Work"),
    "networking-host": ("networking", "Networking"),
}

HOST_GROUP_LABELS: dict[str, str] = {
    "norman": "Norman",
    "hal": "Personal",
    "toy-box": "Personal",
    "work-special": "Work",
    "networking-host": "Shared",
    "private-host": "Private",
}
RUNTIME_BRIDGE_REFERENCE_INSTANCES: tuple[str, ...] = (
    "uplink",
    "networking",
    "housebot",
    "norman",
)
RUNTIME_BRIDGE_TOKEN_SECRET = "norman/console-runtime-token"
RUNTIME_BRIDGE_SECRET_LANE = "shared_infra"
RUNTIME_BRIDGE_DEFAULT_API_BASE = "http://192.168.2.241:8000/api/v1/console-runtime"
RUNTIME_BRIDGE_DEFAULT_KEYS_URL = "http://192.168.2.241:8000"
RUNTIME_BRIDGE_TIMEOUT_SECONDS = "3"
RUNTIME_BRIDGE_JOB_CREATE_TIMEOUT_SECONDS = "15"
RUNTIME_BRIDGE_TOKEN_RETRY_SECONDS = "30"
RUNTIME_BRIDGE_SNAPSHOT_TTL_SECONDS = "5"
RUNTIME_BRIDGE_PROOF_TTL_SECONDS = "120"
RUNTIME_BRIDGE_PROOF_BACKOFF_SECONDS = "30"
RUNTIME_BRIDGE_STARTUP_JITTER_SECONDS = "45"
RUNTIME_BRIDGE_ROUTE_OUTCOME_TTL_SECONDS = "45"
RUNTIME_BRIDGE_ROUTE_OUTCOME_LIMIT = "200"
RUNTIME_BRIDGE_RECENT_ITEMS = "12"
RUNTIME_BRIDGE_LOCAL_FIRST_PROOF_LIMIT = "250"
RUNTIME_BRIDGE_LOCAL_FIRST_SESSION_LIMIT = "20"
LOCAL_LLM_DISABLED_MODEL_PATTERNS = "llama3.2,llama3.2:*"
WORK_BEDROCK_DEFAULT_INSTANCES: tuple[str, ...] = (
    "compere",
    "control-plane",
    "earlybird",
    "gold-book",
    "infra",
    "leadership-kpis",
    "market-sizing",
    "panelbot",
    "platinum-standard",
    "publisher",
    "scout",
    "tmi-dashboards",
)
CODEX_ROLE_POLICY = load_codex_role_policy()
CODEX_ROLE_POLICY_IDENTITY = codex_role_policy_identity(policy=CODEX_ROLE_POLICY)
WORK_SWITCHABLE_MODELS = codex_switchable_models("work", policy=CODEX_ROLE_POLICY)
PERSONAL_SWITCHABLE_MODELS = codex_switchable_models(
    "personal", policy=CODEX_ROLE_POLICY
)
WORK_STANDARD_PROFILE_V2 = codex_role_value(
    "work_standard", "profile_v2", policy=CODEX_ROLE_POLICY
)
WORK_STANDARD_AWS_PROFILE = codex_role_value(
    "work_standard", "aws_profile", policy=CODEX_ROLE_POLICY
)
WORK_STANDARD_MODEL = codex_role_value(
    "work_standard", "model", policy=CODEX_ROLE_POLICY
)
WORK_DIRECT_MODEL = codex_role_value("work_direct", "model", policy=CODEX_ROLE_POLICY)
PERSONAL_DEFAULT_MODEL = codex_role_value(
    "personal_default", "model", policy=CODEX_ROLE_POLICY
)
PERSONAL_DIRECT_MODEL = codex_role_value(
    "personal_direct", "model", default=PERSONAL_DEFAULT_MODEL, policy=CODEX_ROLE_POLICY
)
NON_WORK_BEDROCK_PROFILE_V2 = codex_role_value(
    "personal_default", "profile_v2", policy=CODEX_ROLE_POLICY
)
NON_WORK_BEDROCK_AWS_PROFILE = os.environ.get(
    "NORMAN_SYNC_NON_WORK_BEDROCK_AWS_PROFILE", "kk-personal"
)
NON_WORK_BEDROCK_AWS_REGION = os.environ.get(
    "NORMAN_SYNC_NON_WORK_BEDROCK_AWS_REGION", "us-east-2"
)
WORK_BEDROCK_FAILOVER_SMOKE_PATH = Path(
    os.environ.get(
        "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_SMOKE_PATH",
        "/var/lib/norman/bedrock_region_smoke.json",
    )
)
WORK_BEDROCK_FAILOVER_MAX_AGE_SECONDS = int(
    os.environ.get("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_MAX_AGE_SECONDS", "86400")
)
LOCAL_SOUL_IDENTITY_ROOT = Path(
    os.environ.get(
        "NORMAN_SYNC_SOUL_IDENTITY_ROOT",
        str(SCRIPT_DIR.parent / "db" / "estate" / "identity"),
    )
)
REMOTE_SOUL_IDENTITY_ROOT = os.environ.get(
    "NORMAN_SYNC_REMOTE_SOUL_IDENTITY_ROOT", "/etc/norman/identity"
)
REMOTE_ROUTE_RECEIPT_DIR = os.environ.get(
    "NORMAN_SYNC_ROUTE_RECEIPT_DIR", "/var/lib/norman/route_receipts"
)


def _default_non_work_bedrock_source() -> str:
    if os.environ.get(
        "NORMAN_SYNC_TEST_ALLOW_DEFAULT_NON_WORK_BEDROCK_SOURCE", ""
    ).strip().lower() not in {"1", "true", "yes", "on"}:
        return ""
    homes = [Path(os.environ.get("HOME") or "").expanduser()]
    fallback = os.environ.get("NORMAN_SYNC_NON_WORK_BEDROCK_FALLBACK_HOME", "").strip()
    if fallback:
        homes.append(Path(fallback).expanduser())
    names = ("personal-bedrock.config.toml", "traqline-bedrock.config.toml")
    for home in homes:
        if not str(home):
            continue
        for name in names:
            candidate = home / ".codex-nonwork" / name
            if candidate.exists():
                return str(candidate)
    return ""


NON_WORK_BEDROCK_PROFILE_SOURCE = (
    os.environ.get("NORMAN_SYNC_NON_WORK_BEDROCK_PROFILE_SOURCE", "").strip()
    or _default_non_work_bedrock_source()
)


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str) -> set[str]:
    return {
        item.strip() for item in os.environ.get(name, "").split(",") if item.strip()
    }


def _load_json_file(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _local_llm_inventory() -> (
    tuple[tuple[str, ...], tuple[str, ...], dict[str, list[str]], str]
):
    paths: list[Path] = []
    primary = os.environ.get("NORMAN_SYNC_LOCAL_LLM_SENSE_JSON", "").strip()
    if primary:
        paths.append(Path(primary))
    extra = os.environ.get("NORMAN_SYNC_LOCAL_LLM_SENSE_JSONS", "").strip()
    if extra:
        paths.extend(Path(item.strip()) for item in extra.split(",") if item.strip())

    endpoints: list[str] = []
    model_endpoints: dict[str, list[str]] = {}
    for path in paths:
        payload = _load_json_file(path)
        rows = payload.get("endpoints") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not row.get("ok"):
                continue
            endpoint = str(row.get("endpoint") or "").strip()
            if not endpoint:
                continue
            if endpoint not in endpoints:
                endpoints.append(endpoint)
            models = row.get("models")
            if not isinstance(models, list):
                continue
            for model in models:
                name = str(model or "").strip()
                if not name:
                    continue
                model_endpoints.setdefault(name, [])
                if endpoint not in model_endpoints[name]:
                    model_endpoints[name].append(endpoint)

    priority = {
        "gpt-oss:120b": 0,
        "qwen3.5:122b-a10b-q4_K_M": 1,
        "meta-llama/Llama-3.1-70B-Instruct": 2,
    }
    model_endpoints = {
        model: endpoints
        for model, endpoints in model_endpoints.items()
        if model in priority
    }
    models = tuple(
        sorted(
            model_endpoints,
            key=lambda item: (priority.get(item, 1000), item.lower()),
        )
    )
    default = models[0] if models else ""
    return models, tuple(endpoints), model_endpoints, default


(
    LOCAL_LLM_MODELS,
    LOCAL_LLM_ENDPOINTS,
    LOCAL_LLM_MODEL_ENDPOINTS,
    LOCAL_LLM_DEFAULT_MODEL,
) = _local_llm_inventory()
KERNEL_PRIMARY_CANARY_INSTANCES: tuple[str, ...] = (
    "cloudagent",
    "housebot",
    "networking",
    "scout",
    "uplink",
    "norman",
)
KERNEL_OWNED_TURN_CANARY_INSTANCES: tuple[str, ...] = (
    "cloudagent",
    "housebot",
    "networking",
    "norman",
    "scout",
    "uplink",
)
KERNEL_PRIMARY_MAX_STEPS = "5"
KERNEL_PREFLIGHT_TIMEOUT_SECONDS = "60"
RUNTIME_BRIDGE_ENV_KEYS: tuple[str, ...] = (
    "NORMAN_CONSOLE_RUNTIME_API_BASE",
    "NORMAN_API_BASE_URL",
    "NORMAN_KEYS_URL",
    "NORMAN_KEYS_API_BASE",
    "NORMAN_KEYS_TOKEN",
    "NORMAN_KEYS_API_TOKEN",
    "NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET",
    "NORMAN_CONSOLE_RUNTIME_SECRET_NAME",
)

INSTANCE_LABEL_OVERRIDES = {
    "autocamera": "Autocamera",
    "compere": "Keystone",
    "control-plane": "Control Plane",
    "dj": "DJ Station",
    "theseus": "Theseus",
    "gold-book": "Gold Book",
    "leadership-kpis": "Leadership KPIs",
    "market-sizing": "Market Sizing",
    "mls": "MLS",
    "parkergale": "PEFB",
    "phone-ops": "Phone Ops",
    "platinum-standard": "Platinum Standard",
    "publisher": "Publisher",
    "scout": "Scout",
    "studio": "Studio",
    "tmi-dashboards": "TMI Dashboards",
    "tv": "TV",
    "cloudagent": "CloudAgent",
}

INSTANCE_PROMPT_PLACEHOLDER_OVERRIDES = {
    "dj": "Ask DJ Station to shape sets, tune playback flow, sketch the visualizer, or tighten the music-first UX.",
    "mls": "Ask MLS to inspect listings, summarize property intelligence, or compare candidate homes.",
    "parkergale": "Ask PEFB to inspect the deal room, summarize the thesis, or revise a confidential memo.",
    "platinum-standard": "Ask Platinum Standard to inspect releases, validation inputs, baselines, or a targeted workflow issue.",
    "publisher": "Ask Publisher to tighten the work CMS, connect dashboards, clean up UI flows, or turn a loose surface into a coherent product.",
    "scout": "Ask Scout to refine watchlists, normalize Perplexity findings, or package the weekly datastream.",
    "studio": "Ask Studio to tie DJ, TV, Autocamera, and Glimpser into a cleaner control-room flow.",
    "tv": "Ask TV to shape channels, live sources, camera integrations, or the lean-back viewing surface.",
}

ARCHIVED_INSTANCE_NAMES: set[str] = set()

HOST_HOME_TITLES: dict[str, str] = {
    "norman": "Norman",
    "toy-box": "Toy Box",
    "work-special": "Work Special",
    "networking-host": "Networking Host",
    "private-host": "Private Enclave",
}

HOST_HOME_DESCRIPTIONS: dict[str, str] = {
    "norman": "Host-level landing page for the Norman front door and shared agent hub.",
    "toy-box": "Host-level landing page for the toy-box worker.",
    "work-special": "Host-level landing page for the work-special worker.",
    "networking-host": "Host-level landing page for the networking worker.",
    "private-host": "Dedicated host for Norman confidential bots.",
}

TRUSTED_CONSOLE_CLIENTS = (
    "127.0.0.1",
    "::1",
    "192.168.2.136",  # pixel10
    "100.78.41.73",  # pixel10 tailnet
    "192.168.2.137",  # hal desktop
    "100.112.62.71",  # hal tailnet
    "192.168.2.140",  # plasma-mobile
    "100.109.202.7",  # plasma-mobile tailnet
    "192.168.2.144",  # lollie's desktop
)

TRUSTED_CONSOLE_PROXIES = (
    "127.0.0.1",
    "::1",
    "192.168.2.241",  # norman proxy/front door
)

AUTH_BRIDGE_CLIENTS = (
    "127.0.0.1",
    "::1",
    "192.168.2.136",  # pixel10
    "100.78.41.73",  # pixel10 tailnet
    "192.168.2.137",  # hal desktop
    "100.112.62.71",  # hal tailnet
    "192.168.2.140",  # plasma-mobile
    "100.109.202.7",  # plasma-mobile tailnet
)


REMOTE_COMMAND_TIMEOUT_S = 90
SSH_OPTIONS = (
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "ConnectTimeout=5",
    "-o",
    "ConnectionAttempts=1",
    "-o",
    "ServerAliveInterval=10",
    "-o",
    "ServerAliveCountMax=2",
)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, timeout=REMOTE_COMMAND_TIMEOUT_S)


def capture(cmd: list[str]) -> str:
    completed = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        timeout=REMOTE_COMMAND_TIMEOUT_S,
    )
    return completed.stdout


def ssh_command(host: DiscoveryHost, script: str) -> list[str]:
    if host.local:
        if host.use_sudo:
            return ["sudo", "bash", "-lc", script]
        return ["bash", "-lc", script]
    remote = (
        f"sudo bash -lc {shlex.quote(script)}"
        if host.use_sudo
        else f"bash -lc {shlex.quote(script)}"
    )
    return [
        "ssh",
        *SSH_OPTIONS,
        host.ssh_target,
        remote,
    ]


def scp_command(source: Path, ssh_target: str, remote_path: str) -> list[str]:
    return [
        "scp",
        "-q",
        *SSH_OPTIONS,
        str(source),
        f"{ssh_target}:{remote_path}",
    ]


def local_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_host_instances(host: DiscoveryHost) -> list[ConsoleInstance]:
    payload = json.dumps(list(host.env_globs))
    default_launchers_payload = json.dumps(DEFAULT_LAUNCHERS)
    script = f"""
python3 - <<'PY'
import glob
import json
import os
import re

patterns = json.loads({payload!r})
default_launchers = json.loads({default_launchers_payload!r})


def parse_env(path):
    data = {{}}
    try:
        handle = open(path, "r", encoding="utf-8")
    except PermissionError:
        return None
    with handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def infer_name(path):
    base = os.path.basename(path)
    parent = os.path.basename(os.path.dirname(path))
    if base == "codex-web.env" and parent and parent != "net-agents":
        return parent
    return os.path.splitext(base)[0]


def env_value(env, *keys):
    for key in keys:
        value = (env.get(key) or "").strip()
        if value:
            return value
    return ""


def infer_codex_home(launch_path):
    try:
        text = open(launch_path, "r", encoding="utf-8").read()
    except OSError:
        return ""
    marker = 'CODEX_HOME="$' + chr(123) + 'CODEX_HOME:-'
    start = text.find(marker)
    if start >= 0:
        value_start = start + len(marker)
        value_end = text.find(chr(125) + '"', value_start)
        if value_end >= 0:
            return text[value_start:value_end].strip()
    match = re.search(r"^\\s*CODEX_HOME=(['\\\"]?)([^\\n'\\\"]+)\\1", text, re.M)
    if match:
        return match.group(2).strip()
    return ""


items = []
for pattern in patterns:
    for env_path in sorted(glob.glob(pattern)):
        env = parse_env(env_path)
        if env is None:
            continue
        name = infer_name(env_path)
        launch_path = env_value(env, "HOUSEBOT_CODEX_LAUNCHER", "NORMAN_CODEX_LAUNCHER")
        if not launch_path:
            launch_path = default_launchers.get(name, "")
        if not launch_path:
            continue
        if launch_path.endswith("_launch.sh"):
            web_path = launch_path.replace("_launch.sh", "_web.py")
            supervisor_path = launch_path.replace("_launch.sh", "_supervisor.sh")
        elif launch_path.endswith("/launch.sh"):
            base_dir = os.path.dirname(launch_path)
            web_path = os.path.join(base_dir, "web.py")
            supervisor_path = os.path.join(base_dir, "supervisor.sh")
        else:
            continue
        items.append(
            {{
                "name": name,
                "env_file": env_path,
                "web_path": web_path,
                "launch_path": launch_path,
                "supervisor_path": supervisor_path,
                "agent_label": env_value(env, "HOUSEBOT_CODEX_AGENT_NAME", "NORMAN_CODEX_AGENT_NAME") or name,
                "web_port": env_value(env, "HOUSEBOT_CODEX_WEB_PORT", "NORMAN_CODEX_WEB_PORT"),
                "web_token": env_value(env, "HOUSEBOT_CODEX_WEB_TOKEN", "NORMAN_CODEX_WEB_TOKEN"),
                "prompt_file": env_value(env, "HOUSEBOT_CODEX_PROMPT_FILE", "NORMAN_CODEX_PROMPT_FILE"),
                "codex_home": env_value(env, "HOUSEBOT_CODEX_HOME", "NORMAN_CODEX_HOME", "CODEX_HOME") or infer_codex_home(launch_path),
                "restart_units": [
                    env_value(env, "HOUSEBOT_CODEX_SERVICE_NAME", "NORMAN_CODEX_SERVICE_NAME") or f"{{name}}-codex.service",
                    env_value(env, "HOUSEBOT_CODEX_WEB_SERVICE_NAME", "NORMAN_CODEX_WEB_SERVICE_NAME") or f"{{name}}-codex-web.service",
                ],
            }}
        )

print(json.dumps(items))
PY
"""
    raw = json.loads(capture(ssh_command(host, script)) or "[]")
    instances: list[ConsoleInstance] = []
    for item in raw:
        instances.append(
            ConsoleInstance(
                name=str(item["name"]),
                host_name=host.name,
                ssh_target=host.ssh_target,
                use_sudo=host.use_sudo,
                env_file=str(item["env_file"]),
                web_path=str(item["web_path"]),
                launch_path=str(item["launch_path"]),
                supervisor_path=str(item["supervisor_path"]),
                restart_units=tuple(str(unit) for unit in item["restart_units"]),
                agent_label=str(item.get("agent_label") or item["name"]),
                web_port=str(item.get("web_port") or ""),
                web_token=str(item.get("web_token") or ""),
                prompt_file=str(item.get("prompt_file") or ""),
                codex_home=str(item.get("codex_home") or ""),
            )
        )
    return instances


def discover_all_instances(
    host_filter: list[str] | None = None,
) -> tuple[dict[str, list[ConsoleInstance]], dict[str, ConsoleInstance]]:
    by_host: dict[str, list[ConsoleInstance]] = {}
    by_name: dict[str, ConsoleInstance] = {}
    host_names = host_filter or list(HOSTS)
    for host_name in host_names:
        host = HOSTS[host_name]
        try:
            instances = discover_host_instances(host)
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            print(
                f"warning: skipped {host_name}: {exc.__class__.__name__}",
                file=sys.stderr,
                flush=True,
            )
            by_host[host_name] = []
            continue
        by_host[host_name] = instances
        for instance in instances:
            by_name[instance.name] = instance
    return by_host, by_name


def requested_host_filter(requested: list[str] | None) -> list[str] | None:
    if not requested:
        return None
    if not all(token in HOSTS for token in requested):
        return None
    return list(dict.fromkeys(requested))


def instance_label(instance: ConsoleInstance) -> str:
    override = INSTANCE_LABEL_OVERRIDES.get(instance.name)
    if override:
        return override
    label = (instance.agent_label or "").strip()
    if label:
        return label
    return instance.name.replace("-", " ").title()


def ssh_target_host(ssh_target: str) -> str:
    return ssh_target.rsplit("@", 1)[-1].strip()


def instance_public_host(instance: ConsoleInstance) -> str:
    override = INSTANCE_PUBLIC_HOST_OVERRIDES.get(instance.name, "").strip()
    if override:
        return override
    return HOSTS[instance.host_name].public_host


def host_canonical_host(host: DiscoveryHost) -> str:
    canonical = (host.canonical_host or host.public_host).strip()
    return canonical


def host_frontdoor_hosts(host: DiscoveryHost) -> tuple[str, ...]:
    ordered: list[str] = []
    for value in (
        host_canonical_host(host),
        host.public_host,
        *host.frontdoor_alias_hosts,
    ):
        clean = (value or "").strip()
        if clean and clean not in ordered:
            ordered.append(clean)
    return tuple(ordered)


def instance_uses_frontdoor_proxy(instance: ConsoleInstance) -> bool:
    return bool(INSTANCE_PUBLIC_HOST_OVERRIDES.get(instance.name, "").strip())


def instance_console_urls(
    instance: ConsoleInstance, profile_placeholder: bool = True
) -> dict[str, str]:
    host = HOSTS[instance.host_name]
    public_host = instance_public_host(instance)
    lan_host = host.lan_host
    query = f"?token={instance.web_token}"
    if profile_placeholder:
        query += "&profile={profile}"
    if instance_uses_frontdoor_proxy(instance):
        public_url = f"https://{public_host}/{query}"
    else:
        public_url = f"http://{public_host}:{instance.web_port}/{query}"
    return {
        "url": public_url,
        "lan_url": f"http://{lan_host}:{instance.web_port}/{query}",
    }


def _host_home_title(host: DiscoveryHost) -> str:
    return HOST_HOME_TITLES.get(host.name, host.name.replace("-", " ").title())


def _host_home_description(host: DiscoveryHost) -> str:
    return HOST_HOME_DESCRIPTIONS.get(
        host.name, f"Host-level landing page for the {host.name} worker."
    )


def _instance_console_query(instance: ConsoleInstance) -> str:
    token = urllib.parse.quote(instance.web_token, safe="")
    return f"?token={token}" if token else ""


def _append_query(url: str, query: str) -> str:
    if not query:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query.lstrip('?')}"


def host_home_urls(host: DiscoveryHost) -> list[tuple[str, str]]:
    suffix = "/host/" if host.name == "norman" else "/"
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in host_frontdoor_hosts(host):
        clean = (value or "").strip()
        if not clean:
            continue
        scheme = "https"
        url = f"{scheme}://{clean}{suffix}"
        if url in seen:
            continue
        seen.add(url)
        entries.append((clean, url))
    for value in (*host.alias_hosts, host.lan_host):
        clean = (value or "").strip()
        if not clean:
            continue
        scheme = "http"
        url = f"{scheme}://{clean}{suffix}"
        if url in seen:
            continue
        seen.add(url)
        entries.append((clean, url))
    return entries


def instance_host_home_links(instance: ConsoleInstance) -> list[tuple[str, str]]:
    host = HOSTS[instance.host_name]
    query = _instance_console_query(instance)
    public_host = instance_public_host(instance)
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        normalized = url.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        label = urllib.parse.urlsplit(normalized).netloc or normalized
        entries.append((label, normalized))

    if instance_uses_frontdoor_proxy(instance):
        add(_append_query(f"https://{public_host}/", query))

    add(f"http://{host.public_host}:{instance.web_port}/{query}")
    for alias_host in host.alias_hosts:
        add(f"http://{alias_host}:{instance.web_port}/{query}")
    add(f"http://{host.lan_host}:{instance.web_port}/{query}")
    return entries


def render_host_home_html(host: DiscoveryHost, instances: list[ConsoleInstance]) -> str:
    title = html.escape(_host_home_title(host))
    description = html.escape(_host_home_description(host))
    badge = html.escape(host.name)
    host_link_markup = "".join(
        f'<a class="host-link" href="{html.escape(url)}">{html.escape(label)}</a>'
        for label, url in host_home_urls(host)
    )
    cards: list[str] = []
    for instance in sorted(instances, key=lambda item: instance_label(item).lower()):
        endpoints = instance_host_home_links(instance)
        if not endpoints:
            continue
        links_markup = "".join(
            f'<a class="endpoint" href="{html.escape(url)}">{html.escape(label)}</a>'
            for label, url in endpoints
        )
        cards.append(
            "\n".join(
                [
                    '<article class="service-card">',
                    f"  <h2>{html.escape(instance_label(instance))}</h2>",
                    f'  <div class="service-slug">{html.escape(instance.name)}</div>',
                    f'  <div class="service-links">{links_markup}</div>',
                    "</article>",
                ]
            )
        )
    cards_markup = "\n".join(cards) or "<p>No published services found.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0d1210;
      --panel: #141c18;
      --panel-2: #101714;
      --text: #d9e3dc;
      --muted: #9aac9f;
      --line: rgba(181, 213, 193, 0.18);
      --accent: #86d7aa;
      --accent-2: #9fd0ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top, rgba(72, 110, 86, 0.15), transparent 38%), var(--bg);
      color: var(--text);
      font: 16px/1.5 "IBM Plex Mono", "SFMono-Regular", ui-monospace, monospace;
    }}
    main {{
      max-width: 74rem;
      margin: 6vh auto;
      padding: 1.5rem;
    }}
    .shell {{
      border: 1px solid var(--line);
      background: rgba(20, 28, 24, 0.92);
      box-shadow: 0 26px 80px rgba(0, 0, 0, 0.35);
      padding: 1.5rem;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 1rem;
      align-items: start;
    }}
    .eyebrow {{
      font-size: 0.82rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    h1 {{
      margin: 0.2rem 0 0.5rem;
      font-size: clamp(1.8rem, 3vw, 2.4rem);
      line-height: 1.1;
    }}
    p {{
      margin: 0;
      color: var(--muted);
    }}
    .badge {{
      padding: 0.42rem 0.8rem;
      border: 1px solid var(--line);
      background: rgba(33, 44, 39, 0.9);
      color: var(--text);
      white-space: nowrap;
    }}
    .host-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.55rem;
      margin-top: 1rem;
    }}
    .host-link,
    .endpoint {{
      display: inline-flex;
      align-items: center;
      min-height: 2rem;
      padding: 0.2rem 0.6rem;
      border: 1px solid var(--line);
      color: var(--accent-2);
      text-decoration: none;
      background: rgba(16, 23, 20, 0.96);
      overflow-wrap: anywhere;
    }}
    .host-link:hover,
    .endpoint:hover {{
      border-color: rgba(159, 208, 255, 0.35);
      color: #c6e5ff;
      background: rgba(20, 31, 29, 1);
    }}
    .section {{
      margin-top: 1.4rem;
    }}
    .section-title {{
      margin-bottom: 0.75rem;
      font-size: 0.82rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .services {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
      gap: 0.85rem;
    }}
    .service-card {{
      border: 1px solid var(--line);
      background: var(--panel-2);
      padding: 0.95rem;
      min-height: 100%;
    }}
    .service-card h2 {{
      margin: 0;
      font-size: 1.05rem;
      line-height: 1.2;
    }}
    .service-slug {{
      margin-top: 0.25rem;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .service-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 0.85rem;
    }}
    @media (max-width: 720px) {{
      main {{ margin: 0; padding: 1rem; }}
      .hero {{ grid-template-columns: minmax(0, 1fr); }}
      .badge {{ justify-self: start; }}
      .services {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="shell">
      <div class="hero">
        <div>
          <div class="eyebrow">Norman Host</div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        <div class="badge">{badge}</div>
      </div>
      <div class="host-links">{host_link_markup}</div>
      <div class="section">
        <div class="section-title">Published services</div>
        <div class="services">
{cards_markup}
        </div>
      </div>
    </section>
  </main>
</body>
</html>
"""


def sync_host_home_page(host: DiscoveryHost, instances: list[ConsoleInstance]) -> bool:
    if not host.host_home_path:
        return False
    rendered = render_host_home_html(host, instances)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".html", delete=False
    ) as handle:
        handle.write(rendered)
        temp_path = Path(handle.name)
    try:
        return install_source_path(
            host,
            remote_path=host.host_home_path,
            source=temp_path,
            source_sha256=local_sha256(temp_path),
        )
    finally:
        temp_path.unlink(missing_ok=True)


def desired_console_links(
    instance: ConsoleInstance,
    *,
    discovered_by_host: dict[str, list[ConsoleInstance]],
    discovered_by_name: dict[str, ConsoleInstance],
) -> list[dict[str, object]]:
    links: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def group_priority(group: str) -> int:
        normalized = group.strip().lower()
        if normalized == "norman":
            return 220
        if normalized == "personal":
            return 180
        if normalized == "shared":
            return 120
        if normalized == "work":
            return 70
        return 30

    def add_link(
        label: str,
        target: ConsoleInstance,
        group: str,
        *,
        featured: bool = False,
        priority: int = 0,
    ) -> None:
        if not target.web_port or not target.web_token:
            return
        urls = instance_console_urls(target)
        key = (group, label, urls["url"], urls["lan_url"])
        if target.name == instance.name or key in seen:
            return
        seen.add(key)
        link: dict[str, object] = {"label": label, "group": group, **urls}
        if featured:
            link["featured"] = True
        if priority:
            link["priority"] = priority
        links.append(link)

    for host_name in (
        "norman",
        "hal",
        "toy-box",
        "work-special",
        "networking-host",
        "private-host",
    ):
        if host_name == instance.host_name:
            continue
        hub = HOST_HUBS.get(host_name)
        if not hub:
            continue
        hub_name, hub_label = hub
        target = discovered_by_name.get(hub_name)
        if target:
            group = HOST_GROUP_LABELS.get(host_name, hub_label)
            add_link(
                hub_label,
                target,
                group,
                featured=True,
                priority=group_priority(group),
            )

    for sibling in discovered_by_host.get(instance.host_name, []):
        group = HOST_GROUP_LABELS.get(instance.host_name, "Agents")
        add_link(
            instance_label(sibling),
            sibling,
            group,
            priority=max(20, group_priority(group) - 40),
        )

    return links


def sync_instance_links(
    host: DiscoveryHost, instance: ConsoleInstance, links: list[dict[str, object]]
) -> bool:
    rendered = json.dumps(links, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import re

path = Path({instance.env_file!r})
value = {rendered!r}
text = path.read_text(encoding="utf-8")
line = f"HOUSEBOT_CODEX_LINKS_JSON={{value}}"
pattern = re.compile(r"^HOUSEBOT_CODEX_LINKS_JSON=.*$", re.M)
if pattern.search(text):
    updated = pattern.sub(line, text, count=1)
else:
    updated = text if text.endswith("\\n") else text + "\\n"
    updated += line + "\\n"
if updated != text:
    path.write_text(updated, encoding="utf-8")
    print("changed")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def instance_uses_work_config(host: DiscoveryHost, instance: ConsoleInstance) -> bool:
    if host.name in _env_csv("NORMAN_SYNC_WORK_CONFIG_EXTRA_HOSTS"):
        return True
    if host.name == "work-special":
        return True
    return bool(
        instance.name in WORK_BEDROCK_DEFAULT_INSTANCES and host.name == "work-special"
    )


def non_work_bedrock_profile_source_ready() -> bool:
    return bool(
        NON_WORK_BEDROCK_PROFILE_SOURCE
        and Path(NON_WORK_BEDROCK_PROFILE_SOURCE).exists()
    )


def instance_uses_non_work_bedrock(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    if os.environ.get("NORMAN_SYNC_NON_WORK_BEDROCK_DEFAULT_ENABLED", "1") == "0":
        return False
    if instance_uses_work_config(host, instance):
        return False
    if host.name in {"norman", "networking-host", "work-special"}:
        return False
    return non_work_bedrock_profile_source_ready()


def _fresh_work_bedrock_smoke_profiles() -> list[dict[str, str]]:
    payload = _load_json_file(WORK_BEDROCK_FAILOVER_SMOKE_PATH)
    if not isinstance(payload, dict):
        return []
    checked_at = float(payload.get("checked_at") or 0)
    if (
        checked_at <= 0
        or time.time() - checked_at > WORK_BEDROCK_FAILOVER_MAX_AGE_SECONDS
    ):
        return []
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        return []
    rows: list[dict[str, str]] = []
    for name in ("traqline-bedrock-us-east-1", "traqline-bedrock-us-west-2"):
        item = profiles.get(name)
        if not isinstance(item, dict) or not item.get("ok"):
            continue
        rows.append(
            {
                "profile_v2": str(item.get("profile_v2") or name),
                "model": str(item.get("model") or WORK_DIRECT_MODEL),
                "aws_region": str(item.get("aws_region") or ""),
            }
        )
    return rows


def _work_bedrock_failover_profiles() -> list[dict[str, str]]:
    if _env_truthy("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_ENABLED"):
        return [
            {
                "profile_v2": "traqline-bedrock-us-east-1",
                "model": WORK_DIRECT_MODEL,
                "aws_region": "us-east-1",
            }
        ]
    return _fresh_work_bedrock_smoke_profiles()


def _local_llm_env_updates() -> dict[str, str]:
    disabled_update = {
        "NORMAN_LOCAL_LLM_DISABLED_MODELS": LOCAL_LLM_DISABLED_MODEL_PATTERNS
    }
    if not LOCAL_LLM_MODELS and not LOCAL_LLM_ENDPOINTS:
        return disabled_update
    return {
        **disabled_update,
        "NORMAN_LOCAL_LLM_MODEL": LOCAL_LLM_DEFAULT_MODEL,
        "NORMAN_LOCAL_LLM_MODELS": ",".join(LOCAL_LLM_MODELS),
        "NORMAN_LOCAL_LLM_ENDPOINTS": ",".join(LOCAL_LLM_ENDPOINTS),
        "NORMAN_LOCAL_LLM_MODEL_ENDPOINTS": json.dumps(
            LOCAL_LLM_MODEL_ENDPOINTS, separators=(",", ":"), sort_keys=True
        ),
    }


def _origin_model_updates(
    host: DiscoveryHost, instance: ConsoleInstance
) -> tuple[dict[str, str], list[str]]:
    remove_keys = [
        "NORMAN_CODEX_STANDARD_PROFILE_V2",
        "NORMAN_CODEX_STANDARD_AWS_PROFILE",
        "NORMAN_CODEX_STANDARD_MODEL",
        "NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2",
        "NORMAN_CODEX_BEDROCK_FAILOVER_MODEL",
        "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION",
        "NORMAN_CODEX_BEDROCK_FAILOVER2_PROFILE_V2",
        "NORMAN_CODEX_BEDROCK_FAILOVER2_MODEL",
        "NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_REGION",
        "NORMAN_CODEX_DIRECT_TIERS_ENABLED",
    ]
    use_work = instance_uses_work_config(host, instance)
    work_enabled = (
        os.environ.get("NORMAN_SYNC_WORK_BEDROCK_DEFAULT_ENABLED", "1") != "0"
    )
    role_policy_env = {
        "NORMAN_CODEX_ROLE_POLICY_ID": CODEX_ROLE_POLICY_IDENTITY["policy_id"],
        "NORMAN_CODEX_ROLE_POLICY_HASH": CODEX_ROLE_POLICY_IDENTITY["policy_hash"],
        "NORMAN_CODEX_ROLE_POLICY_VERSION": CODEX_ROLE_POLICY_IDENTITY["version"],
    }
    if use_work and work_enabled:
        direct_tiers = os.environ.get("NORMAN_SYNC_WORK_DIRECT_TIERS_ENABLED", "1")
        failovers = _work_bedrock_failover_profiles()
        updates = {
            **role_policy_env,
            "NORMAN_CODEX_BILLING_SCOPE": "work-special",
            "NORMAN_CODEX_BILLING_OWNER": "openbrand",
            "NORMAN_CODEX_SERVICE_TIER": "default",
            "NORMAN_CODEX_STANDARD_PROFILE_V2": WORK_STANDARD_PROFILE_V2,
            "NORMAN_CODEX_STANDARD_AWS_PROFILE": WORK_STANDARD_AWS_PROFILE,
            "NORMAN_CODEX_STANDARD_MODEL": WORK_STANDARD_MODEL,
            "NORMAN_CODEX_MODEL": WORK_DIRECT_MODEL,
            "NORMAN_CODEX_MODEL_FLOOR": "gpt-5.4",
            "NORMAN_CODEX_DIRECT_MODEL": WORK_DIRECT_MODEL,
            "NORMAN_CODEX_FLEX_MODEL": WORK_DIRECT_MODEL,
            "NORMAN_CODEX_PRIORITY_MODEL": WORK_STANDARD_MODEL,
            "NORMAN_CODEX_SWITCHABLE_MODELS": WORK_SWITCHABLE_MODELS,
            "NORMAN_CODEX_AVAILABLE_MODELS": WORK_SWITCHABLE_MODELS,
            "NORMAN_CODEX_DIRECT_TIERS_ENABLED": direct_tiers,
            "NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES": str(1 + len(failovers)),
            "NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2": "",
            "NORMAN_CODEX_BEDROCK_FAILOVER_MODEL": "",
            "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION": "",
            "NORMAN_CODEX_BEDROCK_FAILOVER2_PROFILE_V2": "",
            "NORMAN_CODEX_BEDROCK_FAILOVER2_MODEL": "",
            "NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_REGION": "",
        }
        if failovers:
            updates.update(
                {
                    "NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2": failovers[0][
                        "profile_v2"
                    ],
                    "NORMAN_CODEX_BEDROCK_FAILOVER_MODEL": failovers[0]["model"],
                    "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION": failovers[0][
                        "aws_region"
                    ],
                }
            )
        if len(failovers) > 1:
            updates.update(
                {
                    "NORMAN_CODEX_BEDROCK_FAILOVER2_PROFILE_V2": failovers[1][
                        "profile_v2"
                    ],
                    "NORMAN_CODEX_BEDROCK_FAILOVER2_MODEL": failovers[1]["model"],
                    "NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_REGION": failovers[1][
                        "aws_region"
                    ],
                }
            )
        return updates, []

    if instance_uses_non_work_bedrock(host, instance):
        return (
            {
                **role_policy_env,
                "NORMAN_CODEX_BILLING_SCOPE": host.name,
                "NORMAN_CODEX_BILLING_OWNER": "kristopher",
                "NORMAN_CODEX_SERVICE_TIER": "default",
                "NORMAN_CODEX_STANDARD_PROFILE_V2": NON_WORK_BEDROCK_PROFILE_V2,
                "NORMAN_CODEX_STANDARD_AWS_PROFILE": NON_WORK_BEDROCK_AWS_PROFILE,
                "NORMAN_CODEX_STANDARD_AWS_REGION": NON_WORK_BEDROCK_AWS_REGION,
                "NORMAN_CODEX_STANDARD_MODEL": PERSONAL_DEFAULT_MODEL,
                "NORMAN_CODEX_MODEL": PERSONAL_DEFAULT_MODEL,
                "NORMAN_CODEX_MODEL_FLOOR": PERSONAL_DEFAULT_MODEL,
                "NORMAN_CODEX_DIRECT_MODEL": PERSONAL_DEFAULT_MODEL,
                "NORMAN_CODEX_FLEX_MODEL": PERSONAL_DEFAULT_MODEL,
                "NORMAN_CODEX_PRIORITY_MODEL": PERSONAL_DEFAULT_MODEL,
                "NORMAN_CODEX_SWITCHABLE_MODELS": PERSONAL_SWITCHABLE_MODELS,
                "NORMAN_CODEX_AVAILABLE_MODELS": PERSONAL_SWITCHABLE_MODELS,
                "NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES": "1",
            },
            [],
        )

    service_tier = "auto" if use_work else "flex"
    updates = {
        **role_policy_env,
        "NORMAN_CODEX_BILLING_SCOPE": host.name,
        "NORMAN_CODEX_BILLING_OWNER": "kristopher",
        "NORMAN_CODEX_SERVICE_TIER": service_tier,
        "NORMAN_CODEX_MODEL": PERSONAL_DIRECT_MODEL,
        "NORMAN_CODEX_MODEL_FLOOR": PERSONAL_DIRECT_MODEL,
        "NORMAN_CODEX_DIRECT_MODEL": PERSONAL_DIRECT_MODEL,
        "NORMAN_CODEX_FLEX_MODEL": PERSONAL_DIRECT_MODEL,
        "NORMAN_CODEX_PRIORITY_MODEL": PERSONAL_DIRECT_MODEL,
        "NORMAN_CODEX_SWITCHABLE_MODELS": PERSONAL_SWITCHABLE_MODELS,
        "NORMAN_CODEX_AVAILABLE_MODELS": PERSONAL_SWITCHABLE_MODELS,
        "NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES": "1",
    }
    return updates, remove_keys


def sync_instance_origin_settings(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    aliases = []
    canonical_host = instance_public_host(instance)
    for value in (
        canonical_host,
        host_canonical_host(host),
        host.public_host,
        *host.frontdoor_alias_hosts,
        host.lan_host,
        *host.alias_hosts,
    ):
        clean = (value or "").strip()
        if clean and clean not in aliases:
            aliases.append(clean)
    updates = {
        "HOUSEBOT_CODEX_CANONICAL_HOST": canonical_host,
        "HOUSEBOT_CODEX_CANONICAL_VIA_PROXY": (
            "1" if instance_uses_frontdoor_proxy(instance) else "0"
        ),
        "HOUSEBOT_CODEX_LOCAL_HOST_ALIASES": ",".join(aliases),
        "HOUSEBOT_CODEX_TRUSTED_CLIENTS": ",".join(TRUSTED_CONSOLE_CLIENTS),
        "HOUSEBOT_CODEX_TRUSTED_PROXIES": ",".join(TRUSTED_CONSOLE_PROXIES),
        "HOUSEBOT_CODEX_BROWSER_AUTH_CLIENTS": ",".join(AUTH_BRIDGE_CLIENTS),
        "HOUSEBOT_CODEX_AGENT_GROUP": HOST_GROUP_LABELS.get(host.name, "Agents"),
        "HOUSEBOT_CODEX_ENV_FILE": instance.env_file,
    }
    model_updates, remove_keys = _origin_model_updates(host, instance)
    bbs_url = os.environ.get("NORMAN_SYNC_BBS_URL", "").strip()
    switchboard_env = f"/etc/{instance.name}/switchboard-bbs.env"
    updates.update(model_updates)
    updates.update(
        {
            "NORMAN_CODEX_BBS_URL": bbs_url,
            "NORMAN_CODEX_BBS_ACTOR": instance.name,
            "NORMAN_CODEX_BBS_ENV_FILE": switchboard_env,
            "SWITCHBOARD_URL": bbs_url,
            "SWITCHBOARD_ACTOR": instance.name,
            "SWITCHBOARD_ENV_FILE": switchboard_env,
            "NORMAN_CODEX_SOUL_ENABLED": "1",
            "NORMAN_CODEX_SOUL_ACTOR": instance.name,
            "NORMAN_CODEX_SOUL_IDENTITY_ROOT": REMOTE_SOUL_IDENTITY_ROOT,
            "NORMAN_CODEX_SOUL_LOADER": f"/opt/{instance.name}/compose_soul_context.py",
            "NORMAN_CODEX_CONTEXT_PREFLIGHT_OFFLINE_COMMAND": (
                f"python3 /opt/{instance.name}/tui_vector_preflight.py"
            ),
            "NORMAN_CODEX_VECTOR_PREFLIGHT_LIMIT": "5",
        }
    )
    updates.update(_local_llm_env_updates())
    payload = json.dumps(updates, separators=(",", ":"))
    remove_payload = json.dumps(remove_keys, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import re

path = Path({instance.env_file!r})
updates = json.loads({payload!r})
remove_keys = json.loads({remove_payload!r})
text = path.read_text(encoding="utf-8")
changed = False
for key in remove_keys:
    pattern = re.compile(rf"^{{re.escape(key)}}=.*\\n?", re.M)
    updated = pattern.sub("", text)
    if updated != text:
        text = updated
        changed = True
for key, value in updates.items():
    line = f"{{key}}={{value}}"
    pattern = re.compile(rf"^{{re.escape(key)}}=.*$", re.M)
    if pattern.search(text):
        updated = pattern.sub(line, text, count=1)
    else:
        updated = text if text.endswith("\\n") else text + "\\n"
        updated += line + "\\n"
    if updated != text:
        text = updated
        changed = True
if changed:
    path.write_text(text, encoding="utf-8")
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_route_receipts(
    host: DiscoveryHost,
    instance: ConsoleInstance,
    *,
    receipt_dir: str = REMOTE_ROUTE_RECEIPT_DIR,
    max_items: str = "250",
) -> bool:
    receipt_path = f"{receipt_dir.rstrip('/')}/{instance.name}.jsonl"
    updates = {
        "NORMAN_CODEX_ROUTE_RECEIPTS_ENABLED": "1",
        "NORMAN_CODEX_ROUTE_RECEIPT_OWNER_TUI": instance.name,
        "NORMAN_CODEX_ROUTE_RECEIPT_DIR": receipt_dir,
        "NORMAN_CODEX_ROUTE_RECEIPT_PATH": receipt_path,
        "NORMAN_CODEX_ROUTE_RECEIPT_ITEMS": str(max_items),
    }
    payload = json.dumps(updates, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import os
import pwd
import grp
import re

env_path = Path({instance.env_file!r})
updates = json.loads({payload!r})
route_receipt_path = Path({receipt_dir!r})
receipt_owner_source = Path('/var/lib/{instance.name}/codex')
try:
    owner_stat = receipt_owner_source.stat()
    target_uid = owner_stat.st_uid
    target_gid = owner_stat.st_gid
except OSError:
    target_uid = pwd.getpwnam('root').pw_uid
    target_gid = grp.getgrnam('root').gr_gid
route_receipt_path.mkdir(parents=True, exist_ok=True)
os.chown(route_receipt_path, target_uid, target_gid)
os.chmod(route_receipt_path, 0o750)
route_receipt_file = Path({receipt_path!r})
route_receipt_file.touch()
os.chown(route_receipt_file, target_uid, target_gid)
os.chmod(route_receipt_file, 0o640)
text = env_path.read_text(encoding="utf-8")
changed = False
for key, value in updates.items():
    line = f"{{key}}={{value}}"
    pattern = re.compile(rf"^{{re.escape(key)}}=.*$", re.M)
    if pattern.search(text):
        updated = pattern.sub(line, text, count=1)
    else:
        updated = text if text.endswith("\\n") else text + "\\n"
        updated += line + "\\n"
    if updated != text:
        text = updated
        changed = True
if changed:
    env_path.write_text(text, encoding="utf-8")
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_runtime_settings(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    if instance_uses_work_config(host, instance):
        desired_model = WORK_DIRECT_MODEL
        switchable_models = [
            item.strip() for item in WORK_SWITCHABLE_MODELS.split(",") if item.strip()
        ]
    else:
        desired_model = PERSONAL_DIRECT_MODEL
        switchable_models = [
            item.strip()
            for item in PERSONAL_SWITCHABLE_MODELS.split(",")
            if item.strip()
        ]
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json

legacy_runtime_path = Path({instance.codex_home!r}) / "runtime_settings.json"
runtime_path = Path({instance.codex_home!r}) / "web-bridge" / "runtime_settings.json"
desired_model = {desired_model!r}
switchable_models = {switchable_models!r}
stale_default_models = {{
    "",
    "gpt-5.5",
    "openai.gpt-5.5",
    "gpt-5.6-terra",
    "openai.gpt-5.6-terra",
}}
stale_model_markers = tuple(
    model for model in stale_default_models if model
)

def is_stale_model(value):
    return str(value or "").strip().lower() in stale_default_models

def has_stale_model_scope(value):
    scope = str(value or "").strip().lower()
    return any(marker in scope for marker in stale_model_markers)

def is_pending(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {{"1", "true", "yes", "on"}}

payload = {{}}
if runtime_path.exists():
    try:
        payload = json.loads(runtime_path.read_text(encoding="utf-8") or "{{}}")
    except json.JSONDecodeError:
        payload = {{}}
payload["model"] = desired_model
payload["service_tier"] = "default"
payload["model_floor"] = desired_model
payload["switchable_models"] = switchable_models
runtime_path.parent.mkdir(parents=True, exist_ok=True)
rendered = json.dumps(payload, sort_keys=True, indent=2) + "\\n"
old = runtime_path.read_text(encoding="utf-8") if runtime_path.exists() else ""
if old != rendered:
    runtime_path.write_text(rendered, encoding="utf-8")
    changed = True
else:
    changed = False
legacy_runtime_path.parent.mkdir(parents=True, exist_ok=True)
old_legacy = (
    legacy_runtime_path.read_text(encoding="utf-8")
    if legacy_runtime_path.exists()
    else ""
)
if old_legacy != rendered:
    legacy_runtime_path.write_text(rendered, encoding="utf-8")
    changed = True
status_path = Path({instance.codex_home!r}) / "web-bridge" / "status.json"
thread_id_path = Path({instance.codex_home!r}) / "web-bridge" / "thread_id.txt"
thread_scope_path = Path({instance.codex_home!r}) / "web-bridge" / "thread_scope.txt"
if status_path.exists():
    try:
        status = json.loads(status_path.read_text(encoding="utf-8") or "{{}}")
    except json.JSONDecodeError:
        status = {{}}
    model_keys = ("selected_model", "running_model", "last_model")
    stale_status_model = isinstance(status, dict) and any(
        is_stale_model(status.get(key)) for key in model_keys
    )
    stale_scope = has_stale_model_scope(
        thread_scope_path.read_text(encoding="utf-8")
        if thread_scope_path.exists()
        else ""
    )
    stale_scope = stale_scope or (
        isinstance(status, dict)
        and has_stale_model_scope(status.get("thread_scope"))
    )
    if (
        isinstance(status, dict)
        and not is_pending(status.get("pending"))
        and (stale_status_model or stale_scope)
    ):
        for key in model_keys:
            status[key] = desired_model
        for key in ("selected_runtime", "running_runtime", "last_runtime"):
            status[key] = "codex"
        status["thread_id"] = ""
        status["thread_scope"] = ""
        for key in (
            "running_cost_route",
            "last_cost_route",
            "running_turn_envelope",
        ):
            status[key] = {{}}
        status_path.write_text(json.dumps(status, sort_keys=True) + "\\n", encoding="utf-8")
        thread_id_path.write_text("", encoding="utf-8")
        thread_scope_path.write_text("", encoding="utf-8")
        changed = True
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_disabled_plugin_settings(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    disabled_plugins = DISABLED_CODEX_PLUGINS_BY_INSTANCE.get(instance.name, ())
    if not disabled_plugins:
        return False

    payload = json.dumps(disabled_plugins)
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import re

config_path = Path({instance.codex_home!r}) / "config.toml"
disabled_plugins = json.loads({payload!r})
if not config_path.exists():
    print("unchanged")
    raise SystemExit(0)

original = config_path.read_text(encoding="utf-8")
updated = original
for plugin in disabled_plugins:
    pattern = re.compile(
        r'^\\[plugins\\."' + re.escape(plugin) + r'"\\]\\n.*?(?=^\\[|\\Z)',
        re.MULTILINE | re.DOTALL,
    )
    updated = pattern.sub("", updated)
updated = re.sub(r"\\n{{3,}}", "\\n\\n", updated)
if updated != original:
    config_path.write_text(updated, encoding="utf-8")
    print("changed")
else:
    print("unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_bedrock_profile(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    if instance_uses_work_config(host, instance):
        profile_specs = [
            {
                "profile_v2": WORK_STANDARD_PROFILE_V2,
                "source": "/home/kristopher/.codex-infra/traqline-bedrock.config.toml",
                "model": WORK_STANDARD_MODEL,
                "reasoning_effort": "xhigh",
                "aws_region": "",
            }
        ]
        if _env_truthy("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_ENABLED"):
            profile_specs.append(
                {
                    "profile_v2": "traqline-bedrock-us-east-1",
                    "source": "/home/kristopher/.codex-infra/traqline-bedrock.config.toml",
                    "model": WORK_DIRECT_MODEL,
                    "reasoning_effort": "xhigh",
                    "aws_region": "us-east-1",
                }
            )
    elif instance_uses_non_work_bedrock(host, instance):
        source_path = Path(NON_WORK_BEDROCK_PROFILE_SOURCE)
        source_text = source_path.read_text(encoding="utf-8")
        profile_specs = [
            {
                "profile_v2": NON_WORK_BEDROCK_PROFILE_V2,
                "source": str(source_path),
                "source_text": source_text,
                "source_text_present": True,
                "model": PERSONAL_DEFAULT_MODEL,
                "reasoning_effort": "xhigh",
                "aws_profile": NON_WORK_BEDROCK_AWS_PROFILE,
                "aws_region": NON_WORK_BEDROCK_AWS_REGION,
            }
        ]
    else:
        return False
    payload = json.dumps(profile_specs, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import re

target_home = Path({instance.codex_home!r})
profile_specs = json.loads({payload!r})
target_home.mkdir(parents=True, exist_ok=True)

def ensure_table_setting(text, table, key, value):
    if not value:
        return text
    aws_table = table
    header = f"[{{aws_table}}]" if aws_table else ""
    line = f"{{key}} = {{json.dumps(value)}}"
    pattern = re.compile(rf"^{{re.escape(key)}}\\s*=.*$", re.M)
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    if header and header not in text:
        text = (text.rstrip() + "\\n\\n" + header + "\\n").lstrip("\\n")
    return text.rstrip() + "\\n" + line + "\\n"

changed = False
for spec in profile_specs:
    profile_name = str(spec["profile_v2"])
    source = Path(str(spec["source"]))
    target = target_home / (profile_name + ".config.toml")
    if spec.get("source_text_present"):
        rendered = str(spec.get("source_text") or "")
    elif source.exists():
        rendered = source.read_text(encoding="utf-8")
    else:
        rendered = ""
    aws_region = str(spec.get("aws_region") or "")
    aws_profile = str(spec.get("aws_profile") or "")
    aws_table = "aws"
    model_reasoning_effort = str(spec.get("reasoning_effort") or "xhigh")
    rendered = ensure_table_setting(rendered, "", "model", str(spec.get("model") or ""))
    rendered = ensure_table_setting(rendered, "", "model_reasoning_effort", model_reasoning_effort)
    rendered = ensure_table_setting(rendered, aws_table, "profile", aws_profile)
    rendered = ensure_table_setting(rendered, aws_table, "region", aws_region)
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    if old != rendered:
        target.write_text(rendered, encoding="utf-8")
        changed = True

print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_agent_label(host: DiscoveryHost, instance: ConsoleInstance) -> bool:
    label = instance_label(instance)
    if not label:
        return False
    updates = {
        "HOUSEBOT_CODEX_AGENT_NAME": label,
        "HOUSEBOT_CODEX_CONSOLE_TITLE": f"{label} Console",
    }
    prompt_placeholder = INSTANCE_PROMPT_PLACEHOLDER_OVERRIDES.get(instance.name)
    if prompt_placeholder:
        updates["HOUSEBOT_CODEX_PROMPT_PLACEHOLDER"] = prompt_placeholder
    payload = json.dumps(updates, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import re

path = Path({instance.env_file!r})
updates = json.loads({payload!r})
text = path.read_text(encoding="utf-8")
changed = False
for key, value in updates.items():
    line = f"{{key}}={{value}}"
    pattern = re.compile(rf"^{{re.escape(key)}}=.*$", re.M)
    if pattern.search(text):
        updated = pattern.sub(line, text, count=1)
    else:
        updated = text if text.endswith("\\n") else text + "\\n"
        updated += line + "\\n"
    if updated != text:
        text = updated
        changed = True
if changed:
    path.write_text(text, encoding="utf-8")
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_local_llm_foreground_settings(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    updates = {
        "NORMAN_LOCAL_LLM_CALL_TIMEOUT_SECONDS": "360",
        "NORMAN_LOCAL_LLM_FOREGROUND_TIMEOUT_SECONDS": "240",
        "NORMAN_LOCAL_LLM_SHORT_TIMEOUT_SECONDS": "120",
        "NORMAN_LOCAL_LLM_QUICK_MAX_OUTPUT_TOKENS": "384",
        "NORMAN_LOCAL_LLM_SHORT_MAX_OUTPUT_TOKENS": "800",
        "NORMAN_LOCAL_LLM_NUM_CTX": "8192",
        "NORMAN_LOCAL_LLM_SHORT_NUM_CTX": "4096",
        "NORMAN_LOCAL_LLM_FALLBACK_MODELS": "",
        "NORMAN_LOCAL_LLM_ALLOW_TINY_FOREGROUND_FALLBACK": "0",
    }
    remove_keys = [
        "NORMAN_LOCAL_PLANNER_PREFLIGHT_MODELS",
        "NORMAN_LOCAL_PLANNER_MODELS",
        "NORMAN_LOCAL_LLM_FILTER_MODELS",
        "NORMAN_LOCAL_LLM_PLANNER_MODELS",
    ]
    payload = json.dumps(updates, separators=(",", ":"))
    remove_payload = json.dumps(remove_keys, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import re

path = Path({instance.env_file!r})
updates = json.loads({payload!r})
remove_keys = json.loads({remove_payload!r})
text = path.read_text(encoding="utf-8")
changed = False
for key in remove_keys:
    pattern = re.compile(rf"^{{re.escape(key)}}=.*\\n?", re.M)
    updated = pattern.sub("", text)
    if updated != text:
        text = updated
        changed = True
for key, value in updates.items():
    line = f"{{key}}={{value}}"
    pattern = re.compile(rf"^{{re.escape(key)}}=.*$", re.M)
    if pattern.search(text):
        updated = pattern.sub(line, text, count=1)
    else:
        updated = text if text.endswith("\\n") else text + "\\n"
        updated += line + "\\n"
    if updated != text:
        text = updated
        changed = True
if changed:
    path.write_text(text, encoding="utf-8")
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def read_instance_env_values(
    host: DiscoveryHost,
    instance: ConsoleInstance,
    keys: tuple[str, ...],
) -> dict[str, str]:
    payload = json.dumps(list(keys), separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json

path = Path({instance.env_file!r})
keys = json.loads({payload!r})
values = {{}}
try:
    text = path.read_text(encoding="utf-8")
except OSError:
    text = ""
for raw_line in text.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    clean_key = key.strip()
    if clean_key in keys:
        values[clean_key] = value.strip()
print(json.dumps(values, sort_keys=True))
PY
"""
    try:
        raw = capture(ssh_command(host, script))
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return {}
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if str(key) in keys and str(value or "").strip()
    }


def runtime_bridge_settings_from_references(
    discovered_by_name: dict[str, ConsoleInstance],
) -> dict[str, str]:
    for reference_name in RUNTIME_BRIDGE_REFERENCE_INSTANCES:
        reference = discovered_by_name.get(reference_name)
        if not reference:
            continue
        values = read_instance_env_values(
            HOSTS[reference.host_name],
            reference,
            RUNTIME_BRIDGE_ENV_KEYS,
        )
        keys_token = values.get("NORMAN_KEYS_TOKEN") or values.get(
            "NORMAN_KEYS_API_TOKEN"
        )
        keys_url = (
            values.get("NORMAN_KEYS_URL")
            or values.get("NORMAN_KEYS_API_BASE")
            or (RUNTIME_BRIDGE_DEFAULT_KEYS_URL if keys_token else "")
        )
        token_secret = (
            values.get("NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET")
            or values.get("NORMAN_CONSOLE_RUNTIME_SECRET_NAME")
            or RUNTIME_BRIDGE_TOKEN_SECRET
        )
        if not keys_url or not keys_token or not token_secret:
            continue
        api_base = (
            values.get("NORMAN_CONSOLE_RUNTIME_API_BASE")
            or values.get("NORMAN_API_BASE_URL")
            or RUNTIME_BRIDGE_DEFAULT_API_BASE
        )
        return {
            "NORMAN_CONSOLE_RUNTIME_ENABLED": "1",
            "NORMAN_CONSOLE_RUNTIME_API_BASE": api_base,
            "NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET": token_secret,
            "NORMAN_KEYS_URL": keys_url,
            "NORMAN_KEYS_TOKEN": keys_token,
            "NORMAN_CONSOLE_RUNTIME_REQUESTER_ID": "runtime-tui-bridge",
            "NORMAN_CONSOLE_RUNTIME_LANE": RUNTIME_BRIDGE_SECRET_LANE,
            "NORMAN_CONSOLE_RUNTIME_TIMEOUT_SECONDS": RUNTIME_BRIDGE_TIMEOUT_SECONDS,
            "NORMAN_CONSOLE_RUNTIME_JOB_CREATE_TIMEOUT_SECONDS": (
                RUNTIME_BRIDGE_JOB_CREATE_TIMEOUT_SECONDS
            ),
            "NORMAN_CONSOLE_RUNTIME_TOKEN_RETRY_SECONDS": (
                RUNTIME_BRIDGE_TOKEN_RETRY_SECONDS
            ),
            "NORMAN_CONSOLE_RUNTIME_SNAPSHOT_TTL_SECONDS": (
                RUNTIME_BRIDGE_SNAPSHOT_TTL_SECONDS
            ),
            "NORMAN_CONSOLE_RUNTIME_PROOF_TTL_SECONDS": (
                RUNTIME_BRIDGE_PROOF_TTL_SECONDS
            ),
            "NORMAN_CONSOLE_RUNTIME_PROOF_BACKOFF_SECONDS": (
                RUNTIME_BRIDGE_PROOF_BACKOFF_SECONDS
            ),
            "NORMAN_CONSOLE_RUNTIME_STARTUP_JITTER_SECONDS": (
                RUNTIME_BRIDGE_STARTUP_JITTER_SECONDS
            ),
            "NORMAN_CONSOLE_RUNTIME_ROUTE_OUTCOME_TTL_SECONDS": (
                RUNTIME_BRIDGE_ROUTE_OUTCOME_TTL_SECONDS
            ),
            "NORMAN_CONSOLE_RUNTIME_ROUTE_OUTCOME_LIMIT": (
                RUNTIME_BRIDGE_ROUTE_OUTCOME_LIMIT
            ),
            "NORMAN_CONSOLE_RUNTIME_RECENT_ITEMS": RUNTIME_BRIDGE_RECENT_ITEMS,
            "NORMAN_CONSOLE_RUNTIME_LOCAL_FIRST_PROOF_LIMIT": (
                RUNTIME_BRIDGE_LOCAL_FIRST_PROOF_LIMIT
            ),
            "NORMAN_CONSOLE_RUNTIME_LOCAL_FIRST_SESSION_LIMIT": (
                RUNTIME_BRIDGE_LOCAL_FIRST_SESSION_LIMIT
            ),
        }
    return {}


def kernel_rollout_settings_for_instance(instance: ConsoleInstance) -> dict[str, str]:
    if instance.name in KERNEL_PRIMARY_CANARY_INSTANCES:
        kernel_owned_turn = (
            "1" if instance.name in KERNEL_OWNED_TURN_CANARY_INSTANCES else "0"
        )
        return {
            "NORMAN_TUI_BACKEND": "kernel",
            "NORMAN_TUI_KERNEL_EXECUTION": "1",
            "NORMAN_TUI_KERNEL_EXECUTION_ENABLED": "1",
            "NORMAN_TUI_KERNEL_PRIMARY": "1",
            "NORMAN_TUI_KERNEL_PRIMARY_ENABLED": "1",
            "NORMAN_TUI_KERNEL_OWNED_TURN": kernel_owned_turn,
            "NORMAN_TUI_KERNEL_OWNED_TURN_ENABLED": kernel_owned_turn,
            "NORMAN_TUI_KERNEL_PRIMARY_STRICT": "0",
            "NORMAN_TUI_KERNEL_CLOUD_FALLBACK": "1",
            "NORMAN_TUI_KERNEL_CLOUD_FALLBACK_ENABLED": "1",
            "NORMAN_TUI_KERNEL_WORKSPACE_PREFLIGHT": "1",
            "NORMAN_TUI_KERNEL_WORKSPACE_PREFLIGHT_ENABLED": "1",
            "NORMAN_TUI_KERNEL_PRIMARY_MAX_STEPS": KERNEL_PRIMARY_MAX_STEPS,
            "NORMAN_TUI_KERNEL_PREFLIGHT_TIMEOUT_SECONDS": (
                KERNEL_PREFLIGHT_TIMEOUT_SECONDS
            ),
        }
    return {
        "NORMAN_TUI_BACKEND": "kernel-shadow",
        "NORMAN_TUI_KERNEL_EXECUTION": "0",
        "NORMAN_TUI_KERNEL_EXECUTION_ENABLED": "0",
        "NORMAN_TUI_KERNEL_PRIMARY": "0",
        "NORMAN_TUI_KERNEL_PRIMARY_ENABLED": "0",
        "NORMAN_TUI_KERNEL_OWNED_TURN": "0",
        "NORMAN_TUI_KERNEL_OWNED_TURN_ENABLED": "0",
        "NORMAN_TUI_KERNEL_PRIMARY_STRICT": "0",
        "NORMAN_TUI_KERNEL_CLOUD_FALLBACK": "0",
        "NORMAN_TUI_KERNEL_CLOUD_FALLBACK_ENABLED": "0",
        "NORMAN_TUI_KERNEL_WORKSPACE_PREFLIGHT": "0",
        "NORMAN_TUI_KERNEL_WORKSPACE_PREFLIGHT_ENABLED": "0",
    }


def sync_instance_runtime_bridge_settings(
    host: DiscoveryHost,
    instance: ConsoleInstance,
    bridge_settings: dict[str, str],
) -> bool:
    if not bridge_settings:
        return False
    payload = json.dumps(bridge_settings, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import re

path = Path({instance.env_file!r})
updates = json.loads({payload!r})
text = path.read_text(encoding="utf-8")
changed = False
for key, value in updates.items():
    line = f"{{key}}={{value}}"
    pattern = re.compile(rf"^{{re.escape(key)}}=.*$", re.M)
    if pattern.search(text):
        updated = pattern.sub(line, text, count=1)
    else:
        updated = text if text.endswith("\\n") else text + "\\n"
        updated += line + "\\n"
    if updated != text:
        text = updated
        changed = True
if changed:
    path.write_text(text, encoding="utf-8")
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_kernel_rollout_settings(
    host: DiscoveryHost,
    instance: ConsoleInstance,
) -> bool:
    updates = kernel_rollout_settings_for_instance(instance)
    payload = json.dumps(updates, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import re

path = Path({instance.env_file!r})
updates = json.loads({payload!r})
text = path.read_text(encoding="utf-8")
changed = False
for key, value in updates.items():
    line = f"{{key}}={{value}}"
    pattern = re.compile(rf"^{{re.escape(key)}}=.*$", re.M)
    if pattern.search(text):
        updated = pattern.sub(line, text, count=1)
    else:
        updated = text if text.endswith("\\n") else text + "\\n"
        updated += line + "\\n"
    if updated != text:
        text = updated
        changed = True
if changed:
    path.write_text(text, encoding="utf-8")
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_model_setting(
    host: DiscoveryHost, instance: ConsoleInstance, model: str
) -> bool:
    clean_model = str(model or "").strip()
    if not clean_model:
        return False
    updates = {"HOUSEBOT_CODEX_MODEL": clean_model}
    payload = json.dumps(updates, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import re

path = Path({instance.env_file!r})
updates = json.loads({payload!r})
text = path.read_text(encoding="utf-8")
changed = False
for key, value in updates.items():
    line = f"{{key}}={{value}}"
    pattern = re.compile(rf"^{{re.escape(key)}}=.*$", re.M)
    if pattern.search(text):
        updated = pattern.sub(line, text, count=1)
    else:
        updated = text if text.endswith("\\n") else text + "\\n"
        updated += line + "\\n"
    if updated != text:
        text = updated
        changed = True
if changed:
    path.write_text(text, encoding="utf-8")
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_codex_home_seed(
    host: DiscoveryHost,
    instance: ConsoleInstance,
    seed_candidates: list[ConsoleInstance],
) -> bool:
    if not instance.codex_home:
        return False

    candidate_homes = [
        candidate.codex_home
        for candidate in seed_candidates
        if candidate.codex_home and candidate.codex_home != instance.codex_home
    ]
    if not candidate_homes:
        return False

    payload = json.dumps(candidate_homes, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import os
import shutil

target_home = Path({instance.codex_home!r})
candidate_homes = [Path(value) for value in json.loads({payload!r})]
target_stat = target_home.stat()
target_uid = target_stat.st_uid
target_gid = target_stat.st_gid

target_home.mkdir(parents=True, exist_ok=True)
changed = False

for source_home in candidate_homes:
    config_source = source_home / "config.toml"
    models_source = source_home / "models_cache.json"

    config_target = target_home / "config.toml"
    if not config_target.exists() and config_source.exists():
        shutil.copy2(config_source, config_target)
        os.chown(config_target, target_uid, target_gid)
        os.chmod(config_target, 0o600)
        changed = True

    models_target = target_home / "models_cache.json"
    if not models_target.exists() and models_source.exists():
        shutil.copy2(models_source, models_target)
        os.chown(models_target, target_uid, target_gid)
        os.chmod(models_target, 0o600)
        changed = True

    break

print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_codex_profile_files(
    host: DiscoveryHost,
    instance: ConsoleInstance,
) -> bool:
    if not instance.codex_home:
        return False

    script = f"""
python3 - <<'PY'
from pathlib import Path
import re

target_home = Path({instance.codex_home!r})
if not target_home.exists():
    print("unchanged")
    raise SystemExit(0)

changed = False
profile_section = re.compile(r"^\\[profiles(?:\\.|\\])")
top_level_profile = re.compile(r"^\\s*profile\\s*=")

profile_paths = list(target_home.glob("*.config.toml"))
base_config = target_home / "config.toml"
if base_config.exists():
    profile_paths.append(base_config)

for path in sorted(set(profile_paths), key=str):
    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        continue
    output = []
    section = ""
    skip_legacy_profile_section = False
    for line in original.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
            skip_legacy_profile_section = bool(profile_section.match(stripped))
            if skip_legacy_profile_section:
                continue
        if skip_legacy_profile_section:
            continue
        if not section and top_level_profile.match(line):
            continue
        output.append(line)
    updated = "".join(output)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        changed = True

print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def remote_file_state(host: DiscoveryHost, remote_path: str) -> RemoteFileState:
    script = f"""
python3 - <<'PY'
import grp
import hashlib
import json
import os
import pathlib
import pwd
import stat

path = pathlib.Path({remote_path!r})

payload = {{
    "exists": False,
    "sha256": None,
    "mode": "755",
    "owner": None,
    "group": None,
}}

target = path if path.exists() else path.parent
if target.exists():
    st = target.stat()
    payload["mode"] = format(stat.S_IMODE(st.st_mode), "o")
    payload["owner"] = pwd.getpwuid(st.st_uid).pw_name
    payload["group"] = grp.getgrgid(st.st_gid).gr_name

if path.exists():
    payload["exists"] = True
    payload["mode"] = format(stat.S_IMODE(path.stat().st_mode), "o")
    with path.open("rb") as handle:
        payload["sha256"] = hashlib.sha256(handle.read()).hexdigest()

print(json.dumps(payload))
PY
"""
    payload = json.loads(capture(ssh_command(host, script)))
    return RemoteFileState(
        exists=bool(payload.get("exists")),
        sha256=payload.get("sha256"),
        mode=str(payload.get("mode") or "755"),
        owner=payload.get("owner"),
        group=payload.get("group"),
    )


def install_file(
    host: DiscoveryHost,
    remote_path: str,
    source_key: str,
    source_sha256: dict[str, str],
) -> bool:
    source = SOURCE_FILES[source_key]
    return install_source_path(
        host,
        remote_path=remote_path,
        source=source,
        source_sha256=source_sha256[source_key],
    )


def install_source_path(
    host: DiscoveryHost,
    remote_path: str,
    source: Path,
    source_sha256: str,
) -> bool:
    remote_state = remote_file_state(host, remote_path)
    if remote_state.sha256 == source_sha256:
        return False

    if host.local:
        install_args = ["install", "-D", "-m", remote_state.mode or "755"]
        if remote_state.owner:
            install_args.extend(["-o", remote_state.owner])
        if remote_state.group:
            install_args.extend(["-g", remote_state.group])
        install_args.extend([str(source), remote_path])
        run(ssh_command(host, shlex.join(install_args)))
        return True

    remote_tmp = f"/tmp/{Path(remote_path).name}.{int(time.time() * 1000)}"
    run(scp_command(source, host.ssh_target, remote_tmp))

    install_args = ["install", "-D", "-m", remote_state.mode or "755"]
    if remote_state.owner:
        install_args.extend(["-o", remote_state.owner])
    if remote_state.group:
        install_args.extend(["-g", remote_state.group])
    install_args.extend([remote_tmp, remote_path])
    script = " && ".join(
        [
            shlex.join(install_args),
            shlex.join(["rm", "-f", remote_tmp]),
        ]
    )
    run(ssh_command(host, script))
    return True


def source_ui_version(source: Path) -> str:
    match = re.search(
        r'^DEFAULT_UI_VERSION\s*=\s*["\']([^"\']+)["\']',
        source.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"DEFAULT_UI_VERSION not found in {source}")
    return match.group(1).strip()


def validate_web_source_versions() -> str:
    versions = {
        source_key: source_ui_version(SOURCE_FILES[source_key])
        for source_key in WEB_SOURCE_KEYS
    }
    if len(set(versions.values())) != 1:
        rendered = ", ".join(
            f"{source_key}=v{version}"
            for source_key, version in sorted(versions.items())
        )
        raise RuntimeError(f"Web UI source versions must match: {rendered}")
    return next(iter(versions.values()))


def sync_norman_fleet_doctor_template(
    host: DiscoveryHost, source_sha256: dict[str, str]
) -> bool:
    if host.name != "norman":
        return False
    return install_source_path(
        host,
        remote_path=NORMAN_FLEET_DOCTOR_TEMPLATE_PATH,
        source=SOURCE_FILES["web"],
        source_sha256=source_sha256["web"],
    )


def sync_soul_identity_tree(host: DiscoveryHost) -> list[str]:
    if not LOCAL_SOUL_IDENTITY_ROOT.exists():
        return []
    candidates = [LOCAL_SOUL_IDENTITY_ROOT / "BASE_SOUL.md"]
    actors_dir = LOCAL_SOUL_IDENTITY_ROOT / "actors"
    if actors_dir.exists():
        candidates.extend(sorted(actors_dir.glob("*/SOUL.md")))

    changed: list[str] = []
    for source in candidates:
        if not source.exists():
            continue
        rel = source.relative_to(LOCAL_SOUL_IDENTITY_ROOT)
        remote_path = str(Path(REMOTE_SOUL_IDENTITY_ROOT) / rel)
        if install_source_path(
            host,
            remote_path=remote_path,
            source=source,
            source_sha256=local_sha256(source),
        ):
            changed.append(remote_path)
    return changed


def restart_instances(host: DiscoveryHost, instances: list[ConsoleInstance]) -> None:
    units = sorted({unit for instance in instances for unit in instance.restart_units})
    if not units:
        return
    unit_list = " ".join(shlex.quote(unit) for unit in units)
    script = " && ".join(
        [
            "systemctl daemon-reload",
            f"systemctl restart {unit_list}",
            f"systemctl is-active {unit_list}",
        ]
    )
    run(ssh_command(host, script))


def web_restart_units(instances: list[ConsoleInstance]) -> list[str]:
    return sorted(
        {
            unit
            for instance in instances
            for unit in instance.restart_units
            if unit.endswith("-web.service") or "-web" in unit
        }
    )


def restart_and_health_check_instances(
    host: DiscoveryHost,
    instances: list[ConsoleInstance],
    *,
    check_health: bool,
    web_only: bool = False,
) -> None:
    if web_only:
        units = web_restart_units(instances)
        if units:
            unit_list = " ".join(shlex.quote(unit) for unit in units)
            run(ssh_command(host, f"systemctl restart {unit_list}"))
    else:
        restart_instances(host, instances)
    if check_health:
        health_check_instances(host, instances)


def restart_scope_for_instance(
    instance: ConsoleInstance,
    *,
    changed_paths: set[str],
    changed_instances: dict[str, ConsoleInstance],
) -> str:
    if instance.name in changed_instances:
        return "full"
    full_paths = {instance.launch_path, instance.supervisor_path, instance.prompt_file}
    if changed_paths & full_paths:
        return "full"
    if instance.web_path in changed_paths:
        return "web"
    for source_key, remote_path in instance.files:
        if source_key not in WEB_SOURCE_KEYS and remote_path in changed_paths:
            return "full"
    return ""


def _status_restart_block_reason(status: dict[str, object]) -> str:
    child_pid = status.get("active_child_pid")
    if child_pid:
        if status.get("model_process_alive") is False:
            return ""
        return f"active child pid {child_pid}"
    if status.get("pending"):
        return "pending prompt"
    queue_depth = int(status.get("queue_depth") or 0)
    if queue_depth > 0:
        return f"{queue_depth} queued"
    return ""


def _status_restart_handoff_summary(status: dict[str, object]) -> str:
    handoff = status.get("context_handoff")
    if not isinstance(handoff, dict) or not handoff.get("can_resume_thread"):
        return ""
    thread_id = str(handoff.get("thread_id") or "thread")
    history = int(handoff.get("history_count") or 0)
    queued = int(handoff.get("queue_depth") or 0)
    return f"handoff resume {thread_id[:8]}, {history} history, {queued} queued"


def restart_block_reasons(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for instance in instances:
        if not instance.web_port:
            continue
        query = urllib.parse.urlencode({"token": instance.web_token})
        url = f"http://127.0.0.1:{instance.web_port}/api/restart-readiness?{query}"
        script = f"""
python3 - <<'PY'
import json
import urllib.request
with urllib.request.urlopen({url!r}, timeout={RESTART_READINESS_TIMEOUT_SECONDS}) as response:
    print(response.read().decode("utf-8"))
PY
"""
        try:
            status = json.loads(capture(ssh_command(host, script)) or "{}")
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ):
            status = {}
        reason = _status_restart_block_reason(status)
        if reason:
            handoff = _status_restart_handoff_summary(status)
            reasons[instance.name] = f"{reason}; {handoff}" if handoff else reason
    return reasons


def restart_selected_web_services(
    selected_by_host: dict[str, list[ConsoleInstance]],
    *,
    force_restart: bool,
    check_health: bool,
) -> None:
    for host_name, instances in selected_by_host.items():
        host = HOSTS[host_name]
        print(f"==> restarting web services on {host_name}")
        reasons = restart_block_reasons(host, instances)
        restartable = []
        for instance in instances:
            reason = reasons.get(instance.name)
            if reason and not force_restart:
                print(f"  - skip web restart {instance.name}: {reason}")
                continue
            restartable.append(instance)
        if not restartable:
            continue
        names = " ".join(instance.name for instance in restartable)
        print(f"  - serial web restart queue: {names}")
        restart_and_health_check_instances(
            host, restartable, check_health=check_health, web_only=True
        )


def health_check_instances(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> None:
    for instance in instances:
        env_path = shlex.quote(instance.env_file)
        script = " && ".join(
            [
                f'PORT=$(grep -E "^(HOUSEBOT_CODEX_WEB_PORT|NORMAN_CODEX_WEB_PORT)=" {env_path} | tail -n1 | cut -d= -f2-)',
                f'TOKEN=$(grep -E "^(HOUSEBOT_CODEX_WEB_TOKEN|NORMAN_CODEX_WEB_TOKEN)=" {env_path} | tail -n1 | cut -d= -f2-)',
                'test -n "$PORT"',
                'for attempt in $(seq 1 20); do curl -fsS "http://127.0.0.1:${PORT}/healthz?token=${TOKEN}" >/dev/null && exit 0; sleep 1; done; curl -fsS "http://127.0.0.1:${PORT}/healthz?token=${TOKEN}" >/dev/null',
            ]
        )
        run(ssh_command(host, script))


def ui_versions(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> dict[str, UiVersionStatus]:
    payload = json.dumps(
        [
            {"name": instance.name, "env_file": instance.env_file}
            for instance in instances
        ]
    )
    script = f"""
python3 - <<'PY'
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request

instances = json.loads({payload!r})
readiness_timeout = {RESTART_READINESS_TIMEOUT_SECONDS}
status_timeout = {STATUS_PROBE_TIMEOUT_SECONDS}


def fetch_json(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace") or "{{}}")


def parse_env(path):
    data = {{}}
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def env_value(env, *keys):
    for key in keys:
        value = (env.get(key) or "").strip()
        if value:
            return value
    return ""


def apply_status(result, status):
    result["web_restart_required"] = bool(status.get("web_restart_required"))
    result["web_restart_reason"] = str(status.get("web_restart_reason") or "")
    result["prompt_idle"] = bool(status.get("prompt_idle") or status.get("idle"))
    result["prompt_done"] = bool(status.get("prompt_done"))
    result["auto_update_safe"] = bool(status.get("auto_update_safe"))
    result["busy"] = bool(status.get("busy"))


results = []
for item in instances:
    name = item["name"]
    env = parse_env(item["env_file"])
    port = env_value(env, "HOUSEBOT_CODEX_WEB_PORT", "NORMAN_CODEX_WEB_PORT")
    token = env_value(env, "HOUSEBOT_CODEX_WEB_TOKEN", "NORMAN_CODEX_WEB_TOKEN")
    result = {{"name": name, "version": "unknown"}}
    if not port:
        result["version_error"] = "missing-port"
        results.append(result)
        continue
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    urllib.request.install_opener(opener)
    token_qs = urllib.parse.quote(token)
    version_url = f"http://127.0.0.1:{{port}}/api/version?token={{token_qs}}"
    readiness_url = f"http://127.0.0.1:{{port}}/api/restart-readiness?token={{token_qs}}"
    status_url = f"http://127.0.0.1:{{port}}/api/status?token={{token_qs}}"
    page_url = f"http://127.0.0.1:{{port}}/?token={{token_qs}}"
    try:
        version_payload = fetch_json(version_url, 3)
        version = str(version_payload.get("ui_version") or "").strip()
        if version:
            result["version"] = version
        else:
            result["version_error"] = "missing-json-version"
    except Exception as exc:
        result["version_error"] = f"{{exc.__class__.__name__}}: {{exc}}"
        try:
            with opener.open(page_url, timeout=12) as response:
                html = response.read().decode("utf-8", errors="replace")
            match = re.search(r'class="version-chip"[^>]*>UI v([^<]+)<', html)
            if not match:
                match = re.search(r"UI v([0-9.]+)", html)
            if match:
                result["version"] = match.group(1).strip()
        except Exception:
            pass
    try:
        status = fetch_json(readiness_url, readiness_timeout)
        apply_status(result, status)
    except Exception as exc:
        result["readiness_error"] = f"{{exc.__class__.__name__}}: {{exc}}"
        try:
            status = fetch_json(status_url, status_timeout)
            apply_status(result, status)
        except Exception as status_exc:
            result["status_error"] = f"{{status_exc.__class__.__name__}}: {{status_exc}}"
    results.append(result)

print(json.dumps(results))
PY
"""
    raw = json.loads(capture(ssh_command(host, script)) or "[]")
    statuses: dict[str, UiVersionStatus] = {}
    for item in raw:
        statuses[str(item["name"])] = UiVersionStatus(
            version=str(item.get("version") or "unknown"),
            version_error=str(item.get("version_error") or ""),
            readiness_error=str(item.get("readiness_error") or ""),
            status_error=str(item.get("status_error") or ""),
            web_restart_required=bool(item.get("web_restart_required")),
            web_restart_reason=str(item.get("web_restart_reason") or ""),
            prompt_idle=bool(item.get("prompt_idle")),
            prompt_done=bool(item.get("prompt_done")),
            auto_update_safe=bool(item.get("auto_update_safe")),
            busy=bool(item.get("busy")),
        )
    return statuses


def deployed_web_versions(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> dict[str, str]:
    payload = json.dumps(
        [
            {"name": instance.name, "web_path": instance.web_path}
            for instance in instances
        ]
    )
    script = f"""
python3 - <<'PY'
import json
import pathlib
import re

instances = json.loads({payload!r})
results = []

for item in instances:
    name = item["name"]
    path = pathlib.Path(item["web_path"])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'^DEFAULT_UI_VERSION\\s*=\\s*["\\']([^"\\']+)["\\']', text, re.M)
        version = match.group(1).strip() if match else "missing"
    except Exception as exc:
        version = f"error: {{exc.__class__.__name__}}"
    results.append({{"name": name, "version": version}})

print(json.dumps(results))
PY
"""
    raw = json.loads(capture(ssh_command(host, script)) or "[]")
    return {str(item["name"]): str(item["version"]) for item in raw}


def verify_ui_version_parity(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> None:
    live_versions = ui_versions(host, instances)
    disk_versions = deployed_web_versions(host, instances)
    mismatches = []
    for instance in instances:
        live_status = live_versions.get(instance.name)
        live_version = live_status.version if live_status else "unknown"
        disk_version = disk_versions.get(instance.name, "unknown")
        if live_version != disk_version:
            mismatches.append(
                f"{instance.name}: live UI v{live_version}, disk UI v{disk_version}"
            )
    if mismatches:
        raise RuntimeError(
            "UI version parity failed on " + host.name + ": " + "; ".join(mismatches)
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync the shared Codex console template to deployed agents."
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        default=None,
        help="Hosts or console names to update. Defaults to every discovered console.",
    )
    parser.add_argument("--no-restart", action="store_true", help="Copy files only.")
    parser.add_argument(
        "--restart", action="store_true", help="Restart changed consoles."
    )
    parser.add_argument(
        "--force-restart",
        action="store_true",
        help="Override guarded restart blocks.",
    )
    parser.add_argument(
        "--restart-web-only",
        action="store_true",
        help="Restart only selected console web services after readiness checks.",
    )
    parser.add_argument(
        "--no-health", action="store_true", help="Skip post-restart health checks."
    )
    parser.add_argument(
        "--list", action="store_true", help="List discovered hosts and consoles."
    )
    parser.add_argument(
        "--versions",
        action="store_true",
        help="Print the live UI version for the selected consoles and exit.",
    )
    parser.add_argument(
        "--set-codex-model",
        default="",
        help="Explicit operator-triggered model update for selected consoles. Template sync does not change models by default.",
    )
    parser.add_argument(
        "--enable-route-receipts",
        action="store_true",
        help="Enable route receipt shadow capture for selected consoles.",
    )
    parser.add_argument(
        "--route-receipt-dir",
        default=REMOTE_ROUTE_RECEIPT_DIR,
        help="Remote directory for per-TUI route receipt JSONL files.",
    )
    parser.add_argument(
        "--route-receipt-items",
        default="250",
        help="Maximum route receipt items each TUI should retain.",
    )
    return parser.parse_args(argv)


def select_instances(
    requested: list[str] | None,
    discovered_by_host: dict[str, list[ConsoleInstance]],
    discovered_by_name: dict[str, ConsoleInstance],
) -> dict[str, list[ConsoleInstance]]:
    if not requested:
        return {
            host_name: list(instances)
            for host_name, instances in discovered_by_host.items()
            if instances
        }

    selected: dict[str, dict[str, ConsoleInstance]] = {}
    unknown: list[str] = []
    for token in requested:
        if token in discovered_by_host:
            selected.setdefault(token, {})
            for instance in discovered_by_host[token]:
                selected[token][instance.name] = instance
            continue
        instance = discovered_by_name.get(token)
        if instance:
            selected.setdefault(instance.host_name, {})
            selected[instance.host_name][instance.name] = instance
            continue
        unknown.append(token)

    if unknown:
        known = sorted(set(discovered_by_host) | set(discovered_by_name))
        raise SystemExit(
            "Unknown targets: "
            + ", ".join(unknown)
            + "\nKnown targets: "
            + ", ".join(known)
        )

    return {
        host_name: list(instances.values())
        for host_name, instances in selected.items()
        if instances
    }


def list_targets(
    discovered_by_host: dict[str, list[ConsoleInstance]],
) -> None:
    for host_name in sorted(discovered_by_host):
        instances = discovered_by_host[host_name]
        print(host_name)
        for instance in instances:
            print(f"  - {instance.name}")


def list_versions(
    selected_by_host: dict[str, list[ConsoleInstance]],
) -> None:
    for host_name, instances in selected_by_host.items():
        host = HOSTS[host_name]
        versions = ui_versions(host, instances)
        print(host_name)
        for instance in instances:
            status = versions.get(instance.name)
            if status is None:
                print(f"  - {instance.name}: UI vunknown")
                continue
            suffix = ""
            if status.version_error:
                suffix = f" (version unavailable: {status.version_error})"
            elif status.web_restart_required:
                labels = ["restart staged"]
                if status.prompt_done:
                    labels.append("prompt done")
                if status.prompt_idle and status.auto_update_safe and not status.busy:
                    labels.append("idle auto-update safe")
                label = "; ".join(labels)
                suffix = f" ({label}: {status.web_restart_reason})"
            elif status.status_error:
                suffix = f" (status unavailable: {status.status_error})"
            elif status.readiness_error:
                suffix = f" (readiness fallback: {status.readiness_error})"
            print(f"  - {instance.name}: UI v{status.version}{suffix}")


def main() -> int:
    args = parse_args()
    for source in SOURCE_FILES.values():
        if not source.exists():
            raise FileNotFoundError(source)
    for source in PROMPT_TEMPLATES.values():
        if not source.exists():
            raise FileNotFoundError(source)
    validate_web_source_versions()

    discovered_by_host, discovered_by_name = discover_all_instances(
        host_filter=requested_host_filter(args.targets)
    )

    if args.list:
        list_targets(discovered_by_host)
        return 0

    selected_by_host = select_instances(
        args.targets,
        discovered_by_host=discovered_by_host,
        discovered_by_name=discovered_by_name,
    )
    runtime_bridge_settings = runtime_bridge_settings_from_references(
        discovered_by_name
    )

    if args.versions:
        list_versions(selected_by_host)
        return 0

    source_sha256 = {key: local_sha256(path) for key, path in SOURCE_FILES.items()}
    prompt_sha256 = {
        name: local_sha256(path) for name, path in PROMPT_TEMPLATES.items()
    }

    for host_name, selected_instances in selected_by_host.items():
        host = HOSTS[host_name]
        all_host_instances = discovered_by_host[host_name]
        all_by_name = {instance.name: instance for instance in all_host_instances}
        changed_paths: set[str] = set()
        changed_static_paths: set[str] = set()
        changed_instances: dict[str, ConsoleInstance] = {}

        print(f"==> syncing {host_name}", flush=True)

        if host.root_managed_local and os.geteuid() != 0:
            print(
                "  - root-managed local host; skipping local template/env writes in user sync",
                flush=True,
            )
            continue

        if host.read_only:
            print(
                "  - read-only discovery host; skipping local template/env writes",
                flush=True,
            )
            continue

        soul_changes = sync_soul_identity_tree(host)
        for remote_path in soul_changes:
            changed_static_paths.add(remote_path)
            print(f"  - soul identity -> {remote_path}", flush=True)
        if sync_norman_fleet_doctor_template(host, source_sha256):
            changed_static_paths.add(NORMAN_FLEET_DOCTOR_TEMPLATE_PATH)
            print(
                "  - fleet-doctor template -> " f"{NORMAN_FLEET_DOCTOR_TEMPLATE_PATH}",
                flush=True,
            )

        for instance in selected_instances:
            if sync_instance_codex_home_seed(
                host,
                instance,
                [
                    candidate
                    for candidate in all_host_instances
                    if candidate.name != instance.name
                ],
            ):
                changed_instances[instance.name] = instance
                print(f"  - codex home seed -> {instance.codex_home}", flush=True)
            if sync_instance_codex_profile_files(host, instance):
                changed_instances[instance.name] = instance
                print(
                    f"  - codex profile files -> {instance.codex_home}",
                    flush=True,
                )
            if sync_instance_disabled_plugin_settings(host, instance):
                changed_instances[instance.name] = instance
                print(
                    f"  - disabled plugins -> {instance.codex_home}",
                    flush=True,
                )
            desired_links = desired_console_links(
                instance,
                discovered_by_host=discovered_by_host,
                discovered_by_name=discovered_by_name,
            )
            if sync_instance_links(host, instance, desired_links):
                changed_instances[instance.name] = instance
                print(f"  - links -> {instance.env_file}", flush=True)
            if sync_instance_origin_settings(host, instance):
                changed_instances[instance.name] = instance
                print(f"  - origin -> {instance.env_file}", flush=True)
            if sync_instance_runtime_settings(host, instance):
                changed_instances[instance.name] = instance
                print(f"  - runtime settings -> {instance.codex_home}", flush=True)
            if sync_instance_bedrock_profile(host, instance):
                changed_instances[instance.name] = instance
                print(f"  - bedrock profile -> {instance.codex_home}", flush=True)
            if sync_instance_agent_label(host, instance):
                changed_instances[instance.name] = instance
                print(f"  - label -> {instance.env_file}", flush=True)
            if sync_instance_local_llm_foreground_settings(host, instance):
                changed_instances[instance.name] = instance
                print(f"  - local llm foreground -> {instance.env_file}", flush=True)
            if sync_instance_runtime_bridge_settings(
                host, instance, runtime_bridge_settings
            ):
                changed_instances[instance.name] = instance
                print(f"  - runtime bridge -> {instance.env_file}", flush=True)
            if sync_instance_kernel_rollout_settings(host, instance):
                changed_instances[instance.name] = instance
                print(f"  - kernel rollout -> {instance.env_file}", flush=True)
            if args.enable_route_receipts and sync_instance_route_receipts(
                host,
                instance,
                receipt_dir=args.route_receipt_dir,
                max_items=args.route_receipt_items,
            ):
                changed_instances[instance.name] = instance
                print(f"  - route receipts -> {instance.env_file}", flush=True)
            if args.set_codex_model and sync_instance_model_setting(
                host, instance, args.set_codex_model
            ):
                changed_instances[instance.name] = instance
                print(f"  - model -> {instance.env_file}", flush=True)

        unique_files: dict[str, str] = {}
        for instance in selected_instances:
            for source_key, remote_path in instance.files:
                unique_files.setdefault(remote_path, source_key)

        for remote_path, source_key in unique_files.items():
            print(f"  - {source_key} -> {remote_path}", flush=True)
            if install_file(host, remote_path, source_key, source_sha256):
                changed_paths.add(remote_path)

        for instance in selected_instances:
            prompt_template = instance.prompt_template
            if not prompt_template or not instance.prompt_file:
                continue
            print(f"  - prompt -> {instance.prompt_file}", flush=True)
            if install_source_path(
                host,
                remote_path=instance.prompt_file,
                source=prompt_template,
                source_sha256=prompt_sha256[instance.name],
            ):
                changed_paths.add(instance.prompt_file)

        if sync_host_home_page(host, all_host_instances):
            changed_static_paths.add(host.host_home_path or "")
            print(f"  - host-home -> {host.host_home_path}", flush=True)

        if not changed_paths and not changed_instances and not changed_static_paths:
            print("  - no template changes detected", flush=True)
            continue

        restart_scope = {
            instance.name: instance for instance in changed_instances.values()
        }
        for instance in [
            instance
            for instance in all_host_instances
            if any(remote_path in changed_paths for _, remote_path in instance.files)
            or (instance.prompt_file and instance.prompt_file in changed_paths)
        ]:
            restart_scope[instance.name] = all_by_name[instance.name]
        restart_scope_list = list(restart_scope.values())

        if args.no_restart:
            continue

        if not restart_scope_list:
            continue

        restart_names = " ".join(instance.name for instance in restart_scope_list)
        print(f"  - restarting {restart_names}", flush=True)
        if args.restart_web_only:
            restart_selected_web_services(
                {host_name: restart_scope_list},
                force_restart=args.force_restart,
                check_health=not args.no_health,
            )
            continue
        restart_and_health_check_instances(
            host,
            restart_scope_list,
            check_health=not args.no_health,
        )

        if args.no_health:
            continue
        print("  - version parity", flush=True)
        verify_ui_version_parity(host, restart_scope_list)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
