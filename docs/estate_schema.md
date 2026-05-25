# Norman Estate Schema v1

This document turns the operating model in [`docs/bot_empire.md`](bot_empire.md)
into concrete application objects. It is the bridge between the kingdom-level
model and the actual Norman UI, API, and database schema.

Status:

- working draft
- intended to reduce ambiguity before deeper app work
- optimized for durability, not for immediate completeness
- machine-readable seed registry lives at `db/estate/registry.yaml.dist`

## Design Rules

1. `principal` is the hard wall.
   OpenBrand, personal, trust, and other principals must not blur together by
   default.
2. `bot` is a role, not a repo, tmux pane, or service.
3. `service` is the managed app or process.
4. `session` is temporary runtime, never the canonical model.
5. `worker` is a real execution host or bridge, not a logical grouping.
6. `place`, `asset`, `service`, and `channel` should be richly modeled under a
   smaller top-level bot fleet.
7. Norman the `role` is durable. Norman the `service` is editable.

## Core Objects

### `principal`

Hard ownership and authority boundary.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `slug` | string | stable id, e.g. `openbrand` |
| `display_name` | string | human label |
| `kind` | enum | `person`, `trust`, `company`, `household`, `venture` |
| `parent_principal_id` | UUID nullable | optional hierarchy |
| `is_active` | bool | soft enable/disable |
| `notes` | text nullable | operator context |

Seed candidates:

- `operator`
- `kubicki-trust`
- `openbrand`
- `tcg`
- `yhix`

### `domain`

Soft operational lane within a principal.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `principal_id` | UUID | owning principal |
| `slug` | string | stable id |
| `display_name` | string | UI label |
| `kind` | enum | `control`, `ops`, `knowledge`, `security`, `health`, etc. |
| `default_policy_profile_id` | UUID nullable | default safety mode |
| `notes` | text nullable | intent and scope |

Likely starting domains:

- `evergreen`
- `household`
- `food`
- `people`
- `places`
- `openbrand-ops`
- `communications`
- `scheduling`
- `knowledge`
- `security`
- `finance`
- `health`
- `observability`
- `radio`
- `labs`
- `fleet`
- `studio`

### `bot`

Durable agent role with a clean mission.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `principal_id` | UUID | hard boundary |
| `domain_id` | UUID | primary lane |
| `slug` | string | stable id |
| `display_name` | string | UI label |
| `class` | enum | `manager`, `operator`, `observer`, `advisor`, `router`, `archivist` |
| `policy_profile_id` | UUID | default action envelope |
| `owner_person_id` | UUID nullable | human owner |
| `is_active` | bool | enable/disable |
| `notes` | text nullable | mission statement |

Current target fleet:

- `norman`
- `evergreen-ops`
- `household-ops`
- `communications`
- `cyber-advisor`
- `archivist`
- `observability`
- `research-analyst`
- `finance-reader`
- `health-reader`
- `radio-supervisor`
- `scheduler`

### `worker`

Real machine, VM, container, bridge host, or edge execution node.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `principal_id` | UUID | owning boundary |
| `slug` | string | stable id |
| `display_name` | string | operator label |
| `kind` | enum | `workstation`, `vm`, `container`, `edge`, `bridge`, `cloud` |
| `hostname` | string nullable | network identity |
| `place_id` | UUID nullable | where it lives |
| `control_class_id` | UUID nullable | root/admin/pending/observed |
| `policy_profile_id` | UUID nullable | runtime safety default |
| `notes` | text nullable | capabilities and constraints |

Examples:

- `hal`
- `phobos-host`
- `quaoar`
- future work node for Earlybird
- Hubitat hubs when modeled as edge nodes

### `place`

Physical or place-like location in the twin.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `principal_id` | UUID | owner/operator boundary |
| `slug` | string | stable id |
| `display_name` | string | UI label |
| `kind` | enum | `home`, `property`, `remote-site`, `region`, `logical-site` |
| `parent_place_id` | UUID nullable | room inside house, etc. |
| `notes` | text nullable | operator context |

Likely seeds from networking:

- `house`
- `beach`
- `waconda`
- `pluto-remote-networks`
- maybe `castle`

### `asset`

Physical or logical thing that is not best modeled as a service.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `principal_id` | UUID | owner boundary |
| `place_id` | UUID nullable | where it lives |
| `worker_id` | UUID nullable | host/controller |
| `slug` | string | stable id |
| `display_name` | string | UI label |
| `kind` | enum | `device`, `hub`, `vehicle`, `radio-node`, `account`, `camera`, `sensor` |
| `control_class_id` | UUID nullable | level of control |
| `notes` | text nullable | operator details |

Examples:

- `phobos`
- `pluto`
- `hubitat-knox`
- `front-door-camera`
- future drones and vehicles

### `service`

Managed app, process, pipeline, or scheduled job.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `principal_id` | UUID | owner boundary |
| `domain_id` | UUID | primary lane |
| `bot_id` | UUID nullable | supervising bot |
| `worker_id` | UUID nullable | where it runs |
| `place_id` | UUID nullable | site affinity if relevant |
| `slug` | string | stable id |
| `display_name` | string | UI label |
| `kind` | enum | `web-app`, `daemon`, `pipeline`, `batch`, `bridge`, `agent-runtime` |
| `policy_profile_id` | UUID nullable | action envelope |
| `web_url` | string nullable | operator jump link |
| `start_command` | text nullable | managed runtime command |
| `healthcheck` | text nullable | health source |
| `notes` | text nullable | runtime caveats |

Examples:

- `earlybird`
- `housebot-cloud`
- `housebot-edge-home`
- `control-plane`
- `tmi-dashboards`
- `norman-service`

