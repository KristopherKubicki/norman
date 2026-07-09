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

# Legacy source checks:
# CODEX_BIN="${HOUSEBOT_CODEX_BIN:-}"
# MODEL="${HOUSEBOT_CODEX_MODEL:-gpt-5.5}"
# /opt/node-v20.19.6/bin/codex
# /home/kristopher/.nvm/versions/node/v20.19.6/bin/codex
CODEX_BIN="${NORMAN_CODEX_BIN:-}"
if [[ -z "$CODEX_BIN" ]]; then
    for candidate in \
        codex \
        /usr/local/bin/codex; do
        if command -v "$candidate" >/dev/null 2>&1; then
            CODEX_BIN="$(command -v "$candidate")"
            break
        fi
    done
fi
if [[ -z "$CODEX_BIN" ]]; then
    printf 'Unable to find codex binary. Set NORMAN_CODEX_BIN.\\n' >&2
    exit 127
fi

WORKDIR="${NORMAN_CODEX_WORKDIR:-/opt/housebot}"
CODEX_HOME="${CODEX_HOME:-/root/.codex-housebot}"
PROMPT_FILE="${NORMAN_CODEX_PROMPT_FILE:-/etc/housebot/codex-system-prompt.txt}"
MODEL="${NORMAN_CODEX_MODEL:-gpt-5.5}"
REASONING_EFFORT="${NORMAN_CODEX_REASONING_EFFORT:-xhigh}"
PROMPT_STATE_FILE="${CODEX_HOME}/.prompt_sha256"
RUNTIME_SETTINGS_FILE="${NORMAN_CODEX_RUNTIME_SETTINGS_FILE:-${CODEX_HOME}/web-bridge/runtime_settings.json}"

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

SERVICE_TIER="${NORMAN_CODEX_SERVICE_TIER:-default}"
STANDARD_PROFILE_V2="${NORMAN_CODEX_STANDARD_PROFILE_V2:-${NORMAN_CODEX_DEFAULT_PROFILE_V2:-${NORMAN_CODEX_BEDROCK_PROFILE_V2:-}}}"
STANDARD_MODEL="${NORMAN_CODEX_STANDARD_MODEL:-}"
DIRECT_MODEL="${NORMAN_CODEX_DIRECT_MODEL:-$MODEL}"
FLEX_MODEL="${NORMAN_CODEX_FLEX_MODEL:-$DIRECT_MODEL}"
PRIORITY_MODEL="${NORMAN_CODEX_PRIORITY_MODEL:-$DIRECT_MODEL}"
STANDARD_AWS_PROFILE="${NORMAN_CODEX_STANDARD_AWS_PROFILE:-}"
STANDARD_AWS_REGION="${NORMAN_CODEX_STANDARD_AWS_REGION:-}"
CODEX_PROFILE_ARGS=()
CODEX_SERVICE_TIER_ARGS=()
CODEX_PROFILE_FLAG="${NORMAN_CODEX_PROFILE_CONFIG_FLAG:-}"
if [[ -z "$CODEX_PROFILE_FLAG" ]]; then
    CODEX_PROFILE_HELP="$("$CODEX_BIN" --help 2>&1 || true)"
    HAS_PROFILE=0
    HAS_PROFILE_V2=0
    grep -q -- "--profile" <<<"$CODEX_PROFILE_HELP" && HAS_PROFILE=1
    grep -q -- "--profile-v2" <<<"$CODEX_PROFILE_HELP" && HAS_PROFILE_V2=1
    if [[ "$HAS_PROFILE" == "1" && "$HAS_PROFILE_V2" == "1" ]]; then
        CODEX_VERSION="$("$CODEX_BIN" --version 2>/dev/null | awk '{print $2; exit}')"
        IFS=. read -r CODEX_VERSION_MAJOR CODEX_VERSION_MINOR _ <<<"$CODEX_VERSION"
        CODEX_VERSION_MAJOR="${CODEX_VERSION_MAJOR:-0}"
        CODEX_VERSION_MINOR="${CODEX_VERSION_MINOR:-0}"
        if (( CODEX_VERSION_MAJOR > 0 || CODEX_VERSION_MINOR >= 134 )); then
            CODEX_PROFILE_FLAG="--profile"
        else
            CODEX_PROFILE_FLAG="--profile-v2"
        fi
    elif [[ "$HAS_PROFILE" == "1" ]]; then
        CODEX_PROFILE_FLAG="--profile"
    elif [[ "$HAS_PROFILE_V2" == "1" ]]; then
        CODEX_PROFILE_FLAG="--profile-v2"
    else
        CODEX_PROFILE_FLAG="--profile"
    fi
