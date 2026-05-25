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
| `*.work.example.test` | Work-facing bots and work apps | Yes | Best place for human-facing OpenBrand work surfaces |
| `*.home.arpa` | LAN-local bots, infra, private, and household surfaces | Yes for non-work browser entry points | Preferred local browser namespace now that `.internal` is causing client/browser friction |
| `*.knox.example.test` | Main-house or Knox-site family-facing services | Yes | Best for the current primary house/site |
| `*.beach.example.test` | Beach-house family-facing services | Yes | Site-based naming for the beach location |
| `*.halsted.example.test` | Halsted-site family-facing services | Yes | Use for services primarily tied to that site |
| `*.argyle.example.test` | Argyle-site family-facing services | Yes | Use for services primarily tied to that site |
| `*.home.example.test` | Family umbrella, shared landing pages, cross-site home entry | Yes, but only for umbrella/shared surfaces | Avoid using it as the canonical home for site-specific apps |
| `*.kris.example.test` | Operator personal surfaces not tied to one site | Yes | Personal identity-owned services, not household-wide services |
| `*.home.arpa` | LAN-local browser names | Yes for non-work local surfaces | Use for local-only naming, private surfaces, and house/shared bots |
| `*.local` | Legacy SMB / Bonjour / mDNS space | No | Avoid as canonical DNS because it conflicts with mDNS and platform discovery rules |
| `*.test` | Temporary experiments | No | Never use as the main operator fleet namespace |
| `*.invalid` | Explicit non-resolution / placeholders | No | Good for sentinels and docs only |
| `*.example` | Documentation and examples | No | Never for live services |

## Audience Rule

| Audience | Canonical namespace |
| --- | --- |
| OpenBrand work users | `*.work.example.test` |
| Infra / admin / control plane | `*.home.arpa` |
| Confidential / private bots | `*.home.arpa` |
| Household or family users at a specific site | `*.<site>.example.test` |
| Family/shared umbrella services spanning sites | `*.home.example.test` |
| Operator personal surfaces spanning sites | `*.kris.example.test` |

## Site Rule

Use site-specific `example.test` subdomains when a service belongs to a place.

Current site roots:

- `knox.example.test`
- `beach.example.test`
- `halsted.example.test`
- `argyle.example.test`

That means:

- `glimpser.knox.example.test`
- `autocamera.knox.example.test`
- `camera.halsted.example.test`
- `relay.beach.example.test`

This is better than forcing everything into `home.example.test`.

## Personal vs Shared on `example.test`

### `home.example.test`

Use for:

- shared family landing pages
- cross-site household directories
- family-wide dashboards
- umbrella home portals

Avoid using it as the canonical home for a service that is clearly tied to one site.

### `kris.example.test`

Use for:

- Operator personal tools
- operator-facing personal surfaces
- personal labs that are not really “the household”
- personal bookmarks or dashboards spanning sites

Examples:

- `notes.kris.example.test`
- `lab.kris.example.test`
- `operator.kris.example.test`

### `<site>.example.test`

Use for:

- site-bound cameras
- site-bound dashboards
- site-specific home assistants
- physical appliances and sensors

Examples:

- `glimpser.knox.example.test`
- `housebot.knox.example.test`
- `autocamera.knox.example.test`
- `relay.halsted.example.test`
- `weather.beach.example.test`

## Canonicalization Rule

Prefer browser-safe names as the real entry points.

Good examples:

- `mls.home.arpa` -> `mls.work.example.test`
- `scout.home.arpa` -> `scout.work.example.test`
- `control.home.arpa` -> `cp.work.example.test`

Do not treat `.internal` as the intended browser namespace for the fleet. If it exists at all, it should be treated as a legacy or operator-only alias, not the name Prime and Directory prefer.

## Proposed Canonical Table

