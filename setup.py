from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib

from setuptools import setup, find_packages


def _load_pyproject() -> dict:
    pyproject_path = Path(__file__).with_name("pyproject.toml")
    with pyproject_path.open("rb") as handle:
        return tomllib.load(handle)


pyproject = _load_pyproject()
project = pyproject.get("project", {})

setup(
    name=project.get("name", "norman"),
    version=project.get("version", "0.2.0"),
    packages=find_packages(),
    install_requires=project.get("dependencies", []),
    extras_require=project.get("optional-dependencies", {}),
    entry_points={
        "console_scripts": [
            "norman = main:main",
        ],
    },
)
