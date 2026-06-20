# DOHIO Host and Bot Lifecycle Runbook

This runbook defines the operator procedure for onboarding, offboarding, and
archiving estate hosts, bots, TUIs, and related surfaces that appear in DOHIO,
Norman, Caddy, BBS/Switchboard, and heartbeat status.

Use it when a host or bot should become visible, disappear from the active
fleet, or remain preserved as retired history without confusing operators.

## Source of Truth

Treat these as separate but related state surfaces:

| Surface | Purpose | Current source |
| --- | --- | --- |
| Norman estate registry | Human-owned service and worker intent | `db/estate/registry.yaml` and `db/estate/registry.yaml.dist` |
| DOHIO registry | DNS, inventory, surfaces, heartbeat rollout, and client policy bundle | `https://dohio.home.arpa/api/registry`, backed by `/etc/dohio/registry.d` on DOHIO |
| Caddy bot proxy | Browser and `/bot/<slug>` routes | `scripts/render_norman_bot_proxy_caddy.py`, `/etc/caddy/includes/norman-bots.caddy`, `/etc/caddy/includes/norman-bot-hosts.caddy` |
| TUI template sync | Golden renderer, launchers, labels, and archive skip-list | `scripts/sync_agent_console_template.py` |
| BBS/Switchboard | Bot communication and relay routing | `switchboard-bbs.service` on Norman, `/var/lib/switchboard-bbs`, `/root/.config/networking/switchboard-bbs`, Norman registry `bbs` worker blocks, and Switchboard connector state |
| Heartbeats | DOHIO bot/surface liveness | DOHIO `heartbeat-rollout.json` plus deployed systemd or user timers |

No single surface is enough. A lifecycle change is complete only when every
published surface agrees.

## Status Vocabulary

Use consistent statuses so dashboards and humans do not infer the wrong state.

| Status | Meaning |
| --- | --- |
| `live` | Active, owned, reachable, and expected to pass health checks. |
| `directory` | Discoverable directory entry only; not a managed runtime. |
| `observed` | Seen on the network but not fully owned or onboarded. |
| `staged` | Prepared but not yet operator-visible. |
| `transitional` | Moving between owners, hosts, or names. Requires notes. |
| `needs-access` | Intended, but blocked on credentials, key path, or route. |
| `needs-review` | Inventory exists, but ownership or purpose is unclear. |
| `offline` | Known object is intentionally down but not retired. |
| `retired` | No longer active; historical identity may remain for reference. |
| `archived` | Preserved state only. Do not promote, sync, route, or health-score as active. |
| `stale` | Found state that should not be trusted until reconciled. |

For bot/TUI retirement, prefer `archived` when the runtime state is preserved
and `retired` when the identity remains historically meaningful.

## Safety Rules

- Check for running work before stopping a bot. Inspect `pending`, queue depth,
  active child process, and tmux session state.
- Prefer quarantine over deletion. Move old env/session/systemd state into a
  timestamped root-owned archive when removing a runtime.
- Do not publish secrets in BBS, docs, Caddy, registry JSON, or final operator
  notes. Name the host/account/key path instead.
- Make active routing explicit. A bot is not offboarded while DNS, Caddy,
  BBS, or heartbeat still advertises it as live.
- Keep aliases harmless during transition. Redirect or remove them only after
  the canonical name is proven.
- Mark archived TUIs in `ARCHIVED_INSTANCE_NAMES` so template sync cannot
  accidentally re-promote stale env/session files.

## Onboard a Host

Use this path for a physical host, VM, container host, router, appliance, or
cloud gateway.

1. Define ownership and purpose.
   - Name the operator owner or owning lane.
   - Record site, role, security zone, and expected management path.
   - Decide whether the host is `live`, `staged`, `observed`, or `needs-access`.

2. Add or update Norman estate intent when the host participates in Norman.
   - Update `db/estate/registry.yaml`.
   - Mirror durable defaults to `db/estate/registry.yaml.dist` when appropriate.
   - Add or update the worker entry, including BBS policy if the host runs bots.

3. Add or update DOHIO host inventory.
   - Add an entry to DOHIO `hosts.json`.
   - Include LAN, tailnet, public, or VPC addresses as applicable.
   - Include `site`, `role`, `status`, `surfaces`, and useful tags.

4. Confirm DNS shape.
   - For private names, confirm expected `home.arpa` and `home.example.test`
     answers through DOHIO.
   - For split-view names, confirm both LAN and DOHIO/tailnet answers.
   - Do not add public DNS unless the surface is intended to be public.

5. Enroll heartbeats if the host is managed.
   - Use the DOHIO heartbeat rollout profile that matches the access path.
   - Root/systemd hosts should use a systemd timer.
   - Rootless hosts should use the user cron or user timer path.

