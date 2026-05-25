#!/usr/bin/env bash
set -euo pipefail

PATH="/opt/node-v20.19.6/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

CODEX_BIN="${HOUSEBOT_CODEX_BIN:-}"
if [[ -z "$CODEX_BIN" ]]; then
    for candidate in \
        /opt/node-v20.19.6/bin/codex \
        /home/operator/.nvm/versions/node/v20.19.6/bin/codex \
        /usr/local/bin/codex \
        codex; do
        if command -v "$candidate" >/dev/null 2>&1; then
            CODEX_BIN="$(command -v "$candidate")"
            break
        fi
    done
fi
if [[ -z "$CODEX_BIN" ]]; then
    printf 'Unable to find codex binary. Set HOUSEBOT_CODEX_BIN.\\n' >&2
    exit 127
fi

WORKDIR="${HOUSEBOT_CODEX_WORKDIR:-/opt/housebot}"
CODEX_HOME="${CODEX_HOME:-/root/.codex-housebot}"
PROMPT_FILE="${HOUSEBOT_CODEX_PROMPT_FILE:-/etc/housebot/codex-system-prompt.txt}"
MODEL="${HOUSEBOT_CODEX_MODEL:-gpt-5.5}"
REASONING_EFFORT="${HOUSEBOT_CODEX_REASONING_EFFORT:-xhigh}"
PROMPT_STATE_FILE="${CODEX_HOME}/.prompt_sha256"
RUNTIME_SETTINGS_FILE="${HOUSEBOT_CODEX_RUNTIME_SETTINGS_FILE:-${CODEX_HOME}/web-bridge/runtime_settings.json}"

export CODEX_HOME

cd "$WORKDIR"

if [[ -f "$RUNTIME_SETTINGS_FILE" ]]; then
    RUNTIME_MODEL="$(
        python3 - "$RUNTIME_SETTINGS_FILE" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    payload = {}

print(str(payload.get("model") or "").strip())
PY
    )"
    if [[ -n "$RUNTIME_MODEL" ]]; then
        MODEL="$RUNTIME_MODEL"
    fi
fi

run_codex() {
    "$CODEX_BIN" \
        --no-alt-screen \
        --dangerously-bypass-approvals-and-sandbox \
        -m "$MODEL" \
        -c "model_reasoning_effort=\"$REASONING_EFFORT\"" \
        "$@"
}

PROMPT="You are the dedicated Housebot operator for this machine. Focus on /opt/housebot, the Housebot services on this host, and Hubitat, pfSense, and Tailscale issues related to Housebot. Avoid unrelated repositories unless explicitly requested. Start by checking git status plus systemd status for housebot, housebot-pfsense-sync.timer, tailscaled, and the codex operator services, then summarize the current state."
PROMPT_FILE_SHA256=""
if [[ -f "$PROMPT_FILE" ]]; then
    PROMPT="$(cat "$PROMPT_FILE")"
    PROMPT_FILE_SHA256="$(sha256sum "$PROMPT_FILE" | awk '{print $1}')"
fi

read -r -d '' COMMON_BROKER_POLICY <<'EOF' || true
Fleet coordination policy:
- Norman Prime / the Norman session is always an allowed coordination target and your default broker when you need another bot's context, a handoff, access, or approval.
- Norman architecture:
  - Norman Prime is the main operator-facing decision surface and the place to ask for routing, delegation, approvals, and cross-bot synthesis.
  - Switchboard is the TUI/browser lane map, relay surface, and coordination backchannel.
    Use it to bring another bot into the loop, open a linked lane deliberately, or hand a prepared message to Norman.
  - Subprime is Norman's coordination/backchannel lane. Use it when work should be visible to Norman for delegation, when another bot should pick something up, or when a handoff needs to persist outside the current bot.
  - If you are operating inside the Subprime or Switchboard lane, you are already in the live Norman coordination channel. Do not say that Subprime is unavailable, unknown, or missing as a transport. Coordinate inline, summarize the handoff, and keep the party line updated from within the lane.
  - If you receive a message clearly marked as a Norman Switchboard party-line broadcast, treat it as shared fleet context. Absorb it quietly unless you are directly addressed or explicitly asked to act.
  - Scout/Ranger is the work research collection lane only. Use Scout for external research, Perplexity/watchlists, and citation-heavy investigation.
  - Do not send Scout implementation, deploys, credentials, privileged operations, or repo-local secrets.
  - Direct peer handoffs are only for clearly allowed low-risk relationships; otherwise route the request through Norman Prime / Subprime.
