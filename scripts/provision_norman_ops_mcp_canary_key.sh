#!/usr/bin/env bash
set -euo pipefail

readonly REMOTE_HOST="${NORMAN_OPS_MCP_CANARY_HOST:-norman.home.arpa}"
readonly AWS_PROFILE_NAME="${OPS_OPENBRAND_MCP_AWS_PROFILE:-ob-openbrand-admin}"
readonly AWS_REGION_NAME="${OPS_OPENBRAND_MCP_AWS_REGION:-us-east-2}"
readonly BINDINGS_SECRET_ID="${OPS_OPENBRAND_MCP_BINDINGS_SECRET_ID:-ops-portal/production/mcp-api-key-bindings}"
readonly KEY_ID="${OPS_OPENBRAND_MCP_KEY_ID:-kris-production-codex-control-plane}"

usage() {
  cat <<'EOF'
Usage: provision_norman_ops_mcp_canary_key.sh

Read the authorized Ops MCP canary key on this workstation and provision it to
the Norman encrypted credential vault through an SSH stdin pipe.
EOF
}

case "${1:-}" in
  "")
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

for command in aws jq ssh; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is unavailable: $command" >&2
    exit 1
  }
done

# Keep the bound key in pipes only: do not put it in an environment variable,
# a command argument, an output file, or terminal output.
timeout 30s aws secretsmanager get-secret-value \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --secret-id "$BINDINGS_SECRET_ID" \
  --query SecretString \
  --output text |
  jq -er --arg key_id "$KEY_ID" \
    '.keys[] | select(.key_id == $key_id) | .api_key | gsub("^\\s+|\\s+$"; "")' |
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_HOST" \
    'sudo -n /usr/local/sbin/norman-ops-mcp-canary-broker provision'
