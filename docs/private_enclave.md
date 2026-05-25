# Private Enclave Plan

`Private` should be a dedicated Norman enclave for confidential bots such as
health, finance, and PEF (ParkerGale / PEFB). It should not be another bot group on
`toy-box`, and it should not share runtime state with the ordinary Personal,
Work, or Shared fleet.

## Goal

Give Norman Prime one protected lane for sensitive work while keeping the
actual bots isolated from each other and from the rest of the fleet.

The intended operator model is:

- talk to `Norman Prime` by default
- let Prime surface private work as summary/status only
- enter `Private` bots deliberately when detail is needed

## Host Model

Use one dedicated worker/host:

- worker slug: `private-host`
- DNS root: `private.home.example.test`
- host purpose: confidential bot enclave only

Current live baseline:

- Proxmox LXC CT `148`
- hostname: `private`
- LAN IP: `192.168.0.148`
- current role: enclave host shell only; the private bots are not published yet

Planned service names:

- `health.private.home.example.test`
- `finance.private.home.example.test`
- `parkergale.private.home.example.test`
  PEF can keep the ParkerGale hostname for compatibility even if the bot-facing name changes.

Optional root/admin entry:

- `private.home.example.test`

If the private host later needs multiple trust zones, that can happen inside
the host boundary. The first rollout should keep the model simple: one enclave
host, multiple isolated runtimes.

## Isolation Rules

Each private bot should have:

- its own Unix user or container
- its own `CODEX_HOME`
- its own tmux socket and systemd units
- its own browser/session profile
- its own Norman Keys aliases and approval path
- no shared auth bundle with any other bot

Bots in the private enclave should not casually inspect each other's homes,
checkouts, or secret material.

## Norman Prime Behavior

Norman Prime should treat `Private` as summary-first:

- default to status and task-card summaries
- do not spill raw finance or health details into ordinary chat
- require deliberate entry into a private bot or private task
- surface approval and secret needs automatically when private work is in play

Prime should still know:

- that the work exists
- whether it is blocked
- who owns it
- what the next step is
- whether approval or secret access is required

## Policy Defaults

Private bots should start with stricter defaults than the rest of the fleet:

- `read-only` by default for health and finance readers
- `manual` for any bot that might write, send, or take side effects
- explicit approval for outbound send, exports, or sensitive writes
- Norman Keys only for secrets

No new plaintext repo-local dotfiles should be introduced for private bots.

## Runtime Shape

Recommended rollout pattern per bot:

1. create isolated runtime account and workspace
2. create bot-specific prompt and env file
3. publish only after Norman Directory and Prime understand the route
4. keep the bot hidden from ordinary fleet navigation
5. surface it through the `Private` lane in Norman Prime

## First Rollout

First bots:

- `health-reader`
- `finance-reader`
- `parkergale`
  Bot-facing name: `PEF` / `Private Equity Funbot`; aliases ParkerGale and PEFB.

Recommended order:

1. stand up `health-reader` shell with no credentials yet
2. wire Norman Prime and Directory to show it under `Private`
3. add Norman Keys aliases for health access
4. only then connect MyChart or other real systems
5. repeat the pattern for finance and PEF

## Why Not Toy Box

`toy-box` is good for household and personal shared operators, but it is the
wrong place for private finance and health work because:

- it already hosts ordinary shared/personal bots
- it encourages shared runtime habits
- it increases accidental cross-bot visibility
- it blurs the trust boundary

The private enclave should be intentionally boring, isolated, and auditable.
