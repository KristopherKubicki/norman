#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import pwd
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_TMP_ROOT = Path("/tmp")
DEFAULT_OUTPUT = Path("/var/lib/norman/state/tui-tmp-workspace-cleanup.json")
DEFAULT_WORKSPACE_AGE_HOURS = 48
DEFAULT_TEST_DB_AGE_HOURS = 24

WORKSPACE_PREFIXES = (
    "chrome-profile5-",
    "control_plane_",
    "dace-",
    "deepbrand-",
    "gold-book-",
    "p12-",
    "profile5-page-probe-",
    "pytest-of-",
)
ARTIFACT_PATTERNS = (
    "dace-*.bundle",
    "dace-*.tar",
    "dace-*.tar.gz",
)
TEST_DB_PATTERN = "norman_test_*.db"


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    kind: str
    age_hours: float


def _path_age_hours(path: Path, *, now: float) -> float:
    return max(0.0, (now - path.stat().st_mtime) / 3600)


def _candidate_kind(path: Path) -> str | None:
    if path.is_symlink():
        return None
    if path.is_file() and fnmatch.fnmatch(path.name, TEST_DB_PATTERN):
        return "test_database"
    if path.is_file() and any(
        fnmatch.fnmatch(path.name, pattern) for pattern in ARTIFACT_PATTERNS
    ):
        return "agent_artifact"
    if path.is_dir() and path.name.startswith(WORKSPACE_PREFIXES):
        return "agent_workspace"
    return None


def discover_candidates(
    tmp_root: Path,
    *,
    now: float,
    workspace_age_hours: int,
    test_db_age_hours: int,
) -> list[CleanupCandidate]:
    candidates: list[CleanupCandidate] = []
    try:
        entries = sorted(tmp_root.iterdir(), key=lambda item: item.name)
    except OSError:
        return candidates

    for path in entries:
        try:
            kind = _candidate_kind(path)
            if not kind:
                continue
            age_hours = _path_age_hours(path, now=now)
        except OSError:
            continue
        min_age_hours = (
            test_db_age_hours if kind == "test_database" else workspace_age_hours
        )
        if age_hours >= min_age_hours:
            candidates.append(
                CleanupCandidate(path=path, kind=kind, age_hours=age_hours)
            )
    return sorted(candidates, key=lambda item: (item.age_hours, str(item.path)))


def _git_status(path: Path) -> tuple[bool, str]:
    owner = path.stat()
    command_env = dict(os.environ)
    preexec_fn = None
    if os.geteuid() == 0 and owner.st_uid != 0:
        account = pwd.getpwuid(owner.st_uid)
        command_env["HOME"] = account.pw_dir

        def run_as_workspace_owner() -> None:
            os.initgroups(account.pw_name, owner.st_gid)
            os.setgid(owner.st_gid)
            os.setuid(owner.st_uid)

        preexec_fn = run_as_workspace_owner
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=command_env,
            preexec_fn=preexec_fn,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, result.stderr.strip() or "not a git worktree"
    if result.stdout.strip():
        return False, "git worktree has uncommitted changes"
    return True, "clean git worktree"


def _has_open_files(path: Path) -> tuple[bool, str]:
    command = ["lsof", "-t", "--", str(path)]
    if path.is_dir():
        command = ["lsof", "-t", "+D", str(path)]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return True, "lsof is unavailable"
    except subprocess.TimeoutExpired:
        return True, "open-file check timed out"
    except OSError as exc:
        return True, f"open-file check failed: {exc}"
    if result.returncode == 0 and result.stdout.strip():
        return True, "workspace has open files"
    if result.returncode not in (0, 1):
        return True, result.stderr.strip() or "open-file check failed"
    return False, "no open files"


