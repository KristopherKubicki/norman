import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import codex_route
from scripts import codex_route_proof


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = REPO_ROOT / "scripts" / "install_codex_route.sh"
REGULAR_WRAPPER_PATH = REPO_ROOT / "scripts" / "codex_cli_wrapper.sh"
WORK_WRAPPER_PATH = REPO_ROOT / "scripts" / "codex_work_wrapper.sh"


def test_route_proof_reports_selected_routes_in_configured_order():
    selected = codex_route_proof.select_routes(["norman", "infra"])
    calls = []

    def verify(route):
        calls.append(route.key)
        return route.key != "infra", f"{route.key} result"

    results = codex_route_proof.prove_routes(
        selected,
        dry_run=False,
        parallelism=1,
        verifier=verify,
    )
    payload = codex_route_proof.report_payload(results, dry_run=False)

    assert calls == ["infra", "norman"]
    assert [result["route"] for result in results] == ["infra", "norman"]
    assert payload["ok"] is False
    assert payload["summary"] == {"total": 2, "successful": 1, "failed": 1}
    assert all("token-real-value" not in str(result) for result in results)


def test_route_proof_dry_run_writes_only_route_metadata(tmp_path, monkeypatch):
    output_path = tmp_path / "proof.json"
    monkeypatch.setattr(
        codex_route_proof,
        "prove_routes",
        lambda routes, **_kwargs: [
            {
                "route": route.key,
                "launcher": route.launcher,
                "endpoint": route.endpoint,
                "token_secret": route.resolved_token_secret,
                "ok": True,
                "detail": "verification planned",
            }
            for route in routes
        ],
    )

    assert (
        codex_route_proof.main(
            [
                "--route",
                "infra",
                "--dry-run",
                "--output-json",
                str(output_path),
            ]
        )
        == 0
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["routes"][0]["route"] == "infra"
    assert payload["routes"][0]["endpoint"] == "https://infra.kris.openbrand.com/v1"
    assert "Bearer " not in output_path.read_text(encoding="utf-8")


def test_route_proof_retries_only_until_a_route_succeeds():
    selected = codex_route_proof.select_routes(["norman"])
    calls = []

    def verify(route):
        calls.append(route.key)
        return len(calls) == 2, "transient gateway timeout"

    results = codex_route_proof.prove_routes(
        selected,
        dry_run=False,
        parallelism=1,
        attempts=2,
        verifier=verify,
    )

    assert calls == ["norman", "norman"]
    assert results[0]["ok"] is True
    assert results[0]["attempts"] == 2


def test_installer_creates_private_runtime_and_idempotent_shell_path(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bash_profile").write_text(
        'export PATH="$HOME/.nvm/bin:$PATH"\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    for _ in range(2):
        result = subprocess.run(
            [str(INSTALLER_PATH)],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    lib_dir = home / ".local" / "lib" / "norman-codex-route"
    bin_dir = home / ".local" / "bin"
    assert (lib_dir / "codex_route.py").is_file()
    assert (lib_dir / "norman_codex_gateway_token.py").is_file()
    assert (lib_dir / "norman_codex_gateway_broker.sh").is_file()
    assert (bin_dir / "codex").is_file()
    assert (bin_dir / "codex-work").is_file()
    assert stat.S_IMODE((bin_dir / "codex").stat().st_mode) == 0o700
    assert stat.S_IMODE((bin_dir / "codex-work").stat().st_mode) == 0o700
    assert (home / ".bashrc").read_text(encoding="utf-8").count(
        'export PATH="$HOME/.local/bin:$PATH"'
    ) == 1
    assert (home / ".bash_profile").read_text(encoding="utf-8").count(
        'export PATH="$HOME/.local/bin:$PATH"'
    ) == 1

    router = subprocess.run(
        [
            sys.executable,
            str(lib_dir / "codex_route.py"),
            "--launcher",
            "regular",
            "--routes",
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert router.returncode == 0, router.stderr
    routes = json.loads(router.stdout)
    assert any(
        route["route"] == "infra" and route["launcher"] == "work" for route in routes
    )


@pytest.mark.parametrize(
    ("wrapper_path", "launcher"),
    (
        (REGULAR_WRAPPER_PATH, "regular"),
        (WORK_WRAPPER_PATH, "work"),
    ),
)
def test_wrappers_dispatch_router_diagnostics_before_starting_codex(
    tmp_path, wrapper_path, launcher
):
    router = tmp_path / "router.py"
    router.write_text(
        "import json\nimport sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["CODEX_ROUTER_SCRIPT"] = str(router)

    result = subprocess.run(
        [str(wrapper_path), "--verify", "--cd", "/tmp/networking"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "--launcher",
        launcher,
        "--verify",
        "--",
        "--cd",
        "/tmp/networking",
    ]
