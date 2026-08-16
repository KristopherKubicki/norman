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
  "${repo_root}/app/core/estate_registry.py"
  "${repo_root}/app/services/norllama/escalation_policy.py"
  "${repo_root}/app/services/norllama/route_policy.py"
  "${repo_root}/app/services/norllama/route_policy_artifact.py"
)
model_role_config="${repo_root}/config/norllama/model_roles.json"
fleet_topology_config="${repo_root}/config/fleet/topology.json"
guardrail_install_script="${repo_root}/scripts/norllama/install_resource_guardrails.sh"
mac_guardrail_install_script="${repo_root}/scripts/norllama/install_macos_launchd_guardrails.py"
guardrail_files=(
  "${repo_root}/scripts/systemd/norllama-gateway.service.d/zz-resource-guardrails.conf"
  "${repo_root}/scripts/systemd/spark-audio-transcribe-core.service.d/zz-resource-guardrails.conf"
)
temp_policy_path=""

topology_address() {
  "$python_bin" - "$fleet_topology_config" "$1" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload["workers"][sys.argv[2]]["address"])
PY
}

mac_target="${NORLLAMA_MAC_TARGET:-k@$(topology_address mac-mini-133)}"
mac_path="${NORLLAMA_MAC_PATH:-/Users/k/norllama/norllama_gateway.py}"
mac_service="${NORLLAMA_MAC_SERVICE:-org.lollie.norllama}"
mac_curl_bin="${NORLLAMA_MAC_CURL_BIN:-/usr/bin/curl}"

spark_targets="${NORLLAMA_SPARK_TARGETS:-kristopher@$(topology_address spark-150) kristopher@$(topology_address spark-151)}"
spark_path="${NORLLAMA_SPARK_PATH:-/home/kristopher/norllama/norllama_gateway.py}"
spark_service="${NORLLAMA_SPARK_SERVICE:-norllama-gateway.service}"

deploy_mac=1
deploy_sparks=0
restart_sparks=1
spark_restart_failed=0