| Thing | Kind | Canonical | Alias / redirect candidates |
| --- | --- | --- | --- |
| Norman Prime | control plane | `norman.home.arpa` | `bots.home.arpa`, `norman.tail00000.ts.net` |
| Norman bot proxy | control plane | `norman.home.arpa/bot/*` | `bots.home.arpa/*` |
| MLS | work bot | `mls.work.example.test` | `mls.home.arpa`, `mlsbot.home.arpa` |
| Scout | work bot | `scout.work.example.test` | `scout.home.arpa`, `scoutbot.home.arpa` |
| Keystone / Compere | work bot | `keystone.work.example.test` | `keystone.home.arpa`, `compere.home.arpa` |
| Infra | work bot | `infra.work.example.test` | `infra.home.arpa` |
| Leadership KPIs | work bot | `kpis.work.example.test` | `leadership.work.example.test`, `leadership.home.arpa`, `kpis.home.arpa` |
| Control Plane | work bot | `cp.work.example.test` | `control.home.arpa`, `cp.home.arpa` |
| Earlybird | work bot | `earlybird.work.example.test` | `earlybird.home.arpa` |
| MC / Monte Carlo | work bot | `mc.work.example.test` | `market.work.example.test`, `mc.home.arpa`, `market.home.arpa` |
| TMI Dashboards | work bot | `dashboards.work.example.test` | `tmi.work.example.test`, `tmi.home.arpa` |
| Gold Book | work bot | `goldbook.work.example.test` | `goldbook.home.arpa` |
| Panelbot | work bot | `panelbot.work.example.test` | `panelbot.home.arpa` |
| Housebot | home bot | `housebot.home.arpa` | `house.home.arpa`, `housebot.knox.example.test` |
| Artmonster | personal-account creative bot | `artmonster.home.arpa` | Controls cloud-hosted Artbot services; Artbot remains the service/application name |
| Phone Ops | home bot | `phone.home.arpa` | `phoneops.home.arpa` |
| DJ Station | home media bot | `dj.home.arpa` | `yt.home.arpa` |
| TV | retired home media bot | `tv.home.arpa` | Archived; do not promote unless re-owned and rebuilt |
| Studio | retired home media bot | `studio.home.arpa` | Archived; `camera-studio.home.arpa` was the legacy alias |
| Null Agent | Yhix game/TUI bot | TBD on Yhix cloud | Started as a game project; should publish only after the Yhix cloud runtime and TUI route exist |
| Glimpser app | home app | `glimpser.home.arpa` | `glimpser.knox.example.test` |
| Glimpser bot | home bot | `eyebat.home.arpa` | `eyeball.home.arpa` |
| Autocamera app | home app | `autocamera.home.arpa` | `autocamera.knox.example.test` |
| Theseus | home/shared bot | `theseus.home.arpa` | `theseus.knox.example.test` |
| Networking | infra bot | `networking.home.arpa` | `networking-host.home.arpa` |
| Grayhat | cyber operator | `grayhat.home.arpa` | Proposed child lane behind Networking; replaces the unfinished Logs lane when built |
| Uplink | infra bot | `uplink.home.arpa` | `phobos.home.arpa` |
| CloudAgent | infra bot | `cloudagent.home.arpa` | `cloud.home.arpa` |
| PEFB / PEF | private bot | `pefb.home.arpa` | `pef.home.arpa`, `parkergale.home.arpa` |
| Health Reader | private bot | `health.home.arpa` | `healthbot.home.arpa` |
| Finance Reader | private bot | `finance.home.arpa` | `financebot.home.arpa` |

## Transition Rule

Do not rename the fleet in one shot.

Use this order:

1. define canonical names
2. publish aliases
3. make aliases redirect to canonical names
4. update Prime and Directory to prefer canonical names
5. retire legacy `.internal` browser names where they no longer fit

## Operational Notes

- `*.home.arpa` will usually need local CA trust for clean HTTPS.
- `glimpser.home.arpa` is the Glimpser app/service name. Do not reuse `glimpse.home.arpa` for the bot surface.
- `artmonster.home.arpa` is the Artmonster bot/session name. It should resolve to Norman's front door once DOHIO/split DNS is updated.
- Artmonster currently uses a personal OpenAI account even though it controls cloud-hosted Artbot services. A dedicated evergreen OpenAI account is a possible future migration, not current state.
- `acast` is retired from the active bot fleet. Do not recreate it unless a new owner and repo scope are named.
- `tv` and `studio` are archived home media lanes. Keep existing compatibility routes harmless, but exclude them from active fleet promotion.
- `null-agent` belongs to the Yhix bot class, not the household/work/shared bot lanes. It should run as a TUI on Yhix cloud once the runtime exists.
- `MC` is the preferred label for the former Market Sizing lane. Use it for Monte Carlo, survey, demographic, and market-modeling work.
- `*.work.example.test` is the best place for work bots if clean public-trust certificates matter.
- Site-based `example.test` names should map to physical place or household context, not arbitrary service buckets.
- `home.example.test` should stay the umbrella, not the dumping ground.
- `kris.example.test` should be the personal operator namespace, not the family/shared namespace.
- Avoid making `.local` the canonical naming scheme for SAN or bot surfaces. It is better to keep:
  - work storage on names like `work.home.arpa`
  - personal/backup storage on names like `backup.home.arpa`
  - and optionally preserve user-friendly SMB share labels like `\\WORK` and `\\BACKUP`
- If the current habits are `\\work.local` and `\\backup.local`, treat those as migration aliases, not the long-term namespace.
