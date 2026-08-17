#!/usr/bin/env bash
set -euo pipefail

OLLAMA_VERSION="${OLLAMA_QWEN38_VERSION:-0.32.13}"
OLLAMA_ROOT="${OLLAMA_QWEN38_ROOT:-$HOME/.local/opt/ollama-$OLLAMA_VERSION}"
OLLAMA_BIN="${OLLAMA_QWEN38_BIN:-$OLLAMA_ROOT/bin/ollama}"
OLLAMA_MODELS="${OLLAMA_QWEN38_MODELS:-$HOME/.local/share/ollama-qwen38/models}"
OLLAMA_BIND="${OLLAMA_QWEN38_BIND:-0.0.0.0}"
OLLAMA_PORT="${OLLAMA_QWEN38_PORT:-11435}"
OLLAMA_NUM_CTX="${OLLAMA_QWEN38_NUM_CTX:-32768}"
OLLAMA_LOG="${OLLAMA_QWEN38_LOG:-$HOME/.local/state/ollama-qwen38/server.log}"
OLLAMA_PID_FILE="${OLLAMA_QWEN38_PID_FILE:-$HOME/.local/state/ollama-qwen38/server.pid}"
health_host="$OLLAMA_BIND"
if [[ "$health_host" == "0.0.0.0" || "$health_host" == "::" ]]; then
  health_host="127.0.0.1"
fi
BASE_URL="${OLLAMA_QWEN38_HEALTH_URL:-http://$health_host:$OLLAMA_PORT}"

if [[ ! -x "$OLLAMA_BIN" ]]; then
  echo "missing Qwen3.8 Ollama runtime: $OLLAMA_BIN" >&2
  exit 1
fi

mkdir -p "$OLLAMA_MODELS" "$(dirname "$OLLAMA_LOG")"

if curl -fsS --max-time 2 "$BASE_URL/api/version" >/dev/null 2>&1; then
  exit 0
fi

if [[ -s "$OLLAMA_PID_FILE" ]]; then
  old_pid="$(cat "$OLLAMA_PID_FILE")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "Qwen3.8 runtime process $old_pid is alive but not ready" >&2
    exit 1
  fi
  rm -f "$OLLAMA_PID_FILE"
fi

nohup env \
  OLLAMA_HOST="$OLLAMA_BIND:$OLLAMA_PORT" \
  OLLAMA_MODELS="$OLLAMA_MODELS" \
  OLLAMA_CONTEXT_LENGTH="$OLLAMA_NUM_CTX" \
  OLLAMA_KEEP_ALIVE=30m \
  OLLAMA_MAX_LOADED_MODELS=1 \
  OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_MAX_QUEUE=16 \
  "$OLLAMA_BIN" serve >>"$OLLAMA_LOG" 2>&1 </dev/null &
pid="$!"
printf '%s\n' "$pid" >"$OLLAMA_PID_FILE"

for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "$BASE_URL/api/version" >/dev/null 2>&1; then
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    tail -n 40 "$OLLAMA_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done

echo "Qwen3.8 runtime did not become ready at $BASE_URL" >&2
exit 1
