# Naming Policy

Canonical naming policy for Norman, the bot fleet, and the supporting app and service surfaces.

This is the operator-review version. It is meant to make the namespace reflect audience, trust boundary, and physical site.

## Core Rule

Every surface gets:

1. one canonical hostname
2. zero or more short aliases
3. redirects from aliases to the canonical name when appropriate

The canonical name should match the real audience and trust boundary.

## Suffix Policy

| Namespace | Use | Canonical? | Notes |
| --- | --- | --- | --- |
| `*.[REDACTED_NAME].openbrand.com` | Work-facing bots and work apps | Yes | Best place for human-facing OpenBrand work surfaces |
| `*.[INTERNAL_DOMAIN]` | LAN-local bots, infra, private, and household surfaces | Yes for non-work browser entry points | Preferred local browser namespace now that `.internal` is causing client/browser friction |
| `*.knox.lollie.org` | Main-house or Knox-site family-facing services | Yes | Best for the current primary house/site |
| `*.beach.lollie.org` | Beach-house family-facing services | Yes | Site-based naming for the beach location |
| `*.halsted.lollie.org` | Halsted-site family-facing services | Yes | Use for services primarily tied to that site |
| `*.argyle.lollie.org` | Argyle-site family-facing services | Yes | Use for services primarily tied to that site |
| `*.home.lollie.org` | Family umbrella, shared landing pages, cross-site home entry | Yes, but only for umbrella/shared surfaces | Avoid using it as the canonical home for site-specific apps |
| `*.[REDACTED_NAME].lollie.org` | [REDACTED_NAME] personal surfaces not tied to one site | Yes | Personal identity-owned services, not household-wide services |
| `*.[INTERNAL_DOMAIN]` | LAN-local browser names | Yes for non-work local surfaces | Use for local-only naming, private surfaces, and house/shared bots |
| `*.local` | Legacy SMB / Bonjour / mDNS space | No | Avoid as canonical DNS because it conflicts with mDNS and platform discovery rules |
| `*.test` | Temporary experiments | No | Never use as the main operator fleet namespace |
| `*.invalid` | Explicit non-resolution / placeholders | No | Good for sentinels and docs only |
| `*.example` | Documentation and examples | No | Never for live services |

## Audience Rule

| Audience | Canonical namespace |
| --- | --- |
| OpenBrand work users | `*.[REDACTED_NAME].openbrand.com` |
| Infra / admin / control plane | `*.[INTERNAL_DOMAIN]` |
| Confidential / private bots | `*.[INTERNAL_DOMAIN]` |
| Household or family users at a specific site | `*.<site>.lollie.org` |
| Family/shared umbrella services spanning sites | `*.home.lollie.org` |
| [REDACTED_NAME] personal surfaces spanning sites | `*.[REDACTED_NAME].lollie.org` |

## Site Rule

Use site-specific `lollie.org` subdomains when a service belongs to a place.

Current site roots:

- `knox.lollie.org`
- `beach.lollie.org`
- `halsted.lollie.org`
- `argyle.lollie.org`
- `kostner.lollie.org`
- `farm.lollie.org`
- `evergreen.lollie.org`

That means:

- `glimpser.knox.lollie.org`
- `autocamera.knox.lollie.org`
- `llm.knox.lollie.org`
- `camera.halsted.lollie.org`
- `relay.beach.lollie.org`

This is better than forcing everything into `home.lollie.org`.

When a service exists at multiple sites, use `*.[INTERNAL_DOMAIN]` as the local
operator/API identity unless the service explicitly needs a public-site
canonical. Example:

- on Knox LAN: `hubitat.[INTERNAL_DOMAIN]` -> `hubitat.knox.lollie.org`
- on Beach LAN: `hubitat.[INTERNAL_DOMAIN]` -> `hubitat.beach.lollie.org`
- on Knox LAN: `llm.[INTERNAL_DOMAIN]` -> Norllama front door with worker failover

That keeps `[INTERNAL_DOMAIN]` contextual and local. The `*.<site>.lollie.org`
origin remains useful for road access and public naming, but it is not always
the primary browser/API identity.

