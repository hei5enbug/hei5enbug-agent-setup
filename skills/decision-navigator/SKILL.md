---
name: decision-navigator
description: >-
  Plan a large effort that spans more than one agent session as a shared map of decision tickets,
  then resolve the tickets one at a time until the route to the destination is clear. Use only when
  the user explicitly asks to create or continue a decision-navigator map.
compatibility: >-
  Requires filesystem access and Python 3 for atomic ticket claims. Independent workers are
  optional. All map state stays in local Markdown files under .decision-navigator.
---

A loose idea has arrived — too big for one agent session, and wrapped in fog: the way from here to
the **destination** isn't visible yet. Decision navigation is about finding that way, not charging
at the destination. This skill charts the way as a **local map** under `.decision-navigator/`, then works its
**decision tickets** — questions whose resolution is a decision, not slices of a build to execute —
one at a time until the route is clear.

The destination varies per effort, and naming it is the first act of charting — it shapes every
ticket. It might be a spec to hand off and iterate on, a decision to lock before planning starts, or
a change made in place like a data-structure migration. The map is domain-agnostic — engineering
work, course content, whatever fits the shape.

## Plan, don't do

Decision Navigator is **planning** by default: each ticket resolves a decision, and the map is done when the
way is clear — nothing left to decide before someone goes and does the thing. The pull to just do
the work is usually the signal you've reached the edge of the map and it's time to hand off. An
effort can override this in its **Notes** — carrying execution into the map itself — but absent
that, produce decisions, not deliverables.

## Refer by name

Every map and ticket has a **name** — its Markdown title. In everything the human reads —
narration, the map's Decisions-so-far — refer to it by that name, never by a bare number or slug. A
wall of `01, 02, 03` is illegible; names read at a glance. The relative path doesn't vanish — a name
wraps its link — but it rides _inside_ the name, never stands in for it.

## The Map

The map is `.decision-navigator/<effort>/map.md` — the canonical artifact. Its tickets are numbered
Markdown files under `.decision-navigator/<effort>/tickets/`.

The map is an **index**, not a store. It lists the decisions made and points at the tickets that
hold their detail; a decision lives in exactly one place — its ticket — so the map never restates
it, only gists it and links.

Read [the local tracker contract](references/local-tracker.md) before reading or writing a map.
Never inspect, configure, read, or write an external issue tracker. Do not use issue-tracker APIs,
connected ticketing tools, `gh`, or `glab`. A repository remote does not change this storage rule.

### The map body

The whole map at low resolution, loaded once per session. Open tickets are **not** listed — find
them by scanning the effort's `tickets/` directory.

```markdown
## Destination

<what reaching the end of this map looks like — the spec, decision, or change this effort is finding
its way to. One or two lines; every session orients to it before choosing a ticket.>

## Notes

<domain context; project documents to consult; standing preferences for this effort>

## Decisions so far

<!-- the index — one line per resolved ticket: enough to judge relevance,
then zoom the link for the detail the ticket holds -->

- [<closed ticket title>](link) — <one-line gist of the answer>

## Not yet specified

<!-- see "Fog of war": in-scope fog you can't ticket yet; graduates as the frontier advances -->

## Out of scope

<!-- see "Out of scope": work ruled beyond the destination; closed, never graduates -->
```

### Tickets

Each ticket is a numbered **child file** of the map. Its filename is its stable identity, and its
body contains a question sized to one agent session:

```markdown
## Question

<the decision or investigation this ticket resolves>
```

