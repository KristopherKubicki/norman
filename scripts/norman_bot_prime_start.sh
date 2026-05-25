#!/usr/bin/env bash
set -euo pipefail

PATH="/opt/node-v20.19.6/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

while IFS='=' read -r name _; do
    unset "${name}"
done < <(env | grep '^HOUSEBOT_CODEX_' || true)
unset CODEX_HOME || true

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME="${NORMAN_SWITCHBOARD_CODEX_HOME:-${NORMAN_BOT_PRIME_CODEX_HOME:-/home/operator/.codex-bot-prime}}"
SEED_CODEX_HOME="${NORMAN_SWITCHBOARD_SEED_CODEX_HOME:-${NORMAN_BOT_PRIME_SEED_CODEX_HOME:-}}"
PROMPT_FILE="${ROOT_DIR}/scripts/norman_switchboard_prompt.txt"
TOKEN_FILE="${CODEX_HOME}/web-token.txt"
PORT="${NORMAN_SWITCHBOARD_PORT:-${NORMAN_BOT_PRIME_PORT:-8796}}"

mkdir -p "${CODEX_HOME}"

if [[ -n "${SEED_CODEX_HOME}" ]]; then
    for name in auth.json config.toml version.json; do
        if [[ -f "${SEED_CODEX_HOME}/${name}" && ! -f "${CODEX_HOME}/${name}" ]]; then
            cp "${SEED_CODEX_HOME}/${name}" "${CODEX_HOME}/${name}"
            chmod 600 "${CODEX_HOME}/${name}" 2>/dev/null || true
        fi
    done
fi

if [[ ! -f "${CODEX_HOME}/auth.json" ]]; then
    cat >&2 <<EOF
norman_bot_prime_start.sh: missing ${CODEX_HOME}/auth.json
Seed it explicitly with NORMAN_SWITCHBOARD_SEED_CODEX_HOME=/path/to/codex-home
or authenticate this CODEX_HOME directly before starting Switchboard.
EOF
    exit 1
fi

for name in config.toml version.json; do
    if [[ -n "${SEED_CODEX_HOME}" && -f "${SEED_CODEX_HOME}/${name}" && ! -f "${CODEX_HOME}/${name}" ]]; then
        cp "${SEED_CODEX_HOME}/${name}" "${CODEX_HOME}/${name}"
        chmod 600 "${CODEX_HOME}/${name}" 2>/dev/null || true
    fi
done

if [[ ! -f "${TOKEN_FILE}" ]]; then
    python3 - <<'PY' >"${TOKEN_FILE}"
import secrets
print(secrets.token_hex(16))
PY
    chmod 600 "${TOKEN_FILE}" 2>/dev/null || true
fi

TOKEN="$(tr -d '\r\n' < "${TOKEN_FILE}")"

export HOUSEBOT_CODEX_SESSION="norman-switchboard"
export HOUSEBOT_CODEX_TMUX_SOCKET="norman-switchboard"
export HOUSEBOT_CODEX_LAUNCHER="${ROOT_DIR}/scripts/norman_codex_launch.sh"
export HOUSEBOT_CODEX_WORKDIR="${ROOT_DIR}"
export HOUSEBOT_CODEX_HOME="${CODEX_HOME}"
export CODEX_HOME="${CODEX_HOME}"
export HOUSEBOT_CODEX_PROMPT_FILE="${PROMPT_FILE}"
export HOUSEBOT_CODEX_AGENT_NAME="Switchboard"
export HOUSEBOT_CODEX_AGENT_GROUP="Norman"
export HOUSEBOT_CODEX_CONSOLE_TITLE="Switchboard Console"
export HOUSEBOT_CODEX_PROMPT_PLACEHOLDER="Ask Switchboard to triage, route, or supervise a fleet issue."
export HOUSEBOT_CODEX_STYLE_HINT="norman"
export HOUSEBOT_CODEX_UI_PROFILE="slate"
export HOUSEBOT_CODEX_WEB_PORT="${PORT}"
export HOUSEBOT_CODEX_WEB_TOKEN="${TOKEN}"
export HOUSEBOT_CODEX_TRUSTED_CLIENTS="${HOUSEBOT_CODEX_TRUSTED_CLIENTS:-127.0.0.1,::1,192.168.0.136,192.168.0.137,192.168.0.140,192.168.0.144}"
export HOUSEBOT_CODEX_BROWSER_AUTH_CLIENTS="${HOUSEBOT_CODEX_BROWSER_AUTH_CLIENTS:-127.0.0.1,::1,192.168.0.136,192.168.0.137,192.168.0.140}"
export HOUSEBOT_CODEX_TRUSTED_PROXIES="${HOUSEBOT_CODEX_TRUSTED_PROXIES:-127.0.0.1,::1,192.168.0.241}"
export HOUSEBOT_CODEX_CANONICAL_HOST="switchboard.home.arpa"
export HOUSEBOT_CODEX_LOCAL_HOST_ALIASES="switchboard.home.arpa,switchboard.norman.home.arpa,norman.home.arpa,subprime.home.arpa,subprime.norman.home.arpa,botprime.home.arpa,bot.norman.home.arpa"
export HOUSEBOT_CODEX_EXTRA_LINKS_JSON='[{"group":"Norman","label":"Norman","url":"http://norman.home.arpa:8788/","note":"human hub"},{"group":"Norman","label":"Estate Home","url":"http://norman.home.arpa:8000/","note":"directory"}]'
export HOUSEBOT_SERVICE_NAME="norman"
export HOUSEBOT_CODEX_SERVICE_NAME="norman-bot-prime-codex.service"
export HOUSEBOT_CODEX_WEB_SERVICE_NAME="norman-bot-prime-codex-web.service"

