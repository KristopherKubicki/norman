# TODO

## High Priority

- [x] Implement and test all connectors (IRC, Slack, etc.)
- [x] Finalize and test CRUD operations and API endpoints for all models
- [x] Set up GitHub Actions for CI/CD
- [x] Configure authentication and authorization
- [x] Create a minimal Web UI for configuration and management
- [x] Implement the core logic for handling incoming messages and triggering actions
- [x] Finalize the configuration system to use `config.yaml` and `config.yaml.dist`
 - [x] Test and optimize the SQLite database configuration
- [x] Develop a system for handling multiple channel connectors
- [x] Implement a lightweight API for external communication
- [x] Refactor the current connector model to use dynamic Connectors that read existing hardcoded models as connector_types
      - This will allow admins to add as many or as few Connectors as they want, or even duplicate connectors for more than 1 connection to a service (e.g., multiple IRC servers)

## Medium Priority

 - [x] Improve logging and exception handling
 - [x] Add more unit tests and integration tests
 - [x] Implement support for additional GPT models
 - [x] Write documentation for the project
- [x] Redesign the bots.html page to be similar to the OpenAI chat window
      - Bots should be listed on the left side of the screen
      - The main chat window should be in the middle of the screen
      - Clicking on a bot should replace the messages in the main window with the messages from that bot's Interactions
- [x] Create a bot_detail.html page for editing details about the bot session, including:
      - GPT model
      - Name
      - Description
      - Enabled status
- [x] Update the message_log.html page to fit the new design
      - Channels should be listed on the left side of the screen instead of bots
      - Clicking on a channel should replace the messages in the main window with the messages from that channel's Interactions

## Low Priority

 - [x] Explore options for direct communication with Norman for configuration
 - [x] Implement additional features and improvements based on user feedback

## Super Console Roadmap

- [ ] `Mission-mode` home view: state-first dashboard (flow, queue, faults) with config hidden behind drawers
- [ ] `Attention rail`: auth expiry, connector down, route failures, retry/dead-letter visibility with one-click remediation
- [x] `Route simulator`: paste sample message + connector and preview rule/bot decision without sending
- [ ] `Route trace`: click any flow edge and inspect “why this routed” with rule + filter evidence
- [ ] `Safety controls`: dry-run/shadow routes, allow/deny policies, and time-window gating
- [x] `Token lifecycle UX`: per-connector scope display, expiry countdown, reconnect before failure

## Operator Control Roadmap

- [ ] Unify `tmux` and `screen` behind one runtime control surface (`start`, `stop`, `restart`, `lock`, `unlock`, `send`, `capture`, `health`)
- [x] Add explicit session operator modes: `auto`, `manual`, `shared`
- [ ] Add operator lease state with owner, expiry, and audit trail for sessions
- [x] Block autonomous writes while a session is in `take` mode
- [x] Add first-class direct outbound send for channels/connectors, not just local `ChannelMessage` storage
- [x] Add explicit channel operator modes: `auto`, `manual`, `shared`
- [ ] Add a unified `Inbox` for escalations, approvals, and “Norman needs you” cards (Editor approvals shell is in place)
- [ ] Add per-target “raise to me” policy so Norman escalates instead of acting when required
- [ ] Add desired-state runtime profiles so Norman can restore named session sets automatically
- [x] Auto-discover running tmux sessions in the Editor and save a live `running_now` snapshot
- [ ] Add one canonical Editor surface for manual override instead of splitting control across multiple views
- [ ] Show human-vs-agent authorship on every write to a session or channel
- [ ] Add tests for runtime control, operator lease enforcement, and escalation routing

## Integration Hardening Checklist

- [x] Add "Send Test" button for Notifications webhook (validate phone path)
- [x] Notify webhook on approval creation (phone-first workflows)
- [x] Add navbar approvals badge (pending approvals count)
- [x] Add approvals UI panel (pending approvals approve/reject) on Connectors page
- [x] Add Safety Controls card on Settings page (execution toggle, read-only, tmux policy mode)
- [x] Add safety policy boundary + command approvals (tmux gate)
- [x] Add deterministic command policy engine (allow/approval/block)
- [x] Add per-agent policy profiles (allowlists, timeouts, rate limits)
- [x] Add global kill switch and read-only mode
- [x] Add ingest-only mode (log events, skip routing jobs/actions)
- [x] Add tmux pane discovery + capture endpoints (console observability)
- [x] Add tmux pane picker in connector modal
- [x] Add Consoles page (tmux pane viewer)
- [x] Add Console Targets (favorites) API + UI

- [x] Reduce Messages page connector status fetches to a single bulk statuses call
- [x] Pause Home dashboard polling when the tab is hidden (reduces cross-tab request storms)
- [x] Add bulk connector statuses endpoint + use it in UI (avoid N status calls)
- [x] Add background connector health scheduler with backoff
- [x] Add connector status history (timeline + recent errors)
- [x] Add outbound send retries + circuit-breaker (raise failures so jobs retry)
- [x] Add dead-letter queue visibility + one-click retry
- [x] Add route trace view (why a message routed)
- [x] Add import/export for connectors and routing rules

- [x] Fix connector-page 429 behavior by limiting rate limits to mutating requests only
- [x] Add static/icon cache headers to reduce repeat fetch pressure
- [x] Add in-memory icon objectURL cache (prevents repeated SVG fetches on rerenders)
- [x] Stop approvals badge polling when logged out (prevents 401/extra requests)
- [x] Add Syslog passive sensor connector (UDP 1514)
- [x] Reduce auth middleware log noise for static asset requests
- [x] Improve connector form defaults and safer config template merge behavior
- [x] Add backend coercion for connector config types (`"true" -> bool`, `"6697" -> int`, CSV -> list)
- [x] Expose connector constructor defaults in `/api/v1/connectors/available`
- [x] Wire frontend to consume backend defaults for easier setup
- [x] Add and update tests for rate limiting, cache headers, defaults, coercion, and connector metadata
- [x] Keep app running in `screen` with latest changes
- [x] Add per-connector Diagnose output (missing config, auth state, connectivity error, suggested fix)
- [x] Add connector capability matrix in UI (inbound/outbound, webhook-only, OAuth provider, media support)
- [x] Add quick-connect presets for top integrations (Slack, Gmail, Teams, Discord, Telegram, Signal)
- [x] Add connector validation hooks before save (schema plus semantic checks)
- [x] Add Passive Sensors routing class (`match_type=passive`) with simulator support
- [x] Add ARP passive connector and Passive Sensors quickstart (one-click SNMP/ARP setup)
- [x] Add background health-check scheduler with cooldown/backoff
- [x] Mobile UX pass: safe areas, larger touch targets, full-screen modals, and conversation-first layouts
- [x] Streamline Streams mobile panes (Chat/Channels/Tools) and fold legacy Consoles pane into Tools
- [x] Add send-path timeout + clearer button status to avoid hanging stream sends on unstable links
- [x] Add health-check status history + UI drill-in
- [x] Add retries and circuit-breaker patterns for outbound connector sends
- [x] Add integration tests for new connector OAuth and routing flows beyond smoke checks
