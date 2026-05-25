#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
    printf 'apply_switchboard_systemd_migration.sh must run as root.\n' >&2
    exit 77
fi

ROOT_DIR="${ROOT_DIR:-/home/operator/code/norman}"
ENV_DIR="${ENV_DIR:-/etc/norman}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

OLD_PREFIX="norman-bot-prime"
NEW_PREFIX="norman-switchboard"
OPS_PREFIX="norman-ops"

OLD_ENV="${ENV_DIR}/${OLD_PREFIX}-codex.env"
NEW_ENV="${ENV_DIR}/${NEW_PREFIX}-codex.env"

quote_env_value() {
    printf '%s' "$1" | sed "s/'/'\\\\''/g; s/.*/'&'/"
}

set_env_value() {
    local key="$1"
    local value="$2"
    local quoted
    quoted="$(quote_env_value "$value")"
    if grep -qE "^${key}=" "$NEW_ENV" 2>/dev/null; then
        sed -i -E "s|^${key}=.*|${key}=${quoted}|" "$NEW_ENV"
    else
        printf '%s=%s\n' "$key" "$quoted" >>"$NEW_ENV"
    fi
}

install -d -m 0755 "$ENV_DIR"

if [[ -f "$OLD_ENV" ]]; then
    cp -a "$OLD_ENV" "$NEW_ENV"
else
    : >"$NEW_ENV"
    chmod 0600 "$NEW_ENV"
fi

set_env_value HOUSEBOT_CODEX_SESSION norman-switchboard
set_env_value HOUSEBOT_CODEX_TMUX_SOCKET norman-switchboard
set_env_value HOUSEBOT_CODEX_AGENT_NAME Switchboard
set_env_value HOUSEBOT_CODEX_AGENT_GROUP Norman
set_env_value HOUSEBOT_CODEX_CONSOLE_TITLE "Switchboard Console"
set_env_value HOUSEBOT_CODEX_PROMPT_PLACEHOLDER "Ask Switchboard to triage, route, or supervise a fleet issue."
set_env_value HOUSEBOT_CODEX_PROMPT_FILE "${ROOT_DIR}/scripts/norman_switchboard_prompt.txt"
set_env_value HOUSEBOT_CODEX_WEB_PORT 8796
set_env_value HOUSEBOT_CODEX_CANONICAL_HOST switchboard.home.arpa
set_env_value HOUSEBOT_CODEX_LOCAL_HOST_ALIASES "switchboard.home.arpa,switchboard.norman.home.arpa,norman.home.arpa,subprime.home.arpa,subprime.norman.home.arpa,botprime.home.arpa,bot.norman.home.arpa"
set_env_value HOUSEBOT_CODEX_SERVICE_NAME "${NEW_PREFIX}-codex.service"
set_env_value HOUSEBOT_CODEX_WEB_SERVICE_NAME "${NEW_PREFIX}-codex-web.service"

cat >"${SYSTEMD_DIR}/${NEW_PREFIX}-codex.service" <<EOF
[Unit]
Description=Norman Switchboard Codex tmux supervisor
After=network-online.target tailscaled.service norman.service
Wants=network-online.target

[Service]
Type=simple
User=operator
Group=operator
WorkingDirectory=${ROOT_DIR}
EnvironmentFile=-${NEW_ENV}
ExecStart=${ROOT_DIR}/scripts/norman_codex_supervisor.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat >"${SYSTEMD_DIR}/${NEW_PREFIX}-codex-web.service" <<EOF
[Unit]
Description=Norman Switchboard Codex web bridge
After=network-online.target ${NEW_PREFIX}-codex.service
Wants=network-online.target

[Service]
Type=simple
User=operator
Group=operator
WorkingDirectory=${ROOT_DIR}
EnvironmentFile=-${NEW_ENV}
ExecStart=${ROOT_DIR}/.venv/bin/python ${ROOT_DIR}/scripts/norman_codex_web.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl stop \
    "${OLD_PREFIX}-codex-web.service" \
    "${OLD_PREFIX}-codex.service" \
    "${OPS_PREFIX}-codex-web.service" \
    "${OPS_PREFIX}-codex.service" 2>/dev/null || true

systemctl disable \
    "${OLD_PREFIX}-codex-web.service" \
    "${OLD_PREFIX}-codex.service" \
    "${OPS_PREFIX}-codex-web.service" \
    "${OPS_PREFIX}-codex.service" 2>/dev/null || true

runuser -u operator -- tmux -L norman-bot-prime kill-session -t norman-bot-prime 2>/dev/null || true
runuser -u operator -- tmux -L norman-ops kill-session -t norman-ops 2>/dev/null || true

systemctl daemon-reload
systemctl enable --now "${NEW_PREFIX}-codex.service" "${NEW_PREFIX}-codex-web.service"
systemctl reset-failed \
    "${OLD_PREFIX}-codex-web.service" \
    "${OLD_PREFIX}-codex.service" \
    "${OPS_PREFIX}-codex-web.service" \
    "${OPS_PREFIX}-codex.service" 2>/dev/null || true

systemctl --no-pager --full status "${NEW_PREFIX}-codex.service" "${NEW_PREFIX}-codex-web.service"