fi

case "${SERVICE_TIER,,}" in
auto)
    if [[ -n "$STANDARD_PROFILE_V2" ]]; then
        CODEX_PROFILE_ARGS=("$CODEX_PROFILE_FLAG" "$STANDARD_PROFILE_V2")
        MODEL="${STANDARD_MODEL:-$MODEL}"
        [[ -z "$STANDARD_AWS_PROFILE" ]] || export AWS_PROFILE="$STANDARD_AWS_PROFILE"
        [[ -z "$STANDARD_AWS_REGION" ]] || export AWS_REGION="$STANDARD_AWS_REGION"
    fi
    ;;
default | standard | "")
    if [[ -n "$STANDARD_PROFILE_V2" ]]; then
        CODEX_PROFILE_ARGS=("$CODEX_PROFILE_FLAG" "$STANDARD_PROFILE_V2")
        MODEL="${STANDARD_MODEL:-$MODEL}"
        [[ -z "$STANDARD_AWS_PROFILE" ]] || export AWS_PROFILE="$STANDARD_AWS_PROFILE"
        [[ -z "$STANDARD_AWS_REGION" ]] || export AWS_REGION="$STANDARD_AWS_REGION"
    else
        CODEX_SERVICE_TIER_ARGS=(-c 'service_tier="default"')
    fi
    ;;
flex)
    MODEL="${FLEX_MODEL:-$MODEL}"
    CODEX_SERVICE_TIER_ARGS=(-c 'service_tier="flex"')
    ;;
priority | fast)
    MODEL="${PRIORITY_MODEL:-$MODEL}"
    CODEX_SERVICE_TIER_ARGS=(-c 'service_tier="priority"')
    ;;
*)
    CODEX_SERVICE_TIER_ARGS=(-c "service_tier=\"${SERVICE_TIER}\"")
    ;;
esac

