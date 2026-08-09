#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_path="${repo_root}/scripts/norllama/norllama_gateway.py"
python_bin="${NORMAN_PYTHON:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -x "${repo_root}/.venv/bin/python" ]]; then
    python_bin="${repo_root}/.venv/bin/python"
  else
    python_bin="python3"
  fi
fi

runtime_package_files=(
  "${repo_root}/app/services/norllama/route_policy.py"
  "${repo_root}/app/services/norllama/route_policy_artifact.py"
)
temp_policy_path=""

mac_target="${NORLLAMA_MAC_TARGET:-k@192.168.2.133}"
mac_path="${NORLLAMA_MAC_PATH:-/Users/k/norllama/norllama_gateway.py}"
mac_service="${NORLLAMA_MAC_SERVICE:-org.lollie.norllama}"

spark_targets="${NORLLAMA_SPARK_TARGETS:-kristopher@192.168.2.150 kristopher@192.168.2.151}"
spark_path="${NORLLAMA_SPARK_PATH:-/home/kristopher/norllama/norllama_gateway.py}"
spark_service="${NORLLAMA_SPARK_SERVICE:-norllama-gateway.service}"

deploy_mac=1
deploy_sparks=0
spark_restart_failed=0

usage() {
  cat <<'EOF'
Usage: scripts/norllama/deploy_gateway.sh [--mac-only|--sparks|--all]

Deploy the repo-owned Norllama gateway and its matching route-policy runtime
to the Mac front door and, optionally, the Spark peer gateways. The script
stages and validates the bundle before publishing it, uses existing SSH
credentials, and never embeds secrets.

Environment overrides:
  NORMAN_PYTHON              local Python interpreter for policy generation
  NORLLAMA_MAC_TARGET       default k@192.168.2.133
  NORLLAMA_MAC_PATH         default /Users/k/norllama/norllama_gateway.py
  NORLLAMA_MAC_SERVICE      default org.lollie.norllama
  NORLLAMA_SPARK_TARGETS    default "kristopher@192.168.2.150 kristopher@192.168.2.151"
  NORLLAMA_SPARK_PATH       default /home/kristopher/norllama/norllama_gateway.py
  NORLLAMA_SPARK_SERVICE    default norllama-gateway.service
EOF
}

cleanup() {
  if [[ -n "$temp_policy_path" ]]; then
    rm -f "$temp_policy_path"
  fi
}

cleanup_remote_stage() {
  local target="$1"
  local stage_path="$2"

  ssh "$target" "rm -rf '$stage_path'" >/dev/null 2>&1 || true
}

stage_worker_bundle() {
  local target="$1"
  local gateway_path="$2"
  local worker_root
  local stage_path

  worker_root="$(dirname "$gateway_path")"
  stage_path="$(ssh "$target" "mktemp -d '${worker_root}/.norllama-deploy.XXXXXX'")"

  if ! ssh "$target" \
    "mkdir -p '$stage_path/app/services/norllama'"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi

  if ! scp -q "$source_path" \
    "${target}:${stage_path}/norllama_gateway.py"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q "$temp_policy_path" \
    "${target}:${stage_path}/route_policy.json"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q \
    "${repo_root}/app/services/norllama/route_policy.py" \
    "${repo_root}/app/services/norllama/route_policy_artifact.py" \
    "${target}:${stage_path}/app/services/norllama/"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi

  if ! ssh "$target" "sh -s -- '$stage_path'" >&2 <<'REMOTE'
set -eu
stage_path="$1"

python3 -m py_compile \
  "$stage_path/norllama_gateway.py" \
  "$stage_path/app/services/norllama/route_policy.py" \
  "$stage_path/app/services/norllama/route_policy_artifact.py"

NORMAN_NORLLAMA_ROUTE_POLICY_PATH="$stage_path/route_policy.json" \
  python3 - "$stage_path" <<'PY'
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


stage_path = Path(sys.argv[1])


def register_package(name: str, path: Path) -> None:
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    package.__package__ = name
    sys.modules[name] = package


def load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load staged module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


register_package("app", stage_path / "app")
register_package("app.services", stage_path / "app" / "services")
register_package(
    "app.services.norllama",
    stage_path / "app" / "services" / "norllama",
)
route_policy = load_module(
    "app.services.norllama.route_policy",
    stage_path / "app" / "services" / "norllama" / "route_policy.py",
)
route_policy_artifact = load_module(
    "app.services.norllama.route_policy_artifact",
    stage_path / "app" / "services" / "norllama" / "route_policy_artifact.py",
)
loaded = route_policy_artifact.load_route_policy_artifact(
    stage_path / "route_policy.json",
    allow_missing_default=False,
)
validation = loaded["validation"]
lifecycle = route_policy.route_policy_lifecycle(loaded["artifact"])
print(
    json.dumps(
        {"validation": validation, "lifecycle": lifecycle},
        sort_keys=True,
    ),
    file=sys.stderr,
)
raise SystemExit(
    0
    if (
        validation.get("integrity_valid")
        and validation.get("default_route_allowed")
        and lifecycle.get("integrity_valid")
        and lifecycle.get("default_route_allowed")
    )
    else 1
)
PY
REMOTE
  then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi

  printf '%s\n' "$stage_path"
}

