# Norllama Kaizen And KPI Control Loop

Date: 2026-08-02
Status: Phase 2 candidate shadow implemented; disabled by default, local-only, and API-only
Audience: Norman operators, TUI maintainers, Console Runtime maintainers, and Norllama maintainers

## Decision

Norman will add one centrally scheduled, Norllama-assisted Kaizen and KPI control loop. It will make
proactive reporting and narrowly bounded control-plane adjustments while a pilot TUI is genuinely idle.
It will not create autonomous loops inside individual TUIs.

The first deployment is one `personal/home` TUI. It starts in observe-only mode. Phase 2 makes no
notifications, inbox delivery, target edits, prepare requests, or apply requests. Shadow candidates are
visible only through an authenticated, realm-scoped API. A later pilot inbox may use a compact badge and
one local-time daily digest; normal popups are not used. Deterministic, critical policy failures may use
the established alert channel only in a later, explicitly enabled phase.

This control loop is not permission for Norman to rewrite itself. Initial improvement targets are:

| Target | Initial authority | Notes |
| --- | --- | --- |
| Runbooks and operating docs | Prepare proposal and diff only | A person reviews before any apply job is created. |
| Skills | Evaluate and suggest only | No automatic skill changes. |
| MCPs | Health and docs suggestions only | No permission, endpoint, schema, credential, or implementation changes. |
| Norman app code and infrastructure | Out of scope | May be reported, but is not initially mutable. |
| Kaizen control plane | Narrow automatic authority | Only the policy-bound actions in this document. |

Accepted candidates create ordinary Console Runtime jobs. Those jobs retain the existing approval, command
policy, safety, lease, verification, and audit controls.

## Why This Shape

Norllama is useful for finding patterns, reducing evidence, drafting a narrow proposal, and explaining
tradeoffs. It must not be the source of truth for metrics, policy thresholds, notifications, or effects.

The deterministic system collects evidence, computes KPI values, applies admission rules, and evaluates
policy thresholds. Norllama receives a small evidence packet and returns a strictly structured candidate.
The candidate is independently validated before it appears in an operator inbox.

This separates three concerns that have different lifecycles:

1. `ConsoleJob`: a unit of requested or approved execution.
2. `KaizenCandidate`: an improvement opportunity that may be rejected, snoozed, or expire.
3. `KaizenPolicyAction`: a bounded automatic adjustment to the Kaizen control plane itself.

The existing Console Runtime is the execution substrate. The current per-TUI human intervention inbox and
KPI snapshot remain useful presentation and signal sources, but they are not the durable Kaizen ledger.

## Safety And Human Control

### Authority Tiers

| Tier | Authority | Initial use |
| --- | --- | --- |
| `0` | Read state, calculate metrics, create reports | Enabled only after the pilot is explicitly enabled. |
| `1` | Adjust Kaizen control plane within fixed bounds | May be enabled after observe-only acceptance. |
| `2` | Prepare a proposal, patch artifact, or verification plan | No external effect and no application of a patch. |
| `3` | Apply a proposal or make a system change | Requires explicit human approval through Console Runtime. |

Tier 1 is limited to:

- pause or resume Kaizen analysis;
- reduce or restore Kaizen-owned Norllama concurrency within configured limits;
- defer, reprioritize, deduplicate, or suppress Kaizen candidates;
- rerun a deterministic, read-only report after a transient collection failure;
- shorten report detail or collection frequency during foreground pressure.

Each Tier 1 action requires a named policy, deterministic trigger, bound, cooldown, verification window,
rollback condition, and audit receipt. Tier 1 never restarts a service, changes a deployment, changes a
route, accesses a secret, calls a network action, or modifies a TUI's user work.

### Hard Prohibitions

The first release must reject any candidate or policy action that would:

