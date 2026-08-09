#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NORMAN_HOST="${NORMAN_NETWORKING_SECRET_BROKER_HOST:-192.168.2.241}"
REMOTE_PROGRAM="/usr/local/libexec/norman-networking-secret-broker"
REMOTE_LAUNCHER="/usr/local/sbin/norman-networking-secret-broker"
REMOTE_SUDOERS="/etc/sudoers.d/norman-networking-secret-broker"

usage() {
  cat <<'EOF'
Usage: deploy_networking_secret_broker.sh [--host HOST]

Deploy the scoped networking-TUI credential broker and install the local Codex
router helper. The broker allows only networking/firewall, networking/netgear,
and networking/dot10. Secret values are never written to local files.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --host)
      NORMAN_HOST="${2:?--host requires a hostname}"
      shift
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
  "$SCRIPT_DIR/norman_networking_secret_broker.py" \
  "$SCRIPT_DIR/norman_networking_secret_broker_launch.sh" \
  "$SCRIPT_DIR/norman_networking_secret_broker.sudoers" \
  "$SCRIPT_DIR/install_codex_route.sh"; do
  [[ -f "$source" ]] || {
    echo "Missing deployment source: $source" >&2
    exit 1
  }
done

remote_tmp_program="/tmp/norman-networking-secret-broker.$$"
remote_tmp_launcher="/tmp/norman-networking-secret-broker-launch.$$"
remote_tmp_sudoers="/tmp/norman-networking-secret-broker-sudoers.$$"
cleanup_remote() {
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$NORMAN_HOST" \
    "rm -f '$remote_tmp_program' '$remote_tmp_launcher' '$remote_tmp_sudoers'" \
    >/dev/null 2>&1 || true
}
trap cleanup_remote EXIT

scp -q -o BatchMode=yes -o ConnectTimeout=5 \
  "$SCRIPT_DIR/norman_networking_secret_broker.py" \
  "${NORMAN_HOST}:${remote_tmp_program}"
scp -q -o BatchMode=yes -o ConnectTimeout=5 \
  "$SCRIPT_DIR/norman_networking_secret_broker_launch.sh" \
  "${NORMAN_HOST}:${remote_tmp_launcher}"
scp -q -o BatchMode=yes -o ConnectTimeout=5 \
  "$SCRIPT_DIR/norman_networking_secret_broker.sudoers" \
  "${NORMAN_HOST}:${remote_tmp_sudoers}"
ssh -o BatchMode=yes -o ConnectTimeout=5 "$NORMAN_HOST" \
  "sudo --non-interactive install -o root -g root -m 0755 '$remote_tmp_program' '$REMOTE_PROGRAM' && \
   sudo --non-interactive install -o root -g root -m 0755 '$remote_tmp_launcher' '$REMOTE_LAUNCHER' && \
   sudo --non-interactive install -o root -g root -m 0440 '$remote_tmp_sudoers' '$REMOTE_SUDOERS' && \
   sudo --non-interactive visudo -cf '$REMOTE_SUDOERS'"

"$SCRIPT_DIR/install_codex_route.sh" --no-shell-path

echo "Norman networking TUI secret broker deployment complete."
