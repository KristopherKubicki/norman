# Examples

These examples use the current Console Runtime rather than the older
OpenAI-shaped bot API. Replace `NORMAN_URL` and `NORMAN_TOKEN` with the
deployment URL and an authenticated user or runtime service token.

```bash
export NORMAN_URL="http://localhost:8000"
export NORMAN_TOKEN="replace-with-a-bearer-token"
```

## Inspect Runtime Capabilities

This request is read-only. It reports supported runtime features and the
current mode without invoking a provider or running a job.

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  "$NORMAN_URL/api/v1/console-runtime/capabilities"
```

## Inspect Routing And Worker State

Route summaries and worker status show the active control-plane posture,
including local-first evidence and degraded state.

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  "$NORMAN_URL/api/v1/console-runtime/route-summary"

curl --fail-with-body \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  "$NORMAN_URL/api/v1/console-runtime/worker/status"
```

## Create A Durable Job

Submitting a job records its objective and policy boundary. It does not itself
grant an external effect. A worker or an explicit run request processes the
job only under the active runtime, route, and approval policy.

```bash
curl --fail-with-body \
  -X POST "$NORMAN_URL/api/v1/console-runtime/jobs" \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "objective": "Summarize the latest route receipts for the operator.",
    "done_when": ["A concise status summary and evidence references exist."],
    "success_metrics": ["No external action", "Route receipts are cited"],
    "required_artifacts": ["operator-summary"],
    "max_runtime_seconds": 300,
    "question_budget": 0,
    "approval_required_for": ["external_message", "filesystem_write"],
    "route_policy": {
      "allow_cloud_proxy": false,
      "allow_cloud_tool_proxy": false
    }
  }'
```

Use the returned job ID to inspect its durable state and ordered event history:

```bash
export JOB_ID="replace-with-the-returned-job-id"

curl --fail-with-body \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  "$NORMAN_URL/api/v1/console-runtime/jobs/$JOB_ID"

curl --fail-with-body \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  "$NORMAN_URL/api/v1/console-runtime/jobs/$JOB_ID/events"
```

Do not invoke a worker run endpoint solely to test connectivity. Use dry-run or
a bounded read-only job, and review the route policy and approval state first.

## Inspect Kaizen Reporting

Kaizen is disabled and observe-only by default. These endpoints expose only
the eligible realm's aggregate KPI evidence and shadow candidates; they do not
apply a change or send a notification.

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  "$NORMAN_URL/api/v1/kaizen/status"

curl --fail-with-body \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  "$NORMAN_URL/api/v1/kaizen/kpis?realm=personal%2Fhome"

curl --fail-with-body \
  -H "Authorization: Bearer $NORMAN_TOKEN" \
  "$NORMAN_URL/api/v1/kaizen/candidates?realm=personal%2Fhome"
```

## Connector Compatibility

Slack and other connector workflows remain supported, but no connector
requires an OpenAI key. Configure only the approved connector credentials,
route its incoming work through Norman policy, and require approval for
outbound effects as appropriate.

The legacy `/api/v1/bots/` endpoint still uses a provider-specific
`gpt_model` field. It is retained for compatibility with existing
connector-oriented bots, not as the preferred interface for new work.

The service's `/docs` endpoint is authoritative for authentication, request
schemas, and any deployment-specific API additions.