For road access to private services, prefer split DNS over teaching every client
LAN routes:

- site DNS / pfSense: `service.<site>.lollie.org -> site LAN front door`
- public DNS: `service.<site>.lollie.org -> Tailscale IP for the same front door`

This lets phones on 5G use the same canonical hostname while still requiring the
tailnet. Use subnet routes as a fallback when a service cannot bind directly on
a Tailscale-reachable front door.

## Personal vs Shared on `lollie.org`

### `home.lollie.org`

Use for:

- shared family landing pages
- cross-site household directories
- family-wide dashboards
- umbrella home portals

Avoid using it as the canonical home for a service that is clearly tied to one site.

### `[REDACTED_NAME].lollie.org`

Use for:

- [REDACTED_NAME] personal tools
- operator-facing personal surfaces
- personal labs that are not really “the household”
- personal bookmarks or dashboards spanning sites

Examples:

- `notes.[REDACTED_NAME].lollie.org`
- `lab.[REDACTED_NAME].lollie.org`
- `operator.[REDACTED_NAME].lollie.org`

### `<site>.lollie.org`

Use for:

- site-bound cameras
- site-bound dashboards
- site-specific home assistants
- physical appliances and sensors

Examples:

- `glimpser.knox.lollie.org`
- `housebot.knox.lollie.org`
- `autocamera.knox.lollie.org`
- `relay.halsted.lollie.org`
- `weather.beach.lollie.org`

## Canonicalization Rule

Prefer browser-safe names as the real entry points.

Good examples:

- `mls.[INTERNAL_DOMAIN]` -> `mls.[REDACTED_NAME].openbrand.com`
- `scout.[INTERNAL_DOMAIN]` -> `scout.[REDACTED_NAME].openbrand.com`
- `control.[INTERNAL_DOMAIN]` -> `cp.[REDACTED_NAME].openbrand.com`
- `keystone.[REDACTED_NAME].lollie.org` -> `keystone.[REDACTED_NAME].openbrand.com`

For work bots, operator shortcut aliases may also live under `*.[REDACTED_NAME].lollie.org`,
but they should still redirect to the `*.[REDACTED_NAME].openbrand.com` canonical host.

Do not treat `.internal` as the intended browser namespace for the fleet. If it exists at all, it should be treated as a legacy or operator-only alias, not the name Prime and Directory prefer.

## Proposed Canonical Table

