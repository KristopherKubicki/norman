#!/usr/bin/env bash
set -euo pipefail

state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/norllama-retired"
mkdir -p "$state_dir"
printf '%s\n' \
  "DeepSeek V4 serving retired in favor of the redundant resident model pool." \
  >"$state_dir/deepseek-v4-retired.txt"

# The legacy unit uses Restart=on-failure. A clean exit retires it without a
# restart loop while preserving the original binary and model artifacts.
exit 0