if ! tmux -L "${HOUSEBOT_CODEX_TMUX_SOCKET}" has-session -t "${HOUSEBOT_CODEX_SESSION}" 2>/dev/null; then
    nohup "${ROOT_DIR}/scripts/norman_codex_supervisor.sh" >"${CODEX_HOME}/supervisor.log" 2>&1 &
    sleep 2
fi

WEB_SESSION="${HOUSEBOT_CODEX_SESSION}-web"
if ! tmux -L "${HOUSEBOT_CODEX_TMUX_SOCKET}" has-session -t "${WEB_SESSION}" 2>/dev/null; then
    tmux -L "${HOUSEBOT_CODEX_TMUX_SOCKET}" new-session -d -s "${WEB_SESSION}" -c "${ROOT_DIR}" \
        "env -i PATH=${PATH} HOME=/home/operator LANG=C.UTF-8 \
        HOUSEBOT_CODEX_SESSION=${HOUSEBOT_CODEX_SESSION} \
        HOUSEBOT_CODEX_TMUX_SOCKET=${HOUSEBOT_CODEX_TMUX_SOCKET} \
        HOUSEBOT_CODEX_WORKDIR=${ROOT_DIR} \
        HOUSEBOT_CODEX_HOME=${CODEX_HOME} \
        CODEX_HOME=${CODEX_HOME} \
        HOUSEBOT_CODEX_AGENT_NAME='Switchboard' \
        HOUSEBOT_CODEX_AGENT_GROUP=Norman \
        HOUSEBOT_CODEX_CONSOLE_TITLE='Switchboard Console' \
        HOUSEBOT_CODEX_PROMPT_PLACEHOLDER='Ask Switchboard to triage, route, or supervise a fleet issue.' \
        HOUSEBOT_CODEX_STYLE_HINT=norman \
        HOUSEBOT_CODEX_UI_PROFILE=slate \
        HOUSEBOT_CODEX_WEB_BIND=0.0.0.0 \
        HOUSEBOT_CODEX_WEB_PORT=${PORT} \
        HOUSEBOT_CODEX_WEB_TOKEN=${TOKEN} \
        HOUSEBOT_CODEX_TRUSTED_CLIENTS="${HOUSEBOT_CODEX_TRUSTED_CLIENTS}" \
        HOUSEBOT_CODEX_BROWSER_AUTH_CLIENTS="${HOUSEBOT_CODEX_BROWSER_AUTH_CLIENTS}" \
        HOUSEBOT_CODEX_TRUSTED_PROXIES="${HOUSEBOT_CODEX_TRUSTED_PROXIES}" \
        HOUSEBOT_CODEX_CANONICAL_HOST=switchboard.home.arpa \
        HOUSEBOT_CODEX_LOCAL_HOST_ALIASES='switchboard.home.arpa,switchboard.norman.home.arpa,norman.home.arpa,subprime.home.arpa,subprime.norman.home.arpa,botprime.home.arpa,bot.norman.home.arpa' \
        HOUSEBOT_CODEX_EXTRA_LINKS_JSON='[{\"group\":\"Norman\",\"label\":\"Norman\",\"url\":\"http://norman.home.arpa:8788/\",\"note\":\"human hub\"},{\"group\":\"Norman\",\"label\":\"Estate Home\",\"url\":\"http://norman.home.arpa:8000/\",\"note\":\"directory\"}]' \
        HOUSEBOT_SERVICE_NAME=norman \
        HOUSEBOT_CODEX_SERVICE_NAME=norman-bot-prime-codex.service \
        HOUSEBOT_CODEX_WEB_SERVICE_NAME=norman-bot-prime-codex-web.service \
        ${ROOT_DIR}/.venv/bin/python ${ROOT_DIR}/scripts/norman_codex_web.py >>${CODEX_HOME}/web.log 2>&1"
    sleep 2
fi

printf 'Switchboard: http://switchboard.home.arpa:%s/?token=%s\n' "${PORT}" "${TOKEN}"
