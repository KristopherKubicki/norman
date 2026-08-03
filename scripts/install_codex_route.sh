#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${CODEX_ROUTER_BIN_DIR:-$HOME/.local/bin}"
LIB_DIR="${CODEX_ROUTER_LIB_DIR:-$HOME/.local/lib/norman-codex-route}"
BASHRC_PATH="${CODEX_ROUTER_BASHRC:-$HOME/.bashrc}"
install_shell_path=1

usage() {
  cat <<'EOF'
Usage: install_codex_route.sh [--no-shell-path]

Installs the Codex checkout router and wrappers into the current user's local
runtime directories. The installed profiles retain brokered token commands;
no bearer token is copied or written.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --no-shell-path)
      install_shell_path=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done

for source in \
  "$SCRIPT_DIR/codex_route.py" \
  "$SCRIPT_DIR/norman_codex_gateway_token.py" \
  "$SCRIPT_DIR/norman_codex_gateway_broker.sh" \
  "$SCRIPT_DIR/codex_cli_wrapper.sh" \
  "$SCRIPT_DIR/codex_work_wrapper.sh"; do
  if [[ ! -f "$source" ]]; then
    echo "codex route installer: required source is missing: $source" >&2
    exit 1
  fi
done

install -d -m 0700 "$BIN_DIR" "$LIB_DIR"
install -m 0700 "$SCRIPT_DIR/codex_route.py" "$LIB_DIR/codex_route.py"
install -m 0700 \
  "$SCRIPT_DIR/norman_codex_gateway_token.py" \
  "$LIB_DIR/norman_codex_gateway_token.py"
install -m 0700 \
  "$SCRIPT_DIR/norman_codex_gateway_broker.sh" \
  "$LIB_DIR/norman_codex_gateway_broker.sh"
install -m 0700 "$SCRIPT_DIR/codex_cli_wrapper.sh" "$BIN_DIR/codex"
install -m 0700 "$SCRIPT_DIR/codex_work_wrapper.sh" "$BIN_DIR/codex-work"

if [[ "$install_shell_path" -eq 1 ]]; then
  path_line='export PATH="$HOME/.local/bin:$PATH"'
  touch "$BASHRC_PATH"
  if ! grep -Fqx "$path_line" "$BASHRC_PATH"; then
    printf '\n# Local Codex checkout router.\n%s\n' "$path_line" >>"$BASHRC_PATH"
  fi
fi

printf 'Installed Codex checkout router in %s and wrappers in %s.\n' \
  "$LIB_DIR" \
  "$BIN_DIR"
