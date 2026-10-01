#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NORMAN_HOST="${NORMAN_CODEX_GATEWAY_BROKER_HOST:-192.168.2.241}"
REMOTE_PROGRAM="/usr/local/libexec/norman-codex-gateway-broker"
REMOTE_LAUNCHER="/usr/local/sbin/norman-codex-gateway-broker"
REMOTE_SUDOERS="/etc/sudoers.d/norman-codex-gateway-broker"

usage() {
  cat <<'EOF'
Usage: deploy_codex_gateway_broker.sh [--host HOST] [--skip-proof]

Deploy the constrained Norman-host gateway token broker, provision its approved
encrypted-vault aliases, install the local Codex router helper, and enable the
workstation's periodic route proof. No bearer token is copied to a local file.
EOF
}

run_proof=1
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --host)
      NORMAN_HOST="${2:?--host requires a hostname}"
      shift
      ;;
    --skip-proof)
      run_proof=0
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
  "$SCRIPT_DIR/norman_codex_gateway_broker.py" \
  "$SCRIPT_DIR/norman_codex_gateway_broker_launch.sh" \
  "$SCRIPT_DIR/norman_codex_gateway_broker.sudoers" \
  "$SCRIPT_DIR/install_codex_route.sh" \
  "$SCRIPT_DIR/systemd/norman-codex-route-proof.env" \
  "$SCRIPT_DIR/systemd/norman-codex-route-proof.service" \
  "$SCRIPT_DIR/systemd/norman-codex-route-proof.timer"; do
  [[ -f "$source" ]] || {
    echo "Missing deployment source: $source" >&2
    exit 1
  }
done

remote_tmp_program="/tmp/norman-codex-gateway-broker.$$"
remote_tmp_launcher="/tmp/norman-codex-gateway-broker-launch.$$"
remote_tmp_sudoers="/tmp/norman-codex-gateway-broker-sudoers.$$"
cleanup_remote() {
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$NORMAN_HOST" \
    "rm -f '$remote_tmp_program' '$remote_tmp_launcher' '$remote_tmp_sudoers'" \
    >/dev/null 2>&1 || true
}
trap cleanup_remote EXIT

scp -q -o BatchMode=yes -o ConnectTimeout=5 \
  "$SCRIPT_DIR/norman_codex_gateway_broker.py" \
  "${NORMAN_HOST}:${remote_tmp_program}"
scp -q -o BatchMode=yes -o ConnectTimeout=5 \
  "$SCRIPT_DIR/norman_codex_gateway_broker_launch.sh" \
  "${NORMAN_HOST}:${remote_tmp_launcher}"
scp -q -o BatchMode=yes -o ConnectTimeout=5 \
  "$SCRIPT_DIR/norman_codex_gateway_broker.sudoers" \
  "${NORMAN_HOST}:${remote_tmp_sudoers}"
ssh -o BatchMode=yes -o ConnectTimeout=5 "$NORMAN_HOST" \
  "sudo --non-interactive install -o root -g root -m 0755 '$remote_tmp_program' '$REMOTE_PROGRAM' && \
   sudo --non-interactive install -o root -g root -m 0755 '$remote_tmp_launcher' '$REMOTE_LAUNCHER' && \
   sudo --non-interactive install -o root -g root -m 0440 '$remote_tmp_sudoers' '$REMOTE_SUDOERS' && \
   sudo --non-interactive visudo -cf '$REMOTE_SUDOERS' && \
   sudo --non-interactive '$REMOTE_LAUNCHER' provision"

"$SCRIPT_DIR/install_codex_route.sh" --no-shell-path
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-codex-route-proof.env" \
  /etc/norman/codex-route-proof.env
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-codex-route-proof.service" \
  /etc/systemd/system/norman-codex-route-proof.service
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-codex-route-proof.timer" \
  /etc/systemd/system/norman-codex-route-proof.timer
sudo --non-interactive systemctl daemon-reload
sudo --non-interactive systemctl enable --now norman-codex-route-proof.timer

if [[ "$run_proof" -eq 1 ]]; then
  "$SCRIPT_DIR/codex_route_proof.py" \
    --parallelism 4 \
    --output-json "$HOME/.local/state/norman/codex-route-proof.json"
fi

echo "Norman Codex gateway broker deployment complete."
