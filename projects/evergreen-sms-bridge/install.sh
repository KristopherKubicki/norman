#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
UNIT_SRC="${ROOT}/systemd/evergreen-sms-bridge.service.in"
UNIT_DST="${HOME}/.config/systemd/user/evergreen-sms-bridge.service"
VENV_DIR="${ROOT}/.venv"

if [[ $# -ne 1 || "$1" != "--legacy" ]]; then
  cat >&2 <<'EOF'
This installer is legacy-only. It cannot install the correlated SMS reply path.

For conversational SMS, provision the encrypted sms-callback-token credential
and install scripts/systemd/norman-sms-bbs.service plus
scripts/systemd/evergreen-sms-bridge.service from the repository root. See
projects/evergreen-sms-bridge/README.md.

To install a non-conversational spool/webhook/collector/tmux migration bridge,
set DELIVERY_MODE to a legacy mode and run:
  bash ./install.sh --legacy
EOF
  exit 2
fi

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

delivery_mode=$(
  sed -n 's/^[[:space:]]*DELIVERY_MODE[[:space:]]*=[[:space:]]*//p' "${ROOT}/.env" \
    | tail -n 1 \
    | sed -e 's/[[:space:]]*#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    | tr -d '\r' \
    | sed "s/[\"']//g" \
    | tr '[:upper:]' '[:lower:]'
)
if [[ "${delivery_mode}" == "sms" ]]; then
  cat >&2 <<'EOF'
Refusing to install DELIVERY_MODE=sms with the legacy user service.
Use the root systemd units documented in README.md so the isolated SMS BBS and
encrypted callback credential are configured together.
EOF
  exit 2
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
echo "Installed legacy bridge mode (${delivery_mode:-unset}); it does not send SMS replies."
