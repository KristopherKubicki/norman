#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SUDOERS_SOURCE="$SCRIPT_DIR/norman_ops_mcp_canary_broker.sudoers"
readonly SUDOERS_TARGET="/etc/sudoers.d/norman-ops-mcp-canary-broker"

for source in \
  "$SCRIPT_DIR/norman_ops_mcp_canary_broker.py" \
  "$SCRIPT_DIR/norman_ops_mcp_canary_broker_launch.sh" \
  "$SUDOERS_SOURCE"; do
  [[ -f "$source" ]] || {
    echo "Ops MCP canary broker deployment source is missing: $source" >&2
    exit 1
  }
done

sudo --non-interactive install -D -o root -g root -m 0755 \
  "$SCRIPT_DIR/norman_ops_mcp_canary_broker.py" \
  /usr/local/libexec/norman-ops-mcp-canary-broker
sudo --non-interactive install -D -o root -g root -m 0755 \
  "$SCRIPT_DIR/norman_ops_mcp_canary_broker_launch.sh" \
  /usr/local/sbin/norman-ops-mcp-canary-broker
sudo --non-interactive visudo -cf "$SUDOERS_SOURCE"
sudo --non-interactive install -D -o root -g root -m 0440 \
  "$SUDOERS_SOURCE" \
  "$SUDOERS_TARGET"
sudo --non-interactive visudo -cf "$SUDOERS_TARGET"