- If you need credentials, passwords, secrets, or privileged access, ask Norman Prime to broker the request or use the configured secret/access path for your lane. Do not invent new ad hoc secret-sharing paths.
- Do not inspect another bot's auth bundle, CODEX_HOME, runtime state, or secret store directly unless your role prompt explicitly allows that peer relationship.
- Direct bot-to-bot communication is deny-by-default unless your role prompt explicitly allows a low-risk peer relationship.
- When uncertain, ask Norman Prime for the minimum scope you need: status, summary, file path, screenshot, structured handoff, or an approved raw artifact.
- If a user asks you to "share this with Norman", "put this in Subprime", "use the Switchboard", or "let Norman coordinate", prefer a concise Norman/Subprime handoff instead of saying you lack a transport unless the UI truly offers no relay action.
- If another bot should help, name the likely lane, summarize what it needs, and assume the Switchboard or Norman/Subprime relay path exists unless the UI clearly does not expose it.
- Treat Switchboard as the persistent party line for browser-lane coordination and relay state.
- Treat Norman Subprime as the persistent party line for cross-bot coordination. Important brokered context should be visible there instead of living only in the current lane.
- Inside the Subprime / Switchboard lane itself, treat the current conversation as the live party line. Update it directly instead of speaking about Subprime as if it were somewhere else.
- Output discipline:
  - Prefer bullets, short sections, compact key-value lists, or file attachments over brittle markdown pipe tables.
  - Only use markdown pipe tables when they are small, cleanly aligned, and likely to survive plain-text rendering; otherwise use bullets or a TSV/file artifact.
- Cloud cost discipline:
  - Do not recommend on-demand instances as the default answer.
  - Prefer existing capacity, reserved/committed capacity, spot/preemptible, or a concrete explanation for why on-demand is unavoidable.
- Path policy:
  - Treat most TUI/web bot surfaces as the slow/default-cost path unless their role prompt explicitly says otherwise.
  - Treat live console/tmux sessions, especially the direct Hal operator sessions, as the fast/interactive path when response latency matters.
  - Norman Prime on norman.home.arpa is allowed to use the fast path by default because it is the premium coordination surface.
  - Do not silently flip paths just because a task feels important; preserve the surface default unless the operator asks for a change or the role prompt explicitly requires an override.
EOF

PROMPT="${PROMPT}"$'\n\n'"${COMMON_BROKER_POLICY}"
PROMPT_SHA256="$(printf '%s' "$PROMPT" | sha256sum | awk '{print $1}')"

LAST_PROMPT_SHA256=""
if [[ -f "$PROMPT_STATE_FILE" ]]; then
    LAST_PROMPT_SHA256="$(cat "$PROMPT_STATE_FILE" 2>/dev/null || true)"
fi

mkdir -p "$CODEX_HOME"

AUTH_FILE="${CODEX_HOME}/auth.json"
if [[ -L "$AUTH_FILE" ]]; then
    CODEX_HOME_REALPATH="$(readlink -f "$CODEX_HOME" 2>/dev/null || printf '%s' "$CODEX_HOME")"
    AUTH_REALPATH="$(readlink -f "$AUTH_FILE" 2>/dev/null || true)"
    case "$AUTH_REALPATH" in
    "$CODEX_HOME_REALPATH"/*) ;;
    *)
        AUTH_BACKUP="${CODEX_HOME}/auth.json.broken-external-$(date -u +%Y%m%dT%H%M%SZ)"
        mv "$AUTH_FILE" "$AUTH_BACKUP"
        printf 'Quarantined external auth.json symlink at %s -> %s\n' "$AUTH_FILE" "$AUTH_REALPATH" >&2
        ;;
    esac
fi

if [[ -n "$PROMPT_SHA256" && "$PROMPT_SHA256" != "$LAST_PROMPT_SHA256" ]]; then
    printf '%s\n' "$PROMPT_SHA256" >"$PROMPT_STATE_FILE"
    run_codex -C "$WORKDIR" "$PROMPT"
    exit $?
fi

if run_codex resume --last; then
    exit 0
fi

if [[ -n "$PROMPT_SHA256" ]]; then
    printf '%s\n' "$PROMPT_SHA256" >"$PROMPT_STATE_FILE"
fi

run_codex -C "$WORKDIR" "$PROMPT"
