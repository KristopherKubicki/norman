#!/usr/bin/env bash
set -euo pipefail

readonly ROUTER_SCRIPT="${CODEX_ROUTER_SCRIPT:-$HOME/.local/lib/norman-codex-route/codex_route.py}"

exec python3 "$ROUTER_SCRIPT" --launcher regular -- "$@"
