#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT_PATH="${ROOT_DIR}/tmp/desktop_snapshots/hal_latest.json"

exec python3 "${ROOT_DIR}/scripts/hal_desktop_layout.py" restore "${SNAPSHOT_PATH}"