publish_worker_bundle() {
  local target="$1"
  local gateway_path="$2"
  local stage_path="$3"
  local worker_root
  local policy_path

  worker_root="$(dirname "$gateway_path")"
  policy_path="${worker_root}/route_policy.json"

  ssh "$target" \
    "set -eu
     mkdir -p '$worker_root/app/services/norllama'
     mv '$stage_path/app/services/norllama/route_policy.py' '$worker_root/app/services/norllama/route_policy.py'
     mv '$stage_path/app/services/norllama/route_policy_artifact.py' '$worker_root/app/services/norllama/route_policy_artifact.py'
     mv '$stage_path/norllama_gateway.py' '$gateway_path'
     mv '$stage_path/route_policy.json' '$policy_path'
     rm -rf '$stage_path'"
}

deploy_worker_bundle() {
  local target="$1"
  local gateway_path="$2"
  local stage_path

  if ! stage_path="$(stage_worker_bundle "$target" "$gateway_path")"; then
    return 1
  fi
  if ! publish_worker_bundle "$target" "$gateway_path" "$stage_path"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
}

restart_mac_gateway() {
  ssh "$mac_target" "sh -s -- '$mac_service'" <<'REMOTE'
set -eu
service="$1"
launchctl kickstart -k "gui/$(id -u)/${service}"
attempt=1
while [ "$attempt" -le 15 ]; do
  if curl -fsS --max-time 5 http://127.0.0.1:18151/healthz >/dev/null \
    && curl -fsS --max-time 5 http://127.0.0.1:18151/readyz >/dev/null \
    && curl -fsS --max-time 5 http://127.0.0.1:18151/v1/models >/dev/null; then
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done
exit 1
REMOTE
}

restart_spark_gateway() {
  local target="$1"

  ssh "$target" "sh -s -- '$spark_service'" <<'REMOTE'
set -eu
service="$1"
sudo -n systemctl restart "$service"
attempt=1
while [ "$attempt" -le 15 ]; do
  if curl -fsS --max-time 5 http://127.0.0.1:18151/healthz >/dev/null \
    && curl -fsS --max-time 5 http://127.0.0.1:18151/readyz >/dev/null \
    && curl -fsS --max-time 5 http://127.0.0.1:18151/v1/models >/dev/null; then
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done
exit 1
REMOTE
}

for arg in "$@"; do
  case "$arg" in
    --mac-only)
      deploy_mac=1
      deploy_sparks=0
      ;;
    --sparks)
      deploy_mac=0
      deploy_sparks=1
      ;;
    --all)
      deploy_mac=1
      deploy_sparks=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

for runtime_file in "${runtime_package_files[@]}"; do
  if [[ ! -f "$runtime_file" ]]; then
    echo "Missing Norllama runtime file: $runtime_file" >&2
    exit 1
  fi
done

temp_policy_path="$(mktemp "${repo_root}/scripts/norllama/route_policy.XXXXXX.json")"
trap cleanup EXIT
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" \
  "$python_bin" "${repo_root}/scripts/norllama/refresh_route_policy.py" --path "$temp_policy_path"
"$python_bin" -m py_compile "$source_path" "${runtime_package_files[@]}"

if [[ "$deploy_mac" == "1" ]]; then
  echo "Deploying validated Mac front-door bundle: ${mac_target}:${mac_path}"
  deploy_worker_bundle "$mac_target" "$mac_path"
  restart_mac_gateway
fi

if [[ "$deploy_sparks" == "1" ]]; then
  for target in $spark_targets; do
    echo "Deploying validated Spark peer bundle: ${target}:${spark_path}"
    if ! deploy_worker_bundle "$target" "$spark_path"; then
      echo \
        "Gateway bundle was not published to ${target}; its staging or validation step failed." \
        >&2
      spark_restart_failed=1
      continue
    fi
    if ! restart_spark_gateway "$target"; then
      echo \
        "Gateway bundle published to ${target}, but ${spark_service} did not restart ready; operator-approved recovery is required." \
        >&2
      spark_restart_failed=1
    fi
  done
fi

if [[ "$spark_restart_failed" == "1" ]]; then
  exit 1
fi

echo "Norllama gateway deploy complete."
