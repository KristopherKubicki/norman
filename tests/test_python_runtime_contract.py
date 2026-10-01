"""Runtime-contract checks for the supported Python minor line."""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_project_declares_runtime_and_operational_syntax_contracts() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert (ROOT / ".python-version").read_text().strip() == "3.14"
    assert project["project"]["requires-python"] == ">=3.14,<3.15"
    assert project["tool"]["ruff"]["target-version"] == "py311"


def test_ci_uses_the_declared_python_line() -> None:
    workflow = (ROOT / ".github/workflows/ci_cd.yml").read_text()

    assert "python-version: '3.14'" in workflow
    assert "python-version: '3.11'" not in workflow
