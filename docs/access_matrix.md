# Access Matrix

Draft access-control and segmentation matrix for the Norman fleet. This is the operator-review version before hardening is handed to Networking and pfSense.

## Client Groups

| Client Group | Meaning | Current Signals | Intended Reach |
| --- | --- | --- | --- |
| `operator-core` | [REDACTED_NAME] on Hal | Trusted console client, localhost auth bridge | Full Norman, shared, personal, work, selected private |
| `operator-mobile` | Plasma phone | Trusted console client, localhost auth bridge | Norman, shared, personal, work summaries, selected private |
| `operator-desktop-secondary` | Lollie desktop | Trusted console client | Norman, shared, personal, limited private by policy |
| `norman-proxy` | Norman front door on `192.168.2.241` | Trusted console client | Front-door access to non-private bot surfaces |
| `untrusted-lan` | Other LAN clients | None | Norman front door only, no tokenless bot access |
| `tailnet-remote` | Tailnet-only clients | Not governed yet | Explicit per-host allowlist only |
| `work-clients` | OpenBrand work devices | Not modeled yet | Norman plus work lane, no private by default |

Current code-backed trusted clients:

- `192.168.2.137` Hal
- `192.168.2.140` Plasma phone
- `192.168.2.144` Lollie desktop
- `192.168.2.241` Norman front door

Browser-auth bridge is currently limited to:

- Hal
- Plasma phone

## Lane Policy

| Lane | Purpose | Default Policy | Prime Visibility | Direct Entry | Cross-Lane Rule |
| --- | --- | --- | --- | --- | --- |
| `shared` | House, transport, shared infra | `shared` or `manual` | Full | Yes | Broad summaries are fine |
| `personal` | Toys, side code, personal systems | `shared` | Full | Yes | No automatic reach into work/private |
| `work` | OpenBrand operational systems | `shared` or `draft-first` | Full | Yes | Isolated from personal/private secrets |
| `private` | Finance, health, confidential deal work | `read-only` or `manual` | Summary-first | Deliberate only | No automatic spill into other lanes |

## Hosts

| Host | Role | Primary Lanes | Should Be Reachable From | Should Not Be Reachable From | Notes |
| --- | --- | --- | --- | --- | --- |
| `norman-host` (`192.168.2.241`) | Prime, Directory, control plane, proxy | All lanes, summary-first | Trusted clients, work clients | Raw untrusted clients to bot leaves | Canonical entry point |
| `toy-box` (`192.168.2.146`) | Personal/shared bot host | Personal, shared | Trusted clients, Norman proxy | Private-only clients do not need direct reach | Housebot, DJ, TV, Studio, Glimpser, Castle, Phone Ops, USCache |
| `hal` (`192.168.2.137`) | Workstation and localhost auth bridge | Personal, shared infra | Operator-core | Broad LAN direct management | Physically tied services and browser auth pinhole |
| `[INTERNAL_HOST]` (`[INTERNAL_IP]`) | OpenBrand work bot host | Work | Work clients, trusted operators, Norman proxy | Personal/private-only clients by default | Preferred place for heavier work bots |
| `networking-host` (`192.168.2.242`) | Networking, radio, shared infra | Shared, manual | Trusted operators, Norman proxy | General LAN direct bot access | Sensitive infra/routing control |
| `private-host` (`192.168.2.148`) | Confidential enclave | Private | Selected client group, Norman summary plane | General LAN, tailnet, ordinary work/personal clients | Should be heavily segmented |
| `quaoar` | Beach edge node | Edge, radio | Networking/Uplink only | General fleet browsing | Former beach-office machine |
| `phobos` | Radio/edge execution node | Shared, radio | Networking/Uplink only | General fleet browsing | Remote comms execution node |
| `pluto` | Remote relay and hot spare | Shared, radio | Networking/Uplink only | General fleet browsing | Backup proxy and future remote radio site |

## Bot Placement

| Bot | Host | Lane | Default Access | Direct Client Reach | Notes |
| --- | --- | --- | --- | --- | --- |
| `Norman Prime` | `norman-host` | Control plane | Login required | All trusted clients | Main start page |
| `Housebot` | `toy-box` | Personal/shared | Trusted clients | Yes | Home ops |
| `DJ Station` | `toy-box` | Personal/media | Trusted clients | Yes | Music-first YT wrapper |
| `TV` | `toy-box` | Personal/media | Trusted clients | Yes | Lean-back fused media surface |
| `Studio` | `toy-box` | Personal/media | Trusted clients | Yes | Control-room layer for DJ/TV/Autocamera |
| `Glimpser` | App `.145`, console `toy-box` | Personal observability | Trusted clients | Yes | App and console are split |
| `Castle` | `toy-box` | Personal | Trusted clients | Yes | Personal ops |
| `Phone Ops` | `toy-box` | Personal/comms | Trusted clients | Yes | Lane may need another pass |
| `USCache` | `toy-box` | Personal/knowledge | Trusted clients | Yes | Archival helper |
| `Autocamera` | `hal` | Shared/manual | Trusted clients | Yes | Physically tied to Hal |
| `Theseus` | `hal` | Shared/manual | Trusted clients | Yes | Physically tied to Hal |
| `Earlybird` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `Infra` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `Control Plane` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `Market Sizing` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `TMI Dashboards` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `Gold Book` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `Keystone / Compere` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `Leadership KPIs` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `Panelbot` | `[INTERNAL_HOST]` | Work | Work + trusted clients | Yes | Work console |
| `Networking` | `networking-host` | Shared/manual | Trusted operators | Limited | Topology, pfSense, VLANs |
| `Uplink` | `networking-host` | Shared/manual | Trusted operators | Limited | Radio and remote-site comms |
| `CloudAgent` | `networking-host` | Shared | Trusted operators | Limited | Cloud/shared infra |
| `PEFB` | `private-host` | Private | Selected clients only | Deliberate only | Confidential deal work |
| `Health Reader` | `private-host` planned | Private | Selected clients only | Deliberate only | Read-only by default |
| `Finance Reader` | `private-host` planned | Private | Selected clients only | Deliberate only | Read-only by default |

