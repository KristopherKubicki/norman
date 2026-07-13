# Bot-to-Bot ACL

Bot-to-bot communication policy for the Norman fleet.

This is the operator-review version. The main goal is to prevent casual lateral movement while still allowing the few peer relationships that are operationally necessary.

## Default Rule

Default posture:

- bot-to-bot communication is **deny by default**
- Norman Prime is the **default broker**
- cross-bot handoff should be **structured and auditable**

In plain terms:

- if a bot lacks another bot's context, it should ask Norman Prime / the Norman session to coordinate the handoff
- it should not directly rummage through another bot's lane, workspace, or auth state unless it is in an explicitly allowed peer cluster

## Communication Levels

| Level | Meaning | Allowed payload |
| --- | --- | --- |
| `forbidden` | No direct cross-bot communication | None |
| `brokered-summary` | Norman Prime may relay summary-only context | Status, conclusions, next steps, non-sensitive findings |
| `brokered-raw` | Norman Prime may relay raw artifacts only after explicit approval | Logs, transcripts, files, screenshots, structured raw findings |
| `direct-structured` | Bots may directly exchange bounded operational handoffs | Status, task brief, findings, next action, non-secret artifacts |
| `direct-peer-ops` | Narrow operational peers may coordinate directly | Structured handoff plus bounded action requests inside the same trust lane |

## Global Rules

1. No bot should read another bot's auth bundle, secret store, or `CODEX_HOME`.
2. No bot should issue arbitrary shell or host-control actions on another bot's machine.
3. Private-lane bots should not directly inspect work, personal, or shared bots unless explicitly approved.
4. Cross-lane movement should default to Norman-mediated summary.
5. Any raw artifact movement across lanes should be explicit, narrow, and ideally operator-approved.
6. Secret-bearing exchanges are not normal bot-to-bot traffic. Use Norman Keys or another brokered secret path.
7. If a product app and its operator bot are split across different hosts, bots should target the operator bot identity, not the app host, for cross-bot coordination.

## Split App / Bot Surfaces

Some services have a user-facing app on one host and a Codex operator console on another host.

Examples:

- `Glimpser` app on `.145`
- `Glimpser` bot console on `toy-box`

In those cases:

- the app host is a product surface
- the bot console is the coordination surface
- cross-bot work should be aimed at the bot console identity
- app scraping or HTTP inspection is a fallback, not the primary broker path

Norman should treat these as paired surfaces, not one ambiguous thing.

## Norman Prime

Norman Prime is the broker, coordinator, and policy-aware handoff surface.

Bots should assume:

- Norman Prime is always an allowed coordination target
- Norman Prime can request handoff material from other bots
- Norman Prime decides whether the receiving bot gets summary-only or raw source material

When uncertain, a bot should prefer:

1. ask Norman Prime for a handoff
2. state what scope it needs
3. wait for a brokered summary or approved artifact

## Cluster Policy

### Shared infra cluster

| Source | Target | Level | Notes |
| --- | --- | --- | --- |
| Networking | Uplink | `direct-peer-ops` | Shared infra / radio peers |
| Networking | CloudAgent | `direct-structured` | Infra coordination only |
| Uplink | Networking | `direct-peer-ops` | Shared infra / radio peers |
| Uplink | CloudAgent | `direct-structured` | Infra coordination only |
| CloudAgent | Networking | `direct-structured` | Infra coordination only |
| CloudAgent | Uplink | `direct-structured` | Infra coordination only |

Constraints:

- no secret-sharing by chat
- no blind host-control across peers
- use structured handoff over free-form transcript dumps

### Work cluster

| Source | Target | Level | Notes |
| --- | --- | --- | --- |
| Compere / Keystone | Scout | `brokered-summary` | Summary-first unless raw research is explicitly needed |
| Scout | Compere / Keystone | `direct-structured` | Scout findings can feed work memos and carve-out context |
| MLS | Compere / Keystone | `brokered-summary` | Different subject areas; only coordinate through Norman by default |
| Compere / Keystone | MLS | `brokered-summary` | Same |
| Work bot | Infra / Control Plane | `brokered-summary` | Infra should not be the first lateral target unless operationally necessary |

Default for work lane:

- structured collaboration is allowed
- but Norman Prime should still be the first broker unless the relationship is already normalized and low-risk

### Home / personal cluster

| Source | Target | Level | Notes |
| --- | --- | --- | --- |
| Glimpser | Housebot | `direct-structured` | Camera/observability status to home ops is fine |
| Autocamera | Housebot | `direct-structured` | Same |
| Housebot | Glimpser | `direct-structured` | Operational follow-up only |
| Housebot | Autocamera | `direct-structured` | Operational follow-up only |
| Castle / Theseus / USCache | Others | `brokered-summary` | No broad lateral assumptions by default |

### Private cluster

| Source | Target | Level | Notes |
| --- | --- | --- | --- |
| PEF | Norman Prime | `direct-structured` | Norman is the allowed broker |
| Health | Norman Prime | `direct-structured` | Norman is the allowed broker |
| Finance | Norman Prime | `direct-structured` | Norman is the allowed broker |
| PEF | work/shared/personal bots | `brokered-summary` by default | Raw movement requires explicit approval |
| Health | work/shared/personal bots | `forbidden` by default | Exception only with explicit operator approval |
| Finance | work/shared/personal bots | `forbidden` by default | Exception only with explicit operator approval |

Default private rule:

- private bots do not directly inspect other bots
- Norman Prime mediates
- raw detail crossing out of private requires deliberate approval

## Bot Guidance

Each bot should understand this behavioral rule:

- If you need another bot's context and do not already have an explicitly allowed peer relationship, ask Norman Prime / the Norman session to broker the handoff.

That means:

- do not guess that you can directly inspect another bot
- do not ask for raw secrets or auth state
- ask for the minimum scope you need:
  - summary
  - source transcript
  - file path
  - screenshot
  - specific memo

## Norman App Implications

The app should eventually expose:

- a bot-to-bot ACL table
- visible brokered handoff state
- summary-only versus raw-artifact handoff controls
- approval requirement when crossing into or out of `private`
- an audit trail for cross-bot requests

## Open Questions

1. Which work-lane pairs should be promoted from `brokered-summary` to `direct-structured`?
2. Should `Scout` be allowed to directly hand structured findings to more work bots, or always through Norman?
3. Should `Housebot` be the only direct home-ops broker for camera bots?
4. Should there be a machine-readable ACL source of truth in the estate model rather than only docs?
