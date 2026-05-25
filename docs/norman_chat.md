# Norman Chat

`Norman Chat` is the product expression of the original Norman goal:

one screen where Operator can keep up with people, obligations, and
conversations without living inside a thousand different apps.

## What It Is

`Norman Chat` is not just another bot console.

It is the front-of-house communication surface that should unify:

- inbound messages
- outbound drafts
- reminders
- follow-ups
- pre-call briefs
- human context
- bot coordination when deeper context is needed

The feeling should be:

- effortless
- relationship-aware
- draft-first
- calm
- proactive without being naggy

## Primary Goal

Give Operator one communication desk that can:

- help him respond
- help him remember
- help him prepare
- help him follow through
- help him stay warm and human
- hide most of the app-switching and fleet complexity underneath

## Role Split

`Norman Chat` depends on the hierarchy:

- `Norman` is the visible public-facing desk
- `Prime` is the core desk between Operator and Norman
- `Switchboard` is the communications fusion layer under Prime
- `Subprime` coordinates the fleet behind the scenes
- specialist bots supply domain context when needed
- connectors bring in Slack, Gmail, SMS, Signal, Jira, calendar, and other
  systems

## What Norman Chat Should Do

### Unified Communication Desk

Show the important threads, people, promises, and drafts in one place.

The user should not need to remember:

- which app a thread lives in
- which bot owns the context
- which service has the detail

Norman should know that and surface the right next move.

### Relationship Support

For a person or thread, Norman Chat should help with:

- who this person is
- recent context
- what was promised
- what is overdue
- what tone makes sense
- what to say next

### Reminder and Follow-Through

Norman Chat should act like a soft obligation manager:

- remind about promised replies
- surface missed follow-ups
- carry meeting or call prep forward into action
- keep a lightweight memory of social and work commitments

### Draft-First Communication

Norman should make talking easier before it makes sending automatic.

Preferred pattern:

1. gather context
2. propose a draft
3. let the operator send or adjust it
4. track whether follow-up is now needed

### Fleet-Backed Context

When deeper context is needed, Norman Chat should quietly pull from:

- `Surveyor`, `Infra`, `Control Plane`, and other work bots
- personal and household bots
- `Subprime` for routing or escalation
- the directory/estate model for route and ownership clarity

The user should feel like Norman already knows where to go.

## Example Behaviors

Good `Norman Chat` behaviors:

- "You told Greg you would send the recap today. Here is the last thread and a
  draft."
- "You have a call with Nolan in 40 minutes. Here are the three points that
  matter and the last unresolved item."
- "Ryan has not gotten a reply in four days. Do you want a warm nudge or a
  direct answer?"
- "This needs work-bot context. I pulled the key point from Surveyor and
  drafted the Slack reply."
- "A bot is blocked on the background task. Subprime is handling it; here is
  the operator-level summary."

## Design Rules

`Norman Chat` should:

- feel like one desk, not a control panel zoo
- hide routing complexity until it matters
- preserve warmth and human tone
- treat reminders as support, not guilt
- keep raw bot churn in the background
- only surface deep system detail when it changes the next human action

## Product Components

Minimum components:

- unified inbox / attention strip
- draft composer
- person/thread memory panel
- reminders and promises panel
- pre-call brief card
- fleet handoff lane
- clear "draft", "send", "remind me", and "ask fleet" actions

## Non-Goals

`Norman Chat` is not:

- a raw multi-app message mirror
- an excuse to expose every bot directly
- a replacement for every specialist tool's native UI
- a fully autonomous sender by default

## Next Build Direction

The next useful implementation steps are:

1. make `Norman` the clear public-facing unified communication desk
2. make `Prime` the internal main desk
3. make `Switchboard` the communication/follow-up layer
4. route bot issues through `Subprime`
5. normalize person, thread, and promise tracking across channels
6. let Norman draft, remind, and brief before expanding autonomous send
