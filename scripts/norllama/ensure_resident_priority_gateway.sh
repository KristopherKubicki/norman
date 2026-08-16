#!/usr/bin/env bash
set -euo pipefail

NORLLAMA_ROOT="${NORLLAMA_ROOT:-$HOME/norllama}"
NORLLAMA_PYTHON="${NORLLAMA_PYTHON:-/usr/bin/python3}"
NORLLAMA_GATEWAY="${NORLLAMA_GATEWAY:-$NORLLAMA_ROOT/norllama_gateway.py}"
NORLLAMA_BIND="${NORLLAMA_PRIORITY_BIND:-0.0.0.0}"
NORLLAMA_PORT="${NORLLAMA_PRIORITY_PORT:-18161}"
NORLLAMA_BACKENDS="${NORLLAMA_PRIORITY_BACKENDS:-http://127.0.0.1:11435}"
NORLLAMA_ADMISSION_BASES="${NORLLAMA_PRIORITY_ADMISSION_BASES:-$NORLLAMA_BACKENDS}"
DEFAULT_POLICY="$NORLLAMA_ROOT/route_policy.json"
if [[ -f "$NORLLAMA_ROOT/route_policy.next.json" ]]; then
  DEFAULT_POLICY="$NORLLAMA_ROOT/route_policy.next.json"
fi
NORLLAMA_POLICY="${NORMAN_NORLLAMA_ROUTE_POLICY_PATH:-$DEFAULT_POLICY}"
NORLLAMA_LOG="${NORLLAMA_PRIORITY_LOG:-$HOME/.local/state/norllama-priority/gateway.log}"
NORLLAMA_PID_FILE="${NORLLAMA_PRIORITY_PID_FILE:-$HOME/.local/state/norllama-priority/gateway.pid}"
health_host="$NORLLAMA_BIND"
if [[ "$health_host" == "0.0.0.0" || "$health_host" == "::" ]]; then
  health_host="127.0.0.1"
fi
BASE_URL="${NORLLAMA_PRIORITY_HEALTH_URL:-http://$health_host:$NORLLAMA_PORT}"

mkdir -p "$(dirname "$NORLLAMA_LOG")"

if curl -fsS --max-time 2 "$BASE_URL/healthz" >/dev/null 2>&1; then
  exit 0
fi

if [[ -s "$NORLLAMA_PID_FILE" ]]; then
  old_pid="$(cat "$NORLLAMA_PID_FILE")"
  if kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid"
    for _ in $(seq 1 20); do
      kill -0 "$old_pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
  rm -f "$NORLLAMA_PID_FILE"
fi

nohup env \
  PYTHONPATH="$NORLLAMA_ROOT" \
  NORLLAMA_BIND="$NORLLAMA_BIND" \
  NORLLAMA_PORT="$NORLLAMA_PORT" \
  NORLLAMA_OLLAMA_BASES="$NORLLAMA_BACKENDS" \
  NORLLAMA_ADMISSION_BASES="$NORLLAMA_ADMISSION_BASES" \
  NORLLAMA_PEER_BASES="" \
  NORLLAMA_CHAT_MAX_ACTIVE=1 \
  NORLLAMA_CHAT_QUEUE_LIMIT=8 \
  NORLLAMA_CHAT_QUEUE_WAIT_S=10 \
  NORLLAMA_CHAT_RETRY_AFTER_S=3 \
  NORMAN_NORLLAMA_ROUTE_POLICY_PATH="$NORLLAMA_POLICY" \
  "$NORLLAMA_PYTHON" "$NORLLAMA_GATEWAY" >>"$NORLLAMA_LOG" 2>&1 </dev/null &
pid="$!"
printf '%s\n' "$pid" >"$NORLLAMA_PID_FILE"

for _ in $(seq 1 40); do
  if curl -fsS --max-time 2 "$BASE_URL/healthz" >/dev/null 2>&1; then
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    tail -n 40 "$NORLLAMA_LOG" >&2 || true
    exit 1
  fi
  sleep 0.25
done

echo "Norllama priority gateway did not become ready at $BASE_URL" >&2
exit 1
