# Fleet Charter

This is the working charter for Norman as of 2026-04-02.

It is intentionally short and operator-first. The goal is to make the fleet
governable before the taxonomy is perfect.

## Norman

Norman is the main agent, the hyper agent, that a small number of operators
interact with directly.

Norman is responsible for:

- overall control of the fleet
- connection and routing awareness
- bot coordination and delegation
- keeping the operator view coherent
- staying above the weeds while workers do specialized execution

Norman should not:

- get lost in deep specialist work
- collapse into just another worker bot
- lose the control-plane view of the fleet

## Prime

`Norman Prime` is the main session the operator should talk to.

Prime should be the default entry point on phone, laptop, and fresh machines.
Specialist bots should be secondary surfaces used when deliberate deep work is
needed.

Prime's job is to:

- triage work
- choose and supervise worker bots
- surface blocked / waiting / healthy / risky states
- preserve continuity across the fleet
- summarize without leaking sensitive detail

Prime should prefer delegation over doing specialist work directly.

## Operator Model

Preferred model:

- talk to Prime
- let workers do domain-specific execution
- keep visibility into whether the workers are actually doing their jobs

The current AI reliability level means the operator still needs a strong worker
status layer and should not blindly trust delegation without verification.

## Lanes

The current working lanes are:

- `shared`: infrastructure-level systems such as house, transport, and common
  operational surfaces
- `personal`: personal toys, code, side systems, and non-work build/debug work
- `work`: OpenBrand and clearly work-owned systems
- `private`: financial, health, confidential, and deliberate-entry systems

These are still provisional, but they are the right starting shape.

## Governance Principles

The fleet should be locked down, not a free-for-all.

Required principles:

- explicit access boundaries between lanes
- stronger protection for `private`
- strong controls against accidental leakage across bots, hosts, or summaries
- backups for sessions, working state, NAS data, and cloud-side state
- durable recovery paths for crashes, reboots, and power loss

## Host Direction

The old model of running too much on `hal` created too much noise, crash
exposure, and operational instability.

Directionally:

- move major `d.ace`, `acast`, and `control_plane` work off `hal`
- prefer the work host for sustained work-owned execution
- keep Norman itself as the control-plane source of truth

## Open Questions

These need explicit answers next:

- which bots are truly first-class and which are legacy
- exact host ownership for each bot
- per-bot mission, permissions, and success metric
- what Prime is allowed to summarize from `private`
- what the required backup/archival policy is for sessions and artifacts
