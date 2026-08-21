# Runaway and Chain Cost Controls

Norman treats long chains as a reliability and cost problem, not merely a token
limit problem. If every uncertain step succeeds with probability `p`, a chain
of `n` independent uncertain steps succeeds with probability `p^n`. Real tool
failures are often correlated, which makes early detection more important than
the simple formula suggests.

## Control Model

The platform uses bounded evidence and three actions:

- `normal`: continue.
- `checkpoint` or `warn`: reduce, batch, or inspect the next operation.
- `stop`: deny another TUI turn or block CLI resume until a fresh handoff.

High-confidence stop signals are repeated prompts, trailing failures,
compaction loops, exhausted tool-continuation repair, and exact repeated tool
calls. Token and tool density trigger checkpoints or warnings unless combined
with a stronger loop signal.

## Surfaces

The OpenAI-compatible proxy emits content-safe prompt, request-shape, and
workflow hashes. Health is scoped to the latest workflow hash so unrelated
traffic does not create a false loop. Alerts expose signal codes and counts,
not prompt text or tool arguments. Requests with an explicit workflow or thread
identifier are rejected before model invocation once that workflow reaches a
stop state. Unscoped traffic remains observe-only.

The TUI reads a bounded recent window from the durable usage and turn ledgers.
It denies a new turn for a stop signal and surfaces the same state in the
context meter. Dense recent token or tool use requires a checkpoint before more
work.

The Codex CLI pressure guard scans at most 4 MiB and 400 events from active and
recent session JSONL files. It blocks direct resume for an oversized session or
a high-confidence compaction/non-polling-tool loop. Repeated passive status
polls do not trigger a hard stop. The monitor never terminates a live process
automatically.

## DAG Guidance

A DAG is only a dependency graph: run independent work together, and run
dependent work in order. Norman does not require a general DAG engine for these
controls. The useful rule is narrower:

1. Remove calls that do not change a decision.
2. Batch independent reads and checks.
3. Put validation at the boundary where failure becomes expensive.
4. Stop when new calls repeat evidence instead of reducing uncertainty.

This keeps graph structure as a planning aid without adding scheduler
complexity to ordinary CLI or TUI work.

## Default Tuning

TUI thresholds use:

- `NORMAN_CODEX_RUNAWAY_WINDOW_TURNS=8`
- `NORMAN_CODEX_MAX_RECENT_COMPACTIONS=3`
- `NORMAN_CODEX_MAX_REPEATED_PROMPTS=3`
- `NORMAN_CODEX_MAX_CONSECUTIVE_FAILURES=3`
- `NORMAN_CODEX_MAX_RECENT_TOOL_CALLS=80`
- `NORMAN_CODEX_MAX_RECENT_TOKENS=100000`

CLI thresholds use:

- `NORMAN_CODEX_SESSION_TAIL_BYTES=4194304`
- `NORMAN_CODEX_SESSION_TAIL_EVENTS=400`
- `NORMAN_CODEX_COMPACTION_STOP_COUNT=3`
- `NORMAN_CODEX_REPEATED_TOOL_STOP_COUNT=3`
- `NORMAN_CODEX_TOOL_DENSITY_WARN_COUNT=80`

The proxy circuit breaker is enabled with
`NORMAN_PROXY_RUNAWAY_GUARD_ENABLED=1`. It only enforces stops for explicit
workflow identifiers.

Tune stop thresholds only with reviewed false-positive and false-negative
examples. Prefer changing warning thresholds first.
