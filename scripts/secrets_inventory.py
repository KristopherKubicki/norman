#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import grp
import importlib.util
import json
import os
import pwd
import re
import sqlite3
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_KEY_RE = re.compile(
    r"(secret|token|password|passwd|credential|api[_-]?key|private[_-]?key|"
    r"auth|client[_-]?secret|webhook[_-]?secret|account[_-]?sid|access[_-]?key|"
    r"refresh[_-]?token|bearer|cookie|csrf)",
    re.IGNORECASE,
)
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "secrets_inventory.md"
LOCAL_SCAN_PATHS = (
    "/etc/norman/*.env",
    "/home/kristopher/.aws/config",
    "/home/kristopher/.aws/credentials",
    "/home/kristopher/.ssh/authorized_keys",
    "/home/kristopher/.config/norman/secrets/*",
    "/home/kristopher/.config/dohio/bot-heartbeats/*.env",
    "/home/kristopher/.codex/auth.json",
    "/home/kristopher/.codex-work/auth.json",
    "/home/kristopher/.codex-bot-prime/auth.json",
    "/home/kristopher/.codex-norman-ops/auth.json",
    "/home/kristopher/.codex-work/web-token.txt",
    "/home/kristopher/.codex-bot-prime/web-token.txt",
    "/home/kristopher/.codex-norman-ops/web-token.txt",
    "config.yaml",
    "projects/*/.env",
)
REMOTE_HOST_STATIC_ROOTS = {
    "hal": {
        "roots": (
            "/home/kristopher/.aws",
            "/home/kristopher/.codex",
            "/home/kristopher/.codex-work",
            "/home/kristopher/.codex-cp",
            "/home/kristopher/.config/autocamera",
            "/home/kristopher/.config/theseus",
            "/home/kristopher/.config/dohio",
            "/home/kristopher/.config/control_plane",
            "/home/kristopher/.config/cloudagent",
            "/home/kristopher/.config/phoneops",
            "/home/kristopher/.config/phobos-transcribe",
            "/home/kristopher/.config/gcloud",
        ),
    },
    "toy-box": {
        "roots": (
            "/root/.aws",
            "/root/.codex",
            "/root/.config/gcloud",
            "/root/.config/norman/secrets",
            "/home/kristopher/.aws",
            "/home/kristopher/.config/gcloud",
        ),
    },
    "work-special": {
        "roots": (
            "/home/kristopher/.aws",
            "/home/kristopher/.codex",
            "/home/kristopher/.codex-work",
            "/home/kristopher/.config/dohio",
            "/home/kristopher/.config/gcloud",
            "/home/kristopher/.config/norman/secrets",
        ),
    },
    "norman": {
        "roots": (
            "/etc/norman",
            "/home/kristopher/.aws",
            "/home/kristopher/.codex",
            "/home/kristopher/.codex-work",
            "/home/kristopher/.config/dohio",
            "/home/kristopher/.config/gcloud",
            "/home/kristopher/.config/norman/secrets",
        ),
    },
    "networking-host": {
        "roots": (
            "/etc/net-agents",
            "/root/.aws",
            "/root/.codex",
            "/root/.config/gcloud",
            "/root/.config/norman/secrets",
        ),
    },
    "private-host": {
        "roots": (
            "/root/.aws",
            "/root/.config/gcloud",
            "/srv/parkergalebot/state",
        ),
    },
}
REMOTE_SECRET_EXTRA_FILES = (
    "/etc/brlapi.key",
    "/etc/ppp/chap-secrets",
    "/etc/ppp/pap-secrets",
)
REMOTE_SECRET_SCAN_MAX_DEPTH = 4


@dataclass
class FileInventory:
    path: str
    exists: bool
    area: str
    mode: str = ""
    owner: str = ""
    group: str = ""
    secret_keys: list[str] = field(default_factory=list)
    nonsecret_keys: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class TuiEnvInventory:
    host: str
    name: str
    env_file: str
    secret_keys: list[str]
    mode: str = ""
    owner: str = ""
    group: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class RemoteFileInventory:
    host: str
    path: str
    exists: bool
    area: str
    mode: str = ""
    owner: str = ""
    group: str = ""
    secret_keys: list[str] = field(default_factory=list)
    nonsecret_keys: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class KeyAliasCoverage:
    alias: str
    source: str
    source_keys: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    status: str = "missing"
    policy_status: str = "missing"
    notes: list[str] = field(default_factory=list)


