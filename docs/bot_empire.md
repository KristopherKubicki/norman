# Norman Operating Model

This document records the high-level operating model for Norman: the "bot empire" view of the estate, the control
plane vocabulary, and the major open questions that still need to be resolved before the app can manage the whole
system cleanly.

Status:

- this is still a working draft
- the overall form is getting close
- major systems and lanes still need refinement
- the goal is a durable operating model, not a perfect taxonomy on the first pass

## Why This Exists

Norman is no longer just a connector router. It is becoming:

- a cross-realm control plane
- a session and service inventory
- a mobile-first operator surface
- an escalation and approval inbox
- a digital twin for sites, devices, services, channels, and people

The key modeling rule is: do not collapse everything into `bots`.

Norman needs separate concepts for:

- `realm`: trust and ownership boundary
- `worker`: where something runs
- `bot`: durable agent role
- `service`: managed app/process
- `session`: live runtime instance
- `channel`: external communication path
- `asset`: device, account, system, or endpoint
- `site`: physical or logical place
- `person`: contact / human relationship
- `policy`: permission and safety profile
- `digital twin`: the graph that links all of the above

## Kingdom Framing

The bot estate is useful to think about like a kingdom, but the metaphor should stay structural rather than theatrical.

| Kingdom Layer | Norman Meaning |
|---|---|
| `Sovereign / General Manager` | `Norman` as the governing control plane |
| `Principal / Crown` | the hard ownership boundary: `[REDACTED_NAME]`, `[REDACTED_NAME] Trust`, `OpenBrand`, `TCG`, `Yhix` |
| `Realm / Province` | the domain or territory inside a principal |
| `Minister / Steward` | a top-level bot with a clean mission |
| `Town / Site / Holding` | a place, property, or operational locus |
| `Guild / Service` | a managed app, process, or system |
| `Scout / Sensor` | an observing edge node, feed, or passive listener |
| `Road / Channel` | a communication or routing path |
| `Ledger / Archive` | durable memory, handoffs, backups, and historical state |

The important point is that kingdoms thrive not just through control, but through:

- continuity
- food and provisioning
- peace and household stability
- trusted communications
- knowledge and records
- finance and material capacity
- health and resilience
- security and identity
- mobility and logistics
- observability and early warning
- improvement over time

That is why the model needs more than runtime control. It needs lanes that represent what makes the estate healthy.

## Guidance Layer

These are not runtime objects. They are planning, prioritization, and dashboard lenses.

### 五福 (Five Blessings)

Use the superior/original term first, then English in parentheses.

| Axis | English | Norman Meaning |
|---|---|---|
| `寿` | `Longevity` | durability, continuity, backups, resilience, health of long-lived systems |
| `富` | `Wealth` | finance, assets, economic strength, work capacity, resource abundance |
| `康宁` | `Peace` | calm operations, family stability, healthy home systems, reduced friction |
| `攸好德` | `Virtue` | ethics, restraint, approvals, safety, trustworthy action boundaries |
| `考终命` | `Completion` | finishing well, handoffs, archival quality, succession, graceful shutdown |

### Kaizen (Continuous Improvement)

`Kaizen (Continuous Improvement)` is the improvement loop over the whole estate:

- friction reports
- recurring failures
- reduction of operator burden
- cleanup of vague ownership
- repeatable playbooks
- postmortems and better defaults

## Proposed Top-Level Domains

These are high-level domains, not necessarily single bots:

| Domain | Default Policy | Notes |
|---|---|---|
| `Control` | `manual` | Norman itself; cross-realm control plane |
| `Evergreen` | `shared` | Castle, Diamond Roc, Cloudagent, and related site/service operations |
| `OpenBrand` | `shared` | work-owned product, infra, content, and data operations |
| `Household` | `manual` | family, home, routines, emergencies, contacts |
| `Health` | `read_only` | biometrics, appointments, medications, trends |
| `Finance` | `read_only` | accounts, bills, taxes, receipts, cashflow, net worth |
| `Communications` | `draft_first` | Gmail, Slack, Signal, SMS, replies, escalations |
| `Scheduling` | `draft_first` | calendar, reminders, follow-ups, commitments |
| `Knowledge` | `shared` | notes, specs, handoffs, journals, runbooks |
| `Security` | `manual` | identity, credentials, account recovery, high-risk alerts |
| `Opportunity` | `manual` | weak signals, luck, serendipity, market opportunities, anomalies |
| `Continuity` | `auto` | backups, snapshots, restore state, session recording, archival health |
| `Observability` | `shared` | monitoring, sensors, dashboards, runtime health, passive listening |

