#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sync_tui_microtextures as texture_sync  # noqa: E402


DEFAULT_REFERENCE_JSON = ROOT / "app/static/textures/tui_microtexture_reference.json"
DEFAULT_REGISTRY = ROOT / "db/estate/registry.yaml"
DEFAULT_ACTORS_DIR = ROOT / "db/estate/identity/actors"
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_microtexture_audit.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_microtexture_audit.md")

GENERATED_TARGETS = (
    ROOT / "scripts/agent_console_template/agent_console_web.py",
    ROOT / "scripts/norman_codex_web.py",
    ROOT / "app/static/js/home.js",
    ROOT / "app/static/js/systems.js",
)
PYTHON_GENERATED_TARGETS = GENERATED_TARGETS[:2]
JS_GENERATED_TARGETS = GENERATED_TARGETS[2:]

CONSOLE_KINDS = {
    "coordination-service",
    "game-tui",
    "ops-console",
    "web-app",
}

NON_TUI_ACTOR_PHRASES = (
    "not an operator-facing tui",
    "retired redundant sidecar",
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_cards(reference_json: Path = DEFAULT_REFERENCE_JSON) -> list[dict[str, Any]]:
    cards = json.loads(reference_json.read_text(encoding="utf-8"))
    if not isinstance(cards, list):
        raise ValueError(f"{display_path(reference_json)} must contain a list")
    return cards


def canonical_texture_map(cards: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for card in cards:
        slug = str(card.get("slug") or "").strip()
        if slug:
            mapping[slug] = slug
    for canonical, aliases in texture_sync.PYTHON_ALIASES.items():
        if canonical in mapping:
            for alias in aliases:
                mapping[str(alias)] = canonical
    for canonical, aliases in texture_sync.DIRECTORY_ALIASES.items():
        if canonical in mapping:
            for alias in aliases:
                mapping[str(alias)] = canonical
    for slug, _spec in texture_sync.EXTRA_DIRECTORY_TEXTURES:
        mapping.setdefault(str(slug), str(slug))
    return mapping


def active_console_services(
    registry_path: Path = DEFAULT_REGISTRY,
) -> list[dict[str, Any]]:
    if not registry_path.exists() and registry_path.with_suffix(".yaml.dist").exists():
        registry_path = registry_path.with_suffix(".yaml.dist")
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    services = raw.get("services") if isinstance(raw, dict) else None
    if not isinstance(services, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in services:
        if not isinstance(item, dict):
            continue
        if item.get("is_active") is False:
            continue
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue
        kind = str(item.get("kind") or "").strip()
        has_console = bool(item.get("console_url") or item.get("console_url_tailnet"))
        if not has_console and kind not in CONSOLE_KINDS:
            continue
        if kind == "host-home":
            continue
        rows.append(
            {
                "slug": slug,
                "display_name": str(item.get("display_name") or slug),
                "kind": kind,
                "principal": str(item.get("principal") or ""),
                "domain": str(item.get("domain") or ""),
                "source": display_path(registry_path),
            }
        )
    return rows


def actor_soul_rows(actors_dir: Path = DEFAULT_ACTORS_DIR) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for soul_path in sorted(actors_dir.glob("*/SOUL.md")):
        slug = soul_path.parent.name
        text = read_text(soul_path)
        lowered = text.lower()
        operator_facing = not any(phrase in lowered for phrase in NON_TUI_ACTOR_PHRASES)
        rows.append(
            {
                "slug": slug,
                "display_name": slug.replace("-", " ").title(),
                "kind": "actor-soul",
                "operator_facing": operator_facing,
                "source": display_path(soul_path),
            }
        )
    return rows


def generated_target_presence(slug: str, target: Path) -> bool:
    source = read_text(target)
    quoted = (f'"{slug}":', f"'{slug}':")
    if any(marker in source for marker in quoted):
        return True
    if target.suffix == ".js" and re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", slug):
        return bool(re.search(rf"(?<![A-Za-z0-9_$]){re.escape(slug)}\s*:", source))
    return False


def generated_targets_for_item(item: dict[str, Any]) -> tuple[Path, ...]:
    kind = str(item.get("kind") or "").strip()
    if kind == "web-app":
        return JS_GENERATED_TARGETS
    return GENERATED_TARGETS


def coverage_row(
    item: dict[str, Any],
    *,
    texture_map: dict[str, str],
) -> dict[str, Any]:
    slug = str(item.get("slug") or "")
    canonical = texture_map.get(slug, "")
    generated_missing = [
        display_path(target)
        for target in generated_targets_for_item(item)
        if canonical and not generated_target_presence(slug, target)
    ]
    return {
        **item,
        "texture": canonical,
        "coverage": "direct"
        if canonical == slug
        else "alias"
        if canonical
        else "missing",
        "generated_missing": generated_missing,
    }


def build_report(
    *,
    reference_json: Path = DEFAULT_REFERENCE_JSON,
    registry_path: Path = DEFAULT_REGISTRY,
    actors_dir: Path = DEFAULT_ACTORS_DIR,
) -> dict[str, Any]:
    cards = load_cards(reference_json)
    texture_map = canonical_texture_map(cards)
    registry_rows = [
        coverage_row(item, texture_map=texture_map)
        for item in active_console_services(registry_path)
    ]
    actor_rows = [
        coverage_row(item, texture_map=texture_map)
        for item in actor_soul_rows(actors_dir)
    ]
    required_rows = registry_rows + [
        row
        for row in actor_rows
        if row.get("operator_facing")
        and row.get("slug") not in {r["slug"] for r in registry_rows}
    ]
    missing_required = [row for row in required_rows if row["coverage"] == "missing"]
    generated_missing_required = [
        row
        for row in required_rows
        if row["coverage"] != "missing" and row["generated_missing"]
    ]
    alias_rows = [row for row in required_rows if row["coverage"] == "alias"]
    direct_rows = [row for row in required_rows if row["coverage"] == "direct"]
    return {
        "schema": "norman.tui.microtexture-audit.v1",
        "generated_at": int(time.time()),
        "sources": {
            "reference_json": display_path(reference_json),
            "registry": display_path(registry_path),
            "actors_dir": display_path(actors_dir),
        },
        "summary": {
            "texture_cards": len(cards),
            "required_tuis": len(required_rows),
            "direct": len(direct_rows),
            "aliases": len(alias_rows),
            "missing": len(missing_required),
            "generated_missing": len(generated_missing_required),
            "registry_console_tuis": len(registry_rows),
            "actor_souls": len(actor_rows),
        },
        "required_rows": sorted(required_rows, key=lambda row: row["slug"]),
        "missing_required": sorted(missing_required, key=lambda row: row["slug"]),
        "generated_missing_required": sorted(
            generated_missing_required, key=lambda row: row["slug"]
        ),
        "alias_rows": sorted(alias_rows, key=lambda row: row["slug"]),
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# TUI Microtexture Audit",
        "",
        "Coverage report for live TUI identities against the contact-sheet texture metadata and generated UI sources.",
        "",
        "## Summary",
        "",
        f"- Texture cards: {summary.get('texture_cards')}",
        f"- Required TUIs: {summary.get('required_tuis')}",
        f"- Direct coverage: {summary.get('direct')}",
        f"- Alias coverage: {summary.get('aliases')}",
        f"- Missing coverage: {summary.get('missing')}",
        f"- Missing generated entries: {summary.get('generated_missing')}",
        "",
        "## Required TUIs",
        "",
        "| TUI | Coverage | Texture | Kind | Principal | Source |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("required_rows", []):
        lines.append(
            "| {slug} | {coverage} | {texture} | {kind} | {principal} | {source} |".format(
                slug=str(row.get("slug") or ""),
                coverage=str(row.get("coverage") or ""),
                texture=str(row.get("texture") or ""),
                kind=str(row.get("kind") or ""),
                principal=str(row.get("principal") or ""),
                source=str(row.get("source") or ""),
            )
        )
    missing = report.get("missing_required")
    generated_missing = report.get("generated_missing_required")
    if missing:
        lines.extend(["", "## Missing Coverage", ""])
        for row in missing:
            lines.append(f"- {row.get('slug')} from {row.get('source')}")
    if generated_missing:
        lines.extend(["", "## Missing Generated Entries", ""])
        for row in generated_missing:
            targets = ", ".join(row.get("generated_missing") or [])
            lines.append(f"- {row.get('slug')}: {targets}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit live TUI identities against contact-sheet microtextures."
    )
    parser.add_argument("--reference-json", type=Path, default=DEFAULT_REFERENCE_JSON)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--actors-dir", type=Path, default=DEFAULT_ACTORS_DIR)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--print-md", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        reference_json=args.reference_json,
        registry_path=args.registry,
        actors_dir=args.actors_dir,
    )
    markdown = render_markdown(report)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_md.write_text(markdown, encoding="utf-8")
    if args.print_md:
        print(markdown)
    else:
        print(f"wrote {args.output_json}")
        print(f"wrote {args.output_md}")
        print(json.dumps(report.get("summary", {}), indent=2, sort_keys=True))
    has_failures = bool(
        report.get("missing_required") or report.get("generated_missing_required")
    )
    return 0 if args.allow_missing or not has_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
