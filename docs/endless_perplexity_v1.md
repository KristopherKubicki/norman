# Endless Perplexity V1

This document proposes a first operating model for an "endless perplexity" service: a research and signal-mining layer
that uses Perplexity as a broad scout while Norman remains the control plane, memory layer, and routing system.

The goal is not to create another giant pile of search threads. The goal is to create a durable signal fabric that:

- scouts widely
- cites aggressively
- emits structured hints
- routes findings into the org
- supports ad hoc curiosity without collapsing into noise

## Status

- this is a v1 proposal
- it assumes an individual Perplexity Pro account, not Max
- it is optimized for a personal operator who wants to spend less time in work execution and more time in strategy,
  making, and opportunistic exploration
- it treats Norman as the system of record

## Core Position

Perplexity should be used as a `scout`, not as the `archive`.

That means:

- `Perplexity` does reconnaissance, synthesis, citation, and draft artifact creation
- `Norman` stores durable findings, deduplicates repeated discoveries, tracks owners, and decides where things go
- `Spaces` are temporary research workbenches, not the final repository of truth
- the org should receive `typed signals`, not a firehose of undifferentiated docs

## Constraints From Current Perplexity Pro

The current design needs to fit the real limits of a normal Pro account.

- Pro and Max subscribers can create up to `10 active Tasks`
- Pro uses a rolling `24-hour` credit restore model for Pro searches and advanced-model usage
- Pro supports `up to 50 files per Space`
- Pro includes a `limited` amount of `Create files and apps` usage every 30 days
- Perplexity positions the `API` separately from the consumer/web plan, so heavy programmatic mining should move to API
  workers later rather than trying to force everything through the web product

Official references:

