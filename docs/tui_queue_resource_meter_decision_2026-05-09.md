# TUI Queue Resource Meter Decision

Date: 2026-05-09

## Decision

The shared Norman console chrome should own the generic queue resource meter
schema, compact embedded KPI meter schema, and baseline rendering. Individual
TUIs should not invent incompatible queue or health indicators.

Lane-specific adapters may enrich the queue meter and may provide a small KPI
strip, but they must be read-only. They must not create, submit, capture,
cancel, or mutate queue work.

## Ownership

| Area | Owner |
| --- | --- |
| Shared schema and chrome | Norman/Subprime shared console |
| Baseline conversation queue fields | Shared console bridge |
| BBS/Switchboard wording | Norman/Subprime with Switchboard review |
| Embedded KPI meter schema | Norman/Subprime shared console |
| Default host/resource fallback | Shared console bridge |
| First rich adapter | Scout/Ranger |
| Scout domain metrics | Scout/Ranger adapter from agent request, PP mining, and monitor artifacts |
| Runtime deployment to all TUIs | Norman template sync lane |

Primary implementation files for shared chrome:

- `scripts/agent_console_template/agent_console_web.py`
- `scripts/norman_codex_web.py`

## Operator Wording

Use three explicit queue classes:

| Label | Meaning |
| --- | --- |
| `Chat` | Conversation prompts waiting in this web console. This is the existing `pending` and `queue_depth` path. |
| `Work` | Domain backlog accepted by the lane, such as Scout agent requests or mining jobs. Accepted means received, not done. |
| `Exec` | Worker or executor capacity, such as active worker slots, capture workers, blocked jobs, or submitted jobs. |

Preferred compact copy:

```text
Queues: Chat 1 running / 2 queued; Work 10 accepted / 73 queued; Exec 0 running / 84 blocked
```

When space is tight:

```text
Q Chat 2; Work 83; Blocked 84
```

Use tooltips or expanded details for source-specific meaning:

- `Chat queue`: messages waiting behind the current `codex exec` reply.
- `Work queue`: lane-specific accepted or queued work that exists outside the
  chat transcript.
- `Exec queue`: worker/capture/submission capacity or blockers.
- `Accepted`: request was received by the lane, but completion still depends on
  executor/capture/submission.
- `Blocked`: work cannot advance without a prerequisite.

Do not label an accepted request as done.

Embedded KPI meters should use plain lane language. They should answer whether
the lane is healthy, busy, blocked, or stale. They should not duplicate the full
host resource monitor or become a dashboard.

Preferred compact copy:

```text
Health: OK; Backlog: 73 queued; Blocked: 84; Oldest: 2h stale
```

If a lane has no domain adapter, the shared console should fall back to host and
service health:

```text
Host: up; Service: active; Disk: 41%; Memory: 62%
```

## Generic Schema

Expose the meter as `resource_meter` in the console status snapshot. All fields
are optional except `version`, `generated_at`, and `read_only`.

```json
{
  "version": "norman.queue-resource-meter.v1",
  "generated_at": "2026-05-09T00:00:00Z",
  "read_only": true,
  "label": "Queues",
  "tone": "ok",
  "summary": "Chat idle; Work 0; Exec idle",
  "conversation": {
    "running": 0,
    "queued": 0,
    "pending": false,
    "oldest_age_seconds": 0,
    "stale": 0
  },
  "domain": {
    "accepted": 0,
    "queued": 0,
    "backlog": 0,
    "done": 0,
    "blocked": 0,
    "stale": 0,
    "oldest_age_seconds": 0
  },
  "executor": {
    "slots_total": 0,
    "slots_running": 0,
    "slots_available": 0,
    "running": 0,
    "blocked": 0,
    "captured": 0,
    "submitted": 0,
    "oldest_age_seconds": 0
  },
  "kpi_meters": [
    {
      "id": "pp_blocked",
      "label": "PP Blocked",
      "value": 84,
      "unit": "jobs",
      "tone": "danger",
      "detail": "Accepted Scout requests are waiting on capture.",
      "source": "scout_monitor",
      "updated_at": "2026-05-09T00:00:00Z",
      "stale_after_seconds": 900
    }
  ],
  "warnings": [],
  "sources": []
}
```

Tone should be derived conservatively:

| Tone | Condition |
| --- | --- |
| `ok` | No backlog or normal low backlog. |
| `watch` | Queue exists but is progressing. |
| `warn` | Backlog is growing, accepted work is waiting, or oldest item is stale. |
| `danger` | Executor is blocked, capture is blocked, or active work cannot advance. |

KPI meter tone should use the same values. A KPI with stale source data should
be at least `warn` even when the numeric value looks healthy.

## Baseline Shared Console Behavior

Every TUI can populate the `conversation` section from existing status fields:

- `pending`
- `queue_depth`
- `queued_prompts`
- `running_prompt`
- active child/process state when available

If no adapter is present, the meter should still show `Chat` queue state and
hide `Work` / `Exec` details.

