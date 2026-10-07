#!/usr/bin/env bash
set -euo pipefail
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Run on Norman CT241, never the HAL workstation.
case "$(hostname -s)" in norman) ;; *) echo 'Install on Norman CT241 only.' >&2; exit 1 ;; esac
sudo -n install -d -m 0755 /var/lib/norman/gateway-health
sudo -n install -m 0755 "$script_dir/gateway_watchdog.py" /usr/local/libexec/norman-gateway-watchdog
sudo -n install -m 0644 "$script_dir/systemd/norman-gateway-watchdog.service" /etc/systemd/system/
sudo -n install -m 0644 "$script_dir/systemd/norman-gateway-watchdog.timer" /etc/systemd/system/
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now norman-gateway-watchdog.timer
sudo -n systemctl start norman-gateway-watchdog.service
