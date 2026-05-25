#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
UNIT_SRC="${ROOT}/systemd/evergreen-sms-bridge.service.in"
UNIT_DST="${HOME}/.config/systemd/user/evergreen-sms-bridge.service"
VENV_DIR="${ROOT}/.venv"

need_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing dependency: $1" >&2
    exit 1
  }
}

need_bin python3
need_bin systemctl

if [[ ! -f "${ROOT}/.env" ]]; then
  echo "missing ${ROOT}/.env" >&2
  echo "copy .env.example to .env first" >&2
  exit 1
fi

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
"${VENV_DIR}/bin/pip" install boto3 >/dev/null

mkdir -p "${HOME}/.config/systemd/user"
sed "s|@PROJECT_ROOT@|${ROOT}|g" "${UNIT_SRC}" >"${UNIT_DST}"

systemctl --user daemon-reload
systemctl --user enable --now evergreen-sms-bridge.service

echo
systemctl --user status evergreen-sms-bridge.service --no-pager --lines=20
