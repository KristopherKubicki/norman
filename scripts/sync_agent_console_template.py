#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import hashlib
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_ROOT = SCRIPT_DIR / "agent_console_template"
PROMPT_TEMPLATE_ROOT = TEMPLATE_ROOT / "prompts"
SOURCE_FILES = {
    "web": TEMPLATE_ROOT / "agent_console_web.py",
    "launch": TEMPLATE_ROOT / "agent_console_launch.sh",
    "supervisor": TEMPLATE_ROOT / "agent_console_supervisor.sh",
    "bbs-lifecycle": SCRIPT_DIR / "bbs_task_lifecycle.py",
    "bbs-janitor": SCRIPT_DIR / "bbs_janitor.py",
    "memory-tool": SCRIPT_DIR / "tui_memory_tool.py",
    "soul-loader": SCRIPT_DIR / "compose_soul_context.py",
    "soul-validator": SCRIPT_DIR / "validate_soul_md.py",
}
LOCAL_SOUL_IDENTITY_ROOT = SCRIPT_DIR.parent / "db" / "estate" / "identity"
REMOTE_SOUL_IDENTITY_ROOT = (
    os.environ.get("NORMAN_SYNC_SOUL_IDENTITY_ROOT", "/etc/norman/identity").strip()
    or "/etc/norman/identity"
)
CANONICAL_CODEX_ENV_PREFIX = "NORMAN_CODEX_"
LEGACY_CODEX_ENV_PREFIX = "HOUSEBOT_CODEX_"


def canonical_codex_env_key(key: str) -> str:
    if key.startswith(LEGACY_CODEX_ENV_PREFIX):
        return (
            f"{CANONICAL_CODEX_ENV_PREFIX}{key.removeprefix(LEGACY_CODEX_ENV_PREFIX)}"
        )
    return key


def legacy_codex_env_key(key: str) -> str:
    if key.startswith(CANONICAL_CODEX_ENV_PREFIX):
        return (
            f"{LEGACY_CODEX_ENV_PREFIX}{key.removeprefix(CANONICAL_CODEX_ENV_PREFIX)}"
        )
    return key


def canonicalize_codex_env_updates(updates: dict[str, str]) -> dict[str, str]:
    return {canonical_codex_env_key(key): value for key, value in updates.items()}


