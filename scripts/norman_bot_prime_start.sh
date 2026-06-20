#!/usr/bin/env bash
set -euo pipefail

BASE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
NODE_BIN_DIRS=()

add_node_bin_dir() {
    local candidate="$1"
    [[ -n "$candidate" ]] || return 0
    if [[ "${candidate##*/}" != "bin" ]]; then
        candidate="${candidate}/bin"
    fi
    [[ -x "${candidate}/node" ]] || return 0
    local existing
    for existing in "${NODE_BIN_DIRS[@]}"; do
        [[ "$existing" != "$candidate" ]] || return 0
    done
    NODE_BIN_DIRS+=("$candidate")
}

collect_node_bin_dirs() {
    local pattern="$1"
    local candidate
    while IFS= read -r candidate; do
        add_node_bin_dir "$candidate"
    done < <(compgen -G "$pattern" | sort -V -r)
}

IFS=':' read -r -a CONFIGURED_NODE_PATHS <<<"${NORMAN_CODEX_NODE_PATHS:-}"
for configured_node_path in "${CONFIGURED_NODE_PATHS[@]}"; do
    add_node_bin_dir "$configured_node_path"
done
add_node_bin_dir "${NORMAN_CODEX_NODE_DIR:-}"
if [[ -n "${NORMAN_CODEX_NODE_BIN:-}" ]]; then
    add_node_bin_dir "$(dirname "$NORMAN_CODEX_NODE_BIN")"
fi
collect_node_bin_dirs "/opt/node-v*/bin"
collect_node_bin_dirs "/home/operator/.nvm/versions/node/v*/bin"
collect_node_bin_dirs "/home/kristopher/.nvm/versions/node/v*/bin"
collect_node_bin_dirs "/root/.nvm/versions/node/v*/bin"