def _allocated_bytes(path: Path) -> int:
    try:
        if path.is_file():
            return int(path.stat().st_blocks) * 512
        total = 0
        for root, _directories, files in os.walk(path, followlinks=False):
            root_path = Path(root)
            try:
                total += int(root_path.stat().st_blocks) * 512
            except OSError:
                pass
            for name in files:
                item = root_path / name
                try:
                    total += int(item.stat().st_blocks) * 512
                except OSError:
                    continue
        return total
    except OSError:
        return 0


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def evaluate_candidate(candidate: CleanupCandidate) -> tuple[bool, str]:
    if candidate.kind == "agent_workspace":
        clean_worktree, git_reason = _git_status(candidate.path)
        if not clean_worktree:
            return False, git_reason

    open_files, open_reason = _has_open_files(candidate.path)
    if open_files:
        return False, open_reason
    if candidate.kind == "agent_workspace":
        return True, "clean git worktree"
    return True, "expired generated artifact"


def cleanup(
    tmp_root: Path,
    *,
    apply: bool,
    now: float | None = None,
    workspace_age_hours: int = DEFAULT_WORKSPACE_AGE_HOURS,
    test_db_age_hours: int = DEFAULT_TEST_DB_AGE_HOURS,
) -> dict[str, Any]:
    checked_at = time.time() if now is None else float(now)
    candidates = discover_candidates(
        tmp_root,
        now=checked_at,
        workspace_age_hours=max(1, int(workspace_age_hours)),
        test_db_age_hours=max(1, int(test_db_age_hours)),
    )
    removed: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for candidate in candidates:
        item = {
            **asdict(candidate),
            "path": str(candidate.path),
            "age_hours": round(candidate.age_hours, 1),
        }
        eligible, reason = evaluate_candidate(candidate)
        item.pop("path", None)
        item["path"] = str(candidate.path)
        if not eligible:
            preserved.append({**item, "reason": reason})
            continue
        allocated_bytes = _allocated_bytes(candidate.path)
        if not apply:
            preserved.append(
                {
                    **item,
                    "reason": f"dry run: {reason}",
                    "allocated_bytes": allocated_bytes,
                }
            )
            continue
        try:
            _remove(candidate.path)
        except OSError as exc:
            errors.append({**item, "reason": str(exc)})
            continue
        removed.append(
            {
                **item,
                "reason": reason,
                "allocated_bytes": allocated_bytes,
            }
        )

    return {
        "schema": "norman.tui.tmp-workspace-cleanup.v1",
        "checked_at_epoch": int(checked_at),
        "apply": apply,
        "tmp_root": str(tmp_root),
        "workspace_age_hours": max(1, int(workspace_age_hours)),
        "test_db_age_hours": max(1, int(test_db_age_hours)),
        "candidates": len(candidates),
        "removed": removed,
        "preserved": preserved,
        "errors": errors,
        "reclaimed_bytes": sum(
            int(item.get("allocated_bytes") or 0) for item in removed
        ),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely remove expired, inactive agent workspaces from /tmp."
    )
    parser.add_argument("--tmp-root", type=Path, default=DEFAULT_TMP_ROOT)
    parser.add_argument(
        "--workspace-age-hours",
        type=int,
        default=DEFAULT_WORKSPACE_AGE_HOURS,
    )
    parser.add_argument(
        "--test-db-age-hours",
        type=int,
        default=DEFAULT_TEST_DB_AGE_HOURS,
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = cleanup(
        args.tmp_root,
        apply=args.apply,
        workspace_age_hours=args.workspace_age_hours,
        test_db_age_hours=args.test_db_age_hours,
    )
    _write_json(args.json_output, payload)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "tmp cleanup: candidates={candidates} removed={removed} "
            "preserved={preserved} errors={errors} reclaimed_bytes={reclaimed}".format(
                candidates=payload["candidates"],
                removed=len(payload["removed"]),
                preserved=len(payload["preserved"]),
                errors=len(payload["errors"]),
                reclaimed=payload["reclaimed_bytes"],
            )
        )
    return 1 if payload["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
