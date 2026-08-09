from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts" / "systemd" / "norman-release-python"
RELEASE_SHA = "0123456789abcdef"


def _fake_python(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {marker!r}\nprintf 'arguments=%s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_resolver(
    releases_dir: Path, *arguments: str, release_sha: str = RELEASE_SHA
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "NORMAN_RELEASES_DIR": str(releases_dir),
        "NORMAN_RELEASE_SHA": release_sha,
    }
    return subprocess.run(
        ["bash", str(RESOLVER), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_release_resolver_prefers_the_canonical_venv(tmp_path: Path) -> None:
    release_root = tmp_path / f"norman-{RELEASE_SHA}"
    _fake_python(release_root / ".venv" / "bin" / "python", "canonical")
    _fake_python(release_root / ".venv-3.10" / "bin" / "python", "legacy")

    result = _run_resolver(tmp_path, RELEASE_SHA, "-c", "pass")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "canonical\narguments=-c pass\n"


def test_release_resolver_accepts_one_legacy_venv_for_rollback(tmp_path: Path) -> None:
    release_root = tmp_path / f"norman-{RELEASE_SHA}"
    _fake_python(release_root / ".venv-3.10" / "bin" / "python", "legacy")
    broker = release_root / "scripts" / "broker.py"
    broker.parent.mkdir()
    broker.write_text("print('unused')\n", encoding="utf-8")

    result = _run_resolver(
        tmp_path,
        "--current",
        "--release-script",
        "scripts/broker.py",
        "get",
        "networking/bedrock-mantle",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        f"legacy\narguments={broker} get networking/bedrock-mantle\n"
    )


def test_release_resolver_rejects_ambiguous_legacy_virtualenvs(tmp_path: Path) -> None:
    release_root = tmp_path / f"norman-{RELEASE_SHA}"
    _fake_python(release_root / ".venv-3.10" / "bin" / "python", "legacy-310")
    _fake_python(release_root / ".venv-3.11" / "bin" / "python", "legacy-311")

    result = _run_resolver(tmp_path, RELEASE_SHA, "-c", "pass")

    assert result.returncode == 1
    assert "multiple legacy virtualenvs" in result.stderr


def test_release_resolver_rejects_script_paths_outside_the_release(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / f"norman-{RELEASE_SHA}"
    _fake_python(release_root / ".venv" / "bin" / "python", "canonical")

    result = _run_resolver(
        tmp_path,
        RELEASE_SHA,
        "--release-script",
        "scripts/../outside.py",
        "get",
    )

    assert result.returncode == 1
    assert "invalid path segment" in result.stderr


def test_release_resolver_has_valid_shell_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(RESOLVER)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