usage() {
  cat <<'EOF'
Usage: scripts/norllama/deploy_gateway.sh [--mac-only|--sparks|--sparks-no-restart|--all]

Deploy the repo-owned Norllama gateway and its matching route-policy runtime
to the Mac front door and, optionally, the Spark peer gateways. The script
stages and validates the bundle before publishing it, uses existing SSH
credentials, and never embeds secrets.

`--sparks-no-restart` publishes the Spark gateway and the co-located resource
guardrail installer but leaves services running and preserves the live policy.
It writes the new policy as `route_policy.next.json`, which the root-owned
activation command promotes only while restarting the gateway.

Mac deployments also stage a launchd guardrail installer. It preserves the
Mac's existing gateway wrapper and environment, but it must be applied from
the Mac user session after deployment.

Environment overrides:
  NORMAN_PYTHON              local Python interpreter for policy generation
  NORLLAMA_MAC_TARGET       default k@192.168.2.133
  NORLLAMA_MAC_PATH         default /Users/k/norllama/norllama_gateway.py
  NORLLAMA_MAC_SERVICE      default org.lollie.norllama
  NORLLAMA_MAC_CURL_BIN     default /usr/bin/curl
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
    "mkdir -p '$stage_path/app/core'
     mkdir -p '$stage_path/app/services/norllama'
     mkdir -p '$stage_path/config/norllama'
     mkdir -p '$stage_path/config/fleet'
     mkdir -p '$stage_path/systemd/norllama-gateway.service.d'
     mkdir -p '$stage_path/systemd/spark-audio-transcribe-core.service.d'"; then
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
    "${repo_root}/app/core/estate_registry.py" \
    "${target}:${stage_path}/app/core/"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q \
    "${repo_root}/app/services/norllama/route_policy.py" \
    "${repo_root}/app/services/norllama/route_policy_artifact.py" \
    "${repo_root}/app/services/norllama/escalation_policy.py" \
    "${target}:${stage_path}/app/services/norllama/"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q "$model_role_config" \
    "${target}:${stage_path}/config/norllama/model_roles.json"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q "$fleet_topology_config" \
    "${target}:${stage_path}/config/fleet/topology.json"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q "$guardrail_install_script" \
    "${target}:${stage_path}/install_resource_guardrails.sh"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q "$mac_guardrail_install_script" \
    "${target}:${stage_path}/install_macos_launchd_guardrails.py"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q "${guardrail_files[0]}" \
    "${target}:${stage_path}/systemd/norllama-gateway.service.d/zz-resource-guardrails.conf"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
  if ! scp -q "${guardrail_files[1]}" \
    "${target}:${stage_path}/systemd/spark-audio-transcribe-core.service.d/zz-resource-guardrails.conf"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi

  if ! ssh "$target" "sh -s -- '$stage_path'" >&2 <<'REMOTE'
set -eu
stage_path="$1"

python3 -m py_compile \
  "$stage_path/norllama_gateway.py" \
  "$stage_path/app/core/estate_registry.py" \
  "$stage_path/app/services/norllama/escalation_policy.py" \
  "$stage_path/app/services/norllama/route_policy.py" \
  "$stage_path/app/services/norllama/route_policy_artifact.py"
bash -n "$stage_path/install_resource_guardrails.sh"
python3 -m py_compile "$stage_path/install_macos_launchd_guardrails.py"
python3 - "$stage_path/config/norllama/model_roles.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["schema"] == "norman.norllama.model-roles.v1"
assert set(payload["roles"]) == {"resident", "economy", "authority", "frontier"}
assert all(payload["roles"][role]["model"] for role in payload["roles"])
assert payload["roles"]["resident"]["endpoints"]
PY

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
register_package("app.core", stage_path / "app" / "core")
register_package("app.services", stage_path / "app" / "services")
register_package(
    "app.services.norllama",
    stage_path / "app" / "services" / "norllama",
)
load_module(
    "app.core.estate_registry",
    stage_path / "app" / "core" / "estate_registry.py",
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
  local defer_policy="$4"
  local worker_root
  local policy_path

  worker_root="$(dirname "$gateway_path")"
  policy_path="${worker_root}/route_policy.json"
  if [[ "$defer_policy" == "1" ]]; then
    policy_path="${worker_root}/route_policy.next.json"
  fi

  ssh "$target" \
    "set -eu
     mkdir -p '$worker_root/app/services/norllama'
     mkdir -p '$worker_root/app/core'
     mkdir -p '$worker_root/config/norllama'
     mkdir -p '$worker_root/config/fleet'
     mv '$stage_path/app/core/estate_registry.py' '$worker_root/app/core/estate_registry.py'
     mv '$stage_path/app/services/norllama/escalation_policy.py' '$worker_root/app/services/norllama/escalation_policy.py'
     mv '$stage_path/app/services/norllama/route_policy.py' '$worker_root/app/services/norllama/route_policy.py'
     mv '$stage_path/app/services/norllama/route_policy_artifact.py' '$worker_root/app/services/norllama/route_policy_artifact.py'
     mv '$stage_path/config/norllama/model_roles.json' '$worker_root/config/norllama/model_roles.json'
     mv '$stage_path/config/fleet/topology.json' '$worker_root/config/fleet/topology.json'
     mv '$stage_path/norllama_gateway.py' '$gateway_path'
     mv '$stage_path/route_policy.json' '$policy_path'
     mv '$stage_path/install_resource_guardrails.sh' '$worker_root/install_resource_guardrails.sh'
     chmod 0755 '$worker_root/install_resource_guardrails.sh'
     mv '$stage_path/install_macos_launchd_guardrails.py' '$worker_root/install_macos_launchd_guardrails.py'
     chmod 0755 '$worker_root/install_macos_launchd_guardrails.py'
     mkdir -p '$worker_root/systemd/norllama-gateway.service.d'
     mkdir -p '$worker_root/systemd/spark-audio-transcribe-core.service.d'
     mv '$stage_path/systemd/norllama-gateway.service.d/zz-resource-guardrails.conf' '$worker_root/systemd/norllama-gateway.service.d/zz-resource-guardrails.conf'
     mv '$stage_path/systemd/spark-audio-transcribe-core.service.d/zz-resource-guardrails.conf' '$worker_root/systemd/spark-audio-transcribe-core.service.d/zz-resource-guardrails.conf'
     rm -rf '$stage_path'"
}

deploy_worker_bundle() {
  local target="$1"
  local gateway_path="$2"
  local defer_policy="$3"
  local stage_path

  if ! stage_path="$(stage_worker_bundle "$target" "$gateway_path")"; then
    return 1
  fi
  if ! publish_worker_bundle "$target" "$gateway_path" "$stage_path" "$defer_policy"; then
    cleanup_remote_stage "$target" "$stage_path"
    return 1
  fi
}

restart_mac_gateway() {
  ssh "$mac_target" \
    "sh -s -- '$mac_service' '$mac_curl_bin'" <<'REMOTE'
set -eu
service="$1"
curl_bin="$2"
launchctl kickstart -k "gui/$(id -u)/${service}"
attempt=1
while [ "$attempt" -le 15 ]; do
  if "$curl_bin" -fsS --max-time 5 http://127.0.0.1:18151/healthz >/dev/null \
    && "$curl_bin" -fsS --max-time 5 http://127.0.0.1:18151/readyz >/dev/null \
    && "$curl_bin" -fsS --max-time 5 http://127.0.0.1:18151/asr-readyz >/dev/null \
    && "$curl_bin" -fsS --max-time 10 http://127.0.0.1:18151/v1/models >/dev/null; then
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
    && curl -fsS --max-time 5 http://127.0.0.1:18151/asr-readyz >/dev/null \
    && curl -fsS --max-time 10 http://127.0.0.1:18151/v1/models >/dev/null; then
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
      restart_sparks=1
      ;;
    --sparks-no-restart)
      deploy_mac=0
      deploy_sparks=1
      restart_sparks=0
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
if [[ ! -f "$model_role_config" ]]; then
  echo "Missing Norllama model-role registry: $model_role_config" >&2
  exit 1
fi
if [[ ! -f "$guardrail_install_script" ]]; then
  echo "Missing Norllama guardrail installer: $guardrail_install_script" >&2
  exit 1
fi
if [[ ! -f "$mac_guardrail_install_script" ]]; then
  echo "Missing Mac Norllama guardrail installer: $mac_guardrail_install_script" >&2
  exit 1
fi
for guardrail_file in "${guardrail_files[@]}"; do
  if [[ ! -f "$guardrail_file" ]]; then
    echo "Missing Norllama guardrail source: $guardrail_file" >&2
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
  deploy_worker_bundle "$mac_target" "$mac_path" 0
  restart_mac_gateway
fi

if [[ "$deploy_sparks" == "1" ]]; then
  for target in $spark_targets; do
    echo "Deploying validated Spark peer bundle: ${target}:${spark_path}"
    if ! deploy_worker_bundle \
      "$target" \
      "$spark_path" \
      "$((1 - restart_sparks))"; then
      echo \
        "Gateway bundle was not published to ${target}; its staging or validation step failed." \
        >&2
      spark_restart_failed=1
      continue
    fi
    if [[ "$restart_sparks" != "1" ]]; then
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