- modify Norman source, service definitions, deployment state, or infrastructure;
- access a secret, request a secret lease, or include secret-bearing evidence;
- call a network, cloud, connector, or external system;
- change an MCP's permissions, endpoint, schema, credential, or implementation;
- apply a runbook or skill change without an explicit human approval;
- start work while the source TUI has an active prompt, queue, human gate, or foreground process;
- emit a human-facing alert based only on a model interpretation;
- silently escalate from Norllama to a cloud model.

The existing emergency safety controls, read-only mode, kill switch, command policy, realm boundaries, and
approval policy always win over Kaizen policy.

### Human Flow

The normal path is:

```text
evidence -> candidate -> validation -> inbox -> prepare artifact -> human apply -> runtime approval
         -> normal Console Runtime job -> deterministic verification -> retain or rollback -> audit
```

`Prepare artifact` may create a proposed diff and verification plan, but it does not edit the target. The
operator can dismiss, snooze, or request preparation. Once a prepared proposal is acceptable, `Apply`
creates a normal Console Runtime job in its established approval state. The job cannot make a mutable
effect until the normal approval gate is satisfied.

## Central Idle Work Broker

The Kaizen broker runs once for the service, not once per browser tab or per TUI process. It considers
eligible pilot TUIs fairly and can perform no more than one Kaizen admission per configured interval.

### Admission Gates

All conditions below must pass before evidence collection or a Norllama call:

1. The TUI is in the enabled pilot set and belongs to the same permitted realm and owner.
2. The TUI has no active prompt, background process, queued prompt, pending request, or human gate.
3. The TUI has remained idle for at least `kaizen_idle_grace_seconds`, initially 900 seconds.
4. The runtime has no higher-priority runnable operator, BBS, recovery, or approval-held work.
5. The TUI KPI snapshot is not blocked, wedged, degraded by a current foreground issue, or stale.
6. Kaizen is not paused globally, for the TUI, or for the candidate lane.
7. Norllama health, warm-policy evidence, token budget, and pool capacity are within policy.
8. Host resource pressure and foreground queue pressure are below configured limits.
9. The realm, target class, policy mode, and read-only evidence scope are allowed.
10. Per-TUI, per-lane, per-fingerprint, and global cooldowns have elapsed.

Failure of any gate is a quiet, auditable skip. A skip must not wake the user, consume a model call, or
create a low-quality candidate.

### Admission Priority

Eligible work is sorted by deterministic score:

```text
priority =
  severity_weight
  + freshness_weight
  + repeated_failure_weight
  + evidence_quality_weight
  + expected_operator_benefit
  - risk_penalty
  - model_cost_penalty
  - recent_attention_penalty
```

Only deterministic inputs may set the priority. Norllama can rank already admitted evidence inside a lane,
but its rank cannot bypass a gate, increase authority, or create an alert level.

The broker first spends a small daily budget on high-quality evidence. It does not run simply because a TUI
is idle. If no evidence crosses the candidate threshold, it records a quiet no-op.

### Evidence-First Lanes

The initial evidence collectors are deterministic and read-only:

- TUI KPI snapshots, sentinel state, prompt queue state, and human-intervention state;
- Console Runtime job failures, blocked reasons, approval waits, route outcomes, and verification receipts;
- Norllama route, warm-policy, pool saturation, latency, and failure receipts;
- scorecard and Kaizen experiment output from `scripts/planner_kaizen_loop.py`;
- versioned runbook freshness and broken-reference checks;
- skill evaluation failures, stale references, and malformed input/output examples;
- MCP health, documented schema mismatch, and repeated user confusion signals;
- report freshness, source coverage, and confidence gaps.

Evidence packets carry references, timestamps, source type, freshness, and sanitized aggregates. They do not
contain raw console transcripts, secrets, credentials, private files, or unbounded logs.

## Candidate Contract

Phase 2 persists only the `shadow` lifecycle state. Feedback, preparation, acceptance, application, and
verification are deliberately deferred to later phases. A shadow candidate is evidence-backed local-model
output that has passed independent validation; it is not an operator task, notification, or permission to
edit its target.

