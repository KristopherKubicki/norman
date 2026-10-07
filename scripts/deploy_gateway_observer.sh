#!/usr/bin/env bash
set -euo pipefail
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
case "$(hostname -s)" in networking) ;; *) echo 'Install on Networking VM232 only.' >&2; exit 1 ;; esac
for module in gateway_observer.py gateway_watchdog.py codex_gateway_status.py codex_rescue.py; do
  sudo -n install -m 0755 "$script_dir/$module" "/opt/hal-services/norman/scripts/$module"
done
sudo -n install -m 0644 "$script_dir/systemd/norman-gateway-observer.service" /etc/systemd/system/
sudo -n install -m 0644 "$script_dir/systemd/norman-gateway-observer.timer" /etc/systemd/system/
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now norman-gateway-observer.timer
sudo -n systemctl start norman-gateway-observer.service
