#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
USER_SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

for source in \
  "$SCRIPT_DIR/codex_session_pressure.py" \
  "$SCRIPT_DIR/codex_session_prune.py" \
  "$SCRIPT_DIR/codex_work_wrapper.sh" \
  "$SCRIPT_DIR/install_codex_route.sh" \
  "$SCRIPT_DIR/systemd/codex-session-prune.service" \
  "$SCRIPT_DIR/systemd/codex-session-prune.timer" \
  "$SCRIPT_DIR/systemd/norman-codex-session-pressure.service" \
  "$SCRIPT_DIR/systemd/norman-codex-session-pressure.timer" \
  "$SCRIPT_DIR/systemd/norman-codex-session-pressure-alerts.service" \
  "$SCRIPT_DIR/systemd/norman-codex-session-pressure-alerts.path" \
  "$SCRIPT_DIR/systemd/norman-tui-local-host-pressure-alerts.service" \
  "$SCRIPT_DIR/systemd/norman-tui-fleet-alerts.service"; do
  [[ -f "$source" ]] || {
    echo "Codex session guard deployment source is missing: $source" >&2
    exit 1
  }
done

"$SCRIPT_DIR/install_codex_route.sh" --no-shell-path

install -d -m 0700 "$USER_SYSTEMD_DIR"
install -m 0600 \
  "$SCRIPT_DIR/systemd/codex-session-prune.service" \
  "$USER_SYSTEMD_DIR/codex-session-prune.service"
install -m 0600 \
  "$SCRIPT_DIR/systemd/codex-session-prune.timer" \
  "$USER_SYSTEMD_DIR/codex-session-prune.timer"
systemctl --user daemon-reload
systemctl --user enable --now codex-session-prune.timer

sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-codex-session-pressure.service" \
  /etc/systemd/system/norman-codex-session-pressure.service
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-codex-session-pressure.timer" \
  /etc/systemd/system/norman-codex-session-pressure.timer
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-codex-session-pressure-alerts.service" \
  /etc/systemd/system/norman-codex-session-pressure-alerts.service
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-codex-session-pressure-alerts.path" \
  /etc/systemd/system/norman-codex-session-pressure-alerts.path
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-tui-local-host-pressure-alerts.service" \
  /etc/systemd/system/norman-tui-local-host-pressure-alerts.service
sudo --non-interactive install -D -o root -g root -m 0644 \
  "$SCRIPT_DIR/systemd/norman-tui-fleet-alerts.service" \
  /etc/systemd/system/norman-tui-fleet-alerts.service
sudo --non-interactive systemctl daemon-reload
sudo --non-interactive systemctl enable --now norman-codex-session-pressure.timer
sudo --non-interactive systemctl enable --now norman-codex-session-pressure-alerts.path

echo "Codex session guard deployment complete."