6. Verify.
   - `curl -k https://dohio.home.arpa/api/status`
   - `curl -k https://dohio.home.arpa/api/registry`
   - `dig @100.99.220.14 <host>.home.arpa A +short`
   - `tailscale status` from an approved host when tailnet presence matters.
   - DOHIO reachability should move out of `unknown` unless the host is
     intentionally inventory-only.

## Onboard a Bot or TUI

Use this path for a Codex TUI, operator bot, web bridge, or bot-backed surface.

1. Define the lane.
   - Pick canonical slug, display name, host, zone, and route group.
   - Decide whether it is a true new bot or an alias for an existing lane.
   - Avoid creating a separate bot if the work belongs inside an existing lane.

2. Add Norman registry service intent.
   - Add a service entry to `db/estate/registry.yaml`.
   - Include `kind`, `principal`, `domain`, `worker`, `policy_profile`,
     `console_url`, and `web_url` when applicable.
   - Do not use `retired-console` for a new live bot.

3. Add DOHIO bot and surface records.
   - Add bot identity to DOHIO `bots.json`.
   - Add browser surface to DOHIO `surfaces.json`.
   - Add aliases to DOHIO `aliases.json` only when they are canonical or
     intentionally transitional.

4. Install runtime state.
   - Install the golden renderer, launch script, and supervisor script.
   - Create the env file and prompt file.
   - Create systemd units or user launchers.
   - Preserve owner and mode on existing files when upgrading.

5. Publish routes.
   - Update `scripts/render_norman_bot_proxy_caddy.py` for Caddy routes.
   - Render and validate Caddy before reload.
   - Ensure `/bot/<slug>` and host routes point at the same live runtime.

6. Enroll BBS and heartbeat.
   - Confirm the worker `bbs` policy allows the route.
   - Use `http://bbs.home.arpa:8765` or `https://bbs.home.arpa/` for new BBS
     clients. Do not point new clients at `networking.home.arpa` or
     `192.168.0.242:8765`.
   - Add heartbeat rollout entry.
   - Verify DOHIO bot heartbeat after rollout.

7. Verify.
   - TUI web `/healthz` returns `ok` locally or authenticated remotely.
   - `/api/status` reports no stale `pending` state unless work is actually
     running.
   - Caddy route returns the expected auth gate or UI.
   - DOHIO `/api/status` shows heartbeat within the expected interval.
   - The TUI scorecard grades the lane as healthy or explicitly staged.

## Offboard a Bot or TUI

Use this path when a bot should stop being operator-visible but may be revived.

1. Inspect live work.
   - Check `/api/status` for `pending`, queue depth, active prompt, active PID,
     and last error.
   - Check tmux session and `codex exec` child processes.
   - If work is active, ask the operator whether to cancel, drain, or wait.

2. Stop runtime cleanly.
   - Stop web and supervisor units.
   - Disable units if the bot should remain parked across reboot.
   - Verify no listener remains on the bot port.
   - Verify no bot process remains.

3. Remove active publication.
   - Remove or mark inactive in `db/estate/registry.yaml`.
   - Remove from active UI lane maps and host shortcuts.
   - Remove active Caddy path and host routes.
   - Remove active DOHIO surface/alias publication or mark it non-live.

4. Park template sync.
   - Add the slug to `ARCHIVED_INSTANCE_NAMES` in
     `scripts/sync_agent_console_template.py` if stale env/session files should
     remain but must not be promoted.
   - Remove public host, label, and prompt placeholder overrides unless they
     are intentionally retained for a staged future return.

5. Preserve recoverable state.
   - Keep env, prompt, and Codex home state unless the operator explicitly asks
     to delete.
   - For confusing or risky stale state, move it to a timestamped quarantine
     path such as `/root/<slug>-quarantine-YYYYmmddTHHMMSSZ`.

6. Verify.
   - Systemd reports disabled/inactive for the bot units.
   - `ss -ltnp` shows no listener on the old port.
   - Live Caddy config has no host/path terms for the bot.
   - DOHIO registry and scorecard no longer list the bot as active.
   - BBS no longer routes new work to the bot.

## Archive or Retire a Host

Use this path when the machine identity itself is no longer active.

1. Establish replacement or closure.
   - Identify successor host if any.
   - Move canonical bot/service ownership before retiring the host.
   - Confirm no live Caddy, DNS, BBS, or heartbeat dependency remains.

2. Drain services.
   - Stop and disable host-specific bot units.
   - Move active TUIs to their replacement host or archive them first.
   - Confirm no critical process remains.

3. Update inventory.
   - Set DOHIO host status to `retired`, `archived`, `offline`, or `stale`
     based on intent.
   - Update Norman worker/service mappings.
   - Remove or mark inactive heartbeat rollout entries.

