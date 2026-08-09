#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RECEIPT_PATH="${HOME}/.local/state/norman/tui-tool-chain-canary.json"

for source in \
  "$SCRIPT_DIR/run_norman_tui_tool_chain_canary.sh" \
  "$SCRIPT_DIR/tui_tool_chain_canary.py" \
  "$SCRIPT_DIR/tui_host_pressure_guard.py" \
  "$SCRIPT_DIR/tui_host_recovery.py" \
  "$SCRIPT_DIR/norman_codex_gateway_token.py" \
  "$SCRIPT_DIR/norman_ops_mcp_canary_token.py" \
  "$SCRIPT_DIR/norman_codex_gateway_broker.sh" \
  "$SCRIPT_DIR/systemd/norman-tui-tool-chain-canary.service" \
  "$SCRIPT_DIR/systemd/norman-tui-tool-chain-canary.timer"; do
  [[ -f "$source" ]] || {
    echo "TUI tool-chain canary deployment source is missing: $source" >&2
    exit 1
  }
done

sudo --non-interactive install -D -o root -g root -m 0755 \
  "$SCRIPT_DIR/run_norman_tui_tool_chain_canary.sh" \
  /usr/local/libexec/norman-tui-tool-chain-canary
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/tui_tool_chain_canary.py" \
  /usr/local/libexec/tui_tool_chain_canary.py
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/tui_host_pressure_guard.py" \
  /usr/local/libexec/tui_host_pressure_guard.py
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/tui_host_recovery.py" \
  /usr/local/libexec/tui_host_recovery.py
sudo --non-interactive install -D -o root -g root -m 0755 \
  "$SCRIPT_DIR/norman_codex_gateway_token.py" \
  /usr/local/libexec/norman_codex_gateway_token.py
sudo --non-interactive install -D -o root -g root -m 0755 \
  "$SCRIPT_DIR/norman_ops_mcp_canary_token.py" \
  /usr/local/libexec/norman_ops_mcp_canary_token.py
sudo --non-interactive install -D -o root -g root -m 0755 \
  "$SCRIPT_DIR/norman_codex_gateway_broker.sh" \
  /usr/local/libexec/norman_codex_gateway_broker.sh
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-tui-tool-chain-canary.service" \
  /etc/systemd/system/norman-tui-tool-chain-canary.service
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-tui-tool-chain-canary.timer" \
  /etc/systemd/system/norman-tui-tool-chain-canary.timer

sudo --non-interactive systemctl daemon-reload
sudo --non-interactive systemctl enable --now norman-tui-tool-chain-canary.timer
sudo --non-interactive systemctl start norman-tui-tool-chain-canary.service

/usr/bin/python3 - "$RECEIPT_PATH" <<'PY'
import json
import sys
from pathlib import Path

receipt_path = Path(sys.argv[1])
try:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"Canary receipt is unavailable: {exc}") from exc

if receipt.get("state") != "passed":
    failure_kind = str(receipt.get("failure_kind") or receipt.get("skip_reason") or "")
    raise SystemExit(f"Public streaming tool-chain canary did not pass: {failure_kind}")

print(
    "Public streaming tool-chain canary passed "
    f"({len(receipt.get('turns', []))} turns, {receipt.get('elapsed_ms', 0)} ms)."
)
PY
