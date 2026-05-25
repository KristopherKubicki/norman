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


SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_ROOT = SCRIPT_DIR / "agent_console_template"
PROMPT_TEMPLATE_ROOT = TEMPLATE_ROOT / "prompts"
SOURCE_FILES = {
    "web": TEMPLATE_ROOT / "agent_console_web.py",
    "launch": TEMPLATE_ROOT / "agent_console_launch.sh",
    "supervisor": TEMPLATE_ROOT / "agent_console_supervisor.sh",
}
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
    # These Toy Box media lanes never materialized as durable operators.
    # Keep their files/envs harmlessly in place, but do not promote or sync them
    # as active Norman bot-console instances.
    "studio",
    "tv",
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
    "acast": "acast.work.example.test",
    "autocamera": "autocamera.home.arpa",
    "castle": "castle.home.arpa",
    "cloudagent": "cloudagent.home.arpa",
    "compere": "keystone.work.example.test",
    "control-plane": "cp.work.example.test",
    "diamond-roc": "diamond-roc.home.arpa",
    "dj": "dj.home.arpa",
    "earlybird": "earlybird.work.example.test",
    "glimpser": "eyebat.home.arpa",
    "gold-book": "goldbook.work.example.test",
    "housebot": "housebot.home.arpa",
    "infra": "infra.work.example.test",
    "leadership-kpis": "kpis.work.example.test",
    "market-sizing": "mc.work.example.test",
    "mls": "mls.work.example.test",
    "networking": "networking.home.arpa",
    "panelbot": "panelbot.work.example.test",
    "parkergale": "pefb.home.arpa",
    "phone-ops": "phone.home.arpa",
    "platinum-standard": "platinum.work.example.test",
    "scout": "scout.work.example.test",
    "studio": "studio.home.arpa",
    "switchboard": "switchboard.home.arpa",
    "theseus": "theseus.home.arpa",
    "tmi-dashboards": "dashboards.work.example.test",
    "tv": "tv.home.arpa",
    "uplink": "uplink.home.arpa",
    "usbhome": "usbhome.home.arpa",
    "uscache": "uscache.home.arpa",
}
INSTANCE_CONSOLE_URL_OVERRIDES: dict[str, str] = {
    "phone-ops": "https://phone.home.arpa/",
}
PROMOTED_FOLD_INSTANCES: tuple[tuple[str, str, str, int], ...] = (
    ("phone-ops", "Phone Ops", "Personal", 170),
)
DEFAULT_LAUNCHERS = {
    "housebot": "/opt/housebot/scripts/housebot_codex_launch.sh",
}
SSH_CONNECT_TIMEOUT_SECONDS = os.environ.get("NORMAN_SYNC_SSH_CONNECT_TIMEOUT", "8")


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
        return (
            ("web", self.web_path),
            ("launch", self.launch_path),
            ("supervisor", self.supervisor_path),
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


HOSTS: dict[str, DiscoveryHost] = {
    "hal": DiscoveryHost(
        name="hal",
        ssh_target="",
        use_sudo=False,
        env_globs=("/etc/*/codex-web.env",),
        public_host="hal.home.arpa",
        lan_host="192.168.0.137",
        alias_hosts=("hal.tail00000.ts.net",),
        host_home_path=None,
        local=True,
        read_only=False,
        root_managed_local=True,
    ),
    "toy-box": DiscoveryHost(
        name="toy-box",
        ssh_target="root@toy-box.tail00000.ts.net",
        use_sudo=False,
        env_globs=("/etc/*/codex-web.env",),
        public_host="toy-box.home.arpa",
        lan_host="192.168.0.146",
        alias_hosts=("toy-box.tail00000.ts.net",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "work-special": DiscoveryHost(
        name="work-special",
        ssh_target="root@192.168.0.147",
        use_sudo=False,
        env_globs=("/etc/*/codex-web.env",),
        public_host="work-special.home.arpa",
        lan_host="192.168.0.147",
        alias_hosts=("work-special.tail00000.ts.net",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "norman": DiscoveryHost(
        name="norman",
        ssh_target="root@192.168.0.241",
        use_sudo=False,
        env_globs=("/etc/norman/codex-web.env",),
        public_host="norman.home.arpa",
        lan_host="192.168.0.241",
        alias_hosts=("norman.tail00000.ts.net",),
        host_home_path="/var/www/host-home/index.html",
        local=True,
    ),
    "networking-host": DiscoveryHost(
        name="networking-host",
        ssh_target="debian@192.168.0.242",
        use_sudo=True,
        env_globs=("/etc/net-agents/*.env",),
        public_host="networking-host.home.arpa",
        lan_host="192.168.0.242",
        alias_hosts=("networking.tail00000.ts.net",),
        host_home_path="/var/www/host-home/index.html",
    ),
    "private-host": DiscoveryHost(
        name="private-host",
        ssh_target="root@192.168.0.148",
        use_sudo=False,
        env_globs=("/etc/*/codex-web.env",),
        public_host="private.home.example.test",
        lan_host="192.168.0.148",
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
    "192.168.0.136",  # pixel10
    "192.168.0.137",  # hal desktop
    "192.168.0.140",  # plasma-mobile
    "192.168.0.144",  # lollie's desktop
)

TRUSTED_CONSOLE_PROXIES = (
    "127.0.0.1",
    "::1",
    "192.168.0.241",  # norman proxy/front door
)

AUTH_BRIDGE_CLIENTS = (
    "127.0.0.1",
    "::1",
    "192.168.0.136",  # pixel10
    "192.168.0.137",  # hal desktop
    "192.168.0.140",  # plasma-mobile
)

TAILNET_CONSOLE_CLIENTS = (
    "100.64.0.0/10",
    "fd7a:115c:a1e0::/48",
)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def capture(cmd: list[str]) -> str:
    completed = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return completed.stdout


def _normalize_host_token(value: str) -> tuple[str, ...]:
    raw = value.strip().lower()
    if not raw:
        return ()
    tokens = {raw}
    if "." in raw:
        tokens.add(raw.split(".", 1)[0])
    return tuple(tokens)


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
        launch_path = (env.get("HOUSEBOT_CODEX_LAUNCHER") or "").strip()
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
                "agent_label": (env.get("HOUSEBOT_CODEX_AGENT_NAME") or name).strip(),
                "web_port": (env.get("HOUSEBOT_CODEX_WEB_PORT") or "").strip(),
                "web_token": (env.get("HOUSEBOT_CODEX_WEB_TOKEN") or "").strip(),
                "prompt_file": (env.get("HOUSEBOT_CODEX_PROMPT_FILE") or "").strip(),
                "codex_home": (
                    env.get("HOUSEBOT_CODEX_HOME")
                    or env.get("CODEX_HOME")
                    or ""
                ).strip(),
                "restart_units": [
                    (env.get("HOUSEBOT_CODEX_SERVICE_NAME") or f"{{name}}-codex.service").strip(),
                    (env.get("HOUSEBOT_CODEX_WEB_SERVICE_NAME") or f"{{name}}-codex-web.service").strip(),
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


def discover_all_instances() -> (
    tuple[dict[str, list[ConsoleInstance]], dict[str, ConsoleInstance]]
):
    by_host: dict[str, list[ConsoleInstance]] = {}
    by_name: dict[str, ConsoleInstance] = {}
    for host_name, host in HOSTS.items():
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
    if public_host.endswith(".work.example.test") or public_host != host.public_host:
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
        scheme = "https" if clean.endswith(".work.example.test") else "http"
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


def sync_instance_origin_settings(
    host: DiscoveryHost, instance: ConsoleInstance
) -> bool:
    aliases = []
    canonical_host = instance_public_host(instance)
    for value in (canonical_host, host.public_host, host.lan_host, *host.alias_hosts):
        clean = (value or "").strip()
        if clean and clean not in aliases:
            aliases.append(clean)
    updates = {
        "HOUSEBOT_CODEX_CANONICAL_HOST": canonical_host,
        "HOUSEBOT_CODEX_LOCAL_HOST_ALIASES": ",".join(aliases),
        "HOUSEBOT_CODEX_TRUSTED_CLIENTS": ",".join(TRUSTED_CONSOLE_CLIENTS),
        "HOUSEBOT_CODEX_TRUSTED_PROXIES": ",".join(TRUSTED_CONSOLE_PROXIES),
        "HOUSEBOT_CODEX_BROWSER_AUTH_CLIENTS": ",".join(AUTH_BRIDGE_CLIENTS),
        "HOUSEBOT_CODEX_TAILNET_CLIENTS": ",".join(TAILNET_CONSOLE_CLIENTS),
        "HOUSEBOT_CODEX_AGENT_GROUP": HOST_GROUP_LABELS.get(host.name, "Agents"),
    }
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


def health_check_instances(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> None:
    for instance in instances:
        env_path = shlex.quote(instance.env_file)
        script = " && ".join(
            [
                f'PORT=$(grep -E "^HOUSEBOT_CODEX_WEB_PORT=" {env_path} | tail -n1 | cut -d= -f2-)',
                f'TOKEN=$(grep -E "^HOUSEBOT_CODEX_WEB_TOKEN=" {env_path} | tail -n1 | cut -d= -f2-)',
                'test -n "$PORT"',
                'curl -fsS "http://127.0.0.1:${PORT}/healthz?token=${TOKEN}" >/dev/null',
            ]
        )
        run(ssh_command(host, script))


def ui_versions(
    host: DiscoveryHost, instances: list[ConsoleInstance]
) -> dict[str, str]:
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


results = []
for item in instances:
    name = item["name"]
    env = parse_env(item["env_file"])
    if env is None:
        results.append({{"name": name, "version": "missing-env"}})
        continue
    port = (env.get("HOUSEBOT_CODEX_WEB_PORT") or "").strip()
    token = (env.get("HOUSEBOT_CODEX_WEB_TOKEN") or "").strip()
    if not port:
        results.append({{"name": name, "version": "missing-port"}})
        continue
    url = f"http://127.0.0.1:{{port}}/?token={{urllib.parse.quote(token)}}"
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        with opener.open(url, timeout=8) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        results.append({{"name": name, "version": f"error: {{exc.__class__.__name__}}"}})
        continue
    match = re.search(r'class="version-chip"[^>]*>UI v([^<]+)<', html)
    if not match:
        match = re.search(r"UI v([0-9.]+)", html)
    results.append({{"name": name, "version": match.group(1).strip() if match else "missing"}})

print(json.dumps(results))
PY
"""
    raw = json.loads(capture(ssh_command(host, script)) or "[]")
    return {str(item["name"]): str(item["version"]) for item in raw}


def parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


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
            print(f"  - {instance.name}: UI v{versions.get(instance.name, 'unknown')}")


def main() -> int:
    args = parse_args()
    for source in SOURCE_FILES.values():
        if not source.exists():
            raise FileNotFoundError(source)

    discovered_by_host, discovered_by_name = discover_all_instances()

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

        print(f"==> syncing {host_name}", flush=True)

        if host.read_only:
            print(
                "  - read-only discovery host; skipping local template/env writes",
                flush=True,
            )
            continue
        if host.root_managed_local:
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
            if sync_instance_agent_label(host, instance):
                changed_instances[instance.name] = instance
                print(f"  - label -> {instance.env_file}", flush=True)

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
        restart_instances(host, restart_scope_list)

        if args.no_health:
            continue
        print("  - health checks", flush=True)
        health_check_instances(host, restart_scope_list)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
