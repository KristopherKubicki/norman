#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_path="${repo_root}/scripts/norllama/norllama_gateway.py"

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

Deploy the repo-owned Norllama gateway source to the Mac front door and,
optionally, the Spark peer gateways. The script uses existing SSH credentials
and never embeds secrets.

Environment overrides:
  NORLLAMA_MAC_TARGET       default k@192.168.2.133
  NORLLAMA_MAC_PATH         default /Users/k/norllama/norllama_gateway.py
  NORLLAMA_MAC_SERVICE      default org.lollie.norllama
  NORLLAMA_SPARK_TARGETS    default "kristopher@192.168.2.150 kristopher@192.168.2.151"
  NORLLAMA_SPARK_PATH       default /home/kristopher/norllama/norllama_gateway.py
  NORLLAMA_SPARK_SERVICE    default norllama-gateway.service
EOF
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

python3 -m py_compile "$source_path"

if [[ "$deploy_mac" == "1" ]]; then
  echo "Deploying Mac front door: ${mac_target}:${mac_path}"
  scp -q "$source_path" "${mac_target}:${mac_path}"
  ssh "$mac_target" \
    "python3 -m py_compile '$mac_path' && launchctl kickstart -k gui/\$(id -u)/'$mac_service' && sleep 2 && curl -fsS --max-time 5 http://127.0.0.1:18151/healthz >/dev/null"
fi

if [[ "$deploy_sparks" == "1" ]]; then
  for target in $spark_targets; do
    echo "Deploying Spark peer: ${target}:${spark_path}"
    scp -q "$source_path" "${target}:${spark_path}"
    ssh "$target" "python3 -m py_compile '$spark_path'"
    if ! ssh "$target" \
      "sudo -n systemctl restart '$spark_service' && sleep 2 && curl -fsS --max-time 5 http://127.0.0.1:18151/healthz >/dev/null"; then
      echo \
        "Gateway source copied to ${target}, but ${spark_service} requires an operator-approved sudo restart." \
        >&2
      spark_restart_failed=1
    fi
  done
fi

if [[ "$spark_restart_failed" == "1" ]]; then
  exit 1
fi

echo "Norllama gateway deploy complete."