### `channel`

External communication path.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `principal_id` | UUID | owner boundary |
| `domain_id` | UUID | usually `communications` |
| `bot_id` | UUID nullable | default supervising bot |
| `person_id` | UUID nullable | human relationship |
| `service_id` | UUID nullable | attached service if any |
| `slug` | string | stable id |
| `display_name` | string | UI label |
| `kind` | enum | `gmail`, `slack`, `signal`, `sms`, `discord`, etc. |
| `policy_profile_id` | UUID | `draft-first` is likely default |
| `notes` | text nullable | operator context |

### `person`

Human counterpart or stakeholder.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `principal_id` | UUID nullable | optional home boundary |
| `slug` | string | stable id |
| `display_name` | string | person label |
| `kind` | enum | `family`, `colleague`, `vendor`, `stakeholder`, `contact` |
| `notes` | text nullable | relationship context |

### `session`

Live runtime handle only.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `service_id` | UUID nullable | service if applicable |
| `bot_id` | UUID nullable | bot if directly attached |
| `worker_id` | UUID nullable | where it runs |
| `runtime_kind` | enum | `codex`, `tmux`, `screen`, `process`, `remote` |
| `external_id` | string | codex session id, tmux target, etc. |
| `status` | enum | `running`, `idle`, `stopped`, `unknown` |
| `last_seen_at` | datetime nullable | inventory freshness |
| `notes` | text nullable | operator context |

### `policy_profile`

Reusable safety envelope.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `slug` | string | stable id |
| `display_name` | string | UI label |
| `mode` | enum | `read-only`, `draft-first`, `manual`, `shared`, `auto` |
| `requires_approval` | bool | guardrail |
| `allows_outbound_send` | bool | messages |
| `allows_runtime_control` | bool | start/stop/restart |
| `allows_side_effects` | bool | broader actions |
| `notes` | text nullable | usage rules |

Default seeds:

- `read-only`
- `draft-first`
- `manual`
- `shared`
- `auto`
- `panic-lock`

### `control_class`

Concrete control state for workers and assets.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `slug` | string | stable id |
| `display_name` | string | UI label |
| `rank` | int | ordering |
| `notes` | text nullable | operator semantics |

Seed values adapted from `../networking`:

- `root-controlled`
- `admin-controlled`
- `pending-control`
- `observed-only`

### `twin_link`

Edge in the digital twin graph.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `source_type` | enum | object type |
| `source_id` | UUID | source object |
| `relation` | enum | `owns`, `contains`, `hosts`, `manages`, `observes`, `belongs-to`, `uses` |
| `target_type` | enum | object type |
| `target_id` | UUID | target object |
| `notes` | text nullable | human explanation |

This avoids forcing a single tree where the estate is really a graph.

## Cross-Cutting Metadata

These should attach to multiple core objects rather than becoming separate
top-level entities immediately.

| Field | Applies To | Notes |
|---|---|---|
| `wufu_axis` | domain, bot, service, inbox item | `寿`, `富`, `康宁`, `攸好德`, `考终命` |
| `kaizen_candidate` | service, session, inbox item | improvement candidate |
| `risk_tier` | worker, asset, service, channel | safety and escalation weight |
| `maturity_stage` | asset, service, bot | `noted`, `observed`, `managed`, `automated`, `autonomous` |

## Relationships

The graph will branch, but the stable mental model is:

```text
principal -> domain -> bot
principal -> place -> worker
principal -> place -> asset
bot -> manages -> service
bot -> observes -> asset
worker -> hosts -> service
service -> exposes -> channel
service/bot/worker -> has -> session
person -> uses -> channel
```

Two important clarifications:

1. `Norman` the role is a `bot`.
2. `norman-service` is a `service`.

That separation keeps self-editing possible without making the governing role
too soft.

## Current Seed Mapping

This is the minimum useful first seed set.

### Principals

- `operator`
- `kubicki-trust`
- `openbrand`
- `tcg`
- `yhix`

### Bots

- `norman`
- `evergreen-ops`
- `household-ops`
- `communications`
- `cyber-advisor`
- `archivist`
- `observability`
- `research-analyst`
- `finance-reader`
- `health-reader`
- `radio-supervisor`
- `scheduler`

### Services

- `norman-service`
- `housebot`
- `glimpser`
- `autocamera`
- `control-plane`
- `d-ace`
- `mc`
- `infra`
- `tmi-dashboards`
- `earlybird`
- `platinum-standard`

### Workers

- `hal`
- `phobos-host`
- `quaoar`
- future OpenBrand work service node
- Hubitat edge nodes as they are inventoried

### Places

- `house`
- `beach`
- `waconda`
- `pluto-remote-networks`
- later: explicit Evergreen site/property mapping

## UI Consequences

This schema implies a simpler phone UI:

1. `Editor`
   direct interaction with sessions and channels
2. `Inbox`
   approvals, escalations, drafts, blocked actions
3. `Systems`
   bots, services, workers, and places
4. `Twin`
   graph view of places, assets, services, and ownership

The app should default to:

- principal-aware grouping
- bot-first supervision
- service/session drill-down
- explicit policy display

## Implementation Order

1. Add the object vocabulary to docs and seed data.
2. Add `principal`, `domain`, `bot`, `worker`, `service`, and `policy_profile`
   first.
3. Attach existing sessions to bots/services instead of treating sessions as the
   model.
4. Add `place`, `asset`, and `control_class`.
5. Add `twin_link` and the first Twin UI.
6. Add cross-cutting metadata like `wufu_axis`, `maturity_stage`, and
   `kaizen_candidate`.
