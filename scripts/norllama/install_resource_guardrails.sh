#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
guardrails_root="${repo_root}/scripts/systemd"
live_policy_path="${script_dir}/route_policy.json"
pending_policy_path="${script_dir}/route_policy.next.json"

# The deployment bundle installs this script next to its `systemd/` payload on
# a Spark worker, which does not need a full Norman checkout.
if [[ ! -d "$guardrails_root" && -d "${script_dir}/systemd" ]]; then
  guardrails_root="${script_dir}/systemd"
fi
apply=0
restart=0

usage() {
  cat <<'EOF'
Usage: scripts/norllama/install_resource_guardrails.sh [--apply] [--restart]

Install the staged cgroup and restart guardrails for a Spark Norllama worker.

Without --apply, prints the files that would be installed and makes no change.
--apply requires root and reloads systemd. It does not restart services unless
--restart is also supplied.

Run only after the matching gateway source has been deployed. A restart applies
the cgroup limits to the new processes without rebooting the host. When a
pending route policy is present, activation promotes it only while the gateway
is stopped, then verifies gateway and ASR readiness.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --apply)
      apply=1
      ;;
    --restart)
      restart=1
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

if [[ "$restart" == "1" && "$apply" != "1" ]]; then
  echo "--restart requires --apply." >&2
  exit 2
fi
if [[ "$restart" == "1" && ! -f "$pending_policy_path" ]]; then
  echo "Missing staged route policy: ${pending_policy_path}" >&2
  exit 1
fi

asr_service_candidates=(
  "spark-audio-transcribe-core.service"
  "spark-audio-transcribe.service"
)

select_asr_service() {
  local candidate
  local load_state

  # Prefer the running unit. This keeps a mixed-version worker from receiving
  # guardrails on an unused compatibility service.
  for candidate in "${asr_service_candidates[@]}"; do
    if systemctl is-active --quiet "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  # A stopped worker still needs its guardrails installed for the next start.
  for candidate in "${asr_service_candidates[@]}"; do
    load_state="$(
      systemctl show "$candidate" --property=LoadState --value 2>/dev/null \
        || true
    )"
    if [[ "$load_state" == "loaded" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo "No supported Spark ASR systemd unit is installed." >&2
  return 1
}

source_path_for_unit() {
  local unit="$1"

  case "$unit" in
    norllama-gateway.service)
      printf '%s\n' \
        "${guardrails_root}/norllama-gateway.service.d/zz-resource-guardrails.conf"
      ;;
    spark-audio-transcribe-core.service|spark-audio-transcribe.service)
      # The cgroup envelope is the same for the legacy and core ASR services.
      printf '%s\n' \
        "${guardrails_root}/spark-audio-transcribe-core.service.d/zz-resource-guardrails.conf"
      ;;
    *)
      echo "No guardrail source is defined for ${unit}." >&2
      return 1
      ;;
  esac
}

asr_service="$(select_asr_service)"
units=(
  "norllama-gateway.service"
  "$asr_service"
)

for unit in "${units[@]}"; do
  source_path="$(source_path_for_unit "$unit")"
  [[ -f "$source_path" ]] || {
    echo "Missing guardrail source: ${source_path}" >&2
    exit 1
  }
  destination="/etc/systemd/system/${unit}.d/zz-resource-guardrails.conf"
  if [[ "$apply" != "1" ]]; then
    printf 'would install %s -> %s\n' "$source_path" "$destination"
  fi
done

if [[ "$apply" != "1" ]]; then
  echo "Dry run only. Re-run as root with --apply after validating the worker."
  exit 0
fi

if [[ "$EUID" -ne 0 ]]; then
  echo "--apply must run as root." >&2
  exit 1
fi

for unit in "${units[@]}"; do
  source_path="$(source_path_for_unit "$unit")"
  install -D -o root -g root -m 0644 \
    "$source_path" \
    "/etc/systemd/system/${unit}.d/zz-resource-guardrails.conf"
done

systemctl daemon-reload

if [[ "$restart" != "1" ]]; then
  echo "Guardrails installed for ${asr_service}. Restart it and Norllama during a maintenance window to apply cgroup limits."
  exit 0
fi

python3 -m json.tool "$pending_policy_path" >/dev/null
policy_backup_path="${live_policy_path}.pre-activation.$(date -u +%Y%m%dT%H%M%SZ)"
policy_owner="$(stat -c '%u:%g' "$live_policy_path")"
policy_uid="${policy_owner%%:*}"
policy_gid="${policy_owner##*:}"

if ! systemctl restart "$asr_service"; then
  echo "ASR restart failed; gateway policy was not changed." >&2
  exit 1
fi

cp -p "$live_policy_path" "$policy_backup_path"
systemctl stop norllama-gateway.service
install -o "$policy_uid" -g "$policy_gid" -m 0644 \
  "$pending_policy_path" \
  "$live_policy_path"

if ! systemctl start norllama-gateway.service; then
  install -o "$policy_uid" -g "$policy_gid" -m 0644 \
    "$policy_backup_path" \
    "$live_policy_path"
  systemctl start norllama-gateway.service || true
  echo "Gateway start failed; restored the prior policy from ${policy_backup_path}." >&2
  exit 1
fi

ready=0
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:18151/healthz >/dev/null \
    && curl -fsS --max-time 5 http://127.0.0.1:18151/readyz >/dev/null \
    && curl -fsS --max-time 5 http://127.0.0.1:18151/asr-readyz >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" == "1" ]] \
  && ! curl -fsS --max-time 15 http://127.0.0.1:18151/v1/models >/dev/null; then
  ready=0
fi

if [[ "$ready" != "1" ]]; then
  install -o "$policy_uid" -g "$policy_gid" -m 0644 \
    "$policy_backup_path" \
    "$live_policy_path"
  systemctl restart norllama-gateway.service || true
  echo "Gateway did not become ASR-ready; restored the prior policy from ${policy_backup_path}." >&2
  exit 1
fi

rm -f "$pending_policy_path"
systemctl is-active --quiet "$asr_service"
systemctl is-active --quiet norllama-gateway.service

echo "Norllama worker resource guardrails and staged route policy are active."
