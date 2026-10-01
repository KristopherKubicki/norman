# Norman Usage

Norman is used to create, supervise, and audit AI-assisted work. Its primary
workflow is a durable Console Runtime job, not an untracked chat completion.
Web and terminal TUIs, CLI tools, BBS/SMS, connectors, schedulers, and APIs are
inputs to that workflow.

Read [Architecture](architecture.md) for the ownership model and
[Provider And Routing Resilience](llm_runtime_fallback.md) for routing,
operating modes, and degraded behavior.

## Start A Deployment

Begin with `config.yaml.dist`, configure the database, authentication, and only
the connectors and model lanes approved for the environment, then start Norman.
The [root README](../README.md) contains the local development command; use
[Deployment](deployment.md) for hosted service, front-door, worker, and
rollback guidance.

An OpenAI key is not a prerequisite. A local-first deployment can configure
only the Norllama front door through the `llm_offline_*` settings. Cloud lanes
are optional and require explicit route, egress, secret, and approval policy.
Provider credentials belong in the approved secret broker or lease path, not in
the repository or an individual client configuration.

Console Runtime workers and the Kaizen broker are disabled by default. Leave
them disabled until the corresponding service account, resource limits,
operating mode, and approval workflow have been reviewed.

## Run Work

1. Submit work from a TUI, CLI, BBS/SMS, connector, scheduler, or API.
2. Norman creates a durable job with an objective, completion criteria,
   boundaries, and route constraints.
3. The Console Runtime selects a deterministic tool or policy-permitted
   capability, records route and execution evidence, and checkpoints progress.
4. A controlled effect waits for approval rather than being performed by a
   model.
5. Operators inspect the job event stream, outputs, receipts, and verification
   evidence, then approve, reject, retry, or cancel as appropriate.

The worker may execute in dry-run, local-first, degraded, or control-only mode.
Those modes are visible in runtime status and do not relax approval or egress
controls.

## TUI Workstreams

The TUI classifies each prompt before it creates or promotes runtime work.
Compact status requests, ordinary short chat, literal-response canaries, and
the fixed read-only deterministic command lane remain one-step interactions.
They should return promptly and do not create a background loop simply because
the TUI is open.

Substantive implementation, investigation, analysis, reporting, or explicitly
long-running work becomes a durable workstream. Its bounded local loop follows
`plan`, `work`, and `verify` phases, records a checkpoint after each bounded
attempt, and can resume from its recorded state. Durable work is not complete
because a worker produced a plausible response or exhausted its configured
steps.

Only the verifier can close a durable workstream. It must emit this exact,
standalone line and provide passing route evidence:

```text
STATUS: COMPLETE
```

The verifier may instead emit `STATUS: NEEDS_MORE_WORK`. Any other wording,
including `STATUS: COMPLETE` embedded in a sentence, is a checkpoint rather
than completion. Repeated identical work output or repeated verifier deferral
pauses the job with a `goal.no_progress` event; it does not spin indefinitely.
The next run resumes from the checkpoint after new evidence, a narrower
objective, or an operator decision.

Runtime SSE is an observation stream for the current client. It reports
planner, worker, verifier, checkpoint, and approval events, but it is not a
notification delivery channel. Sending a BBS/SMS, connector, email, or other
external notification remains a separately policy-controlled effect.

## Route Models And Tools

Norman evaluates safety, approval, and egress policy before choosing a route.
It prefers deterministic work and eligible local Norllama capabilities, then
uses peer failover, prefetch, or deferral before a policy-authorized cloud
escalation. A provider does not receive authority to write, deploy, message,
or access secrets.

Use the Norllama logical front door rather than an individual Ollama worker in
application or TUI configuration. This preserves health, model residency, peer
failover, and receipt attribution. See [Local LLM Node](local_llm_node.md) for
the local service shape.

## Review Proactive Work

Kaizen gathers deterministic KPI evidence and can produce local-only,
API-visible shadow candidates when explicitly enabled. It does not notify,
edit targets, contact external systems, or apply changes automatically.
Runbook, skill, MCP, or policy changes still require normal human review and a
separately approved job.

See [Norllama Kaizen And KPI Control Loop](norllama_kaizen_control_loop_plan.md)
for admission gates, candidate lifecycle, reporting, and rollout stages.

## Use Connectors

Connectors remain supported input and output adapters. Configure only the
connector credentials and scopes needed for the deployment, and treat sending
an external message as a policy-controlled effect. The connector catalog is in
[Connectors](connectors.md).

The older bot, channel-filter, and action API remains a compatibility surface
for connector-oriented workflows. Its bot schema still uses a `gpt_model`
field, so it is not the cross-provider Console Runtime contract. New
operator-work integrations should use durable runtime jobs and route receipts.

## Use The API

By default, the authenticated API root is `/api/v1`; the service exposes its
current OpenAPI contract at `/docs`. Console Runtime clients use an ordinary
Norman user bearer token or the narrowly scoped runtime service token.

Useful read endpoints include:

- `GET /api/v1/console-runtime/capabilities`
- `GET /api/v1/console-runtime/worker/status`
- `GET /api/v1/console-runtime/route-summary`
- `GET /api/v1/console-runtime/route-outcomes`
- `GET /api/v1/kaizen/status`
- `GET /api/v1/kaizen/kpis`

See [Examples](examples.md) for a non-mutating inspection request and a
durable job submission. The exact request and response schemas are maintained
in the OpenAPI document.

## Rate Limiting

Norman applies an IP-based API rate limit. Configure
`rate_limit_requests` and `rate_limit_window_seconds` in `config.yaml` to
match the deployment. Requests over the limit receive `429 Too Many Requests`.
