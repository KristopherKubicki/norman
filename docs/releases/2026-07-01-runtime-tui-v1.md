# Runtime TUI v1 Release Notes

Date: 2026-07-01
Scope: Norman main web app, console runtime kernel/runtime APIs, advanced consoles TUI
Status: Release candidate deployed to `norman.home.arpa`

## 2026.07.01.2 Delta

- Fixed Norman Bedrock profile-v2 startup by removing the stale legacy
  `[profiles.personal-bedrock]` block from the main Codex work config.
- Pinned profile-v2 invocations with `-c profile="<profile>"` so base profile
  defaults do not leak `gpt-5.5` or unsupported Bedrock service tiers into the
  release lane.
- Verified a real Norman TUI `/api/ask` turn over Bedrock `openai.gpt-5.4`
  returned `tui-bedrock-ok` and left the console in `state: ok`.
- Added post-restart sync parity checks so live UI version and deployed script
  version must match after template sync.
- Deployed `UI v2026.07.01.2` to Norman, NetOps, and Uplink.

## Summary

Runtime TUI v1 moves Norman from a browser surface that mostly watches tmux/Codex
into a DB-backed runtime surface that can show jobs, model/tool/planner behavior,
approval holds, and safe one-step execution.

This release keeps live execution disabled by default. Operators can inspect and
dry-run runtime jobs immediately, while live execution requires the explicit
confirmation phrase `ENABLE LIVE RUNTIME`.

## Operator Changes

- Added a Runtime panel to the advanced consoles page.
- Shows worker state, mode, runnable job count, ticks, completions, and failures.
- Lists recent console-runtime jobs.
- Shows a selected job timeline with distinct job, behavior, planner, model,
  tool, and approval events.
- Adds a dry-run step button for safe runtime progress.
- Adds phrase-gated `Approve + run` for a single live step.
- Adds `Reject hold` for jobs waiting on approval.
- Keeps worker defaults safe: worker disabled, dry-run true, live execution off.

## Runtime/API Changes

- Added worker status/control endpoints:
  - `GET /api/v1/console-runtime/worker/status`
  - `POST /api/v1/console-runtime/worker/control`
- Added one-shot run endpoint with explicit live confirmation enforcement:
  - `POST /api/v1/console-runtime/jobs/{job_id}/runs`
- Added approval decision endpoint:
  - `POST /api/v1/console-runtime/jobs/{job_id}/approval`
- Added durable approval transitions:
  - `approval.approved` moves a held job back to `checkpointed` for resume.
  - `approval.rejected` blocks the job and records the rejection reason.
- Tightened live one-shot execution so `live_execution_approved=true` also
  requires `ENABLE LIVE RUNTIME`.

## Verification

- `node --check app/static/js/consoles.js`
- Focused runtime/TUI tests: `35 passed, 4 warnings`
- Profile-v2/sync parity focused tests: `7 passed, 4 warnings`
- `make format`
- `make lint`
- Full backend suite: `860 passed, 5 warnings`
- Live smoke on `norman.home.arpa`:
  - worker status returned `200`
  - worker remained disabled, dry-run, live-off
  - unsafe worker control without phrase returned `400`
  - approval without phrase returned `400`
  - approval with phrase resumed a held job to `checkpointed`
  - dry resume completed the smoke job as `done`
  - Norman services remained active and healthy

## Known Limits

- Runtime timeline updates are polling-based in this release.
- Runtime controls are currently in the advanced consoles TUI, not yet the main
  daily Editor/Super TUI lane.
- Approval is job-level and phrase-gated; richer policy/lease approval UX should
  come in the next slice.
- Background worker remains opt-in and should stay dry-run until operator review.

## Release Guidance

Ship as Runtime TUI v1 if the goal is safe visibility and controlled runtime
execution. The next release should promote runtime visibility into the daily TUI,
add richer streaming/EventSource behavior, and connect BBS/workforce leases
directly to console-runtime jobs.
