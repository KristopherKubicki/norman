from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "norllama" / "install_macos_launchd_guardrails.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "install_macos_launchd_guardrails",
        SCRIPT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_guarded_plist_preserves_gateway_settings_and_adds_launchd_limits() -> None:
    module = _load_module()
    original = {
        "Label": "org.lollie.norllama",
        "ProgramArguments": ["/Users/k/norllama/norllama_launchd_wrapper.sh"],
        "EnvironmentVariables": {"NORLLAMA_PORT": "18151"},
        "KeepAlive": True,
        "ExitTimeOut": 20,
        "SoftResourceLimits": {"NumberOfFiles": 8192},
        "HardResourceLimits": {"NumberOfFiles": 65536},
    }

    guarded = module.guarded_plist(original)

    assert guarded["ProgramArguments"] == original["ProgramArguments"]
    assert guarded["EnvironmentVariables"] == original["EnvironmentVariables"]
    assert guarded["KeepAlive"] == {"SuccessfulExit": False}
    assert guarded["ProcessType"] == "Background"
    assert guarded["ThrottleInterval"] == 15
    assert guarded["ExitTimeOut"] == 30
    assert guarded["SoftResourceLimits"] == {
        "NumberOfFiles": 8192,
        "ResidentSetSize": 3 * 1024 * 1024 * 1024,
    }
    assert guarded["HardResourceLimits"] == {
        "NumberOfFiles": 65536,
        "ResidentSetSize": 4 * 1024 * 1024 * 1024,
    }


def test_write_guarded_plist_keeps_valid_plist_and_creates_backup(
    tmp_path: Path,
) -> None:
    module = _load_module()
    plist_path = tmp_path / "org.lollie.norllama.plist"
    with plist_path.open("wb") as stream:
        plistlib.dump(
            {
                "Label": "org.lollie.norllama",
                "ProgramArguments": ["/Users/k/norllama/norllama_launchd_wrapper.sh"],
            },
            stream,
        )

    backup_path = module.write_guarded_plist(plist_path, "org.lollie.norllama")

    assert backup_path.is_file()
    with plist_path.open("rb") as stream:
        guarded = plistlib.load(stream)
    assert guarded["ThrottleInterval"] == 15
    assert guarded["HardResourceLimits"]["ResidentSetSize"] == 4 * 1024 * 1024 * 1024


def test_restore_plist_reinstates_backup(tmp_path: Path) -> None:
    module = _load_module()
    plist_path = tmp_path / "org.lollie.norllama.plist"
    original = {
        "Label": "org.lollie.norllama",
        "ProgramArguments": ["/Users/k/norllama/norllama_launchd_wrapper.sh"],
    }
    with plist_path.open("wb") as stream:
        plistlib.dump(original, stream)

    backup_path = module.write_guarded_plist(plist_path, "org.lollie.norllama")
    module.restore_plist(plist_path, backup_path)

    with plist_path.open("rb") as stream:
        restored = plistlib.load(stream)
    assert restored == original


def test_failed_restart_restores_and_reloads_prior_plist(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    plist_path = tmp_path / "org.lollie.norllama.plist"
    original = {
        "Label": "org.lollie.norllama",
        "ProgramArguments": ["/Users/k/norllama/norllama_launchd_wrapper.sh"],
    }
    with plist_path.open("wb") as stream:
        plistlib.dump(original, stream)

    reloads = []
    readiness = iter((False, True))
    monkeypatch.setattr(
        module,
        "reload_job",
        lambda label, path: reloads.append((label, path)),
    )
    monkeypatch.setattr(module, "wait_for_ready", lambda port: next(readiness))

    result = module.main(
        [
            "--apply",
            "--restart",
            "--plist",
            str(plist_path),
        ]
    )

    assert result == 1
    assert len(reloads) == 2
    with plist_path.open("rb") as stream:
        assert plistlib.load(stream) == original
    assert "Restored the prior plist" in capsys.readouterr().err


def test_reload_job_retries_bootstrap_after_teardown(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    launchctl = tmp_path / "launchctl"
    launchctl.touch()
    calls = []
    bootstrap_attempts = 0

    monkeypatch.setattr(
        module,
        "time",
        type("Clock", (), {"sleep": staticmethod(lambda _: None)}),
    )

    def fake_run(command, check):
        nonlocal bootstrap_attempts
        calls.append((command, check))
        if command[1] == "bootstrap":
            bootstrap_attempts += 1
            if bootstrap_attempts < 3:
                raise subprocess.CalledProcessError(5, command)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "Path", lambda value: launchctl)

    module.reload_job(
        "org.lollie.norllama",
        tmp_path / "org.lollie.norllama.plist",
    )

    assert calls[0][0][1] == "bootout"
    assert calls[0][1] is False
    assert bootstrap_attempts == 3
