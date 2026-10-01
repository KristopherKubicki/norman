#!/usr/bin/env bash
set -euo pipefail

readonly ROUTER_SCRIPT="${CODEX_ROUTER_SCRIPT:-$HOME/.local/lib/norman-codex-route/codex_route.py}"

case "${1-}" in
  --print-route|--routes|--verify)
    router_command="$1"
    shift
    exec python3 "$ROUTER_SCRIPT" --launcher regular "$router_command" -- "$@"
    ;;
esac

exec python3 "$ROUTER_SCRIPT" --launcher regular -- "$@"
