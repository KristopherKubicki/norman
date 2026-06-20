#!/usr/bin/env python3
"""Seed disabled Norman Keys catalog rows from the no-values inventory."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "norman.db"
DEFAULT_PROVIDER_NAME = "netops-file-secrets"
DEFAULT_PROVIDER_BASE_DIR = "/home/kristopher/.config/norman/secrets"
CATALOG_SCRIPT = Path(__file__).relative_to(REPO_ROOT)
BACKEND_REF_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(frozen=True)
class AliasSeed:
    name: str
    lane: str
    backend_ref: str
    default_ttl_seconds: int = 3600
    allow_raw_reveal: bool = False
    enabled: bool = False
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicySeed:
    name: str
    requester_type: str
    requester_id: str | None
    lane: str
    secret_prefix: str
    allowed_modes: list[str]
    max_ttl_seconds: int = 3600
    approval_required: bool = True
    raw_reveal_allowed: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    reuse_window_seconds: int = 0
    enabled: bool = False


@dataclass(frozen=True)
class SeedPlan:
    provider_name: str
    provider_base_dir: str
    aliases: list[AliasSeed]
    policies: list[PolicySeed]

    def as_jsonable(self) -> dict[str, Any]:
        return {
            "provider": {
                "name": self.provider_name,
                "kind": "file",
                "base_dir": self.provider_base_dir,
            },
            "aliases": [item.__dict__ for item in self.aliases],
            "policies": [item.__dict__ for item in self.policies],
        }


def utc_now_label() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def load_inventory_module():
    script = Path(__file__).resolve().parent / "secrets_inventory.py"
    spec = importlib.util.spec_from_file_location("secrets_inventory", script)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["secrets_inventory"] = module
    spec.loader.exec_module(module)
    return module


def safe_backend_ref(alias: str) -> str:
    cleaned = BACKEND_REF_SAFE_RE.sub("-", alias).strip("-")
    return f"pending/{cleaned}.secret"


def _append_unique(values: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def hosts_from_consumers(consumers: list[str]) -> list[str]:
    hosts: list[str] = []
    for consumer in consumers:
        if "/" not in consumer:
            continue
        host, _name = consumer.split("/", 1)
        _append_unique(hosts, host)
    return hosts


def lane_for_coverage(item: Any) -> str:
    alias = str(item.alias)
    consumers = list(getattr(item, "consumers", []) or [])
    hosts = hosts_from_consumers(consumers)
    if alias.startswith("notify."):
        return "shared_infra"
    if alias.startswith("bbs."):
        return "root"
    if alias.startswith("service."):
        return "shared_infra"
    if alias.startswith("host."):
        parts = alias.split(".")
        if len(parts) > 1:
            return parts[1]
        return "host"
    if "work-special" in hosts:
        return "work"
    if "private-host" in hosts:
        return "private"
    if "networking-host" in hosts:
        return "network"
    if "norman" in hosts:
        return "root"
    return "personal"


def policy_prefix_for_alias(alias: str) -> str:
    parts = alias.split(".")
    if len(parts) >= 3 and parts[0] == "host":
        return alias
    if len(parts) >= 3 and parts[0] == "tui":
        return f"tui.{parts[1]}."
    if len(parts) >= 3 and parts[0] == "notify":
        return "notify.long-job."
    if len(parts) >= 3 and parts[0] == "service":
        return ".".join(parts[:2]) + "."
    if len(parts) >= 3 and parts[0] == "bbs":
        return ".".join(parts[:2]) + "."
    return alias


def policy_name_for_prefix(prefix: str) -> str:
    stem = prefix.rstrip(".").replace(".", "-").replace("_", "-")
    digest = hashlib.sha1(prefix.encode("utf-8")).hexdigest()[:10]
    return f"catalog-{stem[:96]}-{digest}"


def requester_for_prefix(prefix: str) -> tuple[str, str | None]:
    if prefix.startswith("tui."):
        name = prefix.split(".", 2)[1]
        return "agent", name
    if prefix == "bbs.switchboard.":
        return "service", "switchboard"
    if prefix == "service.evergreen-sms-bridge.":
        return "service", "evergreen-sms-bridge"
    if prefix.startswith("notify."):
        return "agent", None
    if prefix.startswith("host."):
        return "operator", None
    return "agent", None


def modes_for_prefix(prefix: str) -> list[str]:
    if prefix.startswith("host."):
        return ["file"]
    if prefix.startswith("service."):
        return ["env", "file"]
    return ["inject", "env", "file"]


def existing_policy_covers(alias: str, policies: list[dict[str, Any]]) -> bool:
    for policy in policies:
        prefix = str(policy.get("secret_prefix") or "").strip()
        if prefix and alias.startswith(prefix):
            return True
    return False


def build_seed_plan(
    *,
    coverage: list[Any],
    keys_db: dict[str, Any],
    provider_name: str = DEFAULT_PROVIDER_NAME,
    provider_base_dir: str = DEFAULT_PROVIDER_BASE_DIR,
) -> SeedPlan:
    existing_aliases = {
        str(item.get("name") or "") for item in keys_db.get("aliases", [])
    }
    existing_policies = list(keys_db.get("policies", []) or [])
    aliases: list[AliasSeed] = []
    policies_by_prefix: dict[str, PolicySeed] = {}

    for item in coverage:
        alias_name = str(item.alias)
        lane = lane_for_coverage(item)
        if alias_name not in existing_aliases:
            aliases.append(
                AliasSeed(
                    name=alias_name,
                    lane=lane,
                    backend_ref=safe_backend_ref(alias_name),
                    metadata_json={
                        "owner": "norman-keys",
                        "status": "pending_value_migration",
                        "migration_mode": "catalog_only_no_secret_values",
                        "source": getattr(item, "source", ""),
                        "source_keys": list(getattr(item, "source_keys", []) or []),
                        "consumers": list(getattr(item, "consumers", []) or []),
                        "locations": list(getattr(item, "locations", []) or []),
                        "notes": list(getattr(item, "notes", []) or []),
                        "created_by": str(CATALOG_SCRIPT),
                        "created_at": utc_now_label(),
                        "next_step": (
                            "stage or rotate the value into backend_ref, then enable "
                            "the alias and policy deliberately"
                        ),
                    },
                )
            )

        if existing_policy_covers(alias_name, existing_policies):
            continue
        prefix = policy_prefix_for_alias(alias_name)
        if prefix in policies_by_prefix:
            continue
        requester_type, requester_id = requester_for_prefix(prefix)
        policies_by_prefix[prefix] = PolicySeed(
            name=policy_name_for_prefix(prefix),
            requester_type=requester_type,
            requester_id=requester_id,
            lane=lane,
            secret_prefix=prefix,
            allowed_modes=modes_for_prefix(prefix),
            allowed_hosts=hosts_from_consumers(
                list(getattr(item, "consumers", []) or [])
            ),
        )

    return SeedPlan(
        provider_name=provider_name,
        provider_base_dir=provider_base_dir,
        aliases=sorted(aliases, key=lambda item: item.name),
        policies=sorted(policies_by_prefix.values(), key=lambda item: item.name),
    )


def connect_db(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def require_tables(db: sqlite3.Connection) -> None:
    required = {"secret_providers", "secret_aliases", "secret_policies"}
    rows = db.execute("select name from sqlite_master where type = 'table'").fetchall()
    found = {str(row["name"]) for row in rows}
    missing = sorted(required - found)
    if missing:
        raise RuntimeError(f"Missing Norman Keys tables: {', '.join(missing)}")


def ensure_provider(
    db: sqlite3.Connection,
    *,
    name: str,
    base_dir: str,
) -> tuple[int, bool]:
    row = db.execute(
        "select id from secret_providers where name = ?",
        (name,),
    ).fetchone()
    if row:
        return int(row["id"]), False
    cur = db.execute(
        """
        insert into secret_providers (name, kind, enabled, config)
        values (?, ?, ?, ?)
        """,
        (name, "file", 1, json.dumps({"base_dir": base_dir}, sort_keys=True)),
    )
    return int(cur.lastrowid), True


def apply_seed_plan(db_path: Path, plan: SeedPlan) -> dict[str, Any]:
    with connect_db(db_path) as db:
        require_tables(db)
        provider_id, provider_created = ensure_provider(
            db, name=plan.provider_name, base_dir=plan.provider_base_dir
        )
        alias_created = 0
        policy_created = 0

        for alias in plan.aliases:
            row = db.execute(
                "select id from secret_aliases where name = ?",
                (alias.name,),
            ).fetchone()
            if row:
                continue
            db.execute(
                """
                insert into secret_aliases (
                    name, provider_id, backend_ref, lane, enabled,
                    default_ttl_seconds, allow_raw_reveal, metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alias.name,
                    provider_id,
                    alias.backend_ref,
                    alias.lane,
                    int(alias.enabled),
                    alias.default_ttl_seconds,
                    int(alias.allow_raw_reveal),
                    json.dumps(alias.metadata_json, sort_keys=True),
                ),
            )
            alias_created += 1

        for policy in plan.policies:
            row = db.execute(
                "select id from secret_policies where name = ?",
                (policy.name,),
            ).fetchone()
            if row:
                continue
            db.execute(
                """
                insert into secret_policies (
                    name, requester_type, requester_id, lane, secret_prefix,
                    allowed_modes, max_ttl_seconds, approval_required,
                    raw_reveal_allowed, allowed_hosts, reuse_window_seconds, enabled
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy.name,
                    policy.requester_type,
                    policy.requester_id,
                    policy.lane,
                    policy.secret_prefix,
                    json.dumps(policy.allowed_modes),
                    policy.max_ttl_seconds,
                    int(policy.approval_required),
                    int(policy.raw_reveal_allowed),
                    json.dumps(policy.allowed_hosts),
                    policy.reuse_window_seconds,
                    int(policy.enabled),
                ),
            )
            policy_created += 1

        db.commit()

    return {
        "provider_created": provider_created,
        "aliases_created": alias_created,
        "policies_created": policy_created,
    }


def build_live_plan(
    *,
    db_path: Path,
    no_remote: bool,
    provider_name: str,
    provider_base_dir: str,
) -> SeedPlan:
    inventory = load_inventory_module()
    files = [
        inventory.inventory_file(path)
        for path in inventory.expand_scan_paths(inventory.LOCAL_SCAN_PATHS)
    ]
    tuis = [] if no_remote else inventory.remote_tui_inventory()
    remote_files = [] if no_remote else inventory.remote_secret_file_inventory()
    keys_db = inventory.norman_keys_inventory(db_path)
    coverage = inventory.build_key_alias_coverage(
        files=files, tuis=tuis, remote_files=remote_files, keys_db=keys_db
    )
    return build_seed_plan(
        coverage=coverage,
        keys_db=keys_db,
        provider_name=provider_name,
        provider_base_dir=provider_base_dir,
    )


def print_text_summary(plan: SeedPlan, *, applied: dict[str, Any] | None) -> None:
    verb = "created" if applied is not None else "would create"
    print(f"provider: {plan.provider_name} ({plan.provider_base_dir})")
    print(f"{verb} disabled aliases: {len(plan.aliases)}")
    print(f"{verb} disabled policies: {len(plan.policies)}")
    if plan.aliases:
        print("alias sample:")
        for alias in plan.aliases[:10]:
            print(f"  - {alias.name} -> {alias.backend_ref} [{alias.lane}]")
        if len(plan.aliases) > 10:
            print(f"  ... {len(plan.aliases) - 10} more")
    if applied is None:
        print("dry run only; use --apply to write catalog rows")
        return
    print(
        "applied: "
        f"provider_created={applied['provider_created']} "
        f"aliases_created={applied['aliases_created']} "
        f"policies_created={applied['policies_created']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed disabled Norman Keys catalog rows from inventory coverage."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--provider-name", default=DEFAULT_PROVIDER_NAME)
    parser.add_argument("--provider-base-dir", default=DEFAULT_PROVIDER_BASE_DIR)
    parser.add_argument("--no-remote", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    plan = build_live_plan(
        db_path=Path(args.db),
        no_remote=args.no_remote,
        provider_name=args.provider_name,
        provider_base_dir=args.provider_base_dir,
    )
    applied = apply_seed_plan(Path(args.db), plan) if args.apply else None
    if args.as_json:
        payload = plan.as_jsonable()
        payload["dry_run"] = not args.apply
        payload["applied"] = applied
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text_summary(plan, applied=applied)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