| Thing | Kind | Canonical | Alias / redirect candidates |
| --- | --- | --- | --- |
| Norman Prime | control plane | `norman.[INTERNAL_DOMAIN]` | `bots.[INTERNAL_DOMAIN]`, `norman.tail94915.ts.net` |
| Norman bot proxy | control plane | `norman.[INTERNAL_DOMAIN]/bot/*` | `bots.[INTERNAL_DOMAIN]/*` |
| MLS | work bot | `mls.[REDACTED_NAME].openbrand.com` | `mls.[INTERNAL_DOMAIN]`, `mlsbot.[INTERNAL_DOMAIN]` |
| Scout | work bot | `scout.[REDACTED_NAME].openbrand.com` | `scout.[INTERNAL_DOMAIN]`, `scoutbot.[INTERNAL_DOMAIN]` |
| Keystone / Compere | work bot | `keystone.[REDACTED_NAME].openbrand.com` | `keystone.[INTERNAL_DOMAIN]`, `compere.[INTERNAL_DOMAIN]` |
| Infra | work bot | `infra.[REDACTED_NAME].openbrand.com` | `infra.[INTERNAL_DOMAIN]` |
| Leadership KPIs | work bot | `kpis.[REDACTED_NAME].openbrand.com` | `leadership.[REDACTED_NAME].openbrand.com`, `leadership.[INTERNAL_DOMAIN]`, `kpis.[INTERNAL_DOMAIN]` |
| Control Plane | work bot | `cp.[REDACTED_NAME].openbrand.com` | `control.[INTERNAL_DOMAIN]`, `cp.[INTERNAL_DOMAIN]` |
| Earlybird | work bot | `earlybird.[REDACTED_NAME].openbrand.com` | `earlybird.[INTERNAL_DOMAIN]` |
| Market Sizing | work bot | `market.[REDACTED_NAME].openbrand.com` | `market.[INTERNAL_DOMAIN]` |
| TMI Dashboards | work bot | `dashboards.[REDACTED_NAME].openbrand.com` | `tmi.[REDACTED_NAME].openbrand.com`, `tmi.[INTERNAL_DOMAIN]` |
| Gold Book | work bot | `goldbook.[REDACTED_NAME].openbrand.com` | `goldbook.[INTERNAL_DOMAIN]` |
| Panelbot | work bot | `panelbot.[REDACTED_NAME].openbrand.com` | `panelbot.[INTERNAL_DOMAIN]` |
| Housebot | home bot | `housebot.[INTERNAL_DOMAIN]` | `house.[INTERNAL_DOMAIN]`, `housebot.knox.lollie.org` |
| DJ Station | home media bot | `dj.[INTERNAL_DOMAIN]` | `yt.[INTERNAL_DOMAIN]` |
| TV | home media bot | `tv.[INTERNAL_DOMAIN]` | |
| Studio | home media bot | `studio.[INTERNAL_DOMAIN]` | `camera-studio.[INTERNAL_DOMAIN]` |
| Glimpser app | home app | `glimpser.[INTERNAL_DOMAIN]` | `glimpser.knox.lollie.org` |
| Eyebat / Glimpser bot | home bot | `eyebat.[INTERNAL_DOMAIN]` | manages the Glimpser code/operator session |
| Autocamera app | home app | `autocamera.[INTERNAL_DOMAIN]` | `autocamera.knox.lollie.org` |
| Theseus | home/shared bot | `theseus.[INTERNAL_DOMAIN]` | `theseus.knox.lollie.org` |
| Local LLM | site-local infra | `llm.[INTERNAL_DOMAIN]` | `llm.knox.lollie.org` |
| Networking | infra bot | `networking.[INTERNAL_DOMAIN]` | `networking-host.[INTERNAL_DOMAIN]` |
| Uplink | infra bot | `uplink.[INTERNAL_DOMAIN]` | `phobos.[INTERNAL_DOMAIN]` |
| CloudAgent | infra bot | `cloudagent.[INTERNAL_DOMAIN]` | `cloud.[INTERNAL_DOMAIN]` |
| PEFB / PEF | private bot | `pefb.[INTERNAL_DOMAIN]` | `pef.[INTERNAL_DOMAIN]`, `parkergale.[INTERNAL_DOMAIN]` |
| Health Reader | private bot | `health.[INTERNAL_DOMAIN]` | `healthbot.[INTERNAL_DOMAIN]` |
| Finance Reader | private bot | `finance.[INTERNAL_DOMAIN]` | `financebot.[INTERNAL_DOMAIN]` |

## Transition Rule

Do not rename the fleet in one shot.

Use this order:

1. define canonical names
2. publish aliases
3. make aliases redirect to canonical names
4. update Prime and Directory to prefer canonical names
5. retire legacy `.internal` browser names where they no longer fit

## Operational Notes

- `*.[INTERNAL_DOMAIN]` will usually need local CA trust for clean HTTPS.
- `*.[INTERNAL_DOMAIN]` should be treated as a local shortcut layer, not the durable
  canonical identity for multi-site services.
- `*.[REDACTED_NAME].openbrand.com` is the best place for work bots if clean public-trust certificates matter.
- Site-based `lollie.org` names should map to physical place or household context, not arbitrary service buckets.
- `home.lollie.org` should stay the umbrella, not the dumping ground.
- `[REDACTED_NAME].lollie.org` should be the personal operator namespace, not the family/shared namespace.
- Avoid making `.local` the canonical naming scheme for SAN or bot surfaces. It is better to keep:
  - work storage on names like `work.[INTERNAL_DOMAIN]`
  - personal/backup storage on names like `backup.[INTERNAL_DOMAIN]`
  - and optionally preserve user-friendly SMB share labels like `\\WORK` and `\\BACKUP`
- If the current habits are `\\work.local` and `\\backup.local`, treat those as migration aliases, not the long-term namespace.
