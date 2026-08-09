#!/usr/bin/env bash
set -euo pipefail

readonly BROKER_PROGRAM="/usr/local/libexec/norman-ops-mcp-canary-broker"
readonly CREDENTIAL_FILE="/etc/norman/credentials/norman-cred-passphrase.cred"

case "${1:-}" in
  get|provision)
    [[ "$#" -eq 1 ]] || {
      echo "Usage: norman-ops-mcp-canary-broker {get|provision}" >&2
      exit 2
    }
    ;;
  *)
    echo "Usage: norman-ops-mcp-canary-broker {get|provision}" >&2
    exit 2
    ;;
esac

exec systemd-run \
  --quiet \
  --wait \
  --pipe \
  --collect \
  --property=User=kristopher \
  --property=Group=kristopher \
  --property="LoadCredentialEncrypted=norman-cred-passphrase:${CREDENTIAL_FILE}" \
  "$BROKER_PROGRAM" "$@"