Each ticket carries a `Type:` field — one of `research`, `prototype`, `grilling`, or `task` (see
[Ticket Types](#ticket-types)).

A session **claims** a ticket by atomically creating its lock under `claims/`, **first**, before any
work, so concurrent sessions skip it. Use the bundled claim helper; changing `Status:` alone is not
a claim.

Blocking uses the ticket's `Blocked by:` field. A ticket is **unblocked** when every listed ticket
has `Status: resolved`; the **frontier** is the open, unblocked, unlocked children — the edge of the
known.

Record the answer under the ticket's `## Answer` heading (see
[Work through the map](#work-through-the-map)). Put supporting findings and notes under the effort's
`artifacts/` directory and link them from the ticket.

## Ticket Types

Every ticket is either **HITL** — human in the loop, worked _with_ a human who speaks for themselves
— or **AFK**, driven by the agent alone. A HITL ticket only resolves through that live exchange; the
agent never stands in for the human's side of it (a grilling agent that answers its own questions
has broken this).

- **Research** (AFK): Read documentation, third-party APIs, or local resources to surface a fact a
  decision waits on. Follow [the research workflow](references/research.md). Use an independent
  worker when available; otherwise run the same workflow sequentially.
- **Prototype** (HITL): Raise the fidelity of the discussion by making a cheap, rough, concrete
  artifact to react to. Follow [the prototype workflow](references/prototype.md) when "how should it
  look" or "how should it behave" is the key question. Link the prototype as an asset.
- **Grilling** (HITL): Interview the human one question at a time using
  [the interviewing discipline](references/interviewing.md). Apply
  [domain modeling](references/domain-modeling.md) when terminology, boundaries, or durable design
  decisions are involved. This is the default case.
- **Task** (HITL or AFK): Manual work that must happen before a _decision_ can be made — nothing to
  decide, prototype, or research, but the discussion is blocked until it's done. Signing up for a
  service so its API can be judged, provisioning access, moving data so its shape can be seen. This
  is the one type that _does_ rather than decides — and it earns its place by unblocking a decision,
  not by delivering the destination. The agent drives it alone where it can (AFK); otherwise it
  hands the human a precise checklist (HITL). Resolved when the work is done; the answer records
  what was done and any resulting facts (credentials location, new URLs, row counts) later tickets
  depend on.

## Fog of war

The map is _deliberately_ incomplete: don't chart what you can't yet see. Beyond the live tickets
lies the **fog of war** — the dim view of decisions and investigations you can tell are coming but
can't yet pin down, because they hang on questions still open. Resolving a ticket clears the fog
ahead of it, graduating whatever's now specifiable into fresh tickets — one at a time, until the way
to the destination is clear and no tickets remain.

The map's **Not yet specified** section is where that dim view is written down: the suspected
question, the area to revisit later. It's the undiscovered frontier _toward_ the destination —
everything here is in scope, just not sharp enough to ticket. Write as loosely or as fully as the
view allows; it doubles as a signpost for collaborators reading where the effort is headed.

**Fog or ticket?** The test is whether you can state the question precisely now — _not_ whether you
can answer it now.

- **Ticket when** the question is already sharp — even if it's blocked and you can't act on it yet.
- **Not yet specified when** you can't yet phrase it that sharply. Don't pre-slice the fog into
  ticket-sized pieces: it's coarser than a ticket, and one patch may graduate into several tickets,
  or none, once the frontier reaches it.

**Not yet specified** excludes what's already decided (Decisions so far), what's already a live
ticket, and what's out of scope (the next section).

## Out of scope

Fog only ever gathers _toward_ the destination. The destination fixes the scope, so work beyond it
is **out of scope** — it isn't fog, and it doesn't belong in **Not yet specified**. It gets its own
**Out of scope** section on the map: work you've consciously ruled out of _this_ effort. Scope, not
sharpness, lands it here.

Out-of-scope work never graduates — the frontier stops at the destination — so it returns only if
the destination is redrawn, and then as a fresh effort, not a resumption.

Ruling something out of scope is a scoping act, not a step on the route. When a ticket that already
exists turns out to sit past the destination — mis-scoped in while charting, or exposed by a
resolution — set it to `resolved`, record the reason under `## Answer`, and leave one line in the
**Out of scope** section linking the ticket. It stays out of **Decisions so far**, which records the
route actually walked — a scope boundary isn't a step on it.

## Bundled references

Load only what the current operation needs:

- Always read [the local tracker contract](references/local-tracker.md) before reading or writing a
  map.
- Read [interviewing](references/interviewing.md) for destination discovery and grilling tickets.
- Also read [domain modeling](references/domain-modeling.md) when the decision changes project
  vocabulary, boundaries, or a durable architectural choice.
- Read [research](references/research.md) for research tickets.
- Read [prototype](references/prototype.md) for prototype tickets, then read its logic or UI branch.

These files are parts of this skill, not separate skills. Do not look for or invoke sibling skills.

## Invocation

Two modes. Either way, **never resolve more than one ticket per session** — with the exception of
research tickets.

### Chart the map

User invokes with a loose idea.

1. **Name the destination.** Read [interviewing](references/interviewing.md) and
   [domain modeling](references/domain-modeling.md), then interview the user to pin down what this
   map is finding its way to — the spec, decision, or change. The destination fixes the scope, so
   settle it first.
2. **Map the frontier.** Continue the interview **breadth-first**: fan out across the whole space
   rather than deep on any one thread, surfacing the open decisions and the first steps takeable
   now. **If this surfaces no fog** — the way to the destination is already clear, the whole journey
   small enough for one session — you don't need a map. Stop and ask the user how they'd like to
   proceed.
3. **Create the effort directory and map**: write `.decision-navigator/<effort>/map.md` with Destination and
   Notes filled in, Decisions-so-far empty, and the fog sketched into **Not yet specified**. Create
   empty `tickets/`, `claims/`, and `artifacts/` directories. Ensure `.decision-navigator/.gitignore`
   contains `*/claims/` so transient locks are never versioned.
4. **Create the tickets you can specify now** as numbered files under `tickets/`, then fill
   `Blocked by:` fields in a **second pass**. Wiring sorts them into the frontier and the blocked;
   everything you can't yet specify stays in the fog — the **Not yet specified** section.
5. **Start the research work.** Read [research](references/research.md). If the host supports
   independent workers, start one per independent research ticket, within the host's safe
   concurrency limit. Otherwise process research tickets sequentially and say that parallelism was
   unavailable. Capture each result under the effort's `artifacts/research/` directory, then add a
   relative context pointer from the ticket.
6. Stop — charting is one session's work; it hand-resolves nothing.

### Work through the map

User invokes with an effort name or local map path. A ticket is **optional** — without one, you pick
the next decision, not the user.

1. Load the **map** — the low-res view, not every ticket body.
2. Choose the ticket. If the user named one, use it. Otherwise take the first frontier ticket in
   order. **Claim it** atomically with the bundled claim helper before any work.
3. Resolve it — **zoom as needed**: fetch the full body of any related or closed ticket on demand;
   read the project documents named in `## Notes`; and load the bundled reference for the ticket
   type. If in doubt, use the interviewing discipline and domain-modeling rules.
4. Write the answer, set `Status: resolved`, release the claim, and append a named relative link and
   one-line gist to the map's Decisions-so-far.
5. Add newly surfaced tickets in a create-then-wire pass. Graduate fog that the answer has made
   specifiable, removing each graduated patch from **Not yet specified** so it lives only as its new
   ticket. If the answer reveals that a ticket sits beyond the destination, **rule it out of scope**
   rather than resolving it on the route. If the decision invalidates another ticket, update it or
   ask before deleting it.

The user may run unblocked tickets in parallel, so expect other sessions to edit local map files
concurrently. Re-read a ticket after claiming it and before recording its resolution.