def expand_codex_env_remove_keys(keys: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    expanded: list[str] = []
    for key in keys:
        for candidate in (
            key,
            canonical_codex_env_key(key),
            legacy_codex_env_key(key),
        ):
            if candidate not in expanded:
                expanded.append(candidate)
    return tuple(expanded)


PROMPT_TEMPLATES = {
    "compere": PROMPT_TEMPLATE_ROOT / "compere.txt",
    "control-plane": PROMPT_TEMPLATE_ROOT / "control-plane.txt",
    "diamond-roc": PROMPT_TEMPLATE_ROOT / "diamond-roc.txt",
    "dj": PROMPT_TEMPLATE_ROOT / "dj.txt",
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
ARCHIVED_INSTANCE_NAMES = {
    # Park Publisher for now; it is confusing as a separate lane and should not
    # be promoted or synced as an active TUI until it is intentionally revived.
    "publisher",
}
CANONICAL_INSTANCE_HOSTS = {
    # Diamond Roc was retired from Hal. Keep any stale Hal env/session out of
    # discovery so the only publishable runtime is the Toy Box one.
    "diamond-roc": "toy-box",
}
INSTANCE_PUBLIC_HOST_OVERRIDES: dict[str, str] = {
    "acast": "acast.kris.openbrand.com",
    "autocamera": "autocamera.home.arpa",
    "castle": "castle.home.arpa",
    "cloudagent": "cloudagent.home.arpa",
    "compere": "keystone.kris.openbrand.com",
    "control-plane": "cp.kris.openbrand.com",
    "diamond-roc": "diamond-roc.home.arpa",
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
    "scout": "scout.kris.openbrand.com",
    "studio": "studio.home.arpa",
    "switchboard": "switchboard.home.arpa",
    "theseus": "theseus.home.arpa",
    "tmi-dashboards": "dashboards.kris.openbrand.com",
    "tv": "tv.home.arpa",
    "uplink": "uplink.home.arpa",
    "usbhome": "usbhome.home.arpa",
    "uscache": "uscache.home.arpa",
}
INSTANCE_CONSOLE_URL_OVERRIDES: dict[str, str] = {
    "phone-ops": "https://phone.home.arpa/",
}
INSTANCE_LOCAL_HOST_ALIAS_OVERRIDES: dict[str, tuple[str, ...]] = {
    "phone-ops": ("phone.home.arpa", "phoneops.home.arpa"),
}
PROMOTED_FOLD_INSTANCES: tuple[tuple[str, str, str, int], ...] = (
    ("phone-ops", "Phone Ops", "Personal", 170),
)
DEFAULT_LAUNCHERS = {
    "housebot": "/opt/housebot/scripts/housebot_codex_launch.sh",
}
SSH_CONNECT_TIMEOUT_SECONDS = os.environ.get("NORMAN_SYNC_SSH_CONNECT_TIMEOUT", "8")
DEFAULT_BBS_SUMMARY_URL = os.environ.get(
    "NORMAN_SYNC_BBS_URL", "http://192.168.2.241:8765"
).strip()
DEFAULT_LONG_JOB_NOTIFY_THRESHOLD_SECONDS = os.environ.get(
    "NORMAN_SYNC_LONG_JOB_NOTIFY_THRESHOLD_SECONDS", str(60 * 60)
).strip()
DEFAULT_LONG_JOB_NOTIFY_TIMEOUT_SECONDS = os.environ.get(
    "NORMAN_SYNC_LONG_JOB_NOTIFY_TIMEOUT_SECONDS", "5"
).strip()
DEFAULT_LONG_JOB_NOTIFY_URL = os.environ.get(
    "NORMAN_SYNC_LONG_JOB_NOTIFY_URL", ""
).strip()
DEFAULT_LONG_JOB_NOTIFY_TOKEN = os.environ.get(
    "NORMAN_SYNC_LONG_JOB_NOTIFY_TOKEN", ""
).strip()
BBS_ACTOR_OVERRIDES = {
    "networking": "netops",
    "phone-ops": "phoneops",
    "studio": "camera-studio",
}


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _epoch_seconds(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        parsed = time.strptime(raw.removesuffix("Z"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return float(time.mktime(parsed))


def _truthy_status(record: dict[str, object]) -> bool:
    ok = record.get("ok")
    if isinstance(ok, bool):
        return ok
    status = str(record.get("status") or "").strip().lower()
    return status in {"ok", "pass", "passed", "healthy", "success", "succeeded"}


def _bedrock_failover_smoke_record_matches(
    record: dict[str, object],
    *,
    profile_v2: str,
    model: str,
    aws_region: str,
    checked_at: object,
    now: float,
    max_age_seconds: int,
) -> bool:
    if not _truthy_status(record):
        return False
    record_profile = str(
        record.get("profile_v2") or record.get("profile") or ""
    ).strip()
    if record_profile and record_profile != profile_v2:
        return False
    record_model = str(record.get("model") or "").strip()
    if record_model and record_model != model:
        return False
    record_region = str(record.get("aws_region") or record.get("region") or "").strip()
    if record_region and record_region != aws_region:
        return False
    if max_age_seconds <= 0:
        return True
    checked_epoch = _epoch_seconds(record.get("checked_at") or checked_at)
    if checked_epoch is None:
        return False
    return checked_epoch <= now + 300 and (now - checked_epoch) <= max_age_seconds


def _iter_bedrock_failover_smoke_records(
    payload: dict[str, object], profile_v2: str, model: str
):
    checked_at = payload.get("checked_at")
    yield payload, checked_at
    for collection_name in ("profiles", "routes", "regions"):
        collection = payload.get(collection_name)
        if isinstance(collection, dict):
            selected = collection.get(profile_v2)
            if isinstance(selected, dict):
                yield selected, selected.get("checked_at") or checked_at
            for value in collection.values():
                if isinstance(value, dict):
                    yield value, value.get("checked_at") or checked_at
        elif isinstance(collection, list):
            for value in collection:
                if isinstance(value, dict):
                    yield value, value.get("checked_at") or checked_at
    models = payload.get("models")
    if isinstance(models, dict):
        selected = models.get(model)
        if isinstance(selected, dict):
            yield selected, selected.get("checked_at") or checked_at


def _bedrock_failover_smoke_allows(
    *,
    path: str,
    profile_v2: str,
    model: str,
    aws_region: str,
    max_age_seconds: int,
) -> bool:
    if not path or not profile_v2 or not model or not aws_region:
        return False
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    now = time.time()
    for record, checked_at in _iter_bedrock_failover_smoke_records(
        payload, profile_v2, model
    ):
        if _bedrock_failover_smoke_record_matches(
            record,
            profile_v2=profile_v2,
            model=model,
            aws_region=aws_region,
            checked_at=checked_at,
            now=now,
            max_age_seconds=max_age_seconds,
        ):
            return True
    return False


HEALTH_CHECK_ATTEMPTS = _positive_int_env("NORMAN_SYNC_HEALTH_ATTEMPTS", 60)
HEALTH_CHECK_SLEEP_SECONDS = _positive_int_env("NORMAN_SYNC_HEALTH_SLEEP_SECONDS", 1)
HEALTH_CHECK_TIMEOUT_SECONDS = _positive_int_env(
    "NORMAN_SYNC_HEALTH_TIMEOUT_SECONDS", 5
)
RESTART_SETTLE_SECONDS = _positive_int_env("NORMAN_SYNC_RESTART_SETTLE_SECONDS", 2)
RESTART_READINESS_TIMEOUT_SECONDS = _positive_int_env(
    "NORMAN_SYNC_RESTART_READINESS_TIMEOUT_SECONDS", 3
)
STATUS_PROBE_TIMEOUT_SECONDS = _positive_int_env(
    "NORMAN_SYNC_STATUS_TIMEOUT_SECONDS", 12
)


@dataclass(frozen=True)
class DiscoveryHost:
    name: str
    ssh_target: str
    use_sudo: bool
    env_globs: tuple[str, ...]
    public_host: str
    lan_host: str
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
        launch_dir = Path(self.launch_path).parent
        helper_path = str(launch_dir / "bbs_task_lifecycle.py")
        janitor_path = str(launch_dir / "bbs_janitor.py")
        memory_tool_path = str(launch_dir / "tui_memory_tool.py")
        soul_loader_path = str(launch_dir / "compose_soul_context.py")
        soul_validator_path = str(launch_dir / "validate_soul_md.py")
        return (
            ("web", self.web_path),
            ("launch", self.launch_path),
            ("supervisor", self.supervisor_path),
            ("bbs-lifecycle", helper_path),
            ("bbs-janitor", janitor_path),
            ("memory-tool", memory_tool_path),
            ("soul-loader", soul_loader_path),
            ("soul-validator", soul_validator_path),
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
    status_error: str = ""
    web_restart_required: bool = False
    web_restart_reason: str = ""


HOSTS: dict[str, DiscoveryHost] = {
    "hal": DiscoveryHost(
        name="hal",
        ssh_target="root@192.168.2.137",
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
        ssh_target="root@192.168.2.146",
        use_sudo=False,
        env_globs=("/etc/*/codex-web.env",),
        public_host="toy-box.home.arpa",
        lan_host="192.168.2.146",
        alias_hosts=("toy-box.tail94915.ts.net",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "work-special": DiscoveryHost(
        name="work-special",
        ssh_target="root@192.168.2.147",
        use_sudo=False,
        env_globs=("/etc/*/codex-web.env",),
        public_host="work-special.home.arpa",
        lan_host="192.168.2.147",
        alias_hosts=("work-special.tail94915.ts.net",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "norman": DiscoveryHost(
        name="norman",
        ssh_target="root@192.168.2.241",
        use_sudo=False,
        env_globs=("/etc/norman/codex-web.env",),
        public_host="norman.home.arpa",
        lan_host="192.168.2.241",
        alias_hosts=("norman.tail94915.ts.net",),
        host_home_path="/var/www/host-home/index.html",
        local=False,
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
    "scout": "Scout",
    "studio": "Studio",
    "tmi-dashboards": "TMI Dashboards",
    "tv": "TV",
    "cloudagent": "CloudAgent",
}

INSTANCE_PROMPT_PLACEHOLDER_OVERRIDES = {
    "control-plane": "Ask Control Plane to inspect admin/data surfaces, execute owned changes, or route research-only collection to Scout.",
    "diamond-roc": "Ask Diamond Roc to inspect Evergreen site/service state, dry-run changes, or coordinate with Castle and CloudAgent.",
    "dj": "Ask DJ Station to shape sets, tune playback flow, sketch the visualizer, or tighten the music-first UX.",
    "mls": "Ask MLS to inspect listings, summarize property intelligence, or compare candidate homes.",
    "parkergale": "Ask PEFB to inspect the deal room, summarize the thesis, or revise a confidential memo.",
    "platinum-standard": "Ask Platinum Standard to inspect releases, validation inputs, baselines, or a targeted workflow issue.",
    "scout": "Ask Scout/Ranger for research collection only: refine watchlists, normalize Perplexity findings, or package a research packet.",
    "studio": "Ask Studio to tie DJ, TV, Autocamera, and Glimpser into a cleaner control-room flow.",
    "tv": "Ask TV to shape channels, live sources, camera integrations, or the lean-back viewing surface.",
}

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
    "192.168.2.241",  # norman LAN/front door
    "100.103.34.17",  # norman tailnet/front door
    "fd7a:115c:a1e0::3438:2211",  # norman tailnet/front door ipv6
    "192.168.2.136",  # pixel10
    "100.78.41.73",  # pixel10 tailnet
    "fd7a:115c:a1e0::4d33:2949",  # pixel10 tailnet ipv6
    "192.168.2.137",  # hal desktop
    "100.112.62.71",  # hal tailnet
    "192.168.2.140",  # plasma-mobile
    "100.109.202.7",  # plasma-mobile tailnet
    "192.168.2.144",  # lollie's desktop
)

SAL_CONSOLE_CLIENTS = (
    "192.168.2.141",  # sal LAN
    "100.77.147.57",  # sal tailscale
)

WORK_SPECIAL_SAL_CONSOLE_INSTANCES = (
    "compere",
    "control-plane",
    "earlybird",
    "gold-book",
    "infra",
    "leadership-kpis",
    "market-sizing",
    "mls",
    "panelbot",
    "platinum-standard",
    "scout",
    "tmi-dashboards",
)
NETOPS_BEDROCK_DEFAULT_INSTANCES: tuple[str, ...] = ()
WORK_BILLING_INSTANCES = frozenset(WORK_SPECIAL_SAL_CONSOLE_INSTANCES) | {
    "mls",
    "work-special",
}
WORK_BEDROCK_DEFAULT_ENABLED = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_DEFAULT_ENABLED", "1"
).strip().lower() in {"1", "true", "yes", "on"}
WORK_BEDROCK_DEFAULT_INSTANCES = (
    frozenset(WORK_SPECIAL_SAL_CONSOLE_INSTANCES)
    | frozenset(NETOPS_BEDROCK_DEFAULT_INSTANCES)
    if WORK_BEDROCK_DEFAULT_ENABLED
    else frozenset()
)
WORK_DIRECT_DEFAULT_INSTANCES = frozenset(WORK_SPECIAL_SAL_CONSOLE_INSTANCES)
NON_WORK_DEFAULT_SERVICE_TIER = (
    os.environ.get("NORMAN_SYNC_NON_WORK_SERVICE_TIER", "flex").strip() or "flex"
)
WORK_BEDROCK_ENV_KEYS = (
    "NORMAN_CODEX_STANDARD_PROFILE_V2",
    "NORMAN_CODEX_DEFAULT_PROFILE_V2",
    "NORMAN_CODEX_BEDROCK_PROFILE_V2",
    "NORMAN_CODEX_STANDARD_MODEL",
    "NORMAN_CODEX_STANDARD_PROVIDER_LABEL",
    "NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2",
    "NORMAN_CODEX_BEDROCK_FAILOVER_MODEL",
    "NORMAN_CODEX_BEDROCK_FAILOVER_PROVIDER_LABEL",
    "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_PROFILE",
    "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION",
    "NORMAN_CODEX_BEDROCK_FAILOVER2_PROFILE_V2",
    "NORMAN_CODEX_BEDROCK_FAILOVER2_MODEL",
    "NORMAN_CODEX_BEDROCK_FAILOVER2_PROVIDER_LABEL",
    "NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_PROFILE",
    "NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_REGION",
    "NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES",
    "NORMAN_CODEX_DIRECT_PROVIDER_LABEL",
    "NORMAN_CODEX_STANDARD_AWS_PROFILE",
    "NORMAN_CODEX_STANDARD_AWS_REGION",
    "NORMAN_CODEX_DIRECT_TIERS_ENABLED",
    "NORMAN_CODEX_SWITCHABLE_MODELS",
    "NORMAN_CODEX_AVAILABLE_MODELS",
)
WORK_BEDROCK_PROFILE_V2 = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_PROFILE_V2", "traqline-bedrock"
).strip()
WORK_BEDROCK_PROFILE_SOURCE = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_PROFILE_SOURCE",
    "/home/kristopher/.codex-infra/traqline-bedrock.config.toml",
).strip()
WORK_BEDROCK_FAILOVER_ENABLEMENT = (
    os.environ.get("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_ENABLED", "auto").strip().lower()
)
WORK_BEDROCK_FAILOVER_PROFILE_V2 = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_PROFILE_V2",
    f"{WORK_BEDROCK_PROFILE_V2}-us-east-1" if WORK_BEDROCK_PROFILE_V2 else "",
).strip()
WORK_BEDROCK_FAILOVER_PROFILE_SOURCE = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_PROFILE_SOURCE",
    WORK_BEDROCK_PROFILE_SOURCE,
).strip()
WORK_BEDROCK_MODEL = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_MODEL", "openai.gpt-5.4"
).strip()
WORK_BEDROCK_FAILOVER_MODEL = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_MODEL", WORK_BEDROCK_MODEL
).strip()
WORK_BEDROCK_FAILOVER2_ENABLEMENT = (
    os.environ.get("NORMAN_SYNC_WORK_BEDROCK_FAILOVER2_ENABLED", "auto").strip().lower()
)
WORK_BEDROCK_FAILOVER2_PROFILE_V2 = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER2_PROFILE_V2",
    f"{WORK_BEDROCK_PROFILE_V2}-us-west-2" if WORK_BEDROCK_PROFILE_V2 else "",
).strip()
WORK_BEDROCK_FAILOVER2_PROFILE_SOURCE = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER2_PROFILE_SOURCE",
    WORK_BEDROCK_PROFILE_SOURCE,
).strip()
WORK_BEDROCK_FAILOVER2_MODEL = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER2_MODEL", WORK_BEDROCK_MODEL
).strip()
WORK_BEDROCK_FALLBACK_MODEL = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FALLBACK_MODEL", "openai.gpt-5.5"
).strip()
WORK_BEDROCK_REASONING_EFFORT = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_REASONING_EFFORT", "xhigh"
).strip()
WORK_DIRECT_MODEL = os.environ.get("NORMAN_SYNC_WORK_DIRECT_MODEL", "gpt-5.4").strip()
WORK_DIRECT_FALLBACK_MODEL = os.environ.get(
    "NORMAN_SYNC_WORK_DIRECT_FALLBACK_MODEL", "gpt-5.5"
).strip()
WORK_DIRECT_TIERS_ENABLED = os.environ.get(
    "NORMAN_SYNC_WORK_DIRECT_TIERS_ENABLED", "1"
).strip().lower() in {"1", "true", "yes", "on"}


