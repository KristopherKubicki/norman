#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


TRACKED_FILES = ("auth.json", "config.toml", "version.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_home(path: Path) -> str:
    name = path.name.lower()
    if name == ".codex-work" or name.endswith("-work"):
        return "company"
    if name == ".codex":
        return "personal"
    return "unassigned"


def read_home_record(path: Path) -> dict:
    files: dict[str, dict[str, object]] = {}
    for name in TRACKED_FILES:
        target = path / name
        if not target.is_file():
            files[name] = {"present": False, "sha256": "", "size": 0}
            continue
        files[name] = {
            "present": True,
            "sha256": sha256_file(target),
            "size": target.stat().st_size,
        }
    auth_fingerprint = files["auth.json"]["sha256"] or files["config.toml"]["sha256"]
    return {
        "path": str(path),
        "label": classify_home(path),
        "auth_fingerprint": auth_fingerprint,
        "files": files,
    }


def discover_homes(explicit: list[str]) -> list[dict]:
    if explicit:
        homes = [Path(item).expanduser() for item in explicit]
    else:
        homes = sorted(
            candidate for candidate in Path.home().glob(".codex*") if candidate.is_dir()
        )
    return [read_home_record(path) for path in homes]


def classify_runtime_scope(text: str) -> str:
    lowered = text.lower()
    work_markers = (
        "work-special",
        "earlybird",
        "infra",
        "control-plane",
        "market-sizing",
        "tmi-dashboards",
        "gold-book",
        "keystone",
        "compere",
        "surveyor",
        "platinum",
    )
    if any(marker in lowered for marker in work_markers):
        return "work"
    if "norman" in lowered:
        return "norman"
    return "other"


def read_cmdline(proc_dir: Path) -> str:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except OSError:
        return ""
    return " ".join(
        part for part in raw.decode("utf-8", errors="ignore").split("\0") if part
    )


def read_environ(proc_dir: Path) -> dict[str, str]:
    try:
        raw = (proc_dir / "environ").read_bytes()
    except OSError:
        return {}
    env: dict[str, str] = {}
    for part in raw.split(b"\0"):
        if not part or b"=" not in part:
            continue
        key, value = part.split(b"=", 1)
        env[key.decode("utf-8", errors="ignore")] = value.decode(
            "utf-8", errors="ignore"
        )
    return env


def discover_runtime_processes(home_index: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        env = read_environ(entry)
        cmd = read_cmdline(entry)
        codex_home = (
            env.get("NORMAN_CODEX_HOME")
            or env.get("HOUSEBOT_CODEX_HOME")
            or env.get("CODEX_HOME")
            or ""
        )
        service_name = (
            env.get("NORMAN_CODEX_SERVICE_NAME")
            or env.get("HOUSEBOT_CODEX_SERVICE_NAME")
            or ""
        )
        agent_name = (
            env.get("NORMAN_CODEX_AGENT_NAME")
            or env.get("HOUSEBOT_CODEX_AGENT_NAME")
            or ""
        )
        if not codex_home and not service_name and "codex" not in cmd:
            continue
        home_record = home_index.get(codex_home)
        match_fingerprint = home_record["auth_fingerprint"] if home_record else ""
        scope_source = " ".join(filter(None, [service_name, agent_name, cmd]))
        rows.append(
            {
                "pid": int(entry.name),
                "service": service_name,
                "agent": agent_name,
                "codex_home": codex_home,
                "home_label": home_record["label"] if home_record else "external",
                "auth_fingerprint": match_fingerprint,
                "scope": classify_runtime_scope(scope_source),
                "cmd": cmd,
            }
        )
    rows.sort(key=lambda item: str(item["service"] or item["agent"] or item["pid"]))
    return rows


def summarize(home_records: list[dict], runtime_records: list[dict]) -> dict:
    company_fingerprints = {
        record["auth_fingerprint"]
        for record in home_records
        if record["label"] == "company" and record["auth_fingerprint"]
    }
    non_company_matching_company = [
        record
        for record in home_records
        if record["label"] != "company"
        and record["auth_fingerprint"]
        and record["auth_fingerprint"] in company_fingerprints
    ]
    non_work_company = [
        record
        for record in runtime_records
        if record["scope"] != "work"
        and record["auth_fingerprint"]
        and record["auth_fingerprint"] in company_fingerprints
    ]
    return {
        "company_auth_fingerprints": sorted(company_fingerprints),
        "non_company_homes_matching_company_auth": non_company_matching_company,
        "non_work_using_company_auth": non_work_company,
    }


def print_human_report(home_records: list[dict], runtime_records: list[dict]) -> None:
    summary = summarize(home_records, runtime_records)
    print("Codex homes")
    for record in home_records:
        auth_hash = record["files"]["auth.json"]["sha256"]
        config_hash = record["files"]["config.toml"]["sha256"]
        print(
            f"- {record['path']} [{record['label']}] "
            f"auth={'present' if auth_hash else 'missing'} "
            f"config={'present' if config_hash else 'missing'}"
        )
        if auth_hash:
            print(f"  auth sha256: {auth_hash}")
        if config_hash:
            print(f"  config sha256: {config_hash}")
    print()
    print("Runtime processes")
    if not runtime_records:
        print("- none detected")
    for record in runtime_records:
        identity = record["service"] or record["agent"] or "unknown"
        print(
            f"- pid={record['pid']} scope={record['scope']} "
            f"service={identity} home={record['codex_home'] or '(unset)'} "
            f"label={record['home_label']}"
        )
    print()
    print("Findings")
    if not summary["non_company_homes_matching_company_auth"]:
        print(
            "- No non-company Codex homes were found sharing the company auth fingerprint."
        )
    else:
        print("- Non-company Codex homes matching the company auth fingerprint:")
        for record in summary["non_company_homes_matching_company_auth"]:
            print(f"  - {record['path']} [{record['label']}]")
    if not summary["non_work_using_company_auth"]:
        print("- No non-work processes were found using the company auth fingerprint.")
    else:
        print("- Non-work processes using the company auth fingerprint:")
        for record in summary["non_work_using_company_auth"]:
            identity = record["service"] or record["agent"] or "unknown"
            print(
                f"  - pid={record['pid']} scope={record['scope']} "
                f"service={identity} home={record['codex_home']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit local Codex auth homes and which live processes use them."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of text."
    )
    parser.add_argument(
        "--home",
        action="append",
        default=[],
        help="Explicit CODEX_HOME path to include. Can be passed more than once.",
    )
    args = parser.parse_args()

    home_records = discover_homes(args.home)
    home_index = {record["path"]: record for record in home_records}
    runtime_records = discover_runtime_processes(home_index)
    payload = {
        "homes": home_records,
        "runtime_processes": runtime_records,
        "summary": summarize(home_records, runtime_records),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print_human_report(home_records, runtime_records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
