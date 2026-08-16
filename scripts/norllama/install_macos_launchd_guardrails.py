#!/usr/bin/env python3
"""Install bounded launchd settings for the Mac mini Norllama gateway."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


DEFAULT_LABEL = "org.lollie.norllama"
DEFAULT_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{DEFAULT_LABEL}.plist"
DEFAULT_PORT = 18151
SOFT_RSS_BYTES = 3 * 1024 * 1024 * 1024
HARD_RSS_BYTES = 4 * 1024 * 1024 * 1024


def _positive_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _at_least(limits: dict[str, Any], key: str, value: int) -> None:
    limits[key] = max(_positive_int(limits.get(key)), value)


def guarded_plist(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with Norllama's launchd recovery controls."""

    result = dict(payload)
    result["KeepAlive"] = {"SuccessfulExit": False}
    result["ProcessType"] = "Background"
    result["ThrottleInterval"] = max(
        _positive_int(result.get("ThrottleInterval")),
        15,
    )
    result["ExitTimeOut"] = max(_positive_int(result.get("ExitTimeOut")), 30)

    soft = dict(result.get("SoftResourceLimits") or {})
    hard = dict(result.get("HardResourceLimits") or {})
    _at_least(soft, "NumberOfFiles", 8192)
    _at_least(hard, "NumberOfFiles", 65536)
    _at_least(soft, "ResidentSetSize", SOFT_RSS_BYTES)
    _at_least(hard, "ResidentSetSize", HARD_RSS_BYTES)
    result["SoftResourceLimits"] = soft
    result["HardResourceLimits"] = hard
    return result


def load_plist(path: Path, label: str) -> dict[str, Any]:
    with path.open("rb") as stream:
        payload = plistlib.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not contain a plist dictionary")
    if payload.get("Label") != label:
        raise ValueError(
            f"{path} has Label={payload.get('Label')!r}, expected {label!r}"
        )
    return payload


def write_guarded_plist(path: Path, label: str) -> Path:
    payload = guarded_plist(load_plist(path, label))
    source_stat = path.stat()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(f"{path.name}.bak-{stamp}-before-resource-guardrails")
    shutil.copy2(path, backup_path)

    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temp_path = Path(stream.name)
        plistlib.dump(payload, stream, fmt=plistlib.FMT_XML, sort_keys=False)

    try:
        os.chmod(temp_path, source_stat.st_mode)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return backup_path


def reload_job(label: str, plist_path: Path) -> None:
    launchctl = Path("/bin/launchctl")
    if not launchctl.is_file():
        raise RuntimeError("launchctl is not available at /bin/launchctl")
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{label}"
    subprocess.run(
        [str(launchctl), "bootout", service],
        check=False,
    )
    bootstrap_command = [str(launchctl), "bootstrap", domain, str(plist_path)]
    last_error: Optional[subprocess.CalledProcessError] = None
    for attempt in range(30):
        try:
            subprocess.run(bootstrap_command, check=True)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt < 29:
                time.sleep(1)
    raise RuntimeError(
        "launchd did not finish removing the previous " f"{label} job before bootstrap"
    ) from last_error


def endpoint_ready(port: int) -> bool:
    for path in ("healthz", "readyz", "asr-readyz", "v1/models"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/{path}",
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status != 200:
                    return False
        except (OSError, urllib.error.URLError):
            return False
    return True


def wait_for_ready(port: int) -> bool:
    for _ in range(30):
        if endpoint_ready(port):
            return True
        time.sleep(1)
    return False


def restore_plist(path: Path, backup_path: Path) -> None:
    shutil.copy2(backup_path, path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install Mac mini Norllama launchd guardrails."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--plist", type=Path, default=DEFAULT_PLIST_PATH)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.restart and not args.apply:
        print("--restart requires --apply.", file=sys.stderr)
        return 2
    if not args.plist.is_file():
        print(f"Missing launchd plist: {args.plist}", file=sys.stderr)
        return 1

    try:
        current = load_plist(args.plist, args.label)
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not args.apply:
        updated = guarded_plist(current)
        print(f"would update {args.plist}")
        for key in (
            "KeepAlive",
            "ProcessType",
            "ThrottleInterval",
            "ExitTimeOut",
            "SoftResourceLimits",
            "HardResourceLimits",
        ):
            print(f"{key}={updated[key]!r}")
        print("Dry run only. Re-run with --apply after validating the Mac mini.")
        return 0

    backup_path: Optional[Path] = None
    try:
        backup_path = write_guarded_plist(args.plist, args.label)
        if args.restart:
            reload_job(args.label, args.plist)
            if not wait_for_ready(args.port):
                raise RuntimeError(
                    "Norllama did not become ASR-ready after the launchd reload"
                )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        recovery_message = ""
        if backup_path is not None and args.restart:
            try:
                restore_plist(args.plist, backup_path)
                reload_job(args.label, args.plist)
                if not wait_for_ready(args.port):
                    raise RuntimeError("the restored gateway did not become ready")
                recovery_message = f" Restored the prior plist from {backup_path}."
            except (
                OSError,
                RuntimeError,
                subprocess.CalledProcessError,
            ) as recovery_exc:
                recovery_message = (
                    f" Recovery from {backup_path} also failed: {recovery_exc}."
                )
        print(f"{exc}.{recovery_message}", file=sys.stderr)
        return 1

    if args.restart:
        print("Mac mini Norllama launchd guardrails and gateway are active.")
    else:
        print(
            "Mac mini Norllama launchd guardrails are installed. "
            "Restart the job to apply them."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