def comma_join_unique(values: Iterable[str]) -> str:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        unique.append(clean)
    return ",".join(unique)


WORK_SWITCHABLE_MODELS = comma_join_unique(
    (
        WORK_BEDROCK_MODEL,
        WORK_BEDROCK_FAILOVER_MODEL,
        WORK_BEDROCK_FAILOVER2_MODEL,
        WORK_BEDROCK_FALLBACK_MODEL,
        WORK_DIRECT_MODEL,
        WORK_DIRECT_FALLBACK_MODEL,
    )
)
WORK_DIRECT_SWITCHABLE_MODELS = comma_join_unique(
    (WORK_DIRECT_MODEL, WORK_DIRECT_FALLBACK_MODEL)
)
WORK_RUNTIME_DEFAULT_MODEL_RESET = os.environ.get(
    "NORMAN_SYNC_WORK_RUNTIME_DEFAULT_MODEL_RESET", "0"
).strip().lower() in {"1", "true", "yes", "on", "force", "forced"}
WORK_RUNTIME_DEFAULT_MODEL_RESET_FROM = tuple(
    value
    for value in (
        item.strip()
        for item in os.environ.get(
            "NORMAN_SYNC_WORK_RUNTIME_DEFAULT_MODEL_RESET_FROM",
            WORK_BEDROCK_FALLBACK_MODEL,
        ).split(",")
    )
    if value
)
WORK_BEDROCK_AWS_PROFILE = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_AWS_PROFILE", "ob-traqline-admin"
).strip()
WORK_BEDROCK_AWS_REGION = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_AWS_REGION", "us-east-2"
).strip()
WORK_BEDROCK_FAILOVER_AWS_PROFILE = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_AWS_PROFILE", WORK_BEDROCK_AWS_PROFILE
).strip()
WORK_BEDROCK_FAILOVER_AWS_REGION = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_AWS_REGION", "us-east-1"
).strip()
WORK_BEDROCK_FAILOVER2_AWS_PROFILE = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER2_AWS_PROFILE", WORK_BEDROCK_AWS_PROFILE
).strip()
WORK_BEDROCK_FAILOVER2_AWS_REGION = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER2_AWS_REGION", "us-west-2"
).strip()
WORK_BEDROCK_FAILOVER_SMOKE_PATH = os.environ.get(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_SMOKE_PATH",
    "/tmp/norman_tui_benchmarks/bedrock_region_smoke.json",
).strip()
WORK_BEDROCK_FAILOVER_SMOKE_MAX_AGE_SECONDS = _positive_int_env(
    "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_SMOKE_MAX_AGE_SECONDS", 24 * 60 * 60
)
WORK_BEDROCK_FAILOVER_FORCE_ENABLED = WORK_BEDROCK_FAILOVER_ENABLEMENT in {
    "1",
    "true",
    "yes",
    "on",
    "force",
    "forced",
}
WORK_BEDROCK_FAILOVER_AUTO_ENABLED = WORK_BEDROCK_FAILOVER_ENABLEMENT in {
    "",
    "auto",
    "smoke",
    "validated",
}
WORK_BEDROCK_FAILOVER_SMOKE_OK = _bedrock_failover_smoke_allows(
    path=WORK_BEDROCK_FAILOVER_SMOKE_PATH,
    profile_v2=WORK_BEDROCK_FAILOVER_PROFILE_V2,
    model=WORK_BEDROCK_FAILOVER_MODEL,
    aws_region=WORK_BEDROCK_FAILOVER_AWS_REGION,
    max_age_seconds=WORK_BEDROCK_FAILOVER_SMOKE_MAX_AGE_SECONDS,
)
WORK_BEDROCK_FAILOVER_ENABLED = WORK_BEDROCK_FAILOVER_FORCE_ENABLED or (
    WORK_BEDROCK_FAILOVER_AUTO_ENABLED and WORK_BEDROCK_FAILOVER_SMOKE_OK
)
WORK_BEDROCK_FAILOVER2_FORCE_ENABLED = WORK_BEDROCK_FAILOVER2_ENABLEMENT in {
    "1",
    "true",
    "yes",
    "on",
    "force",
    "forced",
}
WORK_BEDROCK_FAILOVER2_AUTO_ENABLED = WORK_BEDROCK_FAILOVER2_ENABLEMENT in {
    "",
    "auto",
    "smoke",
    "validated",
}
WORK_BEDROCK_FAILOVER2_SMOKE_OK = _bedrock_failover_smoke_allows(
    path=WORK_BEDROCK_FAILOVER_SMOKE_PATH,
    profile_v2=WORK_BEDROCK_FAILOVER2_PROFILE_V2,
    model=WORK_BEDROCK_FAILOVER2_MODEL,
    aws_region=WORK_BEDROCK_FAILOVER2_AWS_REGION,
    max_age_seconds=WORK_BEDROCK_FAILOVER_SMOKE_MAX_AGE_SECONDS,
)
WORK_BEDROCK_FAILOVER2_ENABLED = WORK_BEDROCK_FAILOVER2_FORCE_ENABLED or (
    WORK_BEDROCK_FAILOVER2_AUTO_ENABLED and WORK_BEDROCK_FAILOVER2_SMOKE_OK
)
WORK_ZERO_TOKEN_PROVIDER_MAX_RETRIES = os.environ.get(
    "NORMAN_SYNC_WORK_ZERO_TOKEN_PROVIDER_MAX_RETRIES",
    "3"
    if (
        WORK_BEDROCK_FAILOVER2_ENABLED
        and WORK_BEDROCK_FAILOVER2_PROFILE_V2
        and WORK_BEDROCK_FAILOVER2_AWS_REGION
    )
    else "2"
    if (
        WORK_BEDROCK_FAILOVER_ENABLED
        and WORK_BEDROCK_FAILOVER_PROFILE_V2
        and WORK_BEDROCK_FAILOVER_AWS_REGION
    )
    else "1",
).strip()
DEFAULT_ROUTE_RECEIPT_DIR = os.environ.get(
    "NORMAN_SYNC_ROUTE_RECEIPT_DIR", "/var/lib/norman/route_receipts"
).strip()
DEFAULT_ROUTE_RECEIPT_ITEMS = os.environ.get(
    "NORMAN_SYNC_ROUTE_RECEIPT_ITEMS", "250"
).strip()

INSTANCE_EXTRA_TRUSTED_CLIENTS: dict[str, tuple[str, ...]] = {
    name: SAL_CONSOLE_CLIENTS for name in WORK_SPECIAL_SAL_CONSOLE_INSTANCES
}

TRUSTED_CONSOLE_PROXIES = (
    "127.0.0.1",
    "::1",
    "192.168.2.241",  # norman proxy/front door
    "100.103.34.17",  # norman tailnet front door
    "fd7a:115c:a1e0::3438:2211",  # norman tailnet front door ipv6
)

AUTH_BRIDGE_CLIENTS = (
    "127.0.0.1",
    "::1",
)

TAILNET_CONSOLE_CLIENTS = (
    "100.64.0.0/10",
    "fd7a:115c:a1e0::/48",
)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)


