#!/bin/sh
set -eu

: "${CREDENTIALS_DIRECTORY:?systemd credentials directory is required}"

NETWORKING_SECRET_BROKER=${NORMAN_NETWORKING_SECRET_BROKER_CMD:-/home/kristopher/code/norman/scripts/norman_networking_secret_broker.sh}

if [ -n "${NORMAN_KEYS_URL:-}" ] || [ -n "${NORMAN_KEYS_API_BASE:-}" ]; then
    if keys_token="$(
        /usr/local/bin/cred \
            --passphrase-file "$CREDENTIALS_DIRECTORY/norman-cred-passphrase" \
            get norman/keys-service-token \
            2>/dev/null
    )" && [ -n "$keys_token" ]; then
        export NORMAN_KEYS_TOKEN="$keys_token"
    elif [ -x "$NETWORKING_SECRET_BROKER" ]; then
        # Norman Keys may be healthy while this host lacks its service-token
        # alias. Fall back to the narrowly allowlisted networking broker
        # instead of leaving DNS reconciliation permanently failed.
        unset NORMAN_KEYS_URL NORMAN_KEYS_API_BASE NORMAN_KEYS_TOKEN
        export NORMAN_SECRET_CMD="$NETWORKING_SECRET_BROKER"
    else
        printf '%s\n' "Norman Keys token and networking secret broker are unavailable." >&2
        exit 1
    fi
elif [ -z "${NORMAN_SECRET_CMD:-}" ] && [ -n "${NORMAN_CONFIG_SECRET_CMD:-}" ]; then
    export NORMAN_SECRET_CMD="$NORMAN_CONFIG_SECRET_CMD"
elif [ -z "${NORMAN_SECRET_CMD:-}" ] && [ -x "$NETWORKING_SECRET_BROKER" ]; then
    export NORMAN_SECRET_CMD="$NETWORKING_SECRET_BROKER"
elif [ -z "${NORMAN_SECRET_CMD:-}" ]; then
    printf '%s\n' "Norman Keys command or URL is required for front-door DNS reconciliation." >&2
    exit 1
fi

exec /usr/bin/python3 \
    /home/kristopher/code/norman/scripts/norman_frontdoor_dns_reconcile.py \
    "$@"
