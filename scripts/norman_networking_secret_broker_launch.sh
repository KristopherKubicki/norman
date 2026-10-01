#!/usr/bin/env bash
set -euo pipefail

readonly BROKER_PROGRAM="/usr/local/libexec/norman-networking-secret-broker"
readonly CREDENTIAL_FILE="/etc/norman/credentials/norman-cred-passphrase.cred"

if [[ "$#" -ne 2 || "$1" != "get" || -z "$2" ]]; then
  echo "Usage: norman-networking-secret-broker get <logical-secret-name>" >&2
  exit 2
fi

exec systemd-run \
  --quiet \
  --wait \
  --pipe \
  --collect \
  --property=User=kristopher \
  --property=Group=kristopher \
  --property="LoadCredentialEncrypted=norman-cred-passphrase:${CREDENTIAL_FILE}" \
  "$BROKER_PROGRAM" "$@"