The durable candidate record has a lifecycle distinct from a job:

```text
discovered -> validated -> presented -> preparing -> prepared -> accepted -> verified
                       \-> snoozed | dismissed | expired | failed
```

`accepted` means the operator requested an apply job after reviewing a prepared artifact. It does not mean
the effect has occurred. `verified` requires the apply job's deterministic verification receipt.

Every candidate is immutable in its historical evidence and proposal revisions. Status changes append an
audit event instead of overwriting the prior reasoning.

### Required Candidate Fields

```json
{
  "schema": "norman.kaizen-candidate.v1",
  "candidate_id": "kc_...",
  "fingerprint": "sha256 of target, lane, normalized failure, and evidence class",
  "realm": "personal/home",
  "source_tui": "personal-tui-id",
  "lane": "runbook|skill|mcp_docs|reporting|control_plane",
  "target_type": "runbook|skill|mcp|kaizen_policy",
  "target_ref": "stable repo or registry reference",
  "status": "discovered",
  "severity": "info|watch|warning|critical",
  "risk_tier": "read_only|proposal_only|approval_required",
  "impact_score": 0,
  "confidence_score": 0,
  "evidence_refs": ["artifact or receipt reference"],
  "evidence_summary": "sanitized, bounded text",
  "proposal": {
    "summary": "one narrow improvement",
    "allowed_action": "report|prepare_diff|adjust_control_plane",
    "verification_plan": ["deterministic check"],
    "expiry_at": "RFC 3339 timestamp"
  },
  "model_receipt_ref": "Norllama route and invocation receipt",
  "created_at": "RFC 3339 timestamp"
}
```

The validation step rejects a candidate unless:

- the schema parses and only uses supported enums;
- every evidence reference resolves and is fresh enough for the lane;
- the fingerprint is not in an active or suppressed cooldown state;
- the target is inside the pilot authority set;
- the proposal has a bounded verification plan and expiry;
- impact, confidence, and risk pass lane thresholds;
- no prohibited action, secret-like content, unsafe external reference, or unsupported mutation appears.

Malformed or unsupported model output is discarded with a route outcome. It is not repaired into a candidate.

### Fingerprints, Cooldowns, And Feedback

`KaizenCandidateFingerprint` is the durable deduplication record. It is unique by owner, realm, target
class, and normalized fingerprint. It tracks first and latest evidence, active candidate, previous outcome,
dismiss reason, snooze expiry, and cooldown expiry.

Default cooldowns:

| Outcome | Default cooldown |
| --- | ---: |
| Dismissed as irrelevant | 30 days |
| Snoozed | Operator-selected date |
| Prepared but not applied | 14 days |
| Verified improvement | 30 days, unless regression evidence reopens it |
| Invalid model output | 24 hours for the lane, not the target |

Candidate feedback is structured: `helpful`, `not_now`, `wrong_target`, `insufficient_evidence`,
`too_risky`, `duplicate`, `applied`, or `verification_failed`. The broker uses feedback only to suppress,
rank, and improve future evidence selection. It never uses feedback to relax a safety rule.

## KPI And Reporting Contract

### Metric Rules

KPI values come from deterministic collectors and are evaluated against versioned definitions. A model may
explain an anomaly only after the value, window, source freshness, and threshold outcome are fixed.

Each definition contains:

- `kpi_id`, display label, owner, realm scope, and definition version;
- source collector and source freshness SLA;
- unit, aggregation, window, target, warning threshold, and critical threshold;
- missing-data behavior and confidence rule;
- allowed reporting action and, if applicable, bounded automatic policy;
- verification and rollback rule for any automatic policy.

No KPI is silently inferred from free-form model text. Missing or stale data is a first-class state and is
never displayed as healthy.

### Initial KPI Catalog

