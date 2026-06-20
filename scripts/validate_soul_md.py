#!/usr/bin/env python3
"""Validate estate SOUL.md identity files."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "db" / "estate" / "identity"
MAX_SOUL_BYTES = 12_000

BASE_REQUIRED_SECTIONS = {
    "Scope",
    "Precedence",
    "Estate Rules",
    "Power Accounting",
    "Return To Dust",
    "Shabbat Audit",
    "Human Recourse And Local Governance",
    "Communication Contract",
    "Memory Boundaries",
    "Change Control",
}

ACTOR_REQUIRED_SECTIONS = {
    "Identity",
    "Role",
    "Operating Principles",
    "Authority",
    "Communication Style",
    "Boundaries",
    "Memory Policy",
}

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bAuthorization:\s*Bearer\s+\S+"),
    re.compile(r"(?i)\bSWITCHBOARD_TOKEN\s*="),
    re.compile(r"(?i)\b[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|PRIVATE_KEY)\s*=\s*\S+"),
    re.compile(r"(?i)\bssh-ed25519\s+[A-Za-z0-9+/=]{40,}"),
]


@dataclass(frozen=True)
class ValidationError:
    path: Path
    message: str


def _headings(text: str) -> set[str]:
    headings: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("## "):
            continue
        headings.add(line[3:].strip())
    return headings


def _relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def validate_soul_file(
    path: Path, *, root: Path = DEFAULT_ROOT
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    text = path.read_text(encoding="utf-8")
    rel = _relative(path, root)

    if path.name != "SOUL.md" and path.name != "BASE_SOUL.md":
        errors.append(
            ValidationError(
                path, "identity files must be named SOUL.md or BASE_SOUL.md"
            )
        )
    if len(text.encode("utf-8")) > MAX_SOUL_BYTES:
        errors.append(ValidationError(path, f"file exceeds {MAX_SOUL_BYTES} bytes"))
    if "This file does not grant authority." not in text:
        errors.append(ValidationError(path, "missing authority disclaimer"))
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            errors.append(ValidationError(path, "contains a secret-like value"))
            break

    headings = _headings(text)
    if path.name == "BASE_SOUL.md":
        missing = BASE_REQUIRED_SECTIONS - headings
        for section in sorted(missing):
            errors.append(ValidationError(path, f"missing base section: {section}"))
        return errors

    missing = ACTOR_REQUIRED_SECTIONS - headings
    for section in sorted(missing):
        errors.append(ValidationError(path, f"missing actor section: {section}"))

    if rel.parts[:1] != ("actors",) or len(rel.parts) != 3:
        errors.append(
            ValidationError(
                path, "actor SOUL.md must live under actors/<actor>/SOUL.md"
            )
        )
        return errors

    actor = rel.parts[1]
    expected = f"Actor ID: {actor}"
    if expected not in text:
        errors.append(
            ValidationError(path, f"missing matching actor id line: {expected}")
        )
    return errors


def iter_soul_files(root: Path) -> list[Path]:
    files = [root / "BASE_SOUL.md"]
    actors_dir = root / "actors"
    if actors_dir.exists():
        files.extend(sorted(actors_dir.glob("*/SOUL.md")))
    return [path for path in files if path.exists()]


def validate_tree(root: Path = DEFAULT_ROOT) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not (root / "BASE_SOUL.md").exists():
        errors.append(
            ValidationError(root / "BASE_SOUL.md", "missing base identity file")
        )
    for path in iter_soul_files(root):
        errors.extend(validate_soul_file(path, root=root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate estate SOUL.md files.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    errors = validate_tree(args.root)
    for error in errors:
        print(f"{error.path}: {error.message}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
