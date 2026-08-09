#!/bin/sh
set -eu

: "${NORMAN_TUI_TOOL_CHAIN_TOKEN_HELPER:=/usr/local/libexec/norman_codex_gateway_token.py}"
: "${NORMAN_TUI_TOOL_CHAIN_CANARY_TOKEN_SECRET:=control-plane/prompt-proxy-token}"

export NORMAN_PROMPT_PROXY_TOKEN="$(
    /usr/bin/python3 "$NORMAN_TUI_TOOL_CHAIN_TOKEN_HELPER" \
        --secret "$NORMAN_TUI_TOOL_CHAIN_CANARY_TOKEN_SECRET"
)"

: "${NORMAN_TUI_TOOL_CHAIN_CANARY_SCRIPT:=/usr/local/libexec/tui_tool_chain_canary.py}"

exec /usr/bin/python3 "$NORMAN_TUI_TOOL_CHAIN_CANARY_SCRIPT" "$@"
