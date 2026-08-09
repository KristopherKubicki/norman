#!/usr/bin/env bash
set -euo pipefail
umask 022

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_GUARD="${SCRIPT_DIR}/norman_codex_secret_guard.py"
REQUIREMENTS_PATH="/etc/codex/requirements.toml"
MANAGED_HOOKS_DIR=""

usage() {
  cat <<'EOF'
Usage: deploy_codex_tui_secret_guard.sh [options]

Install the Norman Codex secret guard as an administrator-managed hook for all
local Codex profiles. The command uses sudo -n and never prompts for a password.

Options:
  --requirements-path PATH  Override /etc/codex/requirements.toml.
  --managed-hooks-dir PATH  Override the managed hooks directory.
  -h, --help                Show this help text.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --requirements-path)
      REQUIREMENTS_PATH="${2:?--requirements-path requires a value}"
      shift 2
      ;;
    --managed-hooks-dir)
      MANAGED_HOOKS_DIR="${2:?--managed-hooks-dir requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$SOURCE_GUARD" ]]; then
  printf 'Managed guard source is unavailable: %s\n' "$SOURCE_GUARD" >&2
  exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
  sudo_args=(--requirements-path "$REQUIREMENTS_PATH")
  if [[ -n "$MANAGED_HOOKS_DIR" ]]; then
    sudo_args+=(--managed-hooks-dir "$MANAGED_HOOKS_DIR")
  fi
  exec sudo -n -- "$0" "${sudo_args[@]}"
fi

if [[ -z "$MANAGED_HOOKS_DIR" ]]; then
  MANAGED_HOOKS_DIR="$(
    python3 "$SOURCE_GUARD" \
      --requirements-path "$REQUIREMENTS_PATH" \
      --print-managed-hooks-dir
  )"
fi

if [[ "$MANAGED_HOOKS_DIR" != /* ]]; then
  printf 'Managed hooks directory must be absolute: %s\n' "$MANAGED_HOOKS_DIR" >&2
  exit 2
fi

MANAGED_GUARD="${MANAGED_HOOKS_DIR}/norman_codex_secret_guard.py"
install -d -m 0755 "$(dirname -- "$REQUIREMENTS_PATH")" "$MANAGED_HOOKS_DIR"
install -m 0755 "$SOURCE_GUARD" "$MANAGED_GUARD"

python3 "$MANAGED_GUARD" \
  --install-managed-policy \
  --requirements-path "$REQUIREMENTS_PATH" \
  --managed-guard-path "$MANAGED_GUARD"
python3 "$MANAGED_GUARD" \
  --verify-managed-policy \
  --requirements-path "$REQUIREMENTS_PATH" \
  --managed-guard-path "$MANAGED_GUARD"

printf 'Installed the enforced Norman TUI secret guard at %s.\n' "$MANAGED_GUARD"
