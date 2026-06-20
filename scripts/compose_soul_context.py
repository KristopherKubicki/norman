#!/usr/bin/env python3
"""Compose advisory SOUL.md context for a single actor."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_soul_md


DEFAULT_ROOT = validate_soul_md.DEFAULT_ROOT
MAX_CONTEXT_BYTES = 30_000

ACTOR_ALIASES = {
    "dashboard": "tmi-dashboards",
    "dashboards": "tmi-dashboards",
    "camera-studio": "autocamera",
    "studio": "autocamera",
    "eyebat": "glimpser",
    "bbs": "subprime",
    "botprime": "subprime",
    "cp": "control-plane",
    "keystone": "compere",
    "kpis": "leadership-kpis",
    "market": "market-sizing",
    "networking": "netops",
    "networking-host": "netops",
    "norman-ops": "norman",
    "norman-prime": "norman",
    "pef": "parkergale",
    "pefb": "parkergale",
    "phoneops": "phone-ops",
    "switchboard": "subprime",
}


class SoulContextError(RuntimeError):
    """Raised when a SOUL context cannot be composed safely."""


@dataclass(frozen=True)
class SoulContext:
    requested_actor: str
    actor: str
    base_path: Path
    actor_path: Path
    text: str

    def as_json(self) -> str:
        payload = {
            "requested_actor": self.requested_actor,
            "actor": self.actor,
            "base_path": str(self.base_path),
            "actor_path": str(self.actor_path),
            "text": self.text,
        }
        return json.dumps(payload, indent=2, sort_keys=True)


def normalize_actor(value: str) -> str:
    actor = value.strip().lower().replace("_", "-")
    return ACTOR_ALIASES.get(actor, actor)


def _validation_error_text(errors: list[validate_soul_md.ValidationError]) -> str:
    return "; ".join(f"{error.path}: {error.message}" for error in errors)


def _validated_text(path: Path, root: Path) -> str:
    errors = validate_soul_md.validate_soul_file(path, root=root)
    if errors:
        raise SoulContextError(_validation_error_text(errors))
    return path.read_text(encoding="utf-8").strip()


def compose_soul_context(
    actor: str,
    *,
    root: Path = DEFAULT_ROOT,
    include_base: bool = True,
) -> SoulContext:
    requested_actor = actor.strip()
    resolved_actor = normalize_actor(requested_actor)
    if not resolved_actor:
        raise SoulContextError("missing actor")

    base_path = root / "BASE_SOUL.md"
    actor_path = root / "actors" / resolved_actor / "SOUL.md"
    if include_base and not base_path.exists():
        raise SoulContextError(f"missing base SOUL file: {base_path}")
    if not actor_path.exists():
        raise SoulContextError(f"missing actor SOUL file: {actor_path}")

    sections = [
        "SOUL.md advisory identity context",
        "",
        "This context is advisory. It does not grant authority, credentials, "
        "permissions, or policy exceptions.",
        "Higher-priority system, developer, operator, repository, BBS, actor-token, "
        "and host-access controls still take precedence.",
        "",
        f"Requested actor: {requested_actor}",
        f"Resolved actor: {resolved_actor}",
    ]

    if include_base:
        base_text = _validated_text(base_path, root)
        sections.extend(["", f"Source: {base_path.relative_to(root)}", "", base_text])

    actor_text = _validated_text(actor_path, root)
    sections.extend(["", f"Source: {actor_path.relative_to(root)}", "", actor_text])

    text = "\n".join(sections).strip() + "\n"
    if len(text.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise SoulContextError(
            f"composed SOUL context exceeds {MAX_CONTEXT_BYTES} bytes"
        )

    return SoulContext(
        requested_actor=requested_actor,
        actor=resolved_actor,
        base_path=base_path,
        actor_path=actor_path,
        text=text,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", required=True, help="Actor name or known alias.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--no-base",
        action="store_true",
        help="Only include the actor SOUL.md file.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    args = parser.parse_args(argv)

    try:
        context = compose_soul_context(
            args.actor,
            root=args.root,
            include_base=not args.no_base,
        )
    except SoulContextError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(context.as_json())
    else:
        print(context.text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
