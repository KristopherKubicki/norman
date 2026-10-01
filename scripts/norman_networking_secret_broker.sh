#!/usr/bin/env bash
set -euo pipefail

readonly BROKER_HOST="${NORMAN_NETWORKING_SECRET_BROKER_HOST:-192.168.2.241}"
readonly BROKER_COMMAND="/usr/local/sbin/norman-networking-secret-broker"
readonly CONNECT_TIMEOUT="${NORMAN_NETWORKING_SECRET_BROKER_CONNECT_TIMEOUT_SECONDS:-5}"

if [[ "$#" -ne 2 || "$1" != "get" || -z "$2" ]]; then
  echo "Usage: norman_networking_secret_broker.sh get <logical-secret-name>" >&2
  exit 2
fi

case "$2" in
  networking/firewall|networking/netgear|networking/dot10)
    ;;
  *)
    echo "Norman networking secret broker denied an unapproved alias." >&2
    exit 1
    ;;
esac

exec ssh \
  -o BatchMode=yes \
  -o "ConnectTimeout=${CONNECT_TIMEOUT}" \
  -o LogLevel=ERROR \
  "$BROKER_HOST" \
  sudo --non-interactive "$BROKER_COMMAND" "$1" "$2"
