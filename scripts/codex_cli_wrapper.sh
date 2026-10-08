#!/usr/bin/env bash
set -euo pipefail

# Keep one terminal supervisor outside router re-entry and the final client.
if [[ -t 0 && -t 1 && "${NORMAN_CODEX_TERMINAL_GUARD:-}" != "1" ]]; then
  terminal_guard="${CODEX_TERMINAL_GUARD_SCRIPT:-$HOME/.local/lib/norman-codex-route/codex_terminal_guard.py}"
  if [[ -r "$terminal_guard" ]]; then
    exec python3 "$terminal_guard" -- "$0" "$@"
  fi
fi

readonly ROUTER_SCRIPT="${CODEX_ROUTER_SCRIPT:-$HOME/.local/lib/norman-codex-route/codex_route.py}"

case "${1-}" in
  --print-route|--routes|--verify)
    router_command="$1"
    shift
    exec python3 "$ROUTER_SCRIPT" --launcher regular "$router_command" -- "$@"
    ;;
esac

exec python3 "$ROUTER_SCRIPT" --launcher regular -- "$@"