| KPI | Source | Target / threshold direction | Initial response |
| --- | --- | --- | --- |
| `tui_foreground_blocked_rate` | TUI KPI | Lower; repeated blocked state | Inbox and daily digest. |
| `tui_wedge_rate` | TUI and sentinel | Lower; deterministic critical trigger | Existing critical alert policy. |
| `runtime_job_verification_pass_rate` | Runtime receipts | Higher | Report regression and candidate evidence. |
| `runtime_approval_wait_age` | Console Runtime jobs | Lower is better | Daily decision queue. |
| `local_route_success_rate` | Norllama route outcomes | Higher is better | Diagnose with route receipts. |
| `norllama_pool_pressure` | Pool and Norllama status | Lower | Tier 1 concurrency reduction with rollback. |
| `norllama_foreground_latency` | Priority route outcomes | Lower | Pause/defer Kaizen before user work degrades. |
| `kaizen_candidate_helpfulness_rate` | Candidate feedback | Higher is better | Reduce or pause weak lanes. |
| `kaizen_duplicate_rate` | Fingerprint ledger | Lower is better | Tier 1 suppression and evidence tuning. |
| `runbook_freshness_rate` | Deterministic document checks | Higher is better | Proposal-only candidate. |
| `skill_evaluation_pass_rate` | Skill evaluation receipts | Higher is better | Suggestion-only candidate. |
| `mcp_documentation_health` | MCP docs and health checks | Higher | Documentation or health suggestion only. |
| `report_source_freshness_rate` | KPI observations | Higher | Mark degraded and rerun safe collection. |

The first implementation pins exact thresholds in version-controlled configuration after baseline observation.
Until each KPI has a baseline, it may report trend and confidence but cannot fire a critical policy.

### Reports

The reporting schedule is local-time and configurable:

| Report | Default schedule | Delivery | Contents |
| --- | --- | --- | --- |
| Daily operational brief | 08:00 | TUI inbox/digest | KPIs, candidates, actions, decisions, stale sources. |
| Weekly trend report | Monday 08:00 | TUI inbox/digest | Trends, policy impact, usefulness, rollout recommendation. |
| Critical alert | Event-driven | Approved alert channel | Trigger, evidence, impact, required decision. |

A daily report always distinguishes:

- observed fact, threshold result, and confidence;
- automatic action already taken, its bound, and verification result;
- a proposed change requiring an operator;
- source freshness and data omitted because it was stale or unavailable.

No ordinary report produces a modal popup. The TUI shows a compact unread badge and an inbox item. Critical
alerts use only an existing deterministic alert policy, never a model-selected severity.

## Policy-Bound Automatic Actions

Every automatic action uses this state machine:

```text
collect -> calculate -> threshold -> policy check -> act within bound -> verify -> retain or rollback -> audit
```

The initial policy catalog is intentionally small:

- `pause_on_foreground_pressure`
  - Trigger: active foreground prompt, queue, or human gate.
  - Action: pause new Kaizen admissions; resume only after idle grace.
- `reduce_norllama_kaizen_concurrency`
  - Trigger: Kaizen pool pressure or foreground latency exceeds baseline.
  - Action: reduce Kaizen-owned concurrency, never below one.
  - Verification: pressure improves; restore one step after stable recovery and cooldown.
- `suppress_duplicate_candidate`
  - Trigger: the same fingerprint recurs within cooldown.
  - Action: update the fingerprint ledger and suppress presentation.
  - Verification: audit the suppression; the operator can reopen it.
- `rerun_stale_safe_report`
  - Trigger: a deterministic report input was transiently stale.
  - Action: rerun its read-only collector once.
  - Verification: retain only a fresh observation; otherwise mark the report degraded.
- `pause_weak_candidate_lane`
  - Trigger: helpfulness or validation remains below its configured floor.
  - Action: pause the lane.
  - Verification: resume only through policy review or explicit operator enablement.

