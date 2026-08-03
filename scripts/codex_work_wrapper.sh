#!/usr/bin/env bash
set -euo pipefail

readonly ROUTER_SCRIPT="${CODEX_ROUTER_SCRIPT:-$HOME/.local/lib/norman-codex-route/codex_route.py}"
readonly CODEX_WORK_HOME="${CODEX_WORK_HOME:-$HOME/.codex-work}"
readonly CODEX_WORK_AWS_PROFILE="${CODEX_WORK_AWS_PROFILE:-ob-openbrand-admin}"
readonly CODEX_WORK_AWS_REGION="${CODEX_WORK_AWS_REGION:-us-east-2}"
readonly CODEX_WORK_DISABLE_APPS="${CODEX_WORK_DISABLE_APPS:-0}"
readonly OPS_OPENBRAND_MCP_LAUNCHER="$HOME/code/control_plane/scripts/with_ops_openbrand_mcp.sh"

if [[ "${CODEX_ROUTER_RESOLVED:-}" != "1" ]]; then
  exec python3 "$ROUTER_SCRIPT" \
    --launcher work \
    --reenter "$0" \
    -- "$@"
fi
unset CODEX_ROUTER_RESOLVED

export CODEX_HOME="$CODEX_WORK_HOME"

case "$CODEX_WORK_DISABLE_APPS" in
  0|1)
    ;;
  *)
    echo "codex-work: CODEX_WORK_DISABLE_APPS must be 0 or 1." >&2
    exit 2
    ;;
esac

run_codex() {
  local codex_bin="${CODEX_REAL_BIN:-codex}"
  if [[ "$CODEX_WORK_DISABLE_APPS" == "1" ]]; then
    exec "$codex_bin" --disable apps "$@"
  fi
  exec "$codex_bin" "$@"
}

# The loader exports the subject-bound Ops Portal binding only to this process.
if [[ "${CODEX_WORK_OPS_BINDING_LOADED:-}" != "1" ]]; then
  exec env -u OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY \
    "$OPS_OPENBRAND_MCP_LAUNCHER" \
    env CODEX_WORK_OPS_BINDING_LOADED=1 "$0" "$@"
fi
unset CODEX_WORK_OPS_BINDING_LOADED

# Static credentials must not override the selected Bedrock profile fallback.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
unset AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN
export AWS_PROFILE="$CODEX_WORK_AWS_PROFILE"
export AWS_REGION="$CODEX_WORK_AWS_REGION"
export AWS_DEFAULT_REGION="$CODEX_WORK_AWS_REGION"

profile_name=""
expect_profile_name=0
for arg in "$@"; do
  if [[ "$expect_profile_name" -eq 1 ]]; then
    profile_name="$arg"
    expect_profile_name=0
    continue
  fi

  case "$arg" in
    --profile|--profile-v2|-p)
      expect_profile_name=1
      ;;
    --profile=*|--profile-v2=*)
      profile_name="${arg#--profile=}"
      profile_name="${profile_name#--profile-v2=}"
      ;;
    -p?*)
      profile_name="${arg#-p}"
      ;;
  esac
done

if [[ "$expect_profile_name" -eq 1 ]]; then
  echo "codex-work: --profile requires a profile name." >&2
  exit 2
fi

selected_profile="${profile_name:-work}"
uses_work_profile=0
if [[ -n "$profile_name" ]]; then
  if [[ "$selected_profile" == "work" ]]; then
    uses_work_profile=1
  fi
else
  case "${1-}" in
    login|logout|mcp|plugin|mcp-server|app-server|remote-control|completion|update|doctor|sandbox|apply|archive|delete|unarchive|cloud|exec-server|features|help)
      ;;
    debug)
      if [[ "${2-}" == "prompt-input" ]]; then
        uses_work_profile=1
      fi
      ;;
    *)
      uses_work_profile=1
      ;;
  esac
fi

needs_bedrock_preflight=0
case "${1-}" in
  --help|-h|help|version|--version|-V|login|logout|mcp|debug|sandbox|features|cloud|config)
    ;;
  *)
    if [[ "$uses_work_profile" -eq 1 ]]; then
      needs_bedrock_preflight=1
    fi
    ;;
esac

if [[ "$needs_bedrock_preflight" -eq 1 ]]; then
  if ! command -v aws >/dev/null 2>&1; then
    echo "codex-work: AWS CLI is required for the Bedrock credential preflight." >&2
    exit 1
  fi

  if ! timeout 20s aws sts get-caller-identity \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --output json >/dev/null; then
    cat >&2 <<EOF
codex-work: Bedrock credential preflight failed for AWS profile "$AWS_PROFILE" in "$AWS_REGION".
Refresh that profile using its configured authentication method, then retry.
To use a deliberate alternate Bedrock profile, set CODEX_WORK_AWS_PROFILE for this invocation.
EOF
    exit 1
  fi
fi

if [[ -n "$profile_name" ]]; then
  run_codex "$@"
fi

case "${1-}" in
  login|logout|mcp|plugin|mcp-server|app-server|remote-control|completion|update|doctor|sandbox|apply|archive|delete|unarchive|cloud|exec-server|features|help)
    run_codex "$@"
    ;;
  debug)
    if [[ "${2-}" == "prompt-input" ]]; then
      run_codex --profile work "$@"
    fi
    run_codex "$@"
    ;;
  *)
    run_codex --profile work "$@"
    ;;
esac
