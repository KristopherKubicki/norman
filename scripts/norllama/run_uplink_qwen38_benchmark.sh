#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PHOBOS_ROOT="${PHOBOS_ROOT:-/home/debian/networking/radio/phobos_hunt}"
NORMAN_MODEL_ROLE_CONFIG="${NORMAN_MODEL_ROLE_CONFIG:-${REPO_ROOT}/config/norllama/model_roles.json}"
RESIDENT_BASE_URL="${RESIDENT_BASE_URL:-}"
RESIDENT_NUM_CTX="${RESIDENT_NUM_CTX:-32768}"
export PHOBOS_ROOT NORMAN_MODEL_ROLE_CONFIG RESIDENT_BASE_URL RESIDENT_NUM_CTX

cd "$PHOBOS_ROOT"
exec python3 - "$@" <<'PY'
from dataclasses import replace
from pathlib import Path
import importlib.util
import json
import os
import sys

root = Path(os.environ.get("PHOBOS_ROOT", "/home/debian/networking/radio/phobos_hunt"))
registry_path = Path(os.environ["NORMAN_MODEL_ROLE_CONFIG"])
registry = json.loads(registry_path.read_text(encoding="utf-8"))
resident = registry["roles"]["resident"]
resident_endpoints = resident.get("endpoints") or []
base_url = os.environ.get("RESIDENT_BASE_URL", "").strip()
if not base_url:
    if not resident_endpoints:
        raise SystemExit("resident role has no configured endpoint")
    base_url = str(resident_endpoints[0])
script = root / "scripts" / "run_norman_planner_packet.py"
sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("uplink_planner_benchmark", script)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)

profile_name = "qwen38_27_local"
module.PROFILES[profile_name] = replace(
    module.PROFILES[profile_name],
    model=str(resident["model"]),
    base_url=base_url,
    num_ctx=int(os.environ.get("RESIDENT_NUM_CTX", "32768")),
)

argv = ["--profiles", profile_name, *sys.argv[1:]]
raise SystemExit(module.main(argv))
PY