Every TUI may also show a compact KPI strip. The strip is capped at four visible
items. When no lane adapter exists, the strip should be populated from generic
host and service health instead of staying blank.

Default fallback KPI candidates:

- service active state
- host heartbeat age
- disk utilization
- memory utilization
- restart count or recent service failure count
- oldest local queue age when available

Only the most useful four should render at once.

## Adapter Contract

Lane adapters should write or provide a read-only JSON object that matches the
generic schema and can be merged into the status snapshot.

Rules:

- Adapter reads local lane artifacts only.
- Adapter must tolerate missing files.
- Adapter must never submit, capture, cancel, or mutate queue work.
- Adapter must include source names and timestamps where possible.
- Adapter must make stale/blocked reasons visible without exposing secrets.
- Adapter KPI meters must be capped at four visible items.
- Adapter KPI meters must include `updated_at` and `source` whenever possible.
- Adapter KPI meters must degrade to stale/warn when source data is older than
  `stale_after_seconds`.

Each `kpi_meters` item uses this shape:

```json
{
  "id": "stable_machine_id",
  "label": "Operator Label",
  "value": 0,
  "unit": "items",
  "tone": "ok",
  "detail": "Short explanation for tooltip or expanded detail.",
  "source": "local_artifact_or_probe",
  "updated_at": "2026-05-09T00:00:00Z",
  "stale_after_seconds": 900,
  "href": ""
}
```

Required fields:

- `id`
- `label`
- `value`
- `tone`

Strongly preferred fields:

- `detail`
- `source`
- `updated_at`
- `stale_after_seconds`

The `href` field is optional and should only point to a local detail page,
artifact, or existing TUI route. It must not trigger work.

## Lane KPI Guidance

Each lane should choose the smallest set of metrics that tells the operator what
matters. Recommended first-pass meters:

| Lane | KPI meters |
| --- | --- |
| Scout/Ranger | accepted requests, PP queued, PP blocked, oldest accepted age |
| NetOps | relay backlog, active correction/deploy, blocked hosts, stale relay age |
| Switchboard/Subprime | passive relay backlog, active handoffs, stale relay count, BBS health |
| Gold Book | pending book jobs, validation failures, latest publish age, SKU delta |
| Diamond Roc | canonical host, deploy/runtime state, failing checks, last heartbeat |
| Platinum Standard | build state, validation failures, artifact freshness, blocked release jobs |
| Generic/unknown TUI | service state, heartbeat age, disk, memory |

Avoid meters that require interpretation across multiple screens. If a metric
needs a paragraph to explain, it belongs in the lane dashboard or runbook, not
in the TUI strip.

## Scout/Ranger First Adapter

Scout/Ranger should be the first rich adapter.

Inputs named by Scout/Ranger:

- `agent_requests_latest.json`
- PP mining status
- `scout_monitor` warnings

Initial Scout mapping:

| Scout signal | Meter field |
| --- | --- |
| accepted agent requests | `domain.accepted` |
| queued agent requests | `domain.queued` |
| completed agent requests | `domain.done` |
| blocked agent requests | `domain.blocked` |
| PP queued jobs | `domain.backlog` or `domain.queued` with source `pp_mining` |
| PP blocked jobs | `executor.blocked` |
| PP captured jobs | `executor.captured` |
| PP submitted jobs | `executor.submitted` |
| `pp_job_not_captured` | warning and `danger` tone when it blocks accepted work |

Scout example based on the 2026-05-09 handoff:

```text
Queues: Chat idle; Work 10 accepted / 73 queued; Exec 84 blocked
Detail: accepted Scout requests are waiting on pp_job_not_captured.
KPI: Accepted 10; PP Queued 73; PP Blocked 84; Oldest accepted stale
```

## Acceptance Criteria

- The meter is visible in shared console chrome or the activity strip.
- It distinguishes `Chat`, `Work`, and `Exec`.
- It supports up to four compact embedded KPI meters per TUI.
- KPI meters use the shared schema and tone values.
- A generic host/resource fallback appears when no lane adapter is present.
- It is read-only.
- Baseline fields work in every TUI without a lane adapter.
- Missing adapter data does not break the console.
- Stale KPI source data is visible to the operator.
- Scout adapter can show accepted, queued, blocked, captured, submitted, stale,
  and warnings.
- BBS/passive context does not look like ignored operator chat.
- Tests cover generic baseline, missing adapter, host/resource fallback, stale
  KPI handling, KPI cap behavior, and one enriched adapter fixture.

## Routing

Implementation lane:

1. Norman/Subprime adds schema, merge logic, shared chrome rendering, and
   default host/resource KPI fallback.
2. Scout/Ranger provides the first adapter fixture and reference output,
   including `kpi_meters`.
3. Norman/Subprime wires the adapter into the template without making Scout a
   hard dependency.
4. Template sync rolls the shared meter to other TUIs after the Scout fixture
   proves the copy and layout.
