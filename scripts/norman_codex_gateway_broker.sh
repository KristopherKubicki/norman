#!/usr/bin/env bash
set -euo pipefail

readonly BROKER_HOST="${NORMAN_CODEX_GATEWAY_BROKER_HOST:-192.168.2.241}"
readonly BROKER_USER="${NORMAN_CODEX_GATEWAY_BROKER_USER:-kristopher}"
readonly BROKER_COMMAND="/usr/local/sbin/norman-codex-gateway-broker"
readonly CONNECT_TIMEOUT="${NORMAN_CODEX_GATEWAY_BROKER_CONNECT_TIMEOUT_SECONDS:-5}"

if [[ "$#" -ne 2 || "$1" != "get" || -z "$2" ]]; then
  echo "Usage: norman_codex_gateway_broker.sh get <logical-secret-name>" >&2
  exit 2
fi

is_local_broker_host() {
  case "$BROKER_HOST" in
    localhost|127.0.0.1|::1|"$(hostname)"|"$(hostname -f)")
      return 0
      ;;
  esac

  command -v getent >/dev/null 2>&1 || return 1
  command -v ip >/dev/null 2>&1 || return 1

  while read -r address; do
    [[ -n "$address" ]] || continue
    if ip -o -4 addr show | awk '{print $4}' | cut -d/ -f1 | grep -Fqx "$address"; then
      return 0
    fi
  done < <(getent ahostsv4 "$BROKER_HOST" 2>/dev/null | awk '{print $1}' | sort -u)

  return 1
}

if is_local_broker_host; then
  exec sudo --non-interactive "$BROKER_COMMAND" "$1" "$2"
fi

exec ssh \
  -o BatchMode=yes \
  -o "ConnectTimeout=${CONNECT_TIMEOUT}" \
  -o LogLevel=ERROR \
  -l "$BROKER_USER" \
  "$BROKER_HOST" \
  sudo --non-interactive "$BROKER_COMMAND" "$1" "$2"
