#!/usr/bin/env bash
set -euo pipefail

readonly ROUTER_SCRIPT="${CODEX_ROUTER_SCRIPT:-$HOME/.local/lib/norman-codex-route/codex_route.py}"
readonly CODEX_SESSION_PRESSURE_SCRIPT="${CODEX_SESSION_PRESSURE_SCRIPT:-$HOME/.local/lib/norman-codex-route/codex_session_pressure.py}"
readonly CODEX_SECRET_GUARD_SCRIPT="${CODEX_SECRET_GUARD_SCRIPT:-$HOME/.local/lib/norman-codex-route/norman_codex_secret_guard.py}"
readonly CODEX_MANAGED_REQUIREMENTS="${NORMAN_CODEX_REQUIREMENTS_PATH:-/etc/codex/requirements.toml}"
readonly CODEX_MANAGED_SECRET_GUARD="${NORMAN_CODEX_MANAGED_SECRET_GUARD:-/usr/local/lib/norman-codex-route/norman_codex_secret_guard.py}"
readonly CODEX_WORK_HOME="${CODEX_WORK_HOME:-$HOME/.codex-work}"
readonly CODEX_WORK_AWS_PROFILE="${CODEX_WORK_AWS_PROFILE:-ob-openbrand-admin}"
readonly CODEX_WORK_AWS_REGION="${CODEX_WORK_AWS_REGION:-us-east-2}"
readonly CODEX_WORK_PYTEST_XDIST_AUTO_WORKERS="${CODEX_WORK_PYTEST_XDIST_AUTO_WORKERS:-4}"
readonly OPS_OPENBRAND_MCP_LAUNCHER="$HOME/code/control_plane/scripts/with_ops_openbrand_mcp.sh"

disable_apps="${CODEX_WORK_DISABLE_APPS:-0}"
if [[ "${1-}" == "--work-no-apps" ]]; then
  disable_apps=1
  shift
fi
readonly CODEX_WORK_DISABLE_APPS="$disable_apps"
export CODEX_WORK_DISABLE_APPS

case "${1-}" in
  --print-route|--routes|--verify)
    router_command="$1"
    shift
    exec python3 "$ROUTER_SCRIPT" --launcher work "$router_command" -- "$@"
    ;;
esac

if [[ "${CODEX_ROUTER_RESOLVED:-}" != "1" ]]; then
  exec python3 "$ROUTER_SCRIPT" \
    --launcher work \
    --reenter "$0" \
    -- "$@"
fi
unset CODEX_ROUTER_RESOLVED

export CODEX_HOME="$CODEX_WORK_HOME"

if [[ ! "$CODEX_WORK_PYTEST_XDIST_AUTO_WORKERS" =~ ^[1-9][0-9]*$ ]]; then
  echo "codex-work: CODEX_WORK_PYTEST_XDIST_AUTO_WORKERS must be a positive integer." >&2
  exit 2
fi

# pytest-xdist reads this only for `pytest -n auto`; leave explicit worker
# selections alone while preserving capacity for interactive TUIs.
export PYTEST_XDIST_AUTO_NUM_WORKERS="$CODEX_WORK_PYTEST_XDIST_AUTO_WORKERS"

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
  exec "$codex_bin" "$@"
}

run_guarded_codex() {
  if [[ ! -r "$CODEX_SECRET_GUARD_SCRIPT" ]]; then
    echo "codex-work: Norman TUI secret guard verifier is unavailable at $CODEX_SECRET_GUARD_SCRIPT." >&2
    exit 1
  fi
  if ! python3 "$CODEX_SECRET_GUARD_SCRIPT" \
    --verify-managed-policy \
    --requirements-path "$CODEX_MANAGED_REQUIREMENTS" \
    --managed-guard-path "$CODEX_MANAGED_SECRET_GUARD"; then
    echo "codex-work: managed Norman credential policy is unavailable. Run sudo -n ~/code/norman/scripts/deploy_codex_tui_secret_guard.sh." >&2
    exit 1
  fi
  export NORMAN_TUI_NO_DIRECT_VAULT=1
  if [[ "$CODEX_WORK_DISABLE_APPS" == "1" ]]; then
    local codex_bin="${CODEX_REAL_BIN:-codex}"
    exec "$codex_bin" --disable apps "$@"
  fi
  run_codex "$@"
}

