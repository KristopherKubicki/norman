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

exec ssh \
  -o BatchMode=yes \
  -o "ConnectTimeout=${CONNECT_TIMEOUT}" \
  -o LogLevel=ERROR \
  -l "$BROKER_USER" \
  "$BROKER_HOST" \
  sudo --non-interactive "$BROKER_COMMAND" "$1" "$2"
