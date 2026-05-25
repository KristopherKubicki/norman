#!/usr/bin/env bash
set -euo pipefail

PORT="${NORMAN_SWITCHBOARD_PORT:-8796}"

cat <<EOF
This legacy lane is retired.
Use Switchboard for Norman coordination:
http://switchboard.home.arpa:${PORT}/
EOF