if ((${#NODE_BIN_DIRS[@]})); then
    NODE_PATH_PREFIX="$(IFS=:; printf '%s' "${NODE_BIN_DIRS[*]}")"
    PATH="${NODE_PATH_PREFIX}:${BASE_PATH}"
else
    PATH="$BASE_PATH"
fi
export PATH

while IFS='=' read -r name _; do
    unset "${name}"
done < <(env | grep -E '^(NORMAN_CODEX_|HOUSEBOT_CODEX_)' || true)
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

export NORMAN_CODEX_SESSION="norman-switchboard"
export NORMAN_CODEX_TMUX_SOCKET="norman-switchboard"
export NORMAN_CODEX_LAUNCHER="${ROOT_DIR}/scripts/norman_codex_launch.sh"
export NORMAN_CODEX_WORKDIR="${ROOT_DIR}"
export NORMAN_CODEX_HOME="${CODEX_HOME}"
export CODEX_HOME="${CODEX_HOME}"
export NORMAN_CODEX_PROMPT_FILE="${PROMPT_FILE}"
export NORMAN_CODEX_AGENT_NAME="Switchboard"
export NORMAN_CODEX_AGENT_GROUP="Norman"
export NORMAN_CODEX_CONSOLE_TITLE="Switchboard Console"
export NORMAN_CODEX_PROMPT_PLACEHOLDER="Ask Switchboard to triage, route, or supervise a fleet issue."
export NORMAN_CODEX_STYLE_HINT="norman"
export NORMAN_CODEX_UI_PROFILE="slate"
export NORMAN_CODEX_WEB_PORT="${PORT}"
export NORMAN_CODEX_WEB_TOKEN="${TOKEN}"
export NORMAN_CODEX_TRUSTED_CLIENTS="${NORMAN_CODEX_TRUSTED_CLIENTS:-127.0.0.1,::1,192.168.2.241,100.103.34.17,fd7a:115c:a1e0::3438:2211,192.168.2.136,100.78.41.73,fd7a:115c:a1e0::4d33:2949,192.168.2.137,100.112.62.71,192.168.2.140,100.109.202.7,192.168.2.144}"
export NORMAN_CODEX_BROWSER_AUTH_CLIENTS="${NORMAN_CODEX_BROWSER_AUTH_CLIENTS:-127.0.0.1,::1}"
export NORMAN_CODEX_TRUSTED_PROXIES="${NORMAN_CODEX_TRUSTED_PROXIES:-127.0.0.1,::1,192.168.2.241,100.103.34.17,fd7a:115c:a1e0::3438:2211}"
export NORMAN_CODEX_CANONICAL_HOST="switchboard.home.arpa"
export NORMAN_CODEX_LOCAL_HOST_ALIASES="switchboard.home.arpa,switchboard.norman.home.arpa,norman.home.arpa,subprime.home.arpa,subprime.norman.home.arpa,botprime.home.arpa,bot.norman.home.arpa"
export NORMAN_CODEX_EXTRA_LINKS_JSON='[{"group":"Norman","label":"Norman","url":"http://norman.home.arpa:8788/","note":"human hub"},{"group":"Norman","label":"Estate Home","url":"http://norman.home.arpa:8000/","note":"directory"}]'
export NORMAN_SERVICE_NAME="norman"
export NORMAN_CODEX_SERVICE_NAME="norman-bot-prime-codex.service"
export NORMAN_CODEX_WEB_SERVICE_NAME="norman-bot-prime-codex-web.service"

if ! tmux -L "${NORMAN_CODEX_TMUX_SOCKET}" has-session -t "${NORMAN_CODEX_SESSION}" 2>/dev/null; then
    nohup "${ROOT_DIR}/scripts/norman_codex_supervisor.sh" >"${CODEX_HOME}/supervisor.log" 2>&1 &
    sleep 2
fi

WEB_SESSION="${NORMAN_CODEX_SESSION}-web"
if ! tmux -L "${NORMAN_CODEX_TMUX_SOCKET}" has-session -t "${WEB_SESSION}" 2>/dev/null; then
    tmux -L "${NORMAN_CODEX_TMUX_SOCKET}" new-session -d -s "${WEB_SESSION}" -c "${ROOT_DIR}" \
        "env -i PATH=${PATH} HOME=/home/operator LANG=C.UTF-8 \
        NORMAN_CODEX_SESSION=${NORMAN_CODEX_SESSION} \
        NORMAN_CODEX_TMUX_SOCKET=${NORMAN_CODEX_TMUX_SOCKET} \
        NORMAN_CODEX_WORKDIR=${ROOT_DIR} \
        NORMAN_CODEX_HOME=${CODEX_HOME} \
        CODEX_HOME=${CODEX_HOME} \
        NORMAN_CODEX_AGENT_NAME='Switchboard' \
        NORMAN_CODEX_AGENT_GROUP=Norman \
        NORMAN_CODEX_CONSOLE_TITLE='Switchboard Console' \
        NORMAN_CODEX_PROMPT_PLACEHOLDER='Ask Switchboard to triage, route, or supervise a fleet issue.' \
        NORMAN_CODEX_STYLE_HINT=norman \
        NORMAN_CODEX_UI_PROFILE=slate \
        NORMAN_CODEX_WEB_BIND=0.0.0.0 \
        NORMAN_CODEX_WEB_PORT=${PORT} \
        NORMAN_CODEX_WEB_TOKEN=${TOKEN} \
        NORMAN_CODEX_TRUSTED_CLIENTS="${NORMAN_CODEX_TRUSTED_CLIENTS}" \
        NORMAN_CODEX_BROWSER_AUTH_CLIENTS="${NORMAN_CODEX_BROWSER_AUTH_CLIENTS}" \
        NORMAN_CODEX_TRUSTED_PROXIES="${NORMAN_CODEX_TRUSTED_PROXIES}" \
        NORMAN_CODEX_CANONICAL_HOST=switchboard.home.arpa \
        NORMAN_CODEX_LOCAL_HOST_ALIASES='switchboard.home.arpa,switchboard.norman.home.arpa,norman.home.arpa,subprime.home.arpa,subprime.norman.home.arpa,botprime.home.arpa,bot.norman.home.arpa' \
        NORMAN_CODEX_EXTRA_LINKS_JSON='[{\"group\":\"Norman\",\"label\":\"Norman\",\"url\":\"http://norman.home.arpa:8788/\",\"note\":\"human hub\"},{\"group\":\"Norman\",\"label\":\"Estate Home\",\"url\":\"http://norman.home.arpa:8000/\",\"note\":\"directory\"}]' \
        NORMAN_SERVICE_NAME=norman \
        NORMAN_CODEX_SERVICE_NAME=norman-bot-prime-codex.service \
        NORMAN_CODEX_WEB_SERVICE_NAME=norman-bot-prime-codex-web.service \
        ${ROOT_DIR}/.venv/bin/python ${ROOT_DIR}/scripts/norman_codex_web.py >>${CODEX_HOME}/web.log 2>&1"
    sleep 2
fi

printf 'Switchboard: http://switchboard.home.arpa:%s/?token=%s\n' "${PORT}" "${TOKEN}"