- [Perplexity Tasks](https://www.perplexity.ai/help-center/en/articles/11521526-perplexity-tasks)
- [What is Perplexity Pro?](https://www.perplexity.ai/help-center/en/articles/9385876-what-is-perplexity-pro)
- [What are Spaces?](https://www.perplexity.ai/help-center/en/articles/10352961-spaces)
- [Which Perplexity subscription plan is right for you?](https://www.perplexity.ai/help-center/en/articles/11187416-which-perplexity-subscription-plan-is-right-for-you)
- [Perplexity Create files and apps](https://www.perplexity.ai/help-center/en/articles/11144811-perplexity-create-files-and-apps)

The immediate implication is simple:

- do not design v1 around 30 or 50 standing automations
- reserve capacity for ad hoc obsession
- use Tasks for recurring pulls, not for every idea
- use Norman to multiply the value of each Perplexity run

## V1 Outcome

V1 should produce a service that does four things well:

1. gathers external signals on a repeatable cadence
2. identifies data quality and contradiction issues
3. writes clean findings into the org with metadata
4. gives [REDACTED_NAME] a lightweight Monday and Friday review ritual

V1 should not try to do all of these yet:

- full autonomous crawl orchestration
- large-scale programmatic web scraping
- deep enterprise search across giant internal repositories
- replacing existing work bots
- becoming a permanent document graveyard

## Naming

Working internal name:

- `Endless Perplexity`

Better Norman-aligned names:

- `Scout`
- `Signal Fabric`
- `Research Scout`
- `Hint Engine`

Recommended v1 service name:

- `Scout`

Reason:

- it matches the estate language in `docs/bot_empire.md`
- it does not overstate authority
- it implies reconnaissance, not final judgment

## System Shape

The clean architecture is:

```text
Perplexity Space / Task / Thread
        ->
Scout Ingest Normalizer
        ->
Signal Object + Evidence Bundle + Dedup Key
        ->
Norman Routing
        ->
Org Docs / Queues / Dashboards / Notes / Follow-ups
```

In practice, that means:

- Perplexity produces a thread, report, or create-files output
- the result is copied, exported, emailed, or otherwise pushed into a Norman ingress path
- Norman extracts typed findings
- Norman decides whether each finding is:
  - a weak signal
  - a watch item
  - a contradiction
  - an action candidate
  - a company note
  - a culture observation
  - an ad hoc idea

## Lane Model

V1 should use five top-level lanes.

### 1. Public Signals

Purpose:

- watch market movement
- spot launches, hiring signals, vendor movement, customer chatter, pricing changes, legal or regulatory shifts

Typical output:

- weak signals
- notable changes
- competitor movement
- opportunity hints

### 2. Data Quality

Purpose:

- detect stale facts, contradictions, uncited claims, broken assumptions, and drift between what the org believes and
  what sources currently say

Typical output:

- contradiction tickets
- stale-note alerts
- missing-citation flags
- "recheck this before reuse" warnings

### 3. Company

Purpose:

- focus on the company and adjacent entities: vendors, partners, competitors, category actors, portfolio entities, and
  related infrastructure

Typical output:

- company watch notes
- ownership or management changes
- product and positioning changes
- mentions worth routing

### 4. Culture

Purpose:

- track posture, narrative, aesthetics, sentiment, public voice, and subtle social proof signals

Typical output:

- narrative trends
- theme shifts
- style references
- cultural artifacts worth saving

### 5. Ad Hoc Lab

Purpose:

- reserve room for curiosity, obsession, and one-off explorations
- let you investigate the interesting thing of the day without blowing up the whole operating model

Typical output:

- one-off research memos
- weird hints
- rabbit holes that might later become standing watches

## Space Design

Do not create dozens of Spaces.

V1 should start with exactly these Spaces:

- `Scout - Public Signals`
- `Scout - Data Quality`
- `Scout - Company`
- `Scout - Culture`
- `Scout - Ad Hoc Lab`

Each Space should define:

- a clear mission
- a narrow set of custom instructions
- a default output structure
- a small curated file set
- a short watchlist of domains, terms, and targets

Each Space should avoid:

- giant mixed-purpose file piles
- unclear ownership
- dumping all prior org docs into the context
- broad instructions like "find anything interesting"

## Task Budget

Because Pro only allows ten active Tasks, V1 should intentionally underfill the budget.

Recommended standing allocation:

- `3` Public Signals Tasks
- `2` Data Quality Tasks
- `2` Company Tasks
- `1` Culture Task
- `1` Weekly synthesis Task
- `1` open slot reserved for ad hoc or temporary campaigns

This uses all `10`, but with one flex slot.

If you want more ad hoc freedom, run this lighter default:

- `2` Public Signals
- `2` Data Quality
- `2` Company
- `1` Culture
- `1` Weekly synthesis
- `2` open ad hoc slots

Recommended v1 default:

- use the lighter model with `2` open slots

That fits your stated preference better:

- Monday and Friday review matter
- the rest of the week should feel more like making and strategy than queue processing

## Task Menu

Here is the initial standing task set.

### Public Signals

`Daily / weekday / morning`

- "What changed in the last 24 hours across our watchlist of companies, products, hiring pages, pricing pages, and
  public mentions? Return only material changes with citations."

`Daily / weekday / afternoon`

- "What new weak signals or second-order hints appeared today across public web, social discussion, and company
  surfaces that might matter in 30 to 180 days?"

### Data Quality

`Tuesday / Friday`

- "Compare our current assumptions and canonical notes against the best public evidence available. Find contradictions,
  stale claims, unsupported claims, and anything that should be reverified."

`Wednesday`

- "Scan the active watchlist and linked notes for facts that now appear weakly supported, out of date, or likely copied
  forward without confirmation."

### Company

`Monday / Thursday`

- "Review our company and competitor watchlist. What changed in product, positioning, people, partnerships, pricing,
  demand signals, or public narrative?"

`Friday`

- "For the tracked company set, summarize only the five highest-signal developments of the week with evidence and why
  they matter."

### Culture

`Wednesday`

- "What cultural or narrative shifts are visible this week in the tracked scenes, communities, and media surfaces? Focus
  on patterns, not headlines."

### Synthesis

`Friday afternoon`

- "Synthesize this week's strongest findings across public signals, data quality, company, and culture. Group them into:
  act now, watch closely, archive, and ignore."

## Prompt Contract

All recurring prompts should force the same output contract.

Use this as the required answer shape:

```text
Return at most 10 findings.

For each finding, use this exact structure:

1. Signal
2. Why it matters
3. Evidence
4. Confidence (high / medium / low)
5. Novelty (new / update / repeat)
6. Suggested destination in the org
7. Recommended next action

Rules:
- Prefer specific changes over general summaries.
- Prefer source-backed claims over speculation.
- If evidence is weak, say so plainly.
- Mark repeated patterns as repeat, not new.
- Do not pad with filler findings.
- If nothing important changed, say "No material findings."
```

This matters more than the exact wording of the topical prompt.

## Ingest Contract For Norman

Norman should convert every Perplexity result into one or more `signal` objects.

Suggested v1 schema:

```json
{
  "signal_id": "scout:2026-04-03:public:abc123",
  "lane": "public_signals",
  "space": "Scout - Public Signals",
  "task_name": "weekday-change-watch",
  "captured_at": "2026-04-03T13:30:00Z",
  "title": "Pricing page quietly added enterprise tier",
  "summary": "Vendor X added an enterprise tier and changed feature gating on its pricing page.",
  "why_it_matters": "This may indicate packaging pressure in the category and changes the benchmark set.",
  "confidence": "medium",
  "novelty": "new",
  "severity": "medium",
  "recommended_action": "Add to pricing benchmark sheet and re-check in 7 days.",
  "destination": "company/watchlist/vendor_x",
  "entities": [
    "Vendor X"
  ],
  "tags": [
    "pricing",
    "benchmark",
    "watchlist"
  ],
  "sources": [
    {
      "url": "https://example.com/pricing",
      "label": "Vendor X pricing"
    }
  ],
  "dedupe_key": "vendor-x:pricing-tier-change",
  "raw_thread_url": "https://www.perplexity.ai/...",
  "raw_excerpt": "..."
}
```

Required v1 fields:

- `lane`
- `captured_at`
- `title`
- `summary`
- `why_it_matters`
- `confidence`
- `novelty`
- `recommended_action`
- `destination`
- `sources`
- `dedupe_key`

Optional fields:

- `severity`
- `entities`
- `owner`
- `follow_up_date`
- `related_signals`
- `raw_thread_url`

## Deduplication Rules

Without dedupe, this system becomes useless.

V1 dedupe rules:

- same entity plus same claim class plus same underlying URL cluster should collapse into one rolling signal thread
- repeated sightings should increment a count and append evidence, not create a new top-level object every time
- weekly synthesis should prefer `novelty = new` and `novelty = update`
- `repeat` items should only surface if repetition itself is meaningful

Examples:

- same pricing page change seen three times in a week -> one signal with evidence updates
- three different sources independently noticing the same hiring move -> one signal, stronger confidence
- recurring vague sentiment with no new evidence -> archive unless it crosses a threshold

## Routing Rules

Each signal should be routed somewhere intentional.

Suggested destinations:

- `public_signals` -> opportunity queue, strategy notes, watchlists
- `data_quality` -> contradiction queue, note repair backlog, stale-fact list
- `company` -> company dossier, competitor files, portfolio notes
- `culture` -> inspiration board, style notes, trend tracker
- `adhoc_lab` -> scratchpad, later triage, possible promotion into a standing lane

Recommended v1 actions:

- `archive`
- `watch`
- `route`
- `escalate`
- `repair`
- `ignore`

## Create Files And Apps Usage

Do not use `Create files and apps` for normal recurring scans.

Use it for these only:

- weekly synthesis packs
- one-off dossiers
- side-by-side comparison tables
- mini dashboards or brief viewers
- exportable artifacts worth keeping

Do not spend limited Create capacity on:

- daily watch tasks
- low-signal topic sweeps
- prompts that mostly produce text you will not revisit

The mental model should be:

- `Search / Research / Tasks` for detection
- `Create files and apps` for packaging

## Monday And Friday Operating Cadence

The cadence should fit the life you described.

### Monday

Goal:

- orient the week
- decide what matters
- avoid drowning in operational residue

Monday ritual:

1. review the Friday synthesis and Monday company/public-signal outputs
2. mark findings as `act now`, `watch`, `archive`, or `ignore`
3. create at most `3` strategic threads for the week
4. explicitly decide which active workstreams are no longer worth occupying mental space

Output:

- one short weekly posture note
- one ranked watchlist
- one "not doing" list

### Friday

Goal:

- compress the week into signal
- prevent memory loss
- close loops before the weekend

Friday ritual:

1. review synthesis task output
2. promote durable findings into org notes
3. convert contradictions into repair tickets
4. kill stale ad hoc threads
5. seed one or two questions for next week

Output:

- one weekly scout memo
- one contradiction list
- one opportunity list

## What "Flood The System" Should Mean

The right interpretation is:

- flood the org with structured hints
- flood watchlists with evidence
- flood company dossiers with changes

The wrong interpretation is:

- flood Perplexity with random spaces
- flood yourself with uncategorized threads
- flood the archive with undifferentiated docs

V1 rule:

- every Perplexity artifact must either become a typed signal, an explicit memo, or be discarded

If it does not deserve one of those destinations, it should not persist.

## Suggested Initial Watchlists

V1 needs explicit watchlists so prompts stay sharp.

Public Signals watchlist:

- tracked companies
- competitors
- key vendors
- pricing pages
- status pages
- job boards
- release notes
- public roadmap surfaces
- selected social communities

Data Quality watchlist:

- core assumptions docs
- active company notes
- benchmark sheets
- repeated talking points
- old strategy docs likely to be copied forward

Company watchlist:

- company pages
- leadership pages
- investor or press pages
- LinkedIn/company updates
- support docs
- help centers
- changelogs

Culture watchlist:

- tastemaker communities
- niche forums
- public social clusters
- creator ecosystems
- design and aesthetic references

## V1 Success Criteria

After 30 days, this should be true:

- the service emits useful findings every week without feeling noisy
- at least `70%` of outputs route cleanly into a known destination
- contradictions are being found before they embarrass you
- Monday and Friday review take less than `30 minutes` each
- ad hoc explorations still fit without breaking the standing model
- the org contains better evidence than it did before the service existed

## Failure Modes

Watch for these immediately:

- too many spaces
- unclear lane ownership
- prompts asking for "anything interesting"
- same finding emitted over and over without dedupe
- Perplexity threads kept as final memory
- Create usage spent on low-value packaging
- review ritual turning into another inbox

## Recommended Next Build Steps

1. Create the five Spaces.
2. Write one custom instruction block per Space.
3. Create the lighter standing Task set with two open ad hoc slots.
4. Define a Norman ingest path for `signal` objects.
5. Build dedupe and routing before scaling prompt volume.
6. Add one Friday synthesis memo format.
7. Run for two weeks before adding more Tasks.

## Expansion Path After V1

Once V1 is stable, the next stage is not "more Tasks." The next stage is:

- Perplexity API workers for heavier and more repeatable mining
- automated capture from exports, emails, or thread links
- lane-specific scorecards
- dashboard views of novelty, contradiction, and opportunity
- promotion of recurring ad hoc topics into permanent watch lanes

The real north star is:

- Perplexity becomes the outer scouting edge
- Norman becomes the knowledge and routing core
- your time moves toward strategy, synthesis, castle-building, and selective intervention

That is the version that scales.