def capture(cmd: list[str]) -> str:
    completed = subprocess.run(
        cmd,
        check=True,
        text=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    return completed.stdout


def _normalize_host_token(value: str) -> tuple[str, ...]:
    raw = value.strip().lower()
    if not raw:
        return ()
    tokens = {raw}
    if "." in raw:
        tokens.add(raw.split(".", 1)[0])
    return tuple(tokens)


def _dedupe_csv_values(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        candidate = str(value or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return tuple(ordered)


def trusted_console_clients_for_instance(instance_name: str) -> tuple[str, ...]:
    return _dedupe_csv_values(
        (
            *TRUSTED_CONSOLE_CLIENTS,
            *INSTANCE_EXTRA_TRUSTED_CLIENTS.get(instance_name, ()),
        )
    )


def _current_host_tokens() -> set[str]:
    tokens: set[str] = set()
    for value in (
        os.environ.get("HOSTNAME", ""),
        socket.gethostname(),
        socket.getfqdn(),
    ):
        tokens.update(_normalize_host_token(value))
    return tokens


def host_runs_locally(host: DiscoveryHost) -> bool:
    if not host.local:
        return False
    expected: set[str] = set(_normalize_host_token(host.name))
    expected.update(_normalize_host_token(host.public_host))
    for alias in host.alias_hosts:
        expected.update(_normalize_host_token(alias))
    return bool(expected & _current_host_tokens())


def _summarize_discovery_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        for stream in (exc.stderr, exc.stdout):
            if not stream:
                continue
            lines = [line.strip() for line in stream.splitlines() if line.strip()]
            if lines:
                return lines[-1]
        return f"command exited {exc.returncode}"
    return str(exc)


def ssh_command(host: DiscoveryHost, script: str) -> list[str]:
    if host_runs_locally(host):
        if host.use_sudo:
            return ["sudo", "bash", "-lc", script]
        return ["bash", "-lc", script]
    if not host.ssh_target:
        raise RuntimeError(f"host {host.name} is not local and has no ssh target")
    remote = (
        f"sudo bash -lc {shlex.quote(script)}"
        if host.use_sudo
        else f"bash -lc {shlex.quote(script)}"
    )
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SECONDS}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
        host.ssh_target,
        remote,
    ]


def scp_command(source: Path, ssh_target: str, remote_path: str) -> list[str]:
    return [
        "scp",
        "-q",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
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

patterns = json.loads({payload!r})
default_launchers = json.loads({default_launchers_payload!r})


def parse_env(path):
    data = {{}}
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError:
        return None
    with handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def env_get(env, key, default=""):
    if key.startswith("HOUSEBOT_CODEX_"):
        canonical = "NORMAN_CODEX_" + key.removeprefix("HOUSEBOT_CODEX_")
        return env.get(canonical) or env.get(key) or default
    if key.startswith("NORMAN_CODEX_"):
        legacy = "HOUSEBOT_CODEX_" + key.removeprefix("NORMAN_CODEX_")
        return env.get(key) or env.get(legacy) or default
    return env.get(key) or default


def infer_name(path):
    base = os.path.basename(path)
    parent = os.path.basename(os.path.dirname(path))
    if base == "codex-web.env" and parent and parent != "net-agents":
        return parent
    return os.path.splitext(base)[0]


items = []
for pattern in patterns:
    for env_path in sorted(glob.glob(pattern)):
        env = parse_env(env_path)
        if env is None:
            continue
        name = infer_name(env_path)
        launch_path = (env_get(env, "NORMAN_CODEX_LAUNCHER") or "").strip()
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
                "agent_label": (env_get(env, "NORMAN_CODEX_AGENT_NAME") or name).strip(),
                "web_port": (env_get(env, "NORMAN_CODEX_WEB_PORT") or "").strip(),
                "web_token": (env_get(env, "NORMAN_CODEX_WEB_TOKEN") or "").strip(),
                "prompt_file": (env_get(env, "NORMAN_CODEX_PROMPT_FILE") or "").strip(),
                "codex_home": (
                    env_get(env, "NORMAN_CODEX_HOME")
                    or env_get(env, "CODEX_HOME")
                    or ""
                ).strip(),
                "restart_units": [
                    (env_get(env, "NORMAN_CODEX_SERVICE_NAME") or f"{{name}}-codex.service").strip(),
                    (env_get(env, "NORMAN_CODEX_WEB_SERVICE_NAME") or f"{{name}}-codex-web.service").strip(),
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
            RuntimeError,
            subprocess.CalledProcessError,
            json.JSONDecodeError,
        ) as exc:
            print(
                f"warning: discovery failed for {host_name}: {_summarize_discovery_error(exc)}",
                file=sys.stderr,
                flush=True,
            )
            instances = []
        instances = [
            instance
            for instance in instances
            if instance.name not in ARCHIVED_INSTANCE_NAMES
            and CANONICAL_INSTANCE_HOSTS.get(instance.name, instance.host_name)
            == instance.host_name
        ]
        by_host[host_name] = instances
        for instance in instances:
            by_name[instance.name] = instance
    return by_host, by_name


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


def instance_public_base_url(instance: ConsoleInstance) -> str:
    public_host = instance_public_host(instance)
    if not public_host:
        return ""
    host = HOSTS[instance.host_name]
    if public_host.endswith(".kris.openbrand.com") or public_host != host.public_host:
        return f"https://{public_host}/"
    return f"http://{public_host}:{instance.web_port}/"


def host_tail_host(host: DiscoveryHost) -> str:
    for alias in host.alias_hosts:
        clean = alias.strip()
        if clean.endswith(".ts.net"):
            return clean
    return ""


def instance_console_urls(
    instance: ConsoleInstance, profile_placeholder: bool = True
) -> dict[str, str]:
    host = HOSTS[instance.host_name]
    lan_host = host.lan_host
    tail_host = host_tail_host(host)
    query = f"?token={instance.web_token}"
    if profile_placeholder:
        query += "&profile={profile}"
    public_url_override = INSTANCE_CONSOLE_URL_OVERRIDES.get(instance.name, "").strip()
    if public_url_override:
        public_url = _append_query(f"{public_url_override.rstrip('/')}/", query)
    else:
        public_url = _append_query(instance_public_base_url(instance), query)
    urls = {
        "url": public_url,
        "lan_url": f"http://{lan_host}:{instance.web_port}/{query}",
    }
    if tail_host:
        urls["tail_url"] = f"http://{tail_host}:{instance.web_port}/{query}"
    return urls


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
    for value in (host.public_host, *host.alias_hosts, host.lan_host):
        clean = (value or "").strip()
        if not clean:
            continue
        scheme = "https" if clean.endswith(".kris.openbrand.com") else "http"
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

    if public_host and public_host != host.public_host:
        add(_append_query(instance_public_base_url(instance), query))

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
    seen: set[tuple[str, str, str, str, str]] = set()

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
        key = (group, label, urls["url"], urls["lan_url"], urls.get("tail_url", ""))
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

    for target_name, label, group, priority in PROMOTED_FOLD_INSTANCES:
        target = discovered_by_name.get(target_name)
        if target:
            add_link(label, target, group, featured=True, priority=priority)

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
line = f"NORMAN_CODEX_LINKS_JSON={{value}}"
pattern = re.compile(r"^NORMAN_CODEX_LINKS_JSON=.*$", re.M)
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


def sync_instance_origin_settings(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    aliases = []
    canonical_host = instance_public_host(instance)
    billing_scope = (
        "work-special" if instance.name in WORK_BILLING_INSTANCES else host.name
    )
    billing_owner = "openbrand" if billing_scope == "work-special" else "kristopher"
    billing_actor = BBS_ACTOR_OVERRIDES.get(instance.name, instance.name)
    soul_actor = BBS_ACTOR_OVERRIDES.get(instance.name, instance.name)
    soul_loader = str(Path(instance.launch_path).with_name("compose_soul_context.py"))
    for value in (
        canonical_host,
        *INSTANCE_LOCAL_HOST_ALIAS_OVERRIDES.get(instance.name, ()),
        host.public_host,
        host.lan_host,
        *host.alias_hosts,
    ):
        clean = (value or "").strip()
        if clean and clean not in aliases:
            aliases.append(clean)
    updates = {
        "NORMAN_CODEX_CANONICAL_HOST": canonical_host,
        "NORMAN_CODEX_LOCAL_HOST_ALIASES": ",".join(aliases),
        "NORMAN_CODEX_TRUSTED_CLIENTS": ",".join(
            trusted_console_clients_for_instance(instance.name)
        ),
        "NORMAN_CODEX_TRUSTED_PROXIES": ",".join(TRUSTED_CONSOLE_PROXIES),
        "NORMAN_CODEX_BROWSER_AUTH_CLIENTS": ",".join(AUTH_BRIDGE_CLIENTS),
        "NORMAN_CODEX_TAILNET_CLIENTS": ",".join(TAILNET_CONSOLE_CLIENTS),
        "NORMAN_CODEX_AGENT_GROUP": HOST_GROUP_LABELS.get(host.name, "Agents"),
        "NORMAN_CODEX_LONG_JOB_NOTIFY_THRESHOLD_SECONDS": (
            DEFAULT_LONG_JOB_NOTIFY_THRESHOLD_SECONDS or str(60 * 60)
        ),
        "NORMAN_CODEX_LONG_JOB_NOTIFY_TIMEOUT_SECONDS": (
            DEFAULT_LONG_JOB_NOTIFY_TIMEOUT_SECONDS or "5"
        ),
        "NORMAN_CODEX_BILLING_SCOPE": billing_scope,
        "NORMAN_CODEX_BILLING_UNIT": f"{billing_scope}:{billing_actor}",
        "NORMAN_CODEX_BILLING_OWNER": billing_owner,
        "NORMAN_CODEX_BILLING_PROJECT": instance.name,
        "NORMAN_CODEX_SOUL_ENABLED": "1",
        "NORMAN_CODEX_SOUL_ACTOR": soul_actor,
        "NORMAN_CODEX_SOUL_IDENTITY_ROOT": REMOTE_SOUL_IDENTITY_ROOT,
        "NORMAN_CODEX_SOUL_LOADER": soul_loader,
    }
    if (
        instance.name in WORK_BEDROCK_DEFAULT_INSTANCES
        and WORK_BEDROCK_PROFILE_V2
        and WORK_BEDROCK_MODEL
    ):
        updates.update(
            {
                "NORMAN_CODEX_MODEL": WORK_BEDROCK_MODEL,
                "NORMAN_CODEX_MODEL_FLOOR": "gpt-5.4",
                "NORMAN_CODEX_SERVICE_TIER": "default",
                "NORMAN_CODEX_STANDARD_PROFILE_V2": WORK_BEDROCK_PROFILE_V2,
                "NORMAN_CODEX_STANDARD_MODEL": WORK_BEDROCK_MODEL,
                "NORMAN_CODEX_STANDARD_PROVIDER_LABEL": "Bedrock Standard",
                "NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2": (
                    WORK_BEDROCK_FAILOVER_PROFILE_V2
                    if WORK_BEDROCK_FAILOVER_ENABLED
                    else ""
                ),
                "NORMAN_CODEX_BEDROCK_FAILOVER_MODEL": (
                    WORK_BEDROCK_FAILOVER_MODEL if WORK_BEDROCK_FAILOVER_ENABLED else ""
                ),
                "NORMAN_CODEX_BEDROCK_FAILOVER_PROVIDER_LABEL": (
                    "Bedrock Failover" if WORK_BEDROCK_FAILOVER_ENABLED else ""
                ),
                "NORMAN_CODEX_BEDROCK_FAILOVER2_PROFILE_V2": (
                    WORK_BEDROCK_FAILOVER2_PROFILE_V2
                    if WORK_BEDROCK_FAILOVER2_ENABLED
                    else ""
                ),
                "NORMAN_CODEX_BEDROCK_FAILOVER2_MODEL": (
                    WORK_BEDROCK_FAILOVER2_MODEL
                    if WORK_BEDROCK_FAILOVER2_ENABLED
                    else ""
                ),
                "NORMAN_CODEX_BEDROCK_FAILOVER2_PROVIDER_LABEL": (
                    "Bedrock Failover 2" if WORK_BEDROCK_FAILOVER2_ENABLED else ""
                ),
                "NORMAN_CODEX_DIRECT_PROVIDER_LABEL": "OpenAI",
                "NORMAN_CODEX_DIRECT_MODEL": WORK_DIRECT_MODEL,
                "NORMAN_CODEX_FLEX_MODEL": WORK_DIRECT_MODEL,
                "NORMAN_CODEX_PRIORITY_MODEL": WORK_DIRECT_MODEL,
                "NORMAN_CODEX_STANDARD_AWS_PROFILE": WORK_BEDROCK_AWS_PROFILE,
                "NORMAN_CODEX_STANDARD_AWS_REGION": WORK_BEDROCK_AWS_REGION,
                "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_PROFILE": (
                    WORK_BEDROCK_FAILOVER_AWS_PROFILE
                    if WORK_BEDROCK_FAILOVER_ENABLED
                    else ""
                ),
                "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION": (
                    WORK_BEDROCK_FAILOVER_AWS_REGION
                    if WORK_BEDROCK_FAILOVER_ENABLED
                    else ""
                ),
                "NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_PROFILE": (
                    WORK_BEDROCK_FAILOVER2_AWS_PROFILE
                    if WORK_BEDROCK_FAILOVER2_ENABLED
                    else ""
                ),
                "NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_REGION": (
                    WORK_BEDROCK_FAILOVER2_AWS_REGION
                    if WORK_BEDROCK_FAILOVER2_ENABLED
                    else ""
                ),
                "NORMAN_CODEX_DIRECT_TIERS_ENABLED": (
                    "1" if WORK_DIRECT_TIERS_ENABLED else "0"
                ),
                "NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES": (
                    WORK_ZERO_TOKEN_PROVIDER_MAX_RETRIES
                ),
                "NORMAN_CODEX_SWITCHABLE_MODELS": WORK_SWITCHABLE_MODELS,
                "NORMAN_CODEX_AVAILABLE_MODELS": WORK_SWITCHABLE_MODELS,
            }
        )
        remove_keys: tuple[str, ...] = ()
    else:
        updates.update(
            {
                "NORMAN_CODEX_MODEL": WORK_DIRECT_MODEL,
                "NORMAN_CODEX_MODEL_FLOOR": "gpt-5.4",
                "NORMAN_CODEX_DIRECT_PROVIDER_LABEL": "OpenAI",
                "NORMAN_CODEX_DIRECT_MODEL": WORK_DIRECT_MODEL,
                "NORMAN_CODEX_FLEX_MODEL": WORK_DIRECT_MODEL,
                "NORMAN_CODEX_PRIORITY_MODEL": WORK_DIRECT_MODEL,
                "NORMAN_CODEX_DIRECT_TIERS_ENABLED": (
                    "1" if WORK_DIRECT_TIERS_ENABLED else "0"
                ),
                "NORMAN_CODEX_SWITCHABLE_MODELS": WORK_DIRECT_SWITCHABLE_MODELS,
                "NORMAN_CODEX_AVAILABLE_MODELS": WORK_DIRECT_SWITCHABLE_MODELS,
            }
        )
        if instance.name in WORK_DIRECT_DEFAULT_INSTANCES:
            updates["NORMAN_CODEX_SERVICE_TIER"] = "auto"
            remove_keys = WORK_BEDROCK_ENV_KEYS
        else:
            updates["NORMAN_CODEX_SERVICE_TIER"] = NON_WORK_DEFAULT_SERVICE_TIER
            remove_keys = WORK_BEDROCK_ENV_KEYS
    if DEFAULT_LONG_JOB_NOTIFY_URL:
        updates["NORMAN_CODEX_LONG_JOB_NOTIFY_URL"] = DEFAULT_LONG_JOB_NOTIFY_URL
    if DEFAULT_LONG_JOB_NOTIFY_TOKEN:
        updates["NORMAN_CODEX_LONG_JOB_NOTIFY_TOKEN"] = DEFAULT_LONG_JOB_NOTIFY_TOKEN
    if DEFAULT_BBS_SUMMARY_URL:
        bbs_actor = BBS_ACTOR_OVERRIDES.get(instance.name, instance.name)
        bbs_env_file = f"/etc/{instance.name}/switchboard-bbs.env"
        updates.update(
            {
                "NORMAN_CODEX_BBS_URL": DEFAULT_BBS_SUMMARY_URL,
                "NORMAN_CODEX_BBS_ACTOR": bbs_actor,
                "NORMAN_CODEX_BBS_ENV_FILE": bbs_env_file,
                "SWITCHBOARD_URL": DEFAULT_BBS_SUMMARY_URL,
                "SWITCHBOARD_ACTOR": bbs_actor,
                "SWITCHBOARD_ENV_FILE": bbs_env_file,
            }
        )
    updates = canonicalize_codex_env_updates(updates)
    remove_keys = list(expand_codex_env_remove_keys(remove_keys))
    for key in updates:
        legacy_key = legacy_codex_env_key(key)
        if legacy_key != key and legacy_key not in remove_keys:
            remove_keys.append(legacy_key)
    remove_keys = tuple(key for key in remove_keys if key not in updates)
    payload = json.dumps(updates, separators=(",", ":"))
    remove_payload = json.dumps(list(remove_keys), separators=(",", ":"))
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


def canonicalize_existing_codex_env(text):
    def replace(match):
        suffix = match.group(1)
        value = match.group(2)
        newline = match.group(3)
        canonical = f"NORMAN_CODEX_{{suffix}}"
        if re.search(rf"^{{re.escape(canonical)}}=", text, re.M):
            return ""
        return f"{{canonical}}={{value}}{{newline}}"

    return re.sub(r"^HOUSEBOT_CODEX_([A-Z0-9_]+)=(.*)(\\n?)", replace, text, flags=re.M)


updated = canonicalize_existing_codex_env(text)
if updated != text:
    text = updated
    changed = True
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
    receipt_dir: str = DEFAULT_ROUTE_RECEIPT_DIR,
    max_items: str = DEFAULT_ROUTE_RECEIPT_ITEMS,
) -> bool:
    clean_dir = (receipt_dir or DEFAULT_ROUTE_RECEIPT_DIR).rstrip("/")
    clean_items = str(max_items or DEFAULT_ROUTE_RECEIPT_ITEMS)
    updates = canonicalize_codex_env_updates(
        {
            "NORMAN_CODEX_ROUTE_RECEIPTS_ENABLED": "1",
            "NORMAN_CODEX_ROUTE_RECEIPT_OWNER_TUI": instance.name,
            "NORMAN_CODEX_ROUTE_RECEIPT_DIR": clean_dir,
            "NORMAN_CODEX_ROUTE_RECEIPT_PATH": f"{clean_dir}/{instance.name}.jsonl",
            "NORMAN_CODEX_ROUTE_RECEIPT_ITEMS": clean_items,
        }
    )
    remove_keys = [
        legacy_codex_env_key(key) for key in updates if legacy_codex_env_key(key) != key
    ]
    payload = json.dumps(updates, separators=(",", ":"))
    remove_payload = json.dumps(remove_keys, separators=(",", ":"))
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import os
import re

path = Path({instance.env_file!r})
updates = json.loads({payload!r})
remove_keys = json.loads({remove_payload!r})
text = path.read_text(encoding="utf-8")
changed = False

route_receipt_dir = updates.get("NORMAN_CODEX_ROUTE_RECEIPT_DIR", "")
if route_receipt_dir:
    route_receipt_path = Path(route_receipt_dir)
    route_receipt_file = Path(updates.get("NORMAN_CODEX_ROUTE_RECEIPT_PATH", ""))
    receipt_owner_source = Path({instance.codex_home!r}) if {bool(instance.codex_home)!r} else path
    if not receipt_owner_source.exists():
        receipt_owner_source = path
    target_stat = receipt_owner_source.stat()
    target_uid = target_stat.st_uid
    target_gid = target_stat.st_gid
    route_receipt_path.mkdir(parents=True, exist_ok=True)
    current_stat = route_receipt_path.stat()
    if current_stat.st_uid != target_uid or current_stat.st_gid != target_gid:
        os.chown(route_receipt_path, target_uid, target_gid)
        changed = True
    if (route_receipt_path.stat().st_mode & 0o777) != 0o750:
        os.chmod(route_receipt_path, 0o750)
        changed = True
    if str(route_receipt_file):
        if not route_receipt_file.exists():
            route_receipt_file.touch()
            changed = True
        current_file_stat = route_receipt_file.stat()
        if current_file_stat.st_uid != target_uid or current_file_stat.st_gid != target_gid:
            os.chown(route_receipt_file, target_uid, target_gid)
            changed = True
        if (route_receipt_file.stat().st_mode & 0o777) != 0o640:
            os.chmod(route_receipt_file, 0o640)
            changed = True


def canonicalize_existing_codex_env(text):
    def replace(match):
        suffix = match.group(1)
        value = match.group(2)
        newline = match.group(3)
        canonical = f"NORMAN_CODEX_{{suffix}}"
        if re.search(rf"^{{re.escape(canonical)}}=", text, re.M):
            return ""
        return f"{{canonical}}={{value}}{{newline}}"

    return re.sub(r"^HOUSEBOT_CODEX_([A-Z0-9_]+)=(.*)(\\n?)", replace, text, flags=re.M)


updated = canonicalize_existing_codex_env(text)
if updated != text:
    text = updated
    changed = True
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


def sync_instance_agent_label(host: DiscoveryHost, instance: ConsoleInstance) -> bool:
    label = instance_label(instance)
    if not label:
        return False
    updates = {
        "NORMAN_CODEX_AGENT_NAME": label,
        "NORMAN_CODEX_CONSOLE_TITLE": f"{label} Console",
    }
    prompt_placeholder = INSTANCE_PROMPT_PLACEHOLDER_OVERRIDES.get(instance.name)
    if prompt_placeholder:
        updates["NORMAN_CODEX_PROMPT_PLACEHOLDER"] = prompt_placeholder
    updates = canonicalize_codex_env_updates(updates)
    remove_keys = [
        legacy_codex_env_key(key) for key in updates if legacy_codex_env_key(key) != key
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


def canonicalize_existing_codex_env(text):
    def replace(match):
        suffix = match.group(1)
        value = match.group(2)
        newline = match.group(3)
        canonical = f"NORMAN_CODEX_{{suffix}}"
        if re.search(rf"^{{re.escape(canonical)}}=", text, re.M):
            return ""
        return f"{{canonical}}={{value}}{{newline}}"

    return re.sub(r"^HOUSEBOT_CODEX_([A-Z0-9_]+)=(.*)(\\n?)", replace, text, flags=re.M)


updated = canonicalize_existing_codex_env(text)
if updated != text:
    text = updated
    changed = True
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


def sync_instance_bedrock_profile(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    if (
        instance.name not in WORK_BEDROCK_DEFAULT_INSTANCES
        or not instance.codex_home
        or not WORK_BEDROCK_PROFILE_SOURCE
        or not WORK_BEDROCK_PROFILE_V2
    ):
        return False

    profile_specs = [
        {
            "source": WORK_BEDROCK_PROFILE_SOURCE,
            "profile_v2": WORK_BEDROCK_PROFILE_V2,
            "model": WORK_BEDROCK_MODEL,
            "aws_profile": WORK_BEDROCK_AWS_PROFILE,
            "aws_region": WORK_BEDROCK_AWS_REGION,
            "reasoning_effort": WORK_BEDROCK_REASONING_EFFORT,
        }
    ]
    if (
        WORK_BEDROCK_FAILOVER_ENABLED
        and WORK_BEDROCK_FAILOVER_PROFILE_SOURCE
        and WORK_BEDROCK_FAILOVER_PROFILE_V2
        and WORK_BEDROCK_FAILOVER_MODEL
        and WORK_BEDROCK_FAILOVER_AWS_REGION
    ):
        profile_specs.append(
            {
                "source": WORK_BEDROCK_FAILOVER_PROFILE_SOURCE,
                "profile_v2": WORK_BEDROCK_FAILOVER_PROFILE_V2,
                "model": WORK_BEDROCK_FAILOVER_MODEL,
                "aws_profile": WORK_BEDROCK_FAILOVER_AWS_PROFILE,
                "aws_region": WORK_BEDROCK_FAILOVER_AWS_REGION,
                "reasoning_effort": WORK_BEDROCK_REASONING_EFFORT,
            }
        )
    if (
        WORK_BEDROCK_FAILOVER2_ENABLED
        and WORK_BEDROCK_FAILOVER2_PROFILE_SOURCE
        and WORK_BEDROCK_FAILOVER2_PROFILE_V2
        and WORK_BEDROCK_FAILOVER2_MODEL
        and WORK_BEDROCK_FAILOVER2_AWS_REGION
    ):
        profile_specs.append(
            {
                "source": WORK_BEDROCK_FAILOVER2_PROFILE_SOURCE,
                "profile_v2": WORK_BEDROCK_FAILOVER2_PROFILE_V2,
                "model": WORK_BEDROCK_FAILOVER2_MODEL,
                "aws_profile": WORK_BEDROCK_FAILOVER2_AWS_PROFILE,
                "aws_region": WORK_BEDROCK_FAILOVER2_AWS_REGION,
                "reasoning_effort": WORK_BEDROCK_REASONING_EFFORT,
            }
        )
    profile_specs_payload = json.dumps(profile_specs, separators=(",", ":"))

    script = f"""
python3 - <<'PY'
from pathlib import Path
import hashlib
import json
import os

target_home = Path({instance.codex_home!r})
profile_specs = json.loads({profile_specs_payload!r})

if not target_home.exists():
    print("unchanged")
    raise SystemExit(0)

def digest_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def ensure_table_setting(text, table, key, value):
    rendered = f'{{key}} = "{{value}}"'
    lines = text.splitlines()
    header = f"[{{table}}]" if table else ""
    start = 0
    end = len(lines)
    if table:
        start = -1
        for index, line in enumerate(lines):
            if line.strip() == header:
                start = index + 1
                break
        if start < 0:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(header)
            lines.append(rendered)
            return "\\n".join(lines).rstrip() + "\\n"
        for index in range(start, len(lines)):
            clean = lines[index].strip()
            if clean.startswith("[") and clean.endswith("]"):
                end = index
                break
    else:
        for index, line in enumerate(lines):
            clean = line.strip()
            if clean.startswith("[") and clean.endswith("]"):
                end = index
                break
    for index in range(start, end):
        if lines[index].strip().startswith(f"{{key}} "):
            lines[index] = rendered
            return "\\n".join(lines).rstrip() + "\\n"
    lines.insert(end, rendered)
    return "\\n".join(lines).rstrip() + "\\n"

def render_profile(source_text, spec):
    profile_name = str(spec.get("profile_v2") or "").strip()
    model = str(spec.get("model") or "").strip()
    aws_profile = str(spec.get("aws_profile") or "").strip()
    aws_region = str(spec.get("aws_region") or "").strip()
    reasoning_effort = str(spec.get("reasoning_effort") or "").strip()
    rendered = source_text
    if model:
        rendered = ensure_table_setting(rendered, "", "model", model)
    rendered = ensure_table_setting(rendered, "", "profile", profile_name)
    rendered = ensure_table_setting(rendered, "", "model_provider", "amazon-bedrock")
    if reasoning_effort:
        rendered = ensure_table_setting(
            rendered, "", "model_reasoning_effort", reasoning_effort
        )
    if profile_name:
        profile_table = f"profiles.{{profile_name}}"
        if model:
            rendered = ensure_table_setting(rendered, profile_table, "model", model)
        rendered = ensure_table_setting(
            rendered, profile_table, "model_provider", "amazon-bedrock"
        )
        if reasoning_effort:
            rendered = ensure_table_setting(
                rendered, profile_table, "model_reasoning_effort", reasoning_effort
            )
    aws_table = "model_providers.amazon-bedrock.aws"
    if aws_profile:
        rendered = ensure_table_setting(rendered, aws_table, "profile", aws_profile)
    if aws_region:
        rendered = ensure_table_setting(rendered, aws_table, "region", aws_region)
    rendered = ensure_table_setting(rendered, aws_table, "wire_api", "responses")
    return rendered

changed = False
target_stat = target_home.stat()
for spec in profile_specs:
    source = Path(str(spec.get("source") or ""))
    profile_name = str(spec.get("profile_v2") or "").strip()
    if not source.exists() or not profile_name:
        continue
    target = target_home / (profile_name + ".config.toml")
    source_text = source.read_text(encoding="utf-8")
    rendered = render_profile(source_text, spec)
    target_changed = (
        not target.exists()
        or digest_text(rendered) != digest_text(target.read_text(encoding="utf-8"))
    )
    if target_changed:
        target.write_text(rendered, encoding="utf-8")
        os.chown(target, target_stat.st_uid, target_stat.st_gid)
        os.chmod(target, 0o600)
        changed = True
print("changed" if changed else "unchanged")
PY
"""
    return capture(ssh_command(host, script)).strip() == "changed"


def sync_instance_runtime_settings(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    if (
        not WORK_RUNTIME_DEFAULT_MODEL_RESET
        or instance.name not in WORK_BEDROCK_DEFAULT_INSTANCES
        or not instance.codex_home
        or not WORK_BEDROCK_MODEL
        or not WORK_RUNTIME_DEFAULT_MODEL_RESET_FROM
    ):
        return False

    reset_from_payload = json.dumps(
        list(WORK_RUNTIME_DEFAULT_MODEL_RESET_FROM), separators=(",", ":")
    )
    script = f"""
python3 - <<'PY'
from pathlib import Path
import json

settings_path = Path({instance.codex_home!r}) / "web-bridge" / "runtime_settings.json"
target_model = {WORK_BEDROCK_MODEL!r}
reset_from = set(json.loads({reset_from_payload!r}))

if not settings_path.exists():
    print("unchanged")
    raise SystemExit(0)

try:
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, OSError):
    print("unchanged")
    raise SystemExit(0)

if not isinstance(payload, dict):
    print("unchanged")
    raise SystemExit(0)

runtime = str(payload.get("runtime") or "codex").strip().lower()
service_tier = str(payload.get("service_tier") or "default").strip().lower()
model = str(payload.get("model") or "").strip()

if runtime == "codex" and service_tier in {{"", "auto", "default", "flex"}} and model in reset_from:
    payload["runtime"] = "codex"
    payload["service_tier"] = "default"
    payload["model"] = target_model
    settings_path.write_text(json.dumps(payload, sort_keys=True) + "\\n", encoding="utf-8")
    print("changed")
else:
    print("unchanged")
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


def owner_name(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def group_name(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


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
    payload["owner"] = owner_name(st.st_uid)
    payload["group"] = group_name(st.st_gid)

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

    if host_runs_locally(host):
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


def iter_soul_identity_files(root: Path | None = None) -> list[Path]:
    root = root or LOCAL_SOUL_IDENTITY_ROOT
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def remote_soul_identity_path(source: Path) -> str:
    rel = source.relative_to(LOCAL_SOUL_IDENTITY_ROOT).as_posix()
    return f"{REMOTE_SOUL_IDENTITY_ROOT.rstrip('/')}/{rel}"


def sync_soul_identity_tree(host: DiscoveryHost) -> list[str]:
    changed_paths: list[str] = []
    for source in iter_soul_identity_files():
        remote_path = remote_soul_identity_path(source)
        if install_source_path(
            host,
            remote_path=remote_path,
            source=source,
            source_sha256=local_sha256(source),
        ):
            changed_paths.append(remote_path)
    return changed_paths


def _coerce_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _status_restart_block_reason(status: dict[str, object]) -> str:
    reasons: list[str] = []

    active_child_pid = _coerce_nonnegative_int(status.get("active_child_pid"))
    model_process_alive = status.get("model_process_alive")
    if active_child_pid and model_process_alive is not False:
        reasons.append(f"active child pid {active_child_pid}")

    queue_depth = _coerce_nonnegative_int(status.get("queue_depth"))
    queue = status.get("queue")
    if not queue_depth and isinstance(queue, list):
        queue_depth = len(queue)
    if queue_depth:
        reasons.append(f"queue depth {queue_depth}")

    active_job = (
        status.get("current_prompt_id")
        or status.get("current_job_id")
        or status.get("active_job_id")
    )
    if active_job:
        reasons.append(f"active job {active_job}")

    if status.get("pending") is True:
        reasons.append("pending prompt")

    state_value = str(status.get("state") or "").strip().lower()
    if state_value in {"active", "busy", "running"}:
        reasons.append(f"state {state_value}")

    status_value = str(status.get("status") or "").strip().lower()
    if not reasons and (
        status.get("busy") is True or status_value in {"active", "busy", "running"}
    ):
        reasons.append(f"status {status_value or 'busy'}")

    return "; ".join(reasons)


def _status_restart_handoff_summary(status: dict[str, object]) -> str:
    handoff = status.get("context_handoff")
    if not isinstance(handoff, dict):
        return ""
    parts: list[str] = []
    if handoff.get("can_resume_thread"):
        thread_id = str(handoff.get("thread_id") or "").strip()
        parts.append(f"resume {thread_id[:8]}" if thread_id else "thread resumable")
    history_count = _coerce_nonnegative_int(handoff.get("history_count"))
    if history_count:
        parts.append(f"{history_count} history")
    queue_depth = _coerce_nonnegative_int(handoff.get("queue_depth"))
    if queue_depth:
        parts.append(f"{queue_depth} queued")
    if not parts and handoff.get("context_preserved"):
        parts.append("context preserved")
    return "handoff " + ", ".join(parts) if parts else ""


def restart_block_reasons(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> dict[str, str]:
    payload = json.dumps(
        [
            {
                "name": instance.name,
                "web_port": instance.web_port,
                "web_token": instance.web_token,
            }
            for instance in instances
        ],
        separators=(",", ":"),
    )
    readiness_timeout = RESTART_READINESS_TIMEOUT_SECONDS
    status_timeout = STATUS_PROBE_TIMEOUT_SECONDS
    script = f"""
python3 - <<'PY'
import json
import urllib.parse
import urllib.request

instances = json.loads({payload!r})
readiness_timeout = {readiness_timeout!r}
status_timeout = {status_timeout!r}
results = {{}}


def fetch_json(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body or "{{}}")


for instance in instances:
    name = str(instance.get("name") or "")
    port = str(instance.get("web_port") or "")
    token = str(instance.get("web_token") or "")

    if not name:
        continue
    if not port:
        results[name] = {{"error": "missing web port"}}
        continue

    query = "?" + urllib.parse.urlencode({{"token": token}}) if token else ""
    readiness_url = "http://127.0.0.1:" + port + "/api/restart-readiness" + query
    status_url = "http://127.0.0.1:" + port + "/api/status" + query
    try:
        results[name] = fetch_json(readiness_url, readiness_timeout)
    except Exception as exc:
        try:
            results[name] = fetch_json(status_url, status_timeout)
        except Exception as fallback_exc:
            results[name] = {{
                "error": type(fallback_exc).__name__ + ": " + str(fallback_exc),
                "readiness_error": type(exc).__name__ + ": " + str(exc),
            }}

print(json.dumps(results))
PY
"""
    raw = json.loads(capture(ssh_command(host, script)) or "{}")
    reasons: dict[str, str] = {}
    for instance in instances:
        status = raw.get(instance.name)
        if not isinstance(status, dict):
            reasons[instance.name] = "status unavailable"
            continue
        error = str(status.get("error") or "").strip()
        if error:
            reasons[instance.name] = f"status unavailable: {error}"
            continue
        reason = _status_restart_block_reason(status)
        if reason:
            handoff = _status_restart_handoff_summary(status)
            if handoff:
                reason = f"{reason}; {handoff}"
            reasons[instance.name] = reason
    return reasons


def restart_instances(host: DiscoveryHost, instances: list[ConsoleInstance]) -> None:
    units = sorted({unit for instance in instances for unit in instance.restart_units})
    if not units:
        return
    restart_systemd_units(host, units)


def web_restart_units(instances: list[ConsoleInstance]) -> list[str]:
    units: set[str] = set()
    for instance in instances:
        if len(instance.restart_units) >= 2:
            units.add(instance.restart_units[1])
            continue
        units.update(unit for unit in instance.restart_units if "web" in unit)
    return sorted(units)


def restart_web_instances(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> None:
    units = web_restart_units(instances)
    if not units:
        return
    restart_systemd_units(host, units)


def restart_systemd_units(host: DiscoveryHost, units: list[str]) -> None:
    unit_list = " ".join(shlex.quote(unit) for unit in units)
    script = " && ".join(
        [
            "systemctl daemon-reload",
            f"systemctl restart {unit_list}",
            f"systemctl is-active {unit_list}",
        ]
    )
    run(ssh_command(host, script))


def health_check_instances(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> None:
    for instance in instances:
        env_path = shlex.quote(instance.env_file)
        name = shlex.quote(instance.name)
        attempts = shlex.quote(str(HEALTH_CHECK_ATTEMPTS))
        sleep_seconds = shlex.quote(str(HEALTH_CHECK_SLEEP_SECONDS))
        timeout_seconds = shlex.quote(str(HEALTH_CHECK_TIMEOUT_SECONDS))
        script = "\n".join(
            [
                "set -e",
                f"NAME={name}",
                f"ATTEMPTS={attempts}",
                f"SLEEP_SECONDS={sleep_seconds}",
                f"TIMEOUT_SECONDS={timeout_seconds}",
                f'PORT=$(grep -E "^(NORMAN_CODEX|HOUSEBOT_CODEX)_WEB_PORT=" {env_path} | tail -n1 | cut -d= -f2-)',
                f'TOKEN=$(grep -E "^(NORMAN_CODEX|HOUSEBOT_CODEX)_WEB_TOKEN=" {env_path} | tail -n1 | cut -d= -f2-)',
                'test -n "$PORT"',
                'URL="http://127.0.0.1:${PORT}/healthz?token=${TOKEN}"',
                'last_error=""',
                'for attempt in $(seq 1 "$ATTEMPTS"); do',
                '  if output=$(curl -fsS --max-time "$TIMEOUT_SECONDS" "$URL" 2>&1 >/dev/null); then',
                '    if [ "$attempt" -gt 1 ]; then',
                '      printf "%s: health ok after %s/%s attempts\\n" "$NAME" "$attempt" "$ATTEMPTS"',
                "    fi",
                "    exit 0",
                "  fi",
                '  last_error="$output"',
                '  sleep "$SLEEP_SECONDS"',
                "done",
                'printf "%s: health check failed on port %s after %s attempts\\n" "$NAME" "$PORT" "$ATTEMPTS" >&2',
                'if [ -n "$last_error" ]; then printf "%s\\n" "$last_error" >&2; fi',
                "exit 1",
            ]
        )
        run(ssh_command(host, script))


def restart_and_health_check_instances(
    host: DiscoveryHost,
    instances: list[ConsoleInstance],
    *,
    check_health: bool,
    web_only: bool = False,
) -> None:
    total = len(instances)
    for index, instance in enumerate(instances, start=1):
        service_scope = "web " if web_only else ""
        print(
            f"  - restarting {service_scope}{instance.name} ({index}/{total})",
            flush=True,
        )
        if web_only:
            restart_web_instances(host, [instance])
        else:
            restart_instances(host, [instance])
        if check_health:
            print(f"  - health check {instance.name}", flush=True)
            health_check_instances(host, [instance])
        if index < total and RESTART_SETTLE_SECONDS:
            time.sleep(RESTART_SETTLE_SECONDS)


def restart_scope_for_instance(
    instance: ConsoleInstance,
    *,
    changed_paths: set[str],
    changed_instances: dict[str, ConsoleInstance],
) -> str:
    if instance.name in changed_instances:
        return "full"
    if instance.prompt_file and instance.prompt_file in changed_paths:
        return "full"

    changed_source_keys = {
        source_key
        for source_key, remote_path in instance.files
        if remote_path in changed_paths
    }
    if not changed_source_keys:
        return ""
    if changed_source_keys <= {"web"}:
        return "web"
    return "full"


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


def parse_env(path):
    data = {{}}
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError:
        return None
    with handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def env_get(env, key, default=""):
    if key.startswith("HOUSEBOT_CODEX_"):
        canonical = "NORMAN_CODEX_" + key.removeprefix("HOUSEBOT_CODEX_")
        return env.get(canonical) or env.get(key) or default
    if key.startswith("NORMAN_CODEX_"):
        legacy = "HOUSEBOT_CODEX_" + key.removeprefix("NORMAN_CODEX_")
        return env.get(key) or env.get(legacy) or default
    return env.get(key) or default


results = []
for item in instances:
    name = item["name"]
    env = parse_env(item["env_file"])
    if env is None:
        results.append({{"name": name, "version": "missing-env"}})
        continue
    port = (env_get(env, "NORMAN_CODEX_WEB_PORT") or "").strip()
    token = (env_get(env, "NORMAN_CODEX_WEB_TOKEN") or "").strip()
    if not port:
        results.append({{"name": name, "version": "missing-port"}})
        continue
    query = "?" + urllib.parse.urlencode({{"token": token}}) if token else ""
    root_url = f"http://127.0.0.1:{{port}}/{{query}}"
    status_url = f"http://127.0.0.1:{{port}}/api/status{{query}}"
    result = {{"name": name, "version": "missing"}}
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        with opener.open(root_url, timeout=8) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        results.append({{"name": name, "version": f"error: {{exc.__class__.__name__}}"}})
        continue
    match = re.search(r'class="version-chip"[^>]*>UI v([^<]+)<', html)
    if not match:
        match = re.search(r"UI v([0-9.]+)", html)
    result["version"] = match.group(1).strip() if match else "missing"
    try:
        with opener.open(status_url, timeout=4) as response:
            status_body = response.read().decode("utf-8", errors="replace")
        status = json.loads(status_body or "{{}}")
        result["web_restart_required"] = bool(status.get("web_restart_required"))
        reason = str(status.get("web_restart_reason") or "").strip()
        if reason:
            result["web_restart_reason"] = reason
    except Exception as exc:
        result["status_error"] = f"{{exc.__class__.__name__}}: {{exc}}"
    results.append(result)

print(json.dumps(results))
PY
"""
    raw = json.loads(capture(ssh_command(host, script)) or "[]")
    versions: dict[str, UiVersionStatus] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        versions[name] = UiVersionStatus(
            version=str(item.get("version") or "missing"),
            status_error=str(item.get("status_error") or ""),
            web_restart_required=bool(item.get("web_restart_required")),
            web_restart_reason=str(item.get("web_restart_reason") or ""),
        )
    return versions


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
    restart_group = parser.add_mutually_exclusive_group()
    restart_group.add_argument(
        "--restart",
        action="store_true",
        help="Restart changed services after sync.",
    )
    restart_group.add_argument(
        "--no-restart",
        action="store_true",
        help="Copy files only. This is the default and is accepted for compatibility.",
    )
    parser.add_argument(
        "--force-restart",
        action="store_true",
        help="Restart even when a console status check reports active work.",
    )
    parser.add_argument(
        "--restart-web-only",
        action="store_true",
        help=(
            "Restart selected console web services only and exit. "
            "Still guarded unless --force-restart is also passed."
        ),
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
        "--enable-route-receipts",
        action="store_true",
        help=(
            "Enable live shadow route-receipt capture env vars for selected "
            "consoles. Use with --restart for a guarded web restart, or "
            "--no-restart to stage only."
        ),
    )
    parser.add_argument(
        "--route-receipt-dir",
        default=DEFAULT_ROUTE_RECEIPT_DIR,
        help="Remote directory for route receipt JSONL sinks.",
    )
    parser.add_argument(
        "--route-receipt-items",
        default=DEFAULT_ROUTE_RECEIPT_ITEMS,
        help="Maximum receipt rows retained per selected console.",
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


def requested_host_filter(requested: list[str] | None) -> list[str] | None:
    if not requested:
        return None
    selected: list[str] = []
    seen: set[str] = set()
    for token in requested:
        if token not in HOSTS:
            return None
        if token in seen:
            continue
        seen.add(token)
        selected.append(token)
    return selected


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
            if status.web_restart_required:
                reason = status.web_restart_reason.strip()
                suffix = (
                    f" (restart staged: {reason})" if reason else " (restart staged)"
                )
            elif status.status_error:
                suffix = f" (status unavailable: {status.status_error})"
            print(f"  - {instance.name}: UI v{status.version}{suffix}")


def restart_selected_web_services(
    selected_by_host: dict[str, list[ConsoleInstance]],
    *,
    force_restart: bool,
    check_health: bool,
) -> None:
    for host_name, instances in selected_by_host.items():
        host = HOSTS[host_name]
        restart_scope_list = list(instances)
        print(f"==> restarting web services on {host_name}", flush=True)
        if not restart_scope_list:
            print("  - no selected consoles", flush=True)
            continue

        if not force_restart:
            block_reasons = restart_block_reasons(host, restart_scope_list)
            if block_reasons:
                for instance in restart_scope_list:
                    reason = block_reasons.get(instance.name)
                    if reason:
                        print(
                            f"  - skip web restart {instance.name}: {reason}",
                            flush=True,
                        )
                restart_scope_list = [
                    instance
                    for instance in restart_scope_list
                    if instance.name not in block_reasons
                ]

        if not restart_scope_list:
            continue

        restart_names = " ".join(instance.name for instance in restart_scope_list)
        print(f"  - serial web restart queue: {restart_names}", flush=True)
        restart_and_health_check_instances(
            host,
            restart_scope_list,
            check_health=check_health,
            web_only=True,
        )


def main() -> int:
    args = parse_args()
    for source in SOURCE_FILES.values():
        if not source.exists():
            raise FileNotFoundError(source)

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

    if args.versions:
        list_versions(selected_by_host)
        return 0

    if args.restart_web_only:
        restart_selected_web_services(
            selected_by_host,
            force_restart=args.force_restart,
            check_health=not args.no_health,
        )
        return 0

    source_sha256 = {key: local_sha256(path) for key, path in SOURCE_FILES.items()}
    prompt_sha256 = {
        name: local_sha256(path)
        for name, path in PROMPT_TEMPLATES.items()
        if path.exists()
    }

    for host_name, selected_instances in selected_by_host.items():
        host = HOSTS[host_name]
        all_host_instances = discovered_by_host[host_name]
        all_by_name = {instance.name: instance for instance in all_host_instances}
        changed_paths: set[str] = set()
        changed_static_paths: set[str] = set()
        changed_instances: dict[str, ConsoleInstance] = {}
        changed_web_instances: dict[str, ConsoleInstance] = {}

        print(f"==> syncing {host_name}", flush=True)

        if host.read_only:
            print(
                "  - read-only discovery host; skipping local template/env writes",
                flush=True,
            )
            continue
        if host.root_managed_local and host_runs_locally(host):
            print(
                "  - root-managed local host; skipping local template/env writes in user sync",
                flush=True,
            )
            continue

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
            if sync_instance_bedrock_profile(host, instance):
                changed_instances[instance.name] = instance
                print(
                    f"  - bedrock profile -> {instance.codex_home}",
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
                print(
                    f"  - runtime settings -> {instance.codex_home}",
                    flush=True,
                )
            if sync_instance_agent_label(host, instance):
                changed_instances[instance.name] = instance
                print(f"  - label -> {instance.env_file}", flush=True)
            if args.enable_route_receipts and sync_instance_route_receipts(
                host,
                instance,
                receipt_dir=args.route_receipt_dir,
                max_items=args.route_receipt_items,
            ):
                changed_web_instances[instance.name] = instance
                print(f"  - route receipts -> {instance.env_file}", flush=True)

        unique_files: dict[str, str] = {}
        for instance in selected_instances:
            for source_key, remote_path in instance.files:
                unique_files.setdefault(remote_path, source_key)

        for remote_path, source_key in unique_files.items():
            print(f"  - {source_key} -> {remote_path}", flush=True)
            if install_file(host, remote_path, source_key, source_sha256):
                changed_paths.add(remote_path)

        soul_identity_changes = sync_soul_identity_tree(host)
        if soul_identity_changes:
            changed_paths.update(soul_identity_changes)
            for instance in selected_instances:
                changed_instances[instance.name] = instance
            print(
                f"  - soul identity -> {REMOTE_SOUL_IDENTITY_ROOT} "
                f"({len(soul_identity_changes)} files changed)",
                flush=True,
            )

        for instance in selected_instances:
            prompt_template = instance.prompt_template
            if (
                not prompt_template
                or not prompt_template.exists()
                or not instance.prompt_file
            ):
                continue
            print(f"  - prompt -> {instance.prompt_file}", flush=True)
            if install_source_path(
                host,
                remote_path=instance.prompt_file,
                source=prompt_template,
                source_sha256=prompt_sha256[str(instance.name)],
            ):
                changed_paths.add(instance.prompt_file)

        if sync_host_home_page(host, all_host_instances):
            changed_static_paths.add(host.host_home_path or "")
            print(f"  - host-home -> {host.host_home_path}", flush=True)

        if (
            not changed_paths
            and not changed_instances
            and not changed_web_instances
            and not changed_static_paths
        ):
            print("  - no template changes detected", flush=True)
            continue

        restart_scope = {
            instance.name: instance for instance in changed_instances.values()
        }
        for instance in changed_web_instances.values():
            restart_scope.setdefault(instance.name, instance)
        for instance in [
            instance
            for instance in all_host_instances
            if any(remote_path in changed_paths for _, remote_path in instance.files)
            or (instance.prompt_file and instance.prompt_file in changed_paths)
        ]:
            restart_scope[instance.name] = all_by_name[instance.name]
        restart_scope_list = list(restart_scope.values())

        if not restart_scope_list:
            continue

        if not args.restart:
            print(
                "  - restart skipped (copy-only; pass --restart for controlled restart)",
                flush=True,
            )
            continue

        full_restart_scope: list[ConsoleInstance] = []
        web_restart_scope: list[ConsoleInstance] = []
        for instance in restart_scope_list:
            if (
                instance.name in changed_web_instances
                and instance.name not in changed_instances
                and not any(
                    remote_path in changed_paths for _, remote_path in instance.files
                )
                and not (instance.prompt_file and instance.prompt_file in changed_paths)
            ):
                scope = "web"
            else:
                scope = restart_scope_for_instance(
                    instance,
                    changed_paths=changed_paths,
                    changed_instances=changed_instances,
                )
            if scope == "web":
                web_restart_scope.append(instance)
            elif scope == "full":
                full_restart_scope.append(instance)

        if not args.force_restart:
            guarded_scope = full_restart_scope + web_restart_scope
            block_reasons = restart_block_reasons(host, guarded_scope)
            if block_reasons:
                for instance in guarded_scope:
                    reason = block_reasons.get(instance.name)
                    if reason:
                        print(
                            f"  - skip restart {instance.name}: {reason}",
                            flush=True,
                        )
                full_restart_scope = [
                    instance
                    for instance in full_restart_scope
                    if instance.name not in block_reasons
                ]
                web_restart_scope = [
                    instance
                    for instance in web_restart_scope
                    if instance.name not in block_reasons
                ]

        if web_restart_scope:
            restart_names = " ".join(instance.name for instance in web_restart_scope)
            print(f"  - serial web restart queue: {restart_names}", flush=True)
            restart_and_health_check_instances(
                host,
                web_restart_scope,
                check_health=not args.no_health,
                web_only=True,
            )

        if full_restart_scope:
            restart_names = " ".join(instance.name for instance in full_restart_scope)
            print(f"  - serial restart queue: {restart_names}", flush=True)
            restart_and_health_check_instances(
                host,
                full_restart_scope,
                check_health=not args.no_health,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
