Runtime TUI v1 release candidate is deployed on `norman.home.arpa`.

Update: `UI v2026.07.01.2` is now deployed to Norman, NetOps, and Uplink.
Norman's Bedrock profile-v2 route has been fixed and verified with a real TUI
model smoke. Template sync now checks live-vs-disk UI version parity after
restart.

Highlights:
- DB-backed console-runtime jobs and event streams are visible from the advanced consoles TUI.
- Runtime events now show job, behavior, planner, model, tool, and approval activity.
- Worker status/control APIs are live with safe defaults: disabled, dry-run, live execution off.
- Approval holds can be approved or rejected; approved holds resume through `checkpointed`.
- Live one-step execution requires the exact phrase `ENABLE LIVE RUNTIME`.

Validation:
- `node --check app/static/js/consoles.js`
- focused runtime/TUI tests: `31 passed`
- `make format`
- `make lint`
- full backend suite: `860 passed`
- live Norman smoke passed
- real Norman TUI Bedrock `/api/ask` smoke returned `tui-bedrock-ok`

This is information-only and closed so it does not create pickup work.
Full release note: `docs/releases/2026-07-01-runtime-tui-v1.md`.