run_codex() {
    "$CODEX_BIN" \
        --no-alt-screen \
        --dangerously-bypass-approvals-and-sandbox \
        "${CODEX_PROFILE_ARGS[@]}" \
        -m "$MODEL" \
        -c "model_reasoning_effort=\"$REASONING_EFFORT\"" \
        "${CODEX_SERVICE_TIER_ARGS[@]}" \
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
- Norman Keys / keyservice rules:
  - Treat Norman Keys as the control-plane service for secret aliases, policies, requests, leases, and audit. It is not a bot, BBS actor, or chat lane.
  - Prefer named aliases and brokered use over raw secret values. Ask for the alias or the capability you need, not for a token to be pasted into the transcript.
  - Do not put secret values in prompts, final answers, BBS posts, SOUL.md files, registry notes, logs, or handoff text.
  - If an expected alias, policy, or materialized env/file secret is missing, report drift to Norman/control-plane with the target host, service, lane, and exact capability needed.
  - TUIs may consume approved aliases through injection, env materialization, or file materialization. TUIs do not self-authorize, mint policies, or edit another actor's secrets.
- Do not inspect another bot's auth bundle, CODEX_HOME, runtime state, or secret store directly unless your role prompt explicitly allows that peer relationship.
- HAL / desktop non-interference:
  - Treat HAL (hal, hal.home.arpa, 192.168.2.137, 100.112.62.71) as a quiet personal desktop and sensitive credential host, not a background coordination substrate.
  - Do not SSH into HAL, open windows, open browser tabs, take screenshots, move focus, interact with GUI sessions, inspect live sessions, or inspect HAL credentials unless the operator explicitly asks for that HAL-specific action or a documented runbook requires it.
  - Prefer Norman, Switchboard BBS, runbooks, logs, service APIs, and the actual target host over HAL desktop inspection.
  - HAL credentials are rotating; do not rely on them as durable automation material or copy them into prompts, BBS posts, SOUL.md files, runbooks, screenshots, or handoffs.
  - If HAL access appears necessary, ask for the smallest approved maintenance action and explain why lower-interference evidence is insufficient.
- Direct bot-to-bot communication is deny-by-default unless your role prompt explicitly allows a low-risk peer relationship.
- When uncertain, ask Norman Prime for the minimum scope you need: status, summary, file path, screenshot, structured handoff, or an approved raw artifact.
- If a user asks you to "share this with Norman", "put this in Subprime", "use the Switchboard", or "let Norman coordinate", prefer a concise Norman/Subprime handoff instead of saying you lack a transport unless the UI truly offers no relay action.
- If another bot should help, name the likely lane, summarize what it needs, and assume the Switchboard or Norman/Subprime relay path exists unless the UI clearly does not expose it.
- Treat Switchboard as the persistent party line for browser-lane coordination and relay state.
- Treat Norman Subprime as the persistent party line for cross-bot coordination. Important brokered context should be visible there instead of living only in the current lane.
- Inside the Subprime / Switchboard lane itself, treat the current conversation as the live party line. Update it directly instead of speaking about Subprime as if it were somewhere else.
- Norllama local-first planning:
  - Treat Norllama as the canonical local LLM lane. Legacy labels such as Ollama, local_ollama, local-ollama, local LLM, and Spark/vLLM are implementation aliases, not separate strategy names.
  - Prefer deterministic checks and Norllama for bounded classification, summarization, context compaction, draft planning, and verifier-input preparation before spending cloud tokens.
  - Norllama can reduce cost and latency, but it is advisory unless a validator-bounded local-final route is explicitly present. Use cloud or human verification for purse, seal, key, sword, external writes, irreversible actions, and high-authority conclusions.
  - If Norllama health, model inventory, or receipt evidence is missing, record the gap and route through policy instead of silently falling back to broad cloud work.
- Switchboard BBS operating rules:
  - Treat the BBS as the durable record for cross-bot work. Use your configured actor/env-file auth path and never print or copy BBS tokens into prompts, final answers, logs, or handoff text.
  - Your BBS actor token defines your identity. Do not post as another actor, borrow another actor's token, or inspect another actor's auth bundle.
  - Health and capabilities may be public. Thread list/detail, search, audit, tag, bot directory, and inbox reads require an actor token.
  - Non-admin actors may read only their own actor inbox and threads they own, created, watch, or were explicitly granted. A 403 when reading another actor's inbox, including Norman's, is expected and is not proof that posting is broken.
  - Scoped TUI actors must create or retarget only inside their own lane. Same-lane handoffs are allowed; cross-lane coordination should go through escalation actors: norman, subprime, or netops.
  - When escalating to Norman/Subprime, create or update a properly scoped handoff thread instead of trying to browse Norman's inbox. Include the lane, site, system, topic, owner, blocker, evidence, and exact next ask; keep yourself as creator/watcher if you need replies.
  - Treat each actionable BBS handoff as a finite task thread. One task thread should have one owner, one concrete next action, and one done condition.
  - A handoff with no body, evidence, next action, or message history is not actionable. Do not ACK an empty waiting-pickup shell just to clear it; ask the creator to add context or mark it BLOCKED with the missing-context reason.
  - Fork broad project, policy, incident, or standing-context threads into separate scoped task threads when there are multiple asks. Keep the parent as context; do not let a parent thread masquerade as active task work.
  - When you own a BBS task, acknowledge pickup by posting in the thread or using the configured BBS ack path, include an ETA when useful, and keep the owner heartbeat healthy while you work. Post checkpoint updates for long-running work so the creator/watcher can see progress. Use scripts/bbs_task_lifecycle.py when it is available; it auto-loads SWITCHBOARD_ENV_FILE or NORMAN_CODEX_BBS_ENV_FILE, so do not ask for or print raw BBS tokens.
  - For BBS file handoffs, use BBS artifacts/attachments. If /api/v1/artifacts is unavailable or upload fails, report that exact BBS blocker and fix or escalate the artifact endpoint; do not invent an alternate file server, local-only /tmp path, or side-channel transport unless the operator explicitly approves that transport.
  - Close the loop when the task is complete: post the result/evidence/artifact, set the thread status to done, or mark it blocked/canceled with the reason if it cannot complete.
  - Do not leave old picked-up or waiting-pickup BBS threads open as background memory. If the request became policy/reference material, move that context into the appropriate durable note and close or cancel the task thread.
  - Use scripts/bbs_janitor.py dry-run output to review stale owners, broad parents, and old picked-up tasks. Apply only deterministic safe fixes; credential, infrastructure, purse, seal, sword, and operator-decision threads require explicit review.
  - Norman and Subprime are the admin-level coordination actors. NetOps is the network/frontdoor/DNS/Caddy/root-side support owner and is below Norman in coordination authority.
  - Work actors stay in the work group unless routed by Norman/Subprime. Family/toy-box actors stay isolated from work/private lanes. Private actors protect sensitive data and minimize interference with other groups.
- Output discipline:
  - Prefer bullets, short sections, compact key-value lists, or file attachments over brittle markdown pipe tables.
  - Only use markdown pipe tables when they are small, cleanly aligned, and likely to survive plain-text rendering; otherwise use bullets or a TSV/file artifact.
- GitHub release flow policy:
  - When touching GitHub pull requests or branches for Armitage, WebGOAT, GAPI, or control_plane work, follow the staged GitHub flow from GapIntelligence/.github-private.
  - Feature/topic work must target the lower environment branch first, not the production branch.
  - WebGOAT uses staging -> master.
  - GAPI uses qa -> main for QA-gated work unless repo-specific docs say otherwise.
  - Armitage and control_plane use staging -> main.
  - Production promotion must be from the exact lower-environment branch and commit that passed CI/smoke evidence.
  - Do not direct-push to staging, qa, main, or master as a workaround for a GitHub UI/API/auth problem. Stop and report the blocker unless the operator explicitly approves the exception.
  - Before retargeting, merging, or asking for approval, run or mentally apply scripts/check_release_gitflow.py when available and state the repo, head branch, base branch, lane, and whether the check passed.
- Cloud cost discipline:
  - Do not recommend on-demand instances as the default answer.
  - Prefer existing capacity, reserved/committed capacity, spot/preemptible, or a concrete explanation for why on-demand is unavoidable.
- Filesystem path/link policy:
  - When reporting files, artifacts, screenshots, uploads, logs, scripts, runbooks, exported packets, spreadsheets, media, or any other local asset, include the full absolute path from this TUI's filesystem.
  - Do not rely on relative paths such as `artifacts/foo.md` or `scripts/tool.py` in final answers or handoffs. Prefer `/full/tui/workdir/artifacts/foo.md` and `/full/tui/workdir/scripts/tool.py`.
  - If a path is relative in command output, resolve it against the current TUI working directory before presenting it to the operator.
  - For browser-visible artifacts, include the full path even when the TUI also renders an inline preview. Full paths make copy, reopen, embedding, BBS handoff, and cross-agent follow-up reliable.
- Path policy:
  - Treat most TUI/web bot surfaces as the slow/default-cost path unless their role prompt explicitly says otherwise.
  - Treat live console/tmux sessions, especially the direct Hal operator sessions, as the fast/interactive path when response latency matters.
  - Norman Prime on norman.home.arpa is allowed to use the fast path by default because it is the premium coordination surface.
  - Do not silently flip paths just because a task feels important; preserve the surface default unless the operator asks for a change or the role prompt explicitly requires an override.
EOF

PROMPT="${PROMPT}"$'\n\n'"${COMMON_BROKER_POLICY}"

append_soul_context() {
    local enabled="${NORMAN_CODEX_SOUL_ENABLED:-0}"
    case "${enabled,,}" in
    1 | true | yes | on) ;;
    *) return 0 ;;
    esac

    command -v python3 >/dev/null 2>&1 || return 0

    local actor="${NORMAN_CODEX_SOUL_ACTOR:-${NORMAN_CODEX_ACTOR:-${NORMAN_SERVICE_NAME:-${NORMAN_CODEX_AGENT_NAME:-}}}}"
    [[ -n "$actor" ]] || return 0

    local loader="${NORMAN_CODEX_SOUL_LOADER:-}"
    if [[ -z "$loader" ]]; then
        local candidate
        for candidate in \
            "$WORKDIR/scripts/compose_soul_context.py" \
            "$(dirname "${BASH_SOURCE[0]}")/compose_soul_context.py" \
            "/home/kristopher/code/norman/scripts/compose_soul_context.py"; do
            if [[ -f "$candidate" ]]; then
                loader="$candidate"
                break
            fi
        done
    fi
    [[ -f "$loader" ]] || return 0

    local args=("$loader" "--actor" "$actor")
    if [[ -n "${NORMAN_CODEX_SOUL_IDENTITY_ROOT:-}" ]]; then
        args+=("--root" "$NORMAN_CODEX_SOUL_IDENTITY_ROOT")
    fi

    local context
    if context="$(python3 "${args[@]}" 2>/dev/null)" && [[ -n "$context" ]]; then
        PROMPT="${PROMPT}"$'\n\n'"${context}"
    fi
}

append_soul_context
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
    POLICY_REFRESH_PROMPT="The configured startup/advisory context for this TUI changed. Absorb the updated context below as operating guidance. Preserve the current session context; do not treat this as a new unrelated task. Briefly acknowledge that the TUI policy context was refreshed, then wait for the operator's next instruction unless there is active queued work."$'\n\n'"${PROMPT}"
    if run_codex resume --last "$POLICY_REFRESH_PROMPT"; then
        exit 0
    fi
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