def utc_now_label() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY_RE.search(key or ""))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def mode_label(path: Path) -> str:
    try:
        return stat.filemode(path.stat().st_mode)
    except OSError:
        return ""


def owner_group_label(path: Path) -> tuple[str, str]:
    try:
        info = path.stat()
    except OSError:
        return "", ""
    try:
        owner = pwd.getpwuid(info.st_uid).pw_name
    except KeyError:
        owner = str(info.st_uid)
    try:
        group = grp.getgrgid(info.st_gid).gr_name
    except KeyError:
        group = str(info.st_gid)
    return owner, group


def file_has_world_access(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & stat.S_IRWXO)
    except OSError:
        return False


def area_for_path(path: str) -> str:
    if path.startswith("/etc/norman/"):
        return "norman system env"
    if "/.aws/" in path:
        return "aws local profile"
    if "/.ssh/" in path:
        return "ssh local access"
    if "/.config/norman/secrets/" in path:
        return "norman local secret files"
    if "/.config/dohio/bot-heartbeats/" in path:
        return "dohio heartbeat env"
    if "/.codex" in path:
        return "codex home auth"
    if path.endswith("config.yaml"):
        return "norman app config"
    if "/projects/" in path and path.endswith("/.env"):
        return "project env"
    return "other"


def remote_area_for_path(path: str) -> str:
    if path.startswith("/etc/"):
        return "remote system secret file"
    if "/.codex-work/secrets/" in path:
        return "remote codex work secrets"
    if "/.codex-work/share/" in path:
        return "remote codex shared bundle"
    if "/.codex" in path:
        return "remote codex auth"
    if "/.aws/" in path:
        return "remote aws local profile"
    if "/.config/gcloud/" in path:
        return "remote gcloud token store"
    if "/.config/" in path:
        return "remote app config secret"
    return "remote other"


def normalize_key_name(key: str) -> str:
    cleaned = (key or "").strip()
    if cleaned.lower().startswith("export "):
        cleaned = cleaned.split(None, 1)[1].strip()
    return cleaned.strip("'\"")