Policy evaluation has hysteresis. A warning must persist for a configured observation count before action, and
a recovery must persist for a configured observation count before rollback or restore. A policy action has one
active lease, an idempotency key, a maximum retry count, and a rollback receipt.

## Proposed Persistence Model

Candidate records must not be stored as `ConsoleJob` JSON because their lifecycle, deduplication, expiry, and
feedback semantics differ. The initial migration should add:

| Table | Purpose |
| --- | --- |
| `kaizen_candidates` | Candidate lifecycle, proposal revisions, prepared artifacts, and job linkage. |
| `kaizen_candidate_fingerprints` | Durable deduplication and suppression per normalized target fingerprint. |
| `kaizen_kpi_observations` | Metrics, source freshness, confidence, definition version, and evidence refs. |
| `kaizen_reports` | Generated daily/weekly report payloads, delivery state, and source observation window. |
| `kaizen_policy_actions` | Trigger, bounds, receipt, verification, cooldown, and rollback. |

All tables include `user_id`, realm scope, timestamps, and indexes for status, owner, TUI, fingerprint, KPI
window, and report period. The store enforces realm and user filtering on every query.

KPI definitions remain version-controlled configuration in the first release. Each observation stores the
definition version that created it. That avoids model-authored metrics and makes a threshold change auditable.

## Planned Implementation Surfaces

This list is an implementation map, not a request to change these files in the documentation phase.

| Surface | Planned change |
| --- | --- |
| `app/models/kaizen.py` | SQLAlchemy records for candidates, fingerprints, KPIs, reports, and policies. |
| `app/models/__init__.py` | Export the new Kaizen records. |
| `alembic/versions/..._add_kaizen_control_loop.py` | Add the five tables, constraints, and indexes. |
| `app/services/kaizen/types.py` | Strict records and enums for candidates, KPIs, reports, and policies. |
| `app/services/kaizen/store.py` | Durable candidate, fingerprint, KPI, report, and policy-action store. |
| `app/services/kaizen/evidence.py` | Read-only collectors and sanitized evidence packets. |
| `app/services/kaizen/broker.py` | Central admission, fair selection, deduplication, and cooldown decisions. |
| `app/services/kaizen/analysis.py` | Strict Norllama request/response boundary and independent candidate validation. |
| `app/services/kaizen/policies.py` | Deterministic thresholds, hysteresis, bounds, verification, and rollback. |
| `app/services/kaizen/reports.py` | Daily/weekly aggregation and report rendering data. |
| `app/services/console_runtime/supervisor.py` | Schedule one Kaizen broker tick under the existing worker lifecycle. |
| `app/services/console_runtime/store.py` | Create a job only after an approved candidate apply request. |
| `app/api/api_v1/routers/kaizen.py` | Read APIs, feedback, prepare/apply request, reports, and status. |
| `app/api/api_v1/api.py` | Register the Kaizen router. |
| `app/core/config.py` and `config.yaml.dist` | Disabled-by-default settings and KPI/policy references. |
| `scripts/norman_codex_web.py` | Inbox badge, digest, and candidate decisions from the central API. |
| `scripts/agent_console_template/agent_console_web.py` | Mirror the pilot presentation after the pilot passes. |

The current `scripts/norman_codex_web.py` human intervention inbox remains the UI behavior reference for
fingerprints, suppression, status, and urgency. It must not be treated as the Kaizen source of truth.

### API Shape

The implemented Phase 2 surface is intentionally read-oriented:

```text
GET  /kaizen/status
POST /kaizen/tui-snapshots
POST /kaizen/tick
GET  /kaizen/kpis?window_seconds=...
GET  /kaizen/reports/latest?kind=daily
GET  /kaizen/candidates?source_tui=...&lane=...
```

`/kaizen/candidates` returns only `shadow` records for the authenticated user and requested allowed realm.
It does not present candidates in a TUI, notify anyone, prepare a patch, modify a target, request an
approval, or create a Console Runtime job.