resume_target() {
  local value=""

  shift
  while [[ "$#" -gt 0 ]]; do
    value="$1"
    shift
    case "$value" in
      --last)
        printf '%s\n' "last"
        return
        ;;
      --help|-h)
        return
        ;;
      --)
        if [[ "$#" -gt 0 ]]; then
          printf '%s\n' "$1"
        fi
        return
        ;;
      -c|--config|--enable|--disable|--remote|--remote-auth-token-env|\
      -i|--image|-m|--model|--local-provider|-p|--profile|-s|--sandbox|\
      -C|--cd|--add-dir|-a|--ask-for-approval)
        if [[ "$#" -gt 0 ]]; then
          shift
        fi
        ;;
      --config=*|--enable=*|--disable=*|--remote=*|--remote-auth-token-env=*|\
      --image=*|--model=*|--local-provider=*|--profile=*|--sandbox=*|\
      --cd=*|--add-dir=*|--ask-for-approval=*)
        ;;
      -c?*|-i?*|-m?*|-p?*|-s?*|-C?*|-a?*)
        ;;
      -*)
        ;;
      *)
        printf '%s\n' "$value"
        return
        ;;
    esac
  done
}

guard_resume() {
  if [[ "${1-}" != "resume" ]]; then
    return 0
  fi

  for argument in "$@"; do
    case "$argument" in
      --help|-h)
        return
        ;;
    esac
  done

  case "${CODEX_WORK_ALLOW_OVERSIZE_RESUME:-0}" in
    0)
      ;;
    1)
      return
      ;;
    *)
      echo "codex-work: CODEX_WORK_ALLOW_OVERSIZE_RESUME must be 0 or 1." >&2
      exit 2
      ;;
  esac

  if [[ ! -f "$CODEX_SESSION_PRESSURE_SCRIPT" ]]; then
    echo "codex-work: session-pressure guard is unavailable at $CODEX_SESSION_PRESSURE_SCRIPT; continuing without a resume size check." >&2
    return
  fi

  local target
  target="$(resume_target "$@")"
  local guard_status=0
  if python3 "$CODEX_SESSION_PRESSURE_SCRIPT" \
    --codex-home "$CODEX_HOME" \
    --resume-target "$target"; then
    return
  else
    guard_status=$?
  fi

  if [[ "$guard_status" -eq 3 ]]; then
    cat >&2 <<'EOF'
codex-work: oversized session resume blocked to protect host responsiveness.
Preserve a concise handoff, start a fresh session, and resume only the required
work. Set CODEX_WORK_ALLOW_OVERSIZE_RESUME=1 only for a deliberate override.
EOF
    exit 3
  fi

  echo "codex-work: session-pressure check failed; continuing without a resume size check." >&2
}

is_help_request() {
  for argument in "$@"; do
    case "$argument" in
      --help|-h)
        return 0
        ;;
    esac
  done
  return 1
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

guard_resume "$@"

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
if ! is_help_request "$@"; then
  case "${1-}" in
    help|version|--version|-V|login|logout|mcp|debug|sandbox|features|cloud|config)
      ;;
    *)
      if [[ "$uses_work_profile" -eq 1 ]]; then
        needs_bedrock_preflight=1
      fi
      ;;
  esac
fi

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
  run_guarded_codex "$@"
fi

case "${1-}" in
  login|logout|mcp|plugin|mcp-server|app-server|remote-control|completion|update|doctor|sandbox|apply|archive|delete|unarchive|cloud|exec-server|features|help)
    run_codex "$@"
    ;;
  debug)
    if [[ "${2-}" == "prompt-input" ]]; then
      run_guarded_codex --profile work "$@"
    fi
    run_codex "$@"
    ;;
  *)
    run_guarded_codex --profile work "$@"
    ;;
esac