These domains are still a draft. They should eventually become a small number of clear lanes that correspond to how the
estate actually thrives and how the phone UI should group work.

## Current Estate Matrix

This is the working classification as of now. It is a control-plane view, not a code ownership map.

| System | Primary Realm | OpenBrand | Work | Type | Twin Role | Notes |
|---|---|---:|---:|---|---|---|
| `Norman` | `Control` | `No` | `Mixed` | `control_plane` | `controller` | Cross-realm operator surface; should not be modeled as just another bot |
| `Digital Twin` | `Control` | `Mixed` | `Mixed` | `graph` | `registry` | Shared graph for sites, assets, services, bots, channels, and people |
| `Housebot` | `Household / Evergreen boundary` | `No` | `No` | `bot` | `site_ops` | Home automation, locks, sensors, Hubitat, local safety operations |
| `Networking` | `Household / Evergreen boundary` | `No` | `No` | `bot` | `infra_inventory` | Network discovery, topology, passive sensors, recovery, documentation |
| `Radio / Phobos` | `Household` | `No` | `No` | `bot` | `edge_sensor` | SDR/radio/hunter box operations |
| `Castle` | `Evergreen` | `No` | `No` | `site/service` | `site` | Evergreen site/system; operator bot should sit above the app |
| `Diamond Roc` | `Evergreen` | `No` | `No` | `site/service` | `site` | Same pattern as Castle |
| `Cloudagent` | `Evergreen` | `No` | `No` | `service` | `infra_service` | Evergreen infra/service lane; should probably live under Evergreen Ops |
| `Theseus` | `Evergreen / Household boundary` | `No` | `No` | `service` | `local_system` | Physical/local system tied to `hal` |
| `Autocamera` | `Household` | `No` | `No` | `service` | `sensor/media_ingest` | Physical camera stack tied to local hardware |
| `Glimpser` | `Household` | `No` | `No` | `service` | `observability` | Monitoring surface and signal source |
| `Maps` | `Household` | `No` | `No` | `service` | `geo_view` | Site/location intelligence |
| `MLS Reader` | `Household` | `No` | `No` | `service` | `property_intel` | Real-estate and property intelligence lane |
| `Gold Book` | `Knowledge boundary` | `No` | `Mixed` | `knowledge_system` | `authority` | Strategically work-relevant but still mostly private in session ownership |
| `d.ace` | `OpenBrand` | `Yes` | `Mixed` | `service_platform` | `production_platform` | Major OpenBrand media/ad intelligence platform |
| `Acast` | `OpenBrand` | `Yes` | `Yes` | `service_platform` | `content_pipeline` | Clear OpenBrand workstream |
| `Acast Tester` | `OpenBrand` | `Yes` | `Mixed` | `repair_lane` | `remediation` | OpenBrand function, but split across private and work/live-side paths |
| `Infra` | `OpenBrand` | `Yes` | `Yes` | `ops_platform` | `infra_control` | Cleanest pure work/OpenBrand cluster |
| `Control Plane` | `OpenBrand` | `Yes` | `Yes` | `workflow_platform` | `admin_ops` | Imports, workflows, remediation, operational tooling |
| `TMI Dashboards` | `OpenBrand` | `Yes` | `Yes` | `scheduled_publish` | `reporting` | Better modeled as scheduled batch/serverless work than as a generic long-lived app |
| `Earlybird` | `OpenBrand` | `Yes` | `Yes` | `app_service` | `work_service` | Strong candidate for a dedicated work container |
| `Platinum Standard` | `OpenBrand` | `Yes` | `Yes` | `research_system` | `model_authority` | Canonical modeling/estimate layer |
| `Surveyor` | `OpenBrand` | `Yes` | `Mixed` | `analysis_lane` | `research` | Mostly work-shaped, but not fully clean in ownership |
| `NFM Matches` | `OpenBrand` | `Yes` | `Mixed` | `analysis_lane` | `matching` | Reconciliation / comparison workflow |
| `Market Sizing` | `OpenBrand` | `Yes` | `Yes` | `analysis_lane` | `strategy` | Strategy/research lane |
| `SOV` | `OpenBrand` | `Yes` | `Yes` | `analysis_lane` | `content_strategy` | Supporting workstream, clearly work-shaped |
| `Podchaser611` | `OpenBrand` | `Yes` | `Mixed` | `support_lane` | `media_support` | Media/content support, less central than `d.ace` or `acast` |
| `Contracts` | `Knowledge / Work boundary` | `Mixed` | `Yes` | `knowledge_system` | `legal_ops` | Work-owned but not necessarily OpenBrand-core runtime infrastructure |
| `Work Email` | `Communications / Work boundary` | `Mixed` | `Yes` | `channel_domain` | `comms` | Work communications lane |
| `Instore Receipts` | `OpenBrand` | `Yes` | `Mixed` | `ops_data_lane` | `receipts_data` | Niche but clearly work-relevant |
| `Web Posture` | `Security` | `No` | `No` | `security_lane` | `external_surface` | Security/perimeter lane |
| `HBM Disto` | `Household` | `No` | `No` | `specialized_lane` | `analysis` | Specialized personal workflow |
| `Finance Bot` | `Finance` | `No` | `No` | `planned_bot` | `finance_reader` | Planned; should start read-only |
| `Health Bot` | `Health` | `No` | `No` | `planned_bot` | `health_reader` | Planned; should start read-only and privacy-constrained |
| `Scheduler` | `Scheduling` | `No` | `No` | `planned_bot` | `calendar_agent` | Planned; draft-first and approval-based |
| `Comms Router` | `Communications` | `Mixed` | `Mixed` | `missing_system` | `message_router` | Missing but central: Gmail/Slack/Signal/SMS normalization and escalation |
| `Archivist` | `Continuity` | `No` | `Mixed` | `missing_system` | `backup_restore` | Missing but clearly needed for snapshots, restores, handoffs, and recovery |
| `Knowledge Keeper` | `Knowledge` | `Mixed` | `Mixed` | `missing_system` | `memory_layer` | Missing layer between session history and durable knowledge |
| `Observability` | `Observability` | `Mixed` | `Mixed` | `missing_system` | `signal_fabric` | Missing roll-up across Glimpser, Autocamera, Networking, Radio, and runtime health |