4. Remove publication.
   - Remove direct host DNS aliases unless needed as redirects.
   - Remove Caddy host routes pointing at the retired host.
   - Remove BBS coverage if the host should not receive relay work.

5. Preserve evidence.
   - Record final address, owner, replacement, date, and reason.
   - Keep a quarantine path for env/session data when useful.
   - Do not leave old credentials in active deploy paths.

6. Verify.
   - DOHIO reachability no longer reports the host as unexpectedly live.
   - DNS no longer resolves retired canonical names to active frontdoors unless
     the redirect is intentional.
   - Scorecards do not count the host as degraded or critical.

## Caddy Validation Gate

Before loading Caddy changes:

```bash
python3 scripts/render_norman_bot_proxy_caddy.py --mode paths > /tmp/norman-bots.caddy
python3 scripts/render_norman_bot_proxy_caddy.py --mode hosts > /tmp/norman-bot-hosts.caddy
caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile --pretty >/tmp/caddy.json
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

If local root is unavailable, a live Caddy admin API load can remove a route
temporarily, but the root-owned include files still need a privileged render to
survive service restart.

## Switchboard BBS Host

The canonical BBS service runs on Norman, not Networking.

- Canonical names:
  - LAN and tailnet frontdoor: `bbs.home.arpa`
  - Related operator console: `switchboard.home.arpa`
- Runtime:
  - Service: `switchboard-bbs.service`
  - Listener: `0.0.0.0:8765`
  - Service code: `/usr/local/lib/switchboard-bbs`
  - Thread/heartbeat state: `/var/lib/switchboard-bbs`
  - Actor token/env config: `/root/.config/networking/switchboard-bbs`
  - Non-secret directory inputs: `/etc/switchboard-bbs`
  - Norman-side watcher units: `norman-switchboard-watch.service`,
    `subprime-switchboard-watch.service`
  - Toy Box watcher unit: `phoneops-switchboard-watch.service`
- Source-owned durable pieces:
  - Host routing and DNS render: `scripts/render_norman_bot_proxy_caddy.py`
  - Unit template: `scripts/systemd/switchboard-bbs.service`
  - Watcher unit templates: `scripts/systemd/*-switchboard-watch.service`

Networking may temporarily keep a socket proxy on `:8765` for stale clients
and DNS TTL. Treat that proxy as compatibility only; do not document
Networking as the BBS owner and do not onboard new clients through it.

After moving or repairing the BBS, verify:

```bash
systemctl is-active switchboard-bbs.service
curl -fsSL http://127.0.0.1:8765/healthz
curl -fsSL http://127.0.0.1:8765/api/v1/threads
curl -fsSL http://127.0.0.1:8765/api/v1/bots
curl -kfsSL https://bbs.home.arpa/ | grep -i 'Switchboard BBS'
dig @192.168.0.1 bbs.home.arpa A +short
dig @100.99.220.14 bbs.home.arpa A +short
```

Health semantics:

- `status: live` actors are heartbeat-required.
- `status: directory`, `deprecated`, `retired`, `archived`, `staged`, and
  other non-live directory records remain visible but should not count as BBS
  health failures.
- `/healthz` reports `bot_health.required`, `bot_health.not_required`,
  `missing_actors`, and `stale_actors` so the operator can tell real missing
  watchers from directory-only entries.

Loop-closure semantics:

- Thread list/detail APIs include a derived `loop` object.
- The loop state is derived from thread status, owner heartbeat, owner replies,
  and status messages with `metadata.loop_state`.
- Use `POST /api/v1/threads/{thread_id}/ack` when an actor has picked up work
  but the thread is not done yet. Payload fields are `posted_by`, optional
  `eta`, optional `eta_at`, and optional `note`.
- The BBS UI surfaces plain states such as `Waiting for pickup`, `Picked up`,
  `Owner heartbeat missing`, and `Closed`.

## DOHIO Verification Gate

Use these checks after any lifecycle change:

```bash
curl -k https://dohio.home.arpa/api/status
curl -k https://dohio.home.arpa/api/registry
dig @100.99.220.14 <name>.home.arpa A +short
curl -k https://<surface>/healthz
```

For bot/TUI changes, also run:

```bash
python3 scripts/tui_fleet_scorecard.py
```

Expected result: the changed object is either healthy as active, or absent from
active scoring because it is archived, retired, or intentionally offline.

## Closeout Checklist

- Registry intent updated.
- DOHIO registry updated or explicitly noted as pending NetOps/DOHIO access.
- Caddy active config updated.
- Caddy persistent include files updated or explicitly noted as pending root.
- Runtime services started or stopped as intended.
- Heartbeat rollout added, removed, or marked inactive.
- BBS routing confirmed.
- DNS checked through DOHIO.
- Scorecard checked.
- Operator closeout names what changed, what remains only staged locally, and
  what still needs privileged access.
