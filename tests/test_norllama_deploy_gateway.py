from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "norllama" / "deploy_gateway.sh"
INSTALLER = ROOT / "scripts" / "norllama" / "install_resource_guardrails.sh"
MAC_INSTALLER = ROOT / "scripts" / "norllama" / "install_macos_launchd_guardrails.py"
PRIORITY_WATCHDOG = (
    ROOT / "scripts" / "norllama" / "ensure_resident_priority_gateway.sh"
)


def _write_fake_worker_transport(bin_dir: Path) -> None:
    ssh = bin_dir / "ssh"
    ssh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
shift
exec /bin/sh -c "$1"
""",
        encoding="utf-8",
    )
    ssh.chmod(0o755)

    scp = bin_dir / "scp"
    scp.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-q" ]]; then
  shift
fi
destination="${!#}"
destination="${destination#*:}"
sources=("${@:1:$#-1}")
cp "${sources[@]}" "$destination"
""",
        encoding="utf-8",
    )
    scp.chmod(0o755)

    for command in ("curl", "launchctl"):
        path = bin_dir / command
        path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)


def test_deploy_gateway_help_is_dependency_free_and_script_is_valid() -> None:
    syntax = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr

    help_result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "matching route-policy runtime" in help_result.stdout


def test_deploy_gateway_stages_runtime_and_uses_safe_restart_transport() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "stage_worker_bundle()" in source
    assert "route_policy_artifact.py" in source
    assert "config/norllama/model_roles.json" in source
    assert "install_resource_guardrails.sh" in source
    assert "install_macos_launchd_guardrails.py" in source
    assert "--sparks-no-restart" in source
    assert "route_policy.next.json" in source
    assert "stat -c '%u:%g'" in (INSTALLER.read_text(encoding="utf-8"))
    assert "app/services/__init__.py" not in source
    assert "importlib.util.spec_from_file_location" in source
    assert 'ssh "$target" "sh -s -- \'$stage_path\'" >&2' in source
    assert 'ssh "$mac_target" \\' in source
    assert "sh -s -- '$mac_service' '$mac_curl_bin'" in source
    assert '"$curl_bin" -fsS --max-time 5 http://127.0.0.1:18151/readyz' in source
    assert '"$curl_bin" -fsS --max-time 10 http://127.0.0.1:18151/v1/models' in source
    assert '"$curl_bin" -fsS --max-time 5 http://127.0.0.1:18151/asr-readyz' in source


def test_priority_gateway_watchdog_requires_policy_readiness() -> None:
    source = PRIORITY_WATCHDOG.read_text(encoding="utf-8")

    assert source.count('"$BASE_URL/readyz"') == 2
    assert '"$BASE_URL/healthz"' not in source


def test_deploy_gateway_publishes_complete_runtime_bundle_to_worker(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_worker_transport(bin_dir)
    worker_root = tmp_path / "worker"
    worker_root.mkdir()

    result = subprocess.run(
        ["bash", str(SCRIPT), "--mac-only"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={
            "NORMAN_PYTHON": sys.executable,
            "NORLLAMA_MAC_TARGET": "fake-worker",
            "NORLLAMA_MAC_PATH": str(worker_root / "norllama_gateway.py"),
            "NORLLAMA_MAC_CURL_BIN": str(bin_dir / "curl"),
            "PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (worker_root / "norllama_gateway.py").is_file()
    assert (worker_root / "route_policy.json").is_file()
    assert (worker_root / "app" / "services" / "norllama" / "route_policy.py").is_file()
    assert (
        worker_root / "app" / "services" / "norllama" / "route_policy_artifact.py"
    ).is_file()
    assert (worker_root / "config" / "norllama" / "model_roles.json").is_file()
    assert (worker_root / "install_resource_guardrails.sh").is_file()
    assert (worker_root / "install_macos_launchd_guardrails.py").is_file()
    assert (
        worker_root
        / "systemd"
        / "norllama-gateway.service.d"
        / "zz-resource-guardrails.conf"
    ).is_file()
    assert (
        worker_root
        / "systemd"
        / "spark-audio-transcribe-core.service.d"
        / "zz-resource-guardrails.conf"
    ).is_file()


def test_spark_no_restart_defers_route_policy_activation(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_worker_transport(bin_dir)
    worker_root = tmp_path / "worker"
    worker_root.mkdir()
    live_policy = worker_root / "route_policy.json"
    live_policy.write_text('{"version":"legacy"}\n', encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SCRIPT), "--sparks-no-restart"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={
            "NORMAN_PYTHON": sys.executable,
            "NORLLAMA_SPARK_TARGETS": "fake-worker",
            "NORLLAMA_SPARK_PATH": str(worker_root / "norllama_gateway.py"),
            "PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert live_policy.read_text(encoding="utf-8") == '{"version":"legacy"}\n'
    assert (worker_root / "route_policy.next.json").is_file()


def test_resource_guardrail_installer_supports_legacy_asr_unit(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
last="${!#}"
case "${1:-}" in
  is-active)
    [[ "$last" == "spark-audio-transcribe.service" ]]
    ;;
  show)
    if [[ "$last" == "spark-audio-transcribe.service" ]]; then
      printf 'loaded\\n'
    else
      printf 'not-found\\n'
    fi
    ;;
  *)
    exit 1
    ;;
esac
""",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)

    result = subprocess.run(
        ["bash", str(INSTALLER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}"},
    )

    assert result.returncode == 0, result.stderr
    assert (
        "spark-audio-transcribe.service.d/zz-resource-guardrails.conf" in result.stdout
    )
