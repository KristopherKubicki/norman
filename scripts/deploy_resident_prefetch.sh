#!/usr/bin/env bash
set -euo pipefail
[[ "$(hostname -s)" == "networking" ]] || { echo "Install the fleet controller on Networking only." >&2; exit 1; }
source_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
install -d -o kristopher -g kristopher -m 0700 /home/kristopher/.local/state/norman
install -m 0755 "$source_dir/norllama/resident_prefetch.py" /opt/hal-services/norman/scripts/norllama/resident_prefetch.py
install -m 0644 "$source_dir/systemd/norllama-resident-prefetch@.service" /etc/systemd/system/
install -m 0644 "$source_dir/systemd/norllama-resident-prefetch@.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now norllama-resident-prefetch@work.timer norllama-resident-prefetch@personal.timer