## Split Surface Rule

Some services are intentionally split:

- a user-facing app lives on one host
- the operator bot console lives on another host

Current example:

- `Glimpser` app on `192.168.2.145`
- `Glimpser` bot console on `toy-box`

Policy:

- operator and cross-bot handoff should target the bot console identity
- app-host inspection is secondary and should be treated as product/app introspection, not the main coordination channel
- Norman should expose both surfaces clearly so bots do not confuse the app host with the bot host

## Network / pfSense Targets

| Surface | DNS / Hostname | Intended Exposure | Policy Direction |
| --- | --- | --- | --- |
| Norman front door | `norman.[INTERNAL_DOMAIN]` | Broad trusted LAN access | Allow trusted clients and normal operator VLANs |
| Shared/personal vanity hosts | `housebot.[INTERNAL_DOMAIN]`, `autocamera.[INTERNAL_DOMAIN]`, etc. | Trusted clients | Allow operator VLANs, block guest/IoT |
| Work vanity hosts | `cp.[REDACTED_NAME].openbrand.com`, `keystone.[REDACTED_NAME].openbrand.com`, `infra.[REDACTED_NAME].openbrand.com`, `kpis.[REDACTED_NAME].openbrand.com`, `dashboards.[REDACTED_NAME].openbrand.com`, etc. | Work clients + trusted operators | Allow work VLAN and operator-core |
| Networking / radio | `networking.[INTERNAL_DOMAIN]`, `uplink.[INTERNAL_DOMAIN]` | Trusted operators only | Explicit allowlist, no broad LAN |
| Private root | `private.home.lollie.org` | Selected group only | Explicit allowlist only |
| Private bots | `pefb.[INTERNAL_DOMAIN]`, `pef.[INTERNAL_DOMAIN]`, `health.[INTERNAL_DOMAIN]`, `finance.[INTERNAL_DOMAIN]` | Selected group only | Explicit allowlist only, no broad tailnet/LAN |
| SAN / Synology / NAS | Not modeled yet | Infra-only | Networking, backups, selected operator clients only |

## Private and SAN Boundary Rules

| Resource | Allowed | Forbidden |
| --- | --- | --- |
| `private-host` | Hal, Plasma, Lollie desktop, Norman summary plane | Ordinary LAN clients, broad work clients, unrestricted tailnet |
| Private bot auth bundles | Local bot runtime only | Norman shared auth, toy-box, [INTERNAL_HOST], Hal shared homes |
| SAN / Synology admin surfaces | Networking, Housebot backups, selected operator clients | Ordinary bots by default |
| Infra secrets like `networking/synology`, `networking/prox_root` | Norman Keys / brokered access | Repo-local plaintext or broad bot access |

## What Prime Should See

| Lane | Prime Visibility |
| --- | --- |
| `shared` | Full status, tasks, incidents |
| `personal` | Full status, tasks, incidents |
| `work` | Full status, tasks, incidents |
| `private` | Existence, owner, blocked state, next step, approval/secret need; not raw details |

## Bot-to-Bot Policy

Default cross-bot rule:

- deny direct lateral movement by default
- use Norman Prime as the broker unless a peer relationship is explicitly allowed

See [Bot-to-Bot ACL](bot_acl.md) for the detailed matrix.

## Current Gaps

1. Trusted client groups only live in config, not in a durable governance document.
2. pfSense and VLAN policy targets are still mostly conversational, not codified.
3. SAN / Synology is represented as secrets, not as a governed service/asset.
4. Private-host segmentation is not yet written as exact source VLAN/client rules.
5. Work vs personal client boundaries are not modeled concretely.
6. `parkergale` / `PEF` still has a few older `work` assumptions elsewhere in the UI/style layer.
7. Radio/edge access for `phobos`, `pluto`, and `quaoar` needs a formal reachability matrix.
8. Tailnet policy is still implicit.
9. Backup and restore rights are not yet documented as part of access control.
10. Bot-to-bot ACLs are only beginning to be documented; the Norman app does not enforce them yet.
