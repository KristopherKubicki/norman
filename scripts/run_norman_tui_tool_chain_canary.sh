#!/bin/sh
set -eu

: "${CREDENTIALS_DIRECTORY:?systemd credentials directory is required}"

export NORMAN_PROMPT_PROXY_TOKEN="$(
    /usr/local/bin/cred \
        --passphrase-file "$CREDENTIALS_DIRECTORY/norman-cred-passphrase" \
        get norman/prompt-proxy-token
)"

: "${NORMAN_TUI_TOOL_CHAIN_CANARY_SCRIPT:=/home/kristopher/code/norman/scripts/tui_tool_chain_canary.py}"

exec /usr/bin/python3 "$NORMAN_TUI_TOOL_CHAIN_CANARY_SCRIPT" "$@"
