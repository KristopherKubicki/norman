#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${CODEX_ROUTER_BIN_DIR:-$HOME/.local/bin}"
LIB_DIR="${CODEX_ROUTER_LIB_DIR:-$HOME/.local/lib/norman-codex-route}"
BASHRC_PATH="${CODEX_ROUTER_BASHRC:-$HOME/.bashrc}"
BASH_PROFILE_PATH="${CODEX_ROUTER_BASH_PROFILE:-$HOME/.bash_profile}"
install_shell_path=1
readonly ROUTER_PATH_BLOCK_BEGIN="# >>> Norman Codex checkout router >>>"
readonly ROUTER_PATH_BLOCK_END="# <<< Norman Codex checkout router <<<"
readonly ROUTER_PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

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
  "$SCRIPT_DIR/codex_session_pressure.py" \
  "$SCRIPT_DIR/codex_session_prune.py" \
  "$SCRIPT_DIR/norman_codex_secret_guard.py" \
  "$SCRIPT_DIR/norman_codex_gateway_token.py" \
  "$SCRIPT_DIR/norman_codex_gateway_broker.sh" \
  "$SCRIPT_DIR/norman_networking_secret_broker.sh" \
  "$SCRIPT_DIR/codex_cli_wrapper.sh" \
  "$SCRIPT_DIR/codex_work_wrapper.sh" \
  "$SCRIPT_DIR/codex_work_fast_wrapper.sh"; do
  if [[ ! -f "$source" ]]; then
    echo "codex route installer: required source is missing: $source" >&2
    exit 1
  fi
done

install -d -m 0700 "$BIN_DIR" "$LIB_DIR"
install -m 0700 "$SCRIPT_DIR/codex_route.py" "$LIB_DIR/codex_route.py"
install -m 0700 \
  "$SCRIPT_DIR/codex_session_pressure.py" \
  "$LIB_DIR/codex_session_pressure.py"
install -m 0700 \
  "$SCRIPT_DIR/codex_session_prune.py" \
  "$LIB_DIR/codex_session_prune.py"
install -m 0700 \
  "$SCRIPT_DIR/norman_codex_secret_guard.py" \
  "$LIB_DIR/norman_codex_secret_guard.py"
install -m 0700 \
  "$SCRIPT_DIR/norman_codex_gateway_token.py" \
  "$LIB_DIR/norman_codex_gateway_token.py"
install -m 0700 \
  "$SCRIPT_DIR/norman_codex_gateway_broker.sh" \
  "$LIB_DIR/norman_codex_gateway_broker.sh"
install -m 0700 \
  "$SCRIPT_DIR/norman_networking_secret_broker.sh" \
  "$LIB_DIR/norman_networking_secret_broker.sh"
install -m 0700 "$SCRIPT_DIR/codex_cli_wrapper.sh" "$BIN_DIR/codex"
install -m 0700 "$SCRIPT_DIR/codex_work_wrapper.sh" "$BIN_DIR/codex-work"
install -m 0700 "$SCRIPT_DIR/codex_work_fast_wrapper.sh" "$BIN_DIR/codex-work-fast"

if [[ "$install_shell_path" -eq 1 ]]; then
  install_path_block() {
    local shell_path="$1"
    local temporary_path=""

    touch "$shell_path"
    temporary_path="$(mktemp "${shell_path}.XXXXXX")"
    awk \
      -v block_begin="$ROUTER_PATH_BLOCK_BEGIN" \
      -v block_end="$ROUTER_PATH_BLOCK_END" \
      -v path_line="$ROUTER_PATH_LINE" \
      '
        $0 == block_begin {
          in_managed_block = 1
          next
        }
        in_managed_block {
          if ($0 == block_end) {
            in_managed_block = 0
          }
          next
        }
        $0 == "# Local Codex checkout router." || $0 == path_line {
          next
        }
        { lines[++line_count] = $0 }
        END {
          while (line_count > 0 && lines[line_count] == "") {
            line_count--
          }
          for (line_number = 1; line_number <= line_count; line_number++) {
            print lines[line_number]
          }
        }
      ' "$shell_path" >"$temporary_path"
    cat "$temporary_path" >"$shell_path"
    rm -f "$temporary_path"

    if [[ -s "$shell_path" ]]; then
      printf '\n' >>"$shell_path"
    fi
    printf '%s\n# Keep the checkout router ahead of NVM and npm Codex shims.\n%s\n%s\n' \
      "$ROUTER_PATH_BLOCK_BEGIN" \
      "$ROUTER_PATH_LINE" \
      "$ROUTER_PATH_BLOCK_END" >>"$shell_path"
  }

  install_path_block "$BASHRC_PATH"
  if [[ -f "$BASH_PROFILE_PATH" ]]; then
    install_path_block "$BASH_PROFILE_PATH"
  fi
fi

printf 'Installed Codex checkout router in %s and wrappers in %s.\n' \
  "$LIB_DIR" \
  "$BIN_DIR"