The following is a later-phase proposal, not a currently exposed API:

The planned API is additive and realm-scoped:

```text
GET  /kaizen/status
GET  /kaizen/candidates?status=presented&source_tui=...
GET  /kaizen/candidates/{candidate_id}
POST /kaizen/candidates/{candidate_id}/feedback
POST /kaizen/candidates/{candidate_id}/prepare
POST /kaizen/candidates/{candidate_id}/apply-request
GET  /kaizen/reports/latest?kind=daily
GET  /kaizen/reports/{report_id}
GET  /kaizen/kpis?window=...
GET  /kaizen/policy-actions?window=...
```

`prepare` is eligible only for a proposal-only candidate and produces a review artifact. `apply-request`
creates a normal Console Runtime job with the candidate, artifact, and verification plan attached. The
normal Console Runtime approval endpoint remains the only way to authorize a mutable job.

## Configuration Scaffold

All Kaizen behavior is disabled by default. The eventual configuration shape is:

```yaml
kaizen_enabled: false
kaizen_observe_only: true
kaizen_auto_actions_enabled: false
kaizen_pilot_tui_ids: []
kaizen_allowed_realms: ["personal/home"]
kaizen_idle_grace_seconds: 900
kaizen_snapshot_max_age_seconds: 300
kaizen_candidate_evidence_max_age_seconds: 300
kaizen_broker_tick_seconds: 60
kaizen_max_admissions_per_tick: 1
kaizen_daily_norllama_token_budget: 0
kaizen_norllama_max_concurrency: 1
kaizen_candidate_shadow_enabled: false
kaizen_candidate_shadow_max_tokens: 0
kaizen_candidate_shadow_max_concurrency: 0
kaizen_daily_digest_local_time: "08:00"
kaizen_weekly_digest_day: "monday"
kaizen_weekly_digest_local_time: "08:00"
kaizen_critical_alerts_enabled: false
kaizen_runbook_prepare_enabled: false
kaizen_skill_suggestions_enabled: false
kaizen_mcp_health_suggestions_enabled: false
```

Live configuration must fail closed. An unknown realm, target class, policy ID, or mode leaves the broker
disabled for that work. Turning off `kaizen_enabled` stops new admissions immediately, preserves history,
and leaves ordinary Console Runtime jobs under their normal operator control.

## Delivery Phases

### Phase 0: Scaffolding

Deliverables:

- this plan and documentation index entry;
- frozen initial authority, notification, target, and data-contract decisions;
- no migration, setting, worker, API, or TUI behavior change.

Exit criteria:

- implementation can proceed without re-deciding who may act, what may change, or how the operator is notified.

### Phase 1: Observe-Only KPI And Evidence

Deliverables:

- persistence, strict contracts, and deterministic KPI collectors;
- central broker that records admission decisions but makes no model calls;
- daily report preview available through the API only.

Exit criteria:

- one pilot TUI produces fresh, realm-scoped observations;
- no candidate, notification, or automatic action is created;
- stale data, realm mismatch, and foreground pressure each cause an audited skip.

### Phase 2: Norllama Candidate Shadow Mode

Deliverables:

- bounded Norllama calls with strict candidate schema and route receipts;
- candidate validation and fingerprint suppression;
- shadow candidate records visible through the authenticated API but not in the normal inbox;
- no feedback, prepare, apply, target-mutation, notification, cloud, or external-call API.

Exit criteria:

- candidates are evidence-backed and deduplicated;
- malformed model output is safely rejected;
- no prepare or apply route exists yet.

### Phase 3: Pilot Inbox And Reporting

Deliverables:

- TUI inbox badge and daily/weekly report rendering;
- dismiss, snooze, and feedback controls;
- no normal popups and no automatic external alerting.

Exit criteria:

