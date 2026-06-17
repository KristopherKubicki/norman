#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACTORS_DIR = REPO_ROOT / "db" / "estate" / "identity" / "actors"
DEFAULT_PROMPTS_DIR = REPO_ROOT / "scripts" / "agent_console_template" / "prompts"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_capability_inventory.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_capability_inventory.md")


def summarize_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}..."


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def actor_id_from_soul(text: str, fallback: str) -> str:
    match = re.search(r"(?im)^Actor ID:\s*(.+?)\s*$", text)
    if not match:
        return fallback
    return match.group(1).strip() or fallback


def section_body(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)"
    )
    match = pattern.search(text)
    return match.group("body").strip() if match else ""


def bullet_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        if item:
            lines.append(summarize_text(item, 220))
    return lines


def matching_lines(text: str, terms: tuple[str, ...], *, limit: int = 10) -> list[str]:
    matches: list[str] = []
    lowered_terms = tuple(term.lower() for term in terms)
    for raw in text.splitlines():
        line = " ".join(raw.strip().split())
        if not line:
            continue
        clean = line.lower()
        if any(term in clean for term in lowered_terms):
            matches.append(summarize_text(line.lstrip("- "), 220))
        if len(matches) >= limit:
            break
    return matches


def prompt_path_for_actor(prompts_dir: Path, slug: str) -> Path | None:
    path = prompts_dir / f"{slug}.txt"
    return path if path.exists() else None


def doc_runbook_refs(
    docs_dir: Path, slug: str, actor_id: str, *, limit: int = 8
) -> list[str]:
    refs: list[str] = []
    aliases = {
        slug.lower(),
        actor_id.lower(),
        slug.replace("-", " ").lower(),
        actor_id.replace("-", " ").lower(),
    }
    for path in sorted(docs_dir.glob("*.md")):
        text = read_text(path)
        clean = text.lower()
        if "runbook" not in clean:
            continue
        if not any(alias and alias in clean for alias in aliases):
            continue
        refs.append(display_path(path))
        if len(refs) >= limit:
            break
    return refs


def build_actor_row(
    soul_path: Path, *, prompts_dir: Path, docs_dir: Path
) -> dict[str, Any]:
    slug = soul_path.parent.name
    soul_text = read_text(soul_path)
    actor_id = actor_id_from_soul(soul_text, slug)
    prompt_path = prompt_path_for_actor(prompts_dir, slug)
    prompt_text = read_text(prompt_path) if prompt_path else ""
    combined_text = "\n".join(part for part in (soul_text, prompt_text) if part)
    role_items = bullet_lines(section_body(soul_text, "Role"))
    operating_items = bullet_lines(section_body(soul_text, "Operating Principles"))
    declared_skills = [*role_items, *operating_items]
    runbook_refs = matching_lines(combined_text, ("runbook", "run book"))
    skill_refs = matching_lines(combined_text, ("skill", "capability", "workflow"))
    doc_refs = doc_runbook_refs(docs_dir, slug, actor_id)
    return {
        "slug": slug,
        "actor_id": actor_id,
        "soul_path": display_path(soul_path),
        "prompt_path": display_path(prompt_path) if prompt_path else "",
        "declared_skill_count": len(declared_skills),
        "declared_skills": declared_skills[:12],
        "skill_ref_count": len(skill_refs),
        "skill_refs": skill_refs,
        "runbook_ref_count": len(runbook_refs) + len(doc_refs),
        "runbook_refs": [*runbook_refs, *doc_refs],
    }


def build_inventory(
    *,
    actors_dir: Path = DEFAULT_ACTORS_DIR,
    prompts_dir: Path = DEFAULT_PROMPTS_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> dict[str, Any]:
    rows = [
        build_actor_row(path, prompts_dir=prompts_dir, docs_dir=docs_dir)
        for path in sorted(actors_dir.glob("*/SOUL.md"))
    ]
    return {
        "schema": "norman.tui.capability-inventory.v1",
        "generated_at": int(time.time()),
        "summary": {
            "actors": len(rows),
            "actors_with_prompt_files": sum(1 for row in rows if row["prompt_path"]),
            "actors_with_declared_skills": sum(
                1 for row in rows if row["declared_skill_count"] > 0
            ),
            "actors_with_skill_refs": sum(
                1 for row in rows if row["skill_ref_count"] > 0
            ),
            "actors_with_runbook_refs": sum(
                1 for row in rows if row["runbook_ref_count"] > 0
            ),
        },
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# TUI Capability Inventory",
        "",
        "Durable inventory of actor-declared skills/capabilities and runbook references. This is a benchmark seed, not yet proof that every remote TUI has every skill installed.",
        "",
        "## Summary",
        "",
        f"- Actors: {summary.get('actors')}",
        f"- Actors with prompt files: {summary.get('actors_with_prompt_files')}",
        f"- Actors with declared skills: {summary.get('actors_with_declared_skills')}",
        f"- Actors with skill refs: {summary.get('actors_with_skill_refs')}",
        f"- Actors with runbook refs: {summary.get('actors_with_runbook_refs')}",
        "",
        "## Rows",
        "",
        "| TUI | Prompt | Declared skills | Skill refs | Runbook refs | Sample |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report.get("rows", []):
        skills = (
            row.get("declared_skills")
            if isinstance(row.get("declared_skills"), list)
            else []
        )
        runbooks = (
            row.get("runbook_refs") if isinstance(row.get("runbook_refs"), list) else []
        )
        sample = skills[0] if skills else runbooks[0] if runbooks else ""
        lines.append(
            "| {slug} | {prompt} | {skills} | {skill_refs} | {runbooks} | {sample} |".format(
                slug=row.get("slug", ""),
                prompt="yes" if row.get("prompt_path") else "no",
                skills=row.get("declared_skill_count", 0),
                skill_refs=row.get("skill_ref_count", 0),
                runbooks=row.get("runbook_ref_count", 0),
                sample=str(sample).replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory TUI actor skills/capabilities and runbook references."
    )
    parser.add_argument("--actors-dir", type=Path, default=DEFAULT_ACTORS_DIR)
    parser.add_argument("--prompts-dir", type=Path, default=DEFAULT_PROMPTS_DIR)
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS_DIR)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--print-md", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_inventory(
        actors_dir=args.actors_dir,
        prompts_dir=args.prompts_dir,
        docs_dir=args.docs_dir,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
