# Norman Hierarchy

This document makes the Norman role split explicit so the system has one clear
operator model instead of several overlapping internal names.

## Core Rule

`Norman` is the public-facing operator identity.

When someone says "Norman" without qualification, it should mean the office,
desk, and communication surface people talk to, not an arbitrary worker,
service, or specialist bot.

## Roles

| Role | Audience | Job | Should Not Be |
|---|---|---|---|
| `Norman` | people and operator | public-facing desk and entry point | just another specialist bot |
| `Prime` | human operator | core desk between Operator and Norman | public-facing brand for every sub-role |
| `Switchboard` | Prime and Norman | communication fusion across apps, people, threads, promises, and reminders | raw bot backchannel |
| `Subprime` | bots and operator | bot-to-bot escalation, routing, unblock, handoff | human relationship manager |
| `Specialist Bots` | Prime/Switchboard/Subprime | domain execution and deep context | main operator hub |
| `Channel / Connector Layer` | system | Slack, Gmail, SMS, Signal, Jira, calendar, other app paths | user-facing coordinator |

## Intended Flow

1. People talk to `Norman`.
2. Inside the system, `Prime` is the main desk between Operator and Norman.
3. Let `Prime` decide whether the next step is:
   - direct answer
   - draft/help for a human conversation
   - specialist bot handoff
   - `Subprime` escalation
   - `Switchboard` context pull
4. Use `Switchboard` when the task is mostly human communication:
   - preparing for a call
   - drafting a note
   - following up
   - reminding you what you owe someone
   - keeping relationships warm
5. Use `Subprime` when the task is mostly fleet coordination:
   - another bot is blocked
   - access or routing is broken
   - a service is down
   - context must move between bots or hosts

## Norman

`Norman` is the thing people should know and remember.

It is the public-facing office:

- the one name
- the one desk
- the one place to start

The outside world should not need to memorize the internal layers.

## Prime

`Prime` is the core desk between Operator and Norman.

Its job is to:

- give you one screen instead of many apps
- understand the current task, person, and obligation
- route work to the right bot, lane, or channel
- keep top-level context coherent
- stay calm, concise, and useful

Prime is the internal main desk, not the public brand for every function.

## Switchboard

`Switchboard` is the full-spectrum communication fusion layer under Prime.

Its job is to:

- pull together messages, threads, people, reminders, and promises
- preserve source and lane without forcing app-switching
- help draft, follow up, and prepare
- keep relationship context available without breaking the conversation
- let Prime work from one fused communication surface

Switchboard is the communications fabric. It is not the bot escalation lane.

## Subprime

`Subprime` is the machine-facing backchannel under Prime.

Its job is to:

- receive bot handoffs
- diagnose blockers
- route work to the right peer or host
- produce concise escalation packets
- keep the fleet moving without dragging the human into every small issue

Subprime is the bot backchannel:

- machine-facing
- routing-heavy
- concise
- escalation-oriented

## Specialist Bots

Specialist bots own their domains:

- work systems
- personal systems
- infra
- labs
- devices
- private enclave lanes

They should not compete with Prime for the role of main desk.

## Naming Guidance

Use these names consistently:

- `Norman`: public-facing office and main name
- `Prime`: internal main desk
- `Switchboard`: communication fusion and follow-through layer
- `Subprime`: bot-facing escalation and broker lane

Avoid vague uses of `Prime` without context when a bot needs a specific target.

## Product Implication

The UI should reflect the hierarchy:

- one obvious `Norman` entry for people
- one clear `Prime`/main-desk concept for the operator
- one clear `Switchboard` lane for communication support
- one clear `Subprime` lane for the fleet
- specialists grouped underneath, not competing at the top level

## Operating Implication

If a bot raises an issue:

- try the local fix if it is obvious
- otherwise escalate to `Subprime`
- only escalate to `Prime` when human judgment, approval, or operator
  context is actually needed

If you need to talk to a person better:

- start with `Norman`
- let `Prime` and `Switchboard` gather the relevant context, draft the
  message, and
  keep the reminder/follow-up loop alive

## Transition Note

The currently live bot broker is still named `Norman Bot Prime` in a few runtime
artifacts. Conceptually, that role maps to `Subprime`.