def parse_key_lines(text: str, *, path: str) -> tuple[list[str], int]:
    keys: list[str] = []
    total = 0
    suffix = Path(path).suffix.lower()
    if suffix == ".json" or path.endswith("auth.json"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            for key in sorted(str(key) for key in payload.keys()):
                total += 1
                if is_secret_key(key):
                    keys.append(key)
        return keys, total - len(keys)

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = normalize_key_name(line.split("=", 1)[0])
        if not key:
            continue
        total += 1
        if is_secret_key(key):
            keys.append(key)
    return sorted(set(keys)), max(0, total - len(set(keys)))


def expand_scan_paths(patterns: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        raw = pattern
        if not raw.startswith("/"):
            raw = str(REPO_ROOT / raw)
        matches = (
            sorted(Path("/").glob(raw.lstrip("/")))
            if any(ch in raw for ch in "*?[")
            else [Path(raw)]
        )
        for path in matches:
            if path not in paths:
                paths.append(path)
    return paths


def inventory_file(path: Path) -> FileInventory:
    display = str(path)
    if str(path).startswith(str(REPO_ROOT) + os.sep):
        display = str(path.relative_to(REPO_ROOT))
    item = FileInventory(
        path=display, exists=path.exists(), area=area_for_path(str(path))
    )
    if not path.exists():
        item.notes.append("missing")
        return item
    item.mode = mode_label(path)
    item.owner, item.group = owner_group_label(path)
    if path.is_dir():
        item.notes.append("directory")
        return item
    keys, nonsecret_count = parse_key_lines(read_text(path), path=str(path))
    item.secret_keys = keys
    item.nonsecret_keys = nonsecret_count
    if item.secret_keys and file_has_world_access(path):
        item.notes.append("world-accessible secret-bearing file")
    return item


def load_sync_module() -> Any | None:
    path = REPO_ROOT / "scripts" / "sync_agent_console_template.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("sync_agent_console_template", path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def remote_tui_inventory() -> list[TuiEnvInventory]:
    sync = load_sync_module()
    if sync is None:
        return []
    by_host, _by_name = sync.discover_all_instances()
    results: list[TuiEnvInventory] = []
    for host_name, instances in by_host.items():
        host = sync.HOSTS[host_name]
        payload = json.dumps(
            [
                {"name": instance.name, "env_file": instance.env_file}
                for instance in instances
            ],
            separators=(",", ":"),
        )
        script = f"""
python3 - <<'PY'
from pathlib import Path
import json
import os
import stat
import pwd
import grp
items = json.loads({payload!r})
results = []
for item in items:
    path = Path(item["env_file"])
    env = {{}}
    try:
        text = path.read_text(encoding="utf-8")
        st = path.stat()
        mode = stat.filemode(st.st_mode)
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        try:
            group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            group = str(st.st_gid)
    except OSError as exc:
        results.append({{"name": item["name"], "env_file": item["env_file"], "error": type(exc).__name__}})
        continue
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            env[key] = True
    results.append({{"name": item["name"], "env_file": item["env_file"], "keys": sorted(env), "mode": mode, "owner": owner, "group": group}})
print(json.dumps(results))
PY
"""
        try:
            raw = sync.capture(sync.ssh_command(host, script))
            host_results = json.loads(raw or "[]")
        except Exception as exc:
            results.append(
                TuiEnvInventory(
                    host=host_name,
                    name="*host*",
                    env_file="",
                    secret_keys=[],
                    notes=[f"remote inventory failed: {type(exc).__name__}"],
                )
            )
            continue
        for item in host_results:
            keys = [key for key in item.get("keys", []) if is_secret_key(key)]
            notes = []
            if item.get("error"):
                notes.append(f"read failed: {item['error']}")
            if item.get("mode", "") and item.get("mode", "")[-3:] != "---" and keys:
                notes.append("world-accessible secret-bearing env")
            results.append(
                TuiEnvInventory(
                    host=host_name,
                    name=str(item.get("name") or ""),
                    env_file=str(item.get("env_file") or ""),
                    secret_keys=keys,
                    mode=str(item.get("mode") or ""),
                    owner=str(item.get("owner") or ""),
                    group=str(item.get("group") or ""),
                    notes=notes,
                )
            )
    return results


def _append_path_root(values: list[str], path: str, *, parent: bool = False) -> None:
    cleaned = str(path or "").strip()
    if not cleaned:
        return
    root = str(Path(cleaned).parent) if parent else cleaned
    if root and root not in values:
        values.append(root)


def remote_secret_scan_specs(
    sync: Any, host_filter: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    host_names = [
        name for name in (host_filter or list(sync.HOSTS)) if name in sync.HOSTS
    ]
    try:
        by_host, _by_name = sync.discover_all_instances(host_names)
    except Exception:
        by_host = {name: [] for name in host_names}

    specs: dict[str, dict[str, Any]] = {}
    for host_name in host_names:
        roots: list[str] = []
        for root in REMOTE_HOST_STATIC_ROOTS.get(host_name, {}).get("roots", ()):
            _append_path_root(roots, str(root))
        for instance in by_host.get(host_name, []):
            _append_path_root(roots, getattr(instance, "env_file", ""), parent=True)
            _append_path_root(roots, getattr(instance, "prompt_file", ""), parent=True)
            _append_path_root(roots, getattr(instance, "codex_home", ""))
        specs[host_name] = {
            "roots": sorted(roots),
            "extra_files": list(REMOTE_SECRET_EXTRA_FILES),
            "max_depth": REMOTE_SECRET_SCAN_MAX_DEPTH,
        }
    return specs


def remote_secret_file_inventory(
    host_filter: list[str] | None = None,
) -> list[RemoteFileInventory]:
    sync = load_sync_module()
    if sync is None:
        return []
    results: list[RemoteFileInventory] = []
    scan_specs = remote_secret_scan_specs(sync, host_filter=host_filter)
    host_names = host_filter or list(scan_specs)
    for host_name in host_names:
        spec = scan_specs.get(host_name)
        host = sync.HOSTS.get(host_name)
        if spec is None or host is None:
            continue
        payload = json.dumps(spec, separators=(",", ":"))
        pattern = SECRET_KEY_RE.pattern
        script = f"""
python3 - <<'PY'
from pathlib import Path
import grp
import json
import os
import pwd
import re
import stat

spec = json.loads({payload!r})
secret_re = re.compile({pattern!r}, re.IGNORECASE)
name_re = re.compile(r"(\\.env$|auth\\.json$|web-token\\.txt$|credentials$|secret|token|\\.key$|\\.pem$)", re.IGNORECASE)
exclude_dirs = {{".git", "node_modules", ".cache", "tmp", ".tmp", "__pycache__"}}


def normalize_key_name(key):
    cleaned = (key or "").strip()
    if cleaned.lower().startswith("export "):
        cleaned = cleaned.split(None, 1)[1].strip()
    return cleaned.strip("'\\\"")


def is_secret_key(key):
    return bool(secret_re.search(key or ""))


def parse_key_lines(text, path):
    keys = []
    total = 0
    p = Path(path)
    if p.suffix.lower() == ".json" or p.name == "auth.json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {{}}
        if isinstance(payload, dict):
            for key in sorted(str(key) for key in payload.keys()):
                total += 1
                if is_secret_key(key) and key not in keys:
                    keys.append(key)
        return sorted(keys), max(0, total - len(keys))

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = normalize_key_name(line.split("=", 1)[0])
        if not key:
            continue
        total += 1
        if is_secret_key(key) and key not in keys:
            keys.append(key)
    return sorted(keys), max(0, total - len(keys))


def owner_group(path):
    st = path.stat()
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return owner, group


paths = []
for raw_root in spec.get("roots", []):
    root = Path(raw_root)
    if not root.exists():
        continue
    if root.is_file():
        paths.append(root)
        continue
    max_depth = int(spec.get("max_depth", 4))
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        try:
            depth = len(current.relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth > max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in exclude_dirs]
        for filename in filenames:
            candidate = current / filename
            if name_re.search(str(candidate)):
                paths.append(candidate)
for raw_path in spec.get("extra_files", []):
    path = Path(raw_path)
    if path.exists():
        paths.append(path)

results = []
for path in sorted(set(paths)):
    item = {{"path": str(path), "exists": path.exists()}}
    try:
        st = path.stat()
        item["mode"] = stat.filemode(st.st_mode)
        item["owner"], item["group"] = owner_group(path)
        if path.is_dir():
            item["notes"] = ["directory"]
            results.append(item)
            continue
        if st.st_size > 1024 * 1024:
            item["notes"] = [f"large file {{st.st_size}} bytes; not parsed"]
            results.append(item)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        item["notes"] = [f"read failed: {{type(exc).__name__}}"]
        results.append(item)
        continue

    keys, nonsecret_count = parse_key_lines(text, str(path))
    item["secret_keys"] = keys
    item["nonsecret_keys"] = nonsecret_count
    if not keys and secret_re.search(path.name):
        item.setdefault("notes", []).append("secret-like filename; no key names parsed")
    if keys and item.get("mode", "")[-3:] != "---":
        item.setdefault("notes", []).append("world-accessible secret-bearing file")
    if keys or item.get("notes"):
        results.append(item)
print(json.dumps(results))
PY
"""
        try:
            raw = sync.capture(sync.ssh_command(host, script))
            host_results = json.loads(raw or "[]")
        except Exception as exc:
            results.append(
                RemoteFileInventory(
                    host=host_name,
                    path="",
                    exists=False,
                    area="remote host scan",
                    notes=[f"remote host file inventory failed: {type(exc).__name__}"],
                )
            )
            continue
        for item in host_results:
            path = str(item.get("path") or "")
            results.append(
                RemoteFileInventory(
                    host=host_name,
                    path=path,
                    exists=bool(item.get("exists", True)),
                    area=remote_area_for_path(path),
                    mode=str(item.get("mode") or ""),
                    owner=str(item.get("owner") or ""),
                    group=str(item.get("group") or ""),
                    secret_keys=list(item.get("secret_keys", []) or []),
                    nonsecret_keys=int(item.get("nonsecret_keys") or 0),
                    notes=list(item.get("notes", []) or []),
                )
            )
    return results


def sqlite_tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        with sqlite3.connect(path) as db:
            rows = db.execute(
                "select name from sqlite_master where type='table'"
            ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]) for row in rows}


def norman_keys_inventory(db_path: Path) -> dict[str, Any]:
    tables = sqlite_tables(db_path)
    required = {"secret_providers", "secret_aliases", "secret_policies"}
    if not required.issubset(tables):
        return {"db_path": str(db_path), "available": False}
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        providers = [
            dict(row)
            for row in db.execute(
                "select name, kind, enabled from secret_providers order by name"
            )
        ]
        aliases = [
            dict(row)
            for row in db.execute(
                """
                select a.name, p.kind as provider_kind, a.lane, a.enabled,
                       a.default_ttl_seconds, a.allow_raw_reveal
                from secret_aliases a
                join secret_providers p on p.id = a.provider_id
                order by a.name
                """
            )
        ]
        policies = [
            dict(row)
            for row in db.execute(
                """
                select name, requester_type, requester_id, lane, secret_prefix,
                       allowed_modes, max_ttl_seconds, approval_required,
                       raw_reveal_allowed, enabled
                from secret_policies
                order by name
                """
            )
        ]
    return {
        "db_path": str(db_path),
        "available": True,
        "providers": providers,
        "aliases": aliases,
        "policies": policies,
    }


TUI_SECRET_ALIAS_BY_KEY = {
    "NORMAN_CODEX_BROWSER_AUTH_CLIENTS": "tui.{name}.browser-auth-clients",
    "NORMAN_CODEX_WEB_TOKEN": "tui.{name}.web-token",
    "NORMAN_CODEX_BBS_TOKEN": "bbs.{name}.actor-token",
    "NORMAN_CODEX_LONG_JOB_NOTIFY_TOKEN": "notify.long-job.fleet-token",
    "NORMAN_CODEX_LONG_JOB_NOTIFY_RECEIVER_TOKEN": "notify.long-job.receiver-token",
    "HOUSEBOT_CODEX_BROWSER_AUTH_CLIENTS": "tui.{name}.browser-auth-clients",
    "HOUSEBOT_CODEX_WEB_TOKEN": "tui.{name}.web-token",
    "HOUSEBOT_CODEX_BBS_TOKEN": "bbs.{name}.actor-token",
    "HOUSEBOT_CODEX_LONG_JOB_NOTIFY_TOKEN": "notify.long-job.fleet-token",
    "HOUSEBOT_CODEX_LONG_JOB_NOTIFY_RECEIVER_TOKEN": "notify.long-job.receiver-token",
    "SWITCHBOARD_TOKEN": "bbs.{name}.actor-token",
}

CANONICAL_TUI_SECRET_NAMES = {
    "networking": "netops",
    "networking-host": "netops",
    "camera-studio": "autocamera",
    "studio": "autocamera",
}

LOCAL_SECRET_ALIAS_BY_PATH_KEY = {
    ("norman system env", "SWITCHBOARD_TOKEN"): "bbs.switchboard.post-token",
    ("project env", "COLLECTOR_TOKEN"): "service.evergreen-sms-bridge.collector-token",
}


def canonical_tui_secret_name(name: str) -> str:
    cleaned = (name or "").strip()
    return CANONICAL_TUI_SECRET_NAMES.get(cleaned, cleaned)


def slug_part(value: str) -> str:
    lowered = (value or "").strip().lower().lstrip(".")
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", lowered).strip("-")
    return cleaned or "item"


def remote_switchboard_alias(path: str) -> str | None:
    name = Path(path).name
    if name not in {"switchboard.env", "switchboard-bbs.env"}:
        return None
    actor = Path(path).parent.name
    if actor.startswith(".codex-"):
        actor = actor.removeprefix(".codex-")
    actor = canonical_tui_secret_name(actor)
    if not actor:
        return None
    return f"bbs.{actor}.post-token"


def remote_file_alias(host: str, path: str) -> str | None:
    path_obj = Path(path)
    if path_obj.name == "codex-web.env":
        return None
    switchboard_alias = remote_switchboard_alias(path)
    if switchboard_alias:
        return switchboard_alias
    raw = path
    prefixes = (
        ("/home/kristopher/.", ""),
        ("/home/kristopher/", "home/"),
        ("/etc/", "etc/"),
    )
    for prefix, replacement in prefixes:
        if raw.startswith(prefix):
            raw = replacement + raw[len(prefix) :]
            break
    parts = [slug_part(part) for part in Path(raw).parts if part not in {"/", ""}]
    if not parts:
        return None
    return ".".join(["host", slug_part(host), *parts])


def _append_unique(values: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _matching_policy_status(alias: str, policies: list[dict[str, Any]]) -> str:
    enabled_matches = []
    disabled_matches = []
    for policy in policies:
        prefix = str(policy.get("secret_prefix") or "").strip()
        if not prefix or not alias.startswith(prefix):
            continue
        if policy.get("enabled"):
            enabled_matches.append(policy)
        else:
            disabled_matches.append(policy)
    if enabled_matches:
        return "covered"
    if disabled_matches:
        return "disabled"
    return "missing"


def build_key_alias_coverage(
    *,
    files: list[FileInventory],
    tuis: list[TuiEnvInventory],
    remote_files: list[RemoteFileInventory] | None = None,
    keys_db: dict[str, Any],
) -> list[KeyAliasCoverage]:
    aliases = keys_db.get("aliases") or []
    policies = keys_db.get("policies") or []
    alias_enabled = {
        str(item.get("name") or ""): bool(item.get("enabled")) for item in aliases
    }
    coverage_by_alias: dict[str, KeyAliasCoverage] = {}

    def upsert(
        alias: str,
        *,
        source: str,
        source_key: str,
        consumer: str,
        location: str,
        note: str = "",
    ) -> None:
        item = coverage_by_alias.get(alias)
        if item is None:
            if alias in alias_enabled:
                status = "covered" if alias_enabled[alias] else "disabled"
            else:
                status = "missing"
            item = KeyAliasCoverage(
                alias=alias,
                source=source,
                status=status,
                policy_status=_matching_policy_status(alias, policies),
            )
            coverage_by_alias[alias] = item
        _append_unique(item.source_keys, source_key)
        _append_unique(item.consumers, consumer)
        _append_unique(item.locations, location)
        if note:
            _append_unique(item.notes, note)

    for tui in tuis:
        raw_name = tui.name.strip()
        name = canonical_tui_secret_name(raw_name)
        if not name:
            continue
        for key in tui.secret_keys:
            template = TUI_SECRET_ALIAS_BY_KEY.get(key)
            if not template:
                continue
            alias = template.format(name=name)
            note = ""
            if raw_name and raw_name != name:
                note = (
                    f"{raw_name} maps to canonical actor {name}; verify per-env "
                    "values before enabling this alias"
                )
            upsert(
                alias,
                source="tui-env",
                source_key=key,
                consumer=f"{tui.host}/{raw_name}",
                location=tui.env_file,
                note=note,
            )

    for file_item in files:
        for key in file_item.secret_keys:
            alias = LOCAL_SECRET_ALIAS_BY_PATH_KEY.get((file_item.area, key))
            if not alias:
                continue
            upsert(
                alias,
                source=file_item.area,
                source_key=key,
                consumer=file_item.area,
                location=file_item.path,
            )

    for file_item in remote_files or []:
        if not file_item.secret_keys and not file_item.notes:
            continue
        alias = remote_file_alias(file_item.host, file_item.path)
        if not alias:
            continue
        source_keys = file_item.secret_keys or ["<secret-like-file>"]
        note = "; ".join(file_item.notes)
        for key in source_keys:
            upsert(
                alias,
                source="remote-host-file",
                source_key=key,
                consumer=file_item.host,
                location=file_item.path,
                note=note,
            )

    return sorted(coverage_by_alias.values(), key=lambda item: item.alias)


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(value: Any) -> str:
        text = str(value if value is not None else "")
        return text.replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(clean(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(clean(value) for value in row) + " |")
    return "\n".join(lines)


def render_report(
    *,
    files: list[FileInventory],
    tuis: list[TuiEnvInventory],
    remote_files: list[RemoteFileInventory] | None = None,
    keys_db: dict[str, Any],
    key_alias_coverage: list[KeyAliasCoverage] | None = None,
) -> str:
    secret_files = [item for item in files if item.secret_keys or item.notes]
    remote_secret_files = [
        item for item in (remote_files or []) if item.secret_keys or item.notes
    ]
    secret_key_count = sum(len(item.secret_keys) for item in files)
    tui_secret_key_count = sum(len(item.secret_keys) for item in tuis)
    remote_secret_key_count = sum(len(item.secret_keys) for item in remote_files or [])
    keys_aliases = keys_db.get("aliases") or []
    keys_policies = keys_db.get("policies") or []
    coverage = key_alias_coverage or build_key_alias_coverage(
        files=files, tuis=tuis, remote_files=remote_files, keys_db=keys_db
    )
    missing_aliases = [item for item in coverage if item.status == "missing"]
    missing_policies = [item for item in coverage if item.policy_status == "missing"]
    disabled_aliases = [item for item in coverage if item.status == "disabled"]
    disabled_policies = [item for item in coverage if item.policy_status == "disabled"]

    parts = [
        "# Secrets Inventory",
        "",
        f"Generated: {utc_now_label()}",
        "",
        "This report intentionally records secret locations, key names, consumers, and policy shape only. It does not include secret values.",
        "",
        "## Summary",
        "",
        markdown_table(
            ["Area", "Count"],
            [
                ["Local files with secret-like keys or notes", len(secret_files)],
                ["Local secret-like key names", secret_key_count],
                ["Discovered TUI env files", len(tuis)],
                ["TUI secret-like key names", tui_secret_key_count],
                [
                    "Remote host files with secret-like keys or notes",
                    len(remote_secret_files),
                ],
                ["Remote host secret-like key names", remote_secret_key_count],
                ["Norman Keys aliases", len(keys_aliases)],
                ["Norman Keys policies", len(keys_policies)],
                ["Expected key aliases from inventory", len(coverage)],
                ["Missing key aliases", len(missing_aliases)],
                ["Disabled key aliases", len(disabled_aliases)],
                ["Missing key policies", len(missing_policies)],
                ["Expected aliases with disabled policies", len(disabled_policies)],
            ],
        ),
        "",
        "## Local Files",
        "",
        markdown_table(
            ["Area", "Path", "Mode", "Owner", "Keys", "Notes"],
            [
                [
                    item.area,
                    item.path,
                    item.mode,
                    f"{item.owner}:{item.group}" if item.owner or item.group else "",
                    ", ".join(item.secret_keys) if item.secret_keys else "-",
                    ", ".join(item.notes) if item.notes else "",
                ]
                for item in secret_files
            ],
        ),
        "",
        "## Remote Host Secret Files",
        "",
        markdown_table(
            ["Host", "Area", "Path", "Mode", "Owner", "Keys", "Notes"],
            [
                [
                    item.host,
                    item.area,
                    item.path,
                    item.mode,
                    f"{item.owner}:{item.group}" if item.owner or item.group else "",
                    ", ".join(item.secret_keys) if item.secret_keys else "-",
                    ", ".join(item.notes) if item.notes else "",
                ]
                for item in remote_secret_files
            ],
        ),
        "",
        "## TUI Env Files",
        "",
        markdown_table(
            ["Host", "TUI", "Env File", "Mode", "Owner", "Secret-Like Keys", "Notes"],
            [
                [
                    item.host,
                    item.name,
                    item.env_file,
                    item.mode,
                    f"{item.owner}:{item.group}" if item.owner or item.group else "",
                    ", ".join(item.secret_keys) if item.secret_keys else "-",
                    ", ".join(item.notes) if item.notes else "",
                ]
                for item in tuis
            ],
        ),
        "",
        "## Norman Keys",
        "",
    ]
    if not keys_db.get("available"):
        parts.append(
            f"Norman Keys tables were not found in `{keys_db.get('db_path')}`."
        )
    else:
        parts.extend(
            [
                "### Providers",
                "",
                markdown_table(
                    ["Name", "Kind", "Enabled"],
                    [
                        [item.get("name"), item.get("kind"), item.get("enabled")]
                        for item in keys_db.get("providers", [])
                    ],
                ),
                "",
                "### Aliases",
                "",
                markdown_table(
                    [
                        "Alias",
                        "Provider",
                        "Lane",
                        "Enabled",
                        "TTL",
                        "Raw Reveal",
                    ],
                    [
                        [
                            item.get("name"),
                            item.get("provider_kind"),
                            item.get("lane"),
                            item.get("enabled"),
                            item.get("default_ttl_seconds"),
                            item.get("allow_raw_reveal"),
                        ]
                        for item in keys_db.get("aliases", [])
                    ],
                ),
                "",
                "### Policies",
                "",
                markdown_table(
                    [
                        "Policy",
                        "Requester",
                        "Lane",
                        "Prefix",
                        "Modes",
                        "Max TTL",
                        "Approval",
                        "Raw Reveal",
                        "Enabled",
                    ],
                    [
                        [
                            item.get("name"),
                            f"{item.get('requester_type')}:{item.get('requester_id') or '*'}",
                            item.get("lane") or "*",
                            item.get("secret_prefix"),
                            item.get("allowed_modes"),
                            item.get("max_ttl_seconds"),
                            item.get("approval_required"),
                            item.get("raw_reveal_allowed"),
                            item.get("enabled"),
                        ]
                        for item in keys_db.get("policies", [])
                    ],
                ),
            ]
        )

    parts.extend(
        [
            "",
            "## Norman Keys Coverage",
            "",
            "Expected aliases are derived from secret-like keys found in env/config locations. This is a no-values migration backlog, not proof that values should be copied directly.",
            "",
            markdown_table(
                [
                    "Alias",
                    "Alias Status",
                    "Policy Status",
                    "Source",
                    "Keys",
                    "Consumers",
                    "Locations",
                    "Notes",
                ],
                [
                    [
                        item.alias,
                        item.status,
                        item.policy_status,
                        item.source,
                        ", ".join(item.source_keys),
                        ", ".join(item.consumers),
                        ", ".join(item.locations),
                        ", ".join(item.notes),
                    ]
                    for item in coverage
                ],
            ),
        ]
    )

    parts.extend(
        [
            "",
            "## Risk Notes",
            "",
            "- Root-managed TUI env files currently carry web, BBS, and long-job notification tokens. That is functional, but it spreads bearer credentials across the estate.",
            "- Codex auth files and web-token files are operational secrets. They should remain local, permission-restricted, and excluded from agent-visible summaries.",
            "- Norman Keys has a useful lease/policy model, but the inventory needs migration coverage so raw env secrets become aliases or managed file references.",
            "- Generated reports must stay no-values. Use this as an index, not as a vault.",
            "",
            "## Recommended Next Actions",
            "",
            "1. Move high-blast-radius values into Norman Keys aliases or an external vault, starting with shared TUI/BBS/notification tokens.",
            "2. Add rotation metadata to each alias: owner, consumers, created date, last rotated, next rotation, and emergency revoke steps.",
            "3. Add a CI secret scanner for repo changes and a local scanner for root env files before sync.",
            "4. Convert raw agent access to short-lived leases where possible; leave direct env secrets only for bootstrap paths.",
        ]
    )
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a no-values secrets inventory.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--no-remote", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    files = [inventory_file(path) for path in expand_scan_paths(LOCAL_SCAN_PATHS)]
    tuis = [] if args.no_remote else remote_tui_inventory()
    remote_files = [] if args.no_remote else remote_secret_file_inventory()
    keys_db = norman_keys_inventory(REPO_ROOT / "db" / "norman.db")
    key_alias_coverage = build_key_alias_coverage(
        files=files, tuis=tuis, remote_files=remote_files, keys_db=keys_db
    )
    if args.as_json:
        payload = {
            "generated_at": utc_now_label(),
            "files": [item.__dict__ for item in files],
            "tuis": [item.__dict__ for item in tuis],
            "remote_files": [item.__dict__ for item in remote_files],
            "norman_keys": keys_db,
            "key_alias_coverage": [item.__dict__ for item in key_alias_coverage],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    report = render_report(
        files=files,
        tuis=tuis,
        remote_files=remote_files,
        keys_db=keys_db,
        key_alias_coverage=key_alias_coverage,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