### Edge Worker Note

`Hubitat` nodes should be treated as `edge workers` or `edge assets` under the household/housebot domain when they are
being governed by `Housebot`.

That means:

- the `Housebot` control lane owns the policy
- each Hubitat node is still a separately modeled runtime/edge object
- location-specific hubs should map cleanly into the digital twin

Examples that likely belong here:

- `Knox`
- `Beach`
- `Halsted`
- `Argyle`

Those should not be flattened into one generic household blob.

## Alignment with `../networking`

The `networking` repo is currently the best reality check for whether this model is grounded in the actual estate.
Its documents are more concrete than the bot model in a few important ways:

- `ROADMAP_20260322.md` already thinks in `places`
- `CONTROL_BIG_BOARD.md` already thinks in `control classes`
- `ARCHITECTURE_CLOUD_EDGE_20260322.md` already thinks in `cloud/edge split`, `workers`, and `bridges`

That means Norman should absorb those concepts rather than inventing a separate vocabulary.

### Place / Site Lanes

These are the concrete place-like lanes already visible in `../networking`:

| Place / Lane | Source | Implication for Norman |
|---|---|---|
| `House` | `ROADMAP_20260322.md` | first-class place |
| `Beach` | `ROADMAP_20260322.md` | first-class place |
| `Pluto / Remote Networks` | `ROADMAP_20260322.md` | place-like remote lane, not just a host |
| `Waconda / farm` | `ROADMAP_20260322.md` | future place/site lane |

Norman should therefore model `Place` explicitly instead of hiding these under generic system names.

### Control Classes

`CONTROL_BIG_BOARD.md` already uses a strong operational classification:

| Control Class | Meaning |
|---|---|
| `ROOT_CONTROLLED` | direct root/sudo control exists |
| `ADMIN_CONTROLLED` | admin/API or appliance-level control exists |
| `PENDING_CONTROL` | known object, but automation/control is incomplete |
| `OBSERVED_ONLY` | should be added later for things Norman can see but not control |

Norman should adopt a version of this instead of using only vague statuses like "managed" or "configured".

### Edge Nodes and Bridges

The networking repo already gives the right shape for edge/worker modeling:

| Object | Current Meaning | Norman Modeling |
|---|---|---|
| `hal` | local workstation / bridge host | `worker` |
| `phobos-host` | radio machine | `edge worker` |
| `quaoar` | beach node | `edge worker` |
| `pluto-host` | remote node | `edge worker` |
| `hal-bridge` | typed local control path | `bridge service` |
| `housebot-cloud` | cloud coordination side | `service` |
| `housebot-edge-home` | local execution side | `service` |
| `phobos-radio-supervisor` | local radio control | `bot/service` boundary |

This supports the architecture rule:

- cloud governs
- edge executes
- bridges translate

### Role Split Clarification

The `networking` repo suggests the following cleaner split:

| Lane | Best Meaning |
|---|---|
| `Household Ops` / `Housebot` | acts on home systems, routines, hubs, and local automation |
| `Networking` | topology, control matrix, path validation, inventory, passive infra sensing |
| `Observability` | roll-up monitoring, dashboards, alerts, camera/runtime health |

This is a better split than treating those three lanes as roughly interchangeable.

### Identity / Recovery as Infrastructure

`ROADMAP_20260322.md` treats `noreply.evergreen.alerts@gmail.com` as shared infrastructure, not just a mailbox.
That supports:

- `Cyber Advisor` as a first-class lane
- `Continuity` as a first-class lane
- explicit modeling for:
  - identity
  - recovery material
  - dependency mapping

### Concrete Adjustment to the Empire Model

The current Norman model should therefore lean more heavily on:

1. `Place`
2. `Control Class`
3. `Edge Worker`
4. `Bridge Service`
5. `Identity / Recovery`

and slightly less on inventing more top-level bots.

## Recommended Bot Catalog

These are role objects, not repos or sessions:

- `Norman`
- `Evergreen Ops`
- `Castle Operator`
- `Diamond Roc Operator`
- `Cloudagent Operator`
- `Housebot`
- `Networking`
- `Phobos Radio`
- `Finance Reader`
- `Health Reader`
- `Scheduler`
- `Comms Router`
- `Archivist`
- `Knowledge Keeper`
- `Observability`
- `Research Analyst`

## Collapsed Bot Fleet v1

The estate should collapse to a smaller top-level fleet. Most nouns in the current map should become `sites`,
`services`, `assets`, or `programs` underneath these bots instead of becoming top-level bots themselves.

| Bot | Primary Domains | Owns / Supervises | What Should Collapse Under It |
|---|---|---|---|
| `Norman` | `Control` | overall governance, approvals, routing, kill switches | nothing above it |
| `Evergreen Ops` | `Evergreen` | Evergreen sites, services, and site operations | `Castle`, `Diamond Roc`, `Cloudagent`, parts of `Theseus`, maybe some of `Housebot` |
| `Housebot` | `Household` | home operations and local safety automation | sensors, locks, thermostats, Hubitat automations |
| `Networking` | `Observability`, `Household`, `Evergreen boundary` | network map, passive sensors, connectivity, topology | local network assets, passive collectors, some radio-network crossover |
| `Radio Supervisor` | `Radio`, `Labs` | radio/space-piracy/ham edge fleet | `phobos`, `pluto`, `quaoar`, future radio edges |
| `Communications` | `Communications`, `Scheduling boundary` | Gmail, Slack, Signal, SMS, reply drafting and routing | `Work Email`, connector-level message routing |
| `Archivist` | `Continuity`, `Knowledge` | snapshots, restores, handoffs, durable summaries | session inventories, backup state, restore sheets |
| `Cyber Advisor` | `Security` | identities, accounts, MFA, recovery, exposure | account inventory, password-manager references, API key posture |
| `Observability` | `Observability` | roll-up monitoring, sensors, dashboards, runtime health | `Glimpser`, `Autocamera`, runtime health, selected Networking feeds |
| `Research Analyst` | `OpenBrand`, `Knowledge`, `Labs` | read-only synthesis and model comparison | `Platinum Standard`, `Surveyor`, `NFM Matches`, `Market Sizing`, maybe parts of `SOV` |
| `Finance Reader` | `Finance` | financial read-only monitoring by principal | account and receipt lanes, later per-principal finance views |
| `Health Reader` | `Health` | health read-only monitoring | metrics, appointments, meds, trends |

This fleet is still a work in progress. It is intended to converge toward the right shape, not freeze too early.

### Bot Demotion Rules

Before adding a new top-level bot, ask:

1. Is this really a bot, or just a `site`, `service`, `asset`, or `program`?
2. Does it have a distinct mission, or is it just a sub-area of an existing bot?
3. Does it need separate permissions and safety policy?
4. Will it remain useful on mobile as a top-level object?

If the answer is mostly "no", it should not become a top-level bot.

Examples:

- `Castle` should probably be a `site/service` under `Evergreen Ops`, not a peer to Norman.
- `Glimpser` should probably be a `service/signal source` under `Observability`, not a peer bot.
- `phobos` should probably be an `edge asset` under `Radio Supervisor`, not a peer bot.
- `TMI Dashboards` should probably be a `scheduled service` under an OpenBrand runtime/analysis domain, not a peer bot.

### Bot Classes

Each top-level bot should fit one primary class:

