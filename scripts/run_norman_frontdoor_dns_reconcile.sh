#!/bin/sh
set -eu

: "${CREDENTIALS_DIRECTORY:?systemd credentials directory is required}"

if [ -n "${NORMAN_KEYS_URL:-}" ] || [ -n "${NORMAN_KEYS_API_BASE:-}" ]; then
    export NORMAN_KEYS_TOKEN="$(
        /usr/local/bin/cred \
            --passphrase-file "$CREDENTIALS_DIRECTORY/norman-cred-passphrase" \
            get norman/keys-service-token
    )"
elif [ -z "${NORMAN_SECRET_CMD:-}" ] && [ -n "${NORMAN_CONFIG_SECRET_CMD:-}" ]; then
    export NORMAN_SECRET_CMD="$NORMAN_CONFIG_SECRET_CMD"
elif [ -z "${NORMAN_SECRET_CMD:-}" ]; then
    printf '%s\n' "Norman Keys command or URL is required for front-door DNS reconciliation." >&2
    exit 1
fi

exec /usr/bin/python3 \
    /home/kristopher/code/norman/scripts/norman_frontdoor_dns_reconcile.py \
    "$@"