- the pilot operator can distinguish fact, proposal, source freshness, and action;
- candidate usefulness and duplicate rates meet the baseline set in Phase 1.

### Phase 4: Proposal Preparation

Deliverables:

- runbook proposal/diff artifacts in a reviewable, non-applied form;
- skill and MCP suggestion artifacts;
- normal Console Runtime job creation for explicit apply requests.

Exit criteria:

- a runbook proposal cannot change the target until an operator requests apply and approves the runtime job;
- all artifacts include deterministic verification commands and expiry.

### Phase 5: Narrow Automatic Control-Plane Actions

Deliverables:

- the small policy catalog in this document, still disabled individually;
- action receipts, verification, cooldowns, rollback, and dashboard history.

Exit criteria:

- each policy is proven in dry-run and shadow mode;
- every action remains inside its configured bound;
- the global kill switch halts new actions within one broker tick.

### Phase 6: Evaluate Expansion

Expansion beyond one personal TUI requires a written review of:

- foreground user impact and model capacity impact;
- candidate helpfulness, duplicate, dismissal, and verified-improvement rates;
- policy action success and rollback rates;
- correctness of realm isolation and audit trails;
- whether runbook, skill, or MCP scope should expand.

No work or OpenBrand TUI is added by default.

## Test Matrix

The implementation must add focused tests before enabling each phase:

| Area | Required tests |
| --- | --- |
| Contracts | Bad enums, missing evidence, unsafe target, secret-like content, expiry, schema version. |
| Store | Realm isolation, fingerprint uniqueness, cooldowns, transitions, audit trail, report windows. |
| Broker | Every admission gate, fairness, priority ordering, no-op behavior, and foreground preemption. |
| KPI | Aggregation, threshold direction, missing/stale source handling, definition versioning, and confidence. |
| Norllama | Strict parse, route receipt, malformed rejection, token budget, health failure, no cloud fallback. |
| Policy | Bounds, hysteresis, idempotency, verification, cooldown, rollback, and kill switch. |
| Runtime bridge | Apply request creates an ordinary approval-held Console Runtime job with evidence artifacts. |
| API | Authentication, realm scoping, candidate feedback, prepare/apply authorization, and report access. |
| TUI | Badge, digest, no-popup default, stale-data state, candidate decision controls, and foreground suppression. |
| Regression | Existing Console Runtime, Norllama routing, TUI KPI, human-intervention, and policy tests. |

No phase can be enabled merely because unit tests pass. The phase exit criteria, a pilot soak window, and a
review of the produced audit records are required.

## Rollback And Kill Switches

The system has layered revocation:

| Control | Effect |
| --- | --- |
| `kaizen_enabled=false` | Stops new broker admissions and scheduled analysis. |
| `kaizen_auto_actions_enabled=false` | Leaves reporting/candidates available but blocks Tier 1 actions. |
| Per-policy disable | Stops one automatic action without disabling reports. |
| Per-TUI or per-lane pause | Stops analysis for a scope while preserving other pilot scopes. |
| Existing safety read-only or kill switch | Overrides Kaizen and prevents mutable runtime jobs. |

Rollback never deletes candidate, KPI, report, or policy history. It records the reason, baseline, action
receipt, verification result, and any restored setting. Existing approved runtime jobs are not canceled
silently; they remain under the Console Runtime cancel and approval controls.

## Success Criteria

The pilot is successful only when all of the following are true:

- the operator can see a daily, evidence-backed operational picture without chasing raw logs;
- Kaizen never competes with foreground work or degrades the pilot TUI's responsiveness;
- proposals are specific, small, deduplicated, and include a verification path;
- every suggested or automatic action has a clear owner, authority tier, audit record, and rollback behavior;
- no initial target bypasses human approval;
- automatic actions improve capacity, noise, or reporting without modifying unrelated systems;
- the operator can pause the loop, dismiss a bad idea, and understand why the loop did or did not act.