| Class | Meaning | Current Examples |
|---|---|---|
| `Manager` | governs other bots and policies | `Norman` |
| `Operator` | runs a domain, site, or service fleet | `Evergreen Ops`, `Housebot`, `Radio Supervisor` |
| `Observer` | watches and reports with minimal action | `Observability`, parts of `Networking` |
| `Advisor` | evaluates, recommends, and drafts | `Cyber Advisor`, `Research Analyst`, `Finance Reader`, `Health Reader` |
| `Archivist` | records, snapshots, restores, and summarizes | `Archivist` |
| `Router` | moves messages/tasks/signals between places | `Communications` |

The target state is a small bot fleet and a rich digital twin below it.

## Thriving Lanes

If the kingdom metaphor is useful, the app should emphasize the lanes that make the estate thrive, not just the lanes
that make it controllable.

These are the likely "thriving lanes" that deserve stronger representation:

| Lane | Why It Matters |
|---|---|
| `Household` | stable home operations, family life, routines, comfort |
| `Food` | pantry, groceries, cooking, nutrition, provisioning |
| `People` | family, contacts, stakeholders, relationship context |
| `Places` | properties, sites, rooms, holdings, geography |
| `Knowledge` | records, notes, runbooks, institutional memory |
| `Finance` | economic capacity, receipts, bills, resources |
| `Health` | personal resilience, appointments, meds, biometrics |
| `Security` | trusted action, identity, recovery, safe boundaries |
| `Communications` | trusted message flow and human coordination |
| `Observability` | awareness, sensing, early warning, monitoring |
| `Continuity` | backups, restore paths, handoffs, graceful recovery |
| `Labs / Opportunity` | experimentation, growth, new ventures, luck |
| `Fleet / Mobility` | vehicles, drones, freighter, logistics, movement |

The phone UI should eventually expose these as clean operational lanes or views, rather than only exposing raw runtime
objects.

## Open Questions

These are the unresolved questions that matter most for the app model.

### Realm and Boundary Questions

- Is `Housebot` primarily `Household`, or should it be an `Evergreen` boundary system?
- Should `Networking` be split into `Household Networking` and `Evergreen Networking`, or remain one shared system?
- Is `Theseus` a pure Evergreen system, or a household/evergreen hybrid?
- Should `Gold Book` be promoted into a clearly work-owned `Knowledge` authority, or remain mixed?
- Should `Contracts` and `Work Email` be treated as `OpenBrand`, or as work-only but organization-neutral domains?

### Bot vs Domain Questions

- Should `Evergreen Ops` exist as one supervisor bot above `Castle`, `Diamond Roc`, `Cloudagent`, and related services?
- Should `Research Analyst` be one bot with multiple workspaces, or several narrower bots (`Market`, `Platinum`, `Surveyor`)?
- Should `Observability` be one roll-up bot, or should Glimpser/Autocamera/Networking remain independent bots feeding a shared inbox?

### Digital Twin Questions

- What is the canonical graph root: `realm -> site -> asset -> service -> session`, or `realm -> worker -> service -> session` with sites as a separate axis?
- How should people fit into the twin: as `person` objects linked to channels, households, schedules, and approvals?
- How much of the twin should be hand-authored versus discovered from tmux, connectors, devices, and passive sensors?

### Safety and Policy Questions

- Which domains are permanently `read_only` (`Health`, `Finance`)?
- Which domains are `draft_first` (`Communications`, `Scheduling`)?
- Which systems are allowed `auto` behavior, and where should `manual` remain the default?
- How should `攸好德` (`Virtue`) show up in policy: simple modes, or a richer approval/risk system?

### Runtime Questions

- Which things should run on `hal` indefinitely because they are physically tied there (`Autocamera`, `Theseus`, local sensing)?
- Which work services should become remotely managed worker services first (`Earlybird`)?
- When should Norman split into `norman-core` and remote worker runtimes?

### Knowledge and Continuity Questions

- Where should session summaries, handoffs, and state snapshots live so they are durable and queryable?
- Should `Archivist` automatically summarize every significant session into the knowledge layer?
- What is the canonical handoff format for bots, services, and sites?

## Immediate App Implications

If Norman is going to manage the estate cleanly, the app needs first-class support for:

1. `realm`
2. `worker`
3. `bot`
4. `service`
5. `asset`
6. `site`
7. `policy_profile`
8. `digital_twin_link`
9. `wufu_axis`
10. `kaizen_candidate`

The implementation order should be:

1. add the schema primitives
2. seed the current estate matrix
3. make sessions attach to bots and services rather than pretending they are the same thing
4. build the digital twin view
5. build the operator inbox over the twin and policy model

The concrete object definitions for that next step live in
[`docs/estate_schema.md`](estate_schema.md).
