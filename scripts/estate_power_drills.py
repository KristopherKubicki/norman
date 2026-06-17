#!/usr/bin/env python3
"""List and record estate power revocation drills."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services import estate_registry  # noqa: E402


DEFAULT_DRILL_POWERS = ("mouth", "purse", "key", "seal")
DRILL_SECTIONS = (
    "policy_profiles",
    "bots",
    "workers",
    "assets",
    "services",
    "channels",
)
PENDING_REVOCATION_TEST_VALUES = {"", "never", "pending", "unknown", "untested"}


@dataclass(frozen=True)
class RevocationDrillTarget:
    section: str
    slug: str
    power: str
    level: str
    revoker: str
    revocation_tested_at: str
    coverage: int
    display_name: str | None = None

    @property
    def selector(self) -> str:
        return f"{self.section}/{self.slug}/{self.power}"

    def as_jsonable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selector"] = self.selector
        return payload


def _normalize_entry(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"level": raw.strip().lower()}
    if isinstance(raw, dict):
        entry = dict(raw)
        entry["level"] = str(entry.get("level") or "").strip().lower()
        return entry
    raise ValueError("power entry must be a string or mapping")


def _power_active(entry: dict[str, Any]) -> bool:
    return str(entry.get("level") or "none").strip().lower() not in {"none", "denied"}


def _revocation_status(entry: dict[str, Any]) -> str:
    if not _power_active(entry):
        return "not_applicable"
    tested_at = str(entry.get("revocation_tested_at") or "").strip().lower()
    if tested_at in PENDING_REVOCATION_TEST_VALUES:
        return "pending"
    return "tested"


def _powers_declares(item: dict[str, Any], power: str) -> bool:
    powers = item.get("powers")
    return isinstance(powers, dict) and power in powers


def _item_index(registry: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    by_selector: dict[str, dict[str, Any]] = {}
    for section in ("bots", "workers", "assets", "services", "channels"):
        for item in registry.get(section, []):
            if isinstance(item, dict):
                slug = str(item.get("slug") or "").strip()
                if slug:
                    by_selector[f"{section}/{slug}"] = item
    return by_selector


def _coverage_for_declared_power(
    registry: dict[str, list[dict[str, Any]]],
    *,
    section: str,
    slug: str,
    power: str,
) -> int:
    manifest = estate_registry.power_manifest(registry)
    raw_items = _item_index(registry)
    count = 0
    for item in manifest["items"]:
        if not item["is_active"]:
            continue
        effective = item["powers"].get(power) or {}
        if not _power_active(effective):
            continue
        if section == "policy_profiles":
            if item.get("policy_profile") != slug:
                continue
            raw = raw_items.get(f"{item['section']}/{item['slug']}", {})
            if _powers_declares(raw, power):
                continue
            count += 1
        elif item["section"] == section and item["slug"] == slug:
            count += 1
    return count


def revocation_drill_targets(
    registry: dict[str, list[dict[str, Any]]],
    *,
    powers: Iterable[str] = DEFAULT_DRILL_POWERS,
    statuses: Iterable[str] = ("pending",),
) -> list[RevocationDrillTarget]:
    wanted_powers = {str(power).strip().lower() for power in powers}
    wanted_statuses = {str(status).strip().lower() for status in statuses}
    targets: list[RevocationDrillTarget] = []

    for section in DRILL_SECTIONS:
        for item in registry.get(section, []):
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or "").strip()
            if not slug:
                continue
            powers_map = item.get("powers")
            if not isinstance(powers_map, dict):
                continue
            for power in sorted(wanted_powers):
                if power not in powers_map:
                    continue
                entry = _normalize_entry(powers_map[power])
                status = _revocation_status(entry)
                if status not in wanted_statuses:
                    continue
                targets.append(
                    RevocationDrillTarget(
                        section=section,
                        slug=slug,
                        power=power,
                        level=str(entry.get("level") or "none"),
                        revoker=str(entry.get("revoker") or ""),
                        revocation_tested_at=str(
                            entry.get("revocation_tested_at") or "pending"
                        ),
                        coverage=_coverage_for_declared_power(
                            registry, section=section, slug=slug, power=power
                        ),
                        display_name=item.get("display_name"),
                    )
                )
    return sorted(targets, key=lambda item: item.selector)


def _load_raw_registry(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("registry root must be a mapping")
    return raw


def _find_raw_item(raw: dict[str, Any], *, section: str, slug: str) -> dict[str, Any]:
    rows = raw.get(section)
    if not isinstance(rows, list):
        raise ValueError(f"registry section `{section}` must be a list")
    for item in rows:
        if isinstance(item, dict) and str(item.get("slug") or "").strip() == slug:
            return item
    raise ValueError(f"no `{section}` entry found for slug `{slug}`")


def _validate_tested_at(value: str) -> str:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("tested-at must be an ISO date like 2026-05-31") from exc


def record_revocation_test(
    path: Path,
    *,
    section: str,
    slug: str,
    power: str,
    tested_at: str,
    notes: str | None = None,
    revoker: str | None = None,
) -> dict[str, Any]:
    section = section.strip()
    slug = slug.strip()
    power = power.strip().lower()
    tested_at = _validate_tested_at(tested_at)
    if section not in DRILL_SECTIONS:
        raise ValueError(f"unsupported registry section `{section}`")
    if power not in estate_registry.POWER_CLASSES:
        raise ValueError(f"unsupported power `{power}`")

    raw = _load_raw_registry(path)
    item = _find_raw_item(raw, section=section, slug=slug)
    powers_map = item.setdefault("powers", {})
    if not isinstance(powers_map, dict):
        raise ValueError(f"`{section}/{slug}` powers must be a mapping")
    if power not in powers_map:
        raise ValueError(f"`{section}/{slug}` does not declare `{power}` power")

    entry = _normalize_entry(powers_map[power])
    if not _power_active(entry):
        raise ValueError(f"`{section}/{slug}/{power}` is not active")
    if revoker:
        entry["revoker"] = revoker.strip()
    if not str(entry.get("revoker") or "").strip():
        raise ValueError(f"`{section}/{slug}/{power}` needs revoker before recording")
    entry["revocation_tested_at"] = tested_at
    if notes:
        entry["revocation_test_notes"] = notes.strip()
    powers_map[power] = entry

    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    estate_registry.load_registry(path)
    return entry


def render_table(targets: list[RevocationDrillTarget]) -> str:
    if not targets:
        return "No pending revocation drill targets."
    rows = [
        (
            target.selector,
            target.level,
            target.revoker or "-",
            str(target.coverage),
            target.revocation_tested_at,
        )
        for target in targets
    ]
    headers = ("target", "level", "revoker", "coverage", "tested_at")
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    lines = [
        "  ".join(header.ljust(width) for header, width in zip(headers, widths)),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(value.ljust(width) for value, width in zip(row, widths))
        for row in rows
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=estate_registry.DEFAULT_REGISTRY_PATH,
        help="Estate registry YAML path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List revocation drill targets.")
    list_parser.add_argument(
        "--power",
        choices=estate_registry.POWER_CLASSES,
        action="append",
        help="Power class to include. Defaults to mouth, key, and seal.",
    )
    list_parser.add_argument("--json", action="store_true", help="Emit JSON.")

    record_parser = subparsers.add_parser(
        "record", help="Record a completed revocation drill."
    )
    record_parser.add_argument("--section", choices=DRILL_SECTIONS, required=True)
    record_parser.add_argument("--slug", required=True)
    record_parser.add_argument(
        "--power", choices=estate_registry.POWER_CLASSES, required=True
    )
    record_parser.add_argument("--tested-at", required=True)
    record_parser.add_argument("--revoker")
    record_parser.add_argument("--notes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        registry = estate_registry.load_registry(args.registry)
        targets = revocation_drill_targets(
            registry, powers=args.power or DEFAULT_DRILL_POWERS
        )
        if args.json:
            print(json.dumps([target.as_jsonable() for target in targets], indent=2))
        else:
            print(render_table(targets))
        return 0

    entry = record_revocation_test(
        args.registry,
        section=args.section,
        slug=args.slug,
        power=args.power,
        tested_at=args.tested_at,
        notes=args.notes,
        revoker=args.revoker,
    )
    print(
        f"Recorded {args.section}/{args.slug}/{args.power} revocation test "
        f"at {entry['revocation_tested_at']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
