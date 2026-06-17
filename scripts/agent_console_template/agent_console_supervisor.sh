#!/usr/bin/env bash
set -euo pipefail

bridge_console_env_prefixes() {
    local name suffix alias
    for name in ${!NORMAN_CODEX_@}; do
        suffix="${name#NORMAN_CODEX_}"
        alias="HOUSEBOT_CODEX_${suffix}"
        if [[ -z "${!alias+x}" ]]; then
            export "$alias=${!name}"
        fi
    done
    for name in ${!HOUSEBOT_CODEX_@}; do
        suffix="${name#HOUSEBOT_CODEX_}"
        alias="NORMAN_CODEX_${suffix}"
        if [[ -z "${!alias+x}" ]]; then
            export "$alias=${!name}"
        fi
    done
}

bridge_console_env_prefixes

SESSION="${NORMAN_CODEX_SESSION:-housebot-codex}"
TMUX_SOCKET="${NORMAN_CODEX_TMUX_SOCKET:-$SESSION}"
WORKDIR="${NORMAN_CODEX_WORKDIR:-/opt/housebot}"
LAUNCHER="${NORMAN_CODEX_LAUNCHER:-/opt/housebot/scripts/housebot_codex_launch.sh}"
CODEX_HOME="${CODEX_HOME:-${NORMAN_CODEX_HOME:-}}"
UPDATE_INTERSTITIAL_CHOICE="${NORMAN_CODEX_UPDATE_INTERSTITIAL_CHOICE:-2}"
AUTO_CLEAR_UPDATE_INTERSTITIAL="${NORMAN_CODEX_AUTO_CLEAR_UPDATE_INTERSTITIAL:-1}"
AUTO_CLEAR_AUTH_INTERSTITIAL="${NORMAN_CODEX_AUTO_CLEAR_AUTH_INTERSTITIAL:-1}"

tmux_cmd() {
    tmux -L "$TMUX_SOCKET" "$@"
}

start_session() {
    tmux_cmd new-session -d -s "$SESSION" -c "$WORKDIR" "$LAUNCHER"
}

capture_pane() {
    tmux_cmd capture-pane -p -t "${SESSION}:0.0" -S -120 2>/dev/null || true
}

latest_line_number() {
    local pane_text="$1"
    local needle="$2"
    printf '%s\n' "$pane_text" | nl -ba | grep -F "$needle" | tail -n1 | awk '{print $1}'
}

clear_update_interstitial() {
    [[ "$AUTO_CLEAR_UPDATE_INTERSTITIAL" == "0" ]] && return 1
    local pane_text="$1"
    if [[ "$pane_text" == *"Update available!"* && "$pane_text" == *"Press enter to continue"* ]]; then
        case "$UPDATE_INTERSTITIAL_CHOICE" in
            1)
                tmux_cmd send-keys -t "${SESSION}:0.0" Enter
                ;;
            3)
                tmux_cmd send-keys -t "${SESSION}:0.0" Down Down Enter
                ;;
            *)
                tmux_cmd send-keys -t "${SESSION}:0.0" Down Enter
                ;;
        esac
        return 0
    fi
    return 1
}

clear_auth_interstitial() {
    [[ "$AUTO_CLEAR_AUTH_INTERSTITIAL" == "0" ]] && return 1
    local pane_text="$1"
    local signed_in_line trust_line ready_line
    signed_in_line="$(latest_line_number "$pane_text" "Signed in with your ChatGPT account")"
    trust_line="$(latest_line_number "$pane_text" "Do you trust the contents of this directory?")"
    ready_line="$(latest_line_number "$pane_text" "OpenAI Codex (v")"

    signed_in_line="${signed_in_line:-0}"
    trust_line="${trust_line:-0}"
    ready_line="${ready_line:-0}"

    if (( trust_line > ready_line )) && [[ "$pane_text" == *"1. Yes, continue"* ]] && [[ "$pane_text" == *"2. No, quit"* ]]; then
        tmux_cmd send-keys -t "${SESSION}:0.0" "1" Enter
        return 0
    fi
    if (( signed_in_line > ready_line && trust_line == 0 )) && [[ "$pane_text" == *"Press Enter to continue"* ]]; then
        tmux_cmd send-keys -t "${SESSION}:0.0" Enter
        return 0
    fi
    return 1
}

while true; do
    if ! tmux_cmd has-session -t "$SESSION" 2>/dev/null; then
        start_session
        sleep 2
    else
        pane_text="$(capture_pane)"
        clear_update_interstitial "$pane_text" || clear_auth_interstitial "$pane_text" || true
    fi
    sleep 5
done
