#!/usr/bin/env python3
"""Prune old inactive Codex session histories while retaining a recovery floor."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "norman.codex.session-prune.v1"
DEFAULT_RETENTION_DAYS = int(os.environ.get("CODEX_SESSION_RETENTION_DAYS", "14"))
DEFAULT_RETAIN_COUNT = int(os.environ.get("CODEX_SESSION_RETAIN_COUNT", "20"))
DEFAULT_OUTPUT_JSON = Path(
    os.environ.get(
        "CODEX_SESSION_PRUNE_STATE",
        str(Path.home() / ".local/state/norman/codex-session-prune.json"),
    )
)


def _default_codex_homes() -> list[Path]:
    configured = os.environ.get("CODEX_HOME", "").strip()
    homes = [Path(configured).expanduser()] if configured else []
    homes.extend([Path.home() / ".codex", Path.home() / ".codex-work"])
    return list(dict.fromkeys(path.resolve() for path in homes))


def _iter_session_files(home: Path) -> list[Path]:
    root = home / "sessions"
    if not root.is_dir():
        return []
    try:
        return sorted(
            (path for path in root.rglob("*.jsonl") if path.is_file()),
            key=lambda path: (path.stat().st_mtime, str(path)),
            reverse=True,
        )
    except OSError:
        return []


def active_session_paths(
    codex_homes: Iterable[Path], *, proc_root: Path = Path("/proc")
) -> set[Path]:
    """Find all open session JSONLs; this is the hard deletion exclusion."""

    homes = [path.expanduser().resolve() for path in codex_homes]
    active: set[Path] = set()
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return active
    for process in entries:
        fd_dir = process / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = Path(os.readlink(fd).removesuffix(" (deleted)"))
            except (OSError, ValueError):
                continue
            if target.suffix != ".jsonl":
                continue
            for home in homes:
                try:
                    target.relative_to(home / "sessions")
                except ValueError:
                    continue
                active.add(target)
                break
    return active


def _cleanup_empty_parents(home: Path) -> None:
    sessions_root = home / "sessions"
    if not sessions_root.is_dir():
        return
    directories = sorted(
        (path for path in sessions_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in directories:
        try:
            path.rmdir()
        except OSError:
            continue


def prune_sessions(
    codex_homes: Iterable[Path],
    *,
    retention_days: int,
    retain_count: int,
    active_paths: set[Path],
    now: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    observed_at = time.time() if now is None else float(now)
    cutoff = observed_at - max(0, retention_days) * 24 * 60 * 60
    homes = list(dict.fromkeys(path.expanduser().resolve() for path in codex_homes))
    removed: list[dict[str, Any]] = []
    skipped_active: list[str] = []
    skipped_floor: list[str] = []
    skipped_recent: list[str] = []

    for home in homes:
        sessions = _iter_session_files(home)
        retained_paths = {path for path in sessions[: max(0, retain_count)]}
        for path in sessions:
            try:
                stat = path.stat()
            except OSError:
                continue
            if path in active_paths:
                skipped_active.append(str(path))
                continue
            if path in retained_paths:
                skipped_floor.append(str(path))
                continue
            if stat.st_mtime >= cutoff:
                skipped_recent.append(str(path))
                continue
            record = {
                "codex_home": str(home),
                "path": str(path),
                "size_bytes": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
            if not dry_run:
                try:
                    path.unlink()
                except OSError:
                    continue
            removed.append(record)
        if not dry_run:
            _cleanup_empty_parents(home)

    reclaimed = sum(int(item["size_bytes"]) for item in removed)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.fromtimestamp(
            observed_at, tz=timezone.utc
        ).isoformat(),
        "status": "dry_run" if dry_run else ("pruned" if removed else "no_change"),
        "retention_days": max(0, retention_days),
        "retain_count_per_home": max(0, retain_count),
        "active_session_count": len(active_paths),
        "removed_count": len(removed),
        "reclaimed_bytes": reclaimed,
        "reclaimed_mib": round(reclaimed / (1024 * 1024), 1),
        "removed": removed[-100:],
        "skipped_active": skipped_active[-100:],
        "skipped_retention_floor": skipped_floor[-100:],
        "skipped_recent": skipped_recent[-100:],
        "roots": [str(home) for home in homes],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prune inactive old Codex sessions while preserving active files."
    )
    parser.add_argument("--codex-home", type=Path, action="append", default=[])
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--retain-count", type=int, default=DEFAULT_RETAIN_COUNT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    homes = args.codex_home or _default_codex_homes()
    active = active_session_paths(homes)
    report = prune_sessions(
        homes,
        retention_days=max(0, int(args.retention_days)),
        retain_count=max(0, int(args.retain_count)),
        active_paths=active,
        dry_run=bool(args.dry_run),
    )
    _write_json(args.output_json, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
