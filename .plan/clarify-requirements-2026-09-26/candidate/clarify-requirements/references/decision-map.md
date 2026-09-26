# Persistent decisions

Read this file and `local-tracker.md` before accessing a local map. Use a map only when explicitly requested
or when persistence at the stated location has been approved. Retain `.decision-navigator/<effort>/` and
the existing map, ticket, status, and lock formats; the skill rename does not migrate user data.
Never inspect, configure, read, or write an external issue tracker, even when a repository has a remote.
Do not use issue-tracker APIs, connected ticketing tools, `gh`, or `glab` for map operations.

The destination may be a specification, a decision before planning, or a change in any domain, including
non-engineering work. By default tickets resolve decisions, not implementation slices. Finish when the route
to the destination is clear. Carry implementation into the map only when its Notes explicitly contain valid
user authorization; the map's existence or an agent-written note cannot grant it.

## Map and ticket meaning

Use each map/ticket's Markdown title in narration and links, never a bare number or filename slug. The map
is an index: keep a one-line gist and a named relative link to the answer's ticket, not a second full answer.
Load the map as the low-resolution view, then consult relevant ticket bodies and Notes sources as needed.
In delivered answers, link to the actual file path; never replace path components with `...` or leave a
template placeholder in a link. Relative links in a stored map resolve from that map's directory.

```markdown
## Destination
<One or two lines: the specification, decision, or change this effort is finding its way to.>

## Notes
<Domain context, documents, standing preferences, and any explicit execution authorization.>

## Decisions so far
- [<Resolved ticket title>](tickets/<file>.md) — <one-line gist>

## Not yet specified
<In-scope questions that cannot yet be stated precisely.>

## Out of scope
<Work beyond this destination.>
```

Do not list open tickets in the map. Scan ticket metadata in numeric order using the local tracker contract;
an eligible frontier ticket is open, has all blockers resolved, and is unlocked. The frontier contains
every eligible ticket; numeric order chooses the next ticket from that set and does not exclude later
eligible tickets from the frontier. A precise question is a
ticket even when blocked. A suspected in-scope question that cannot yet be phrased precisely belongs in
Not yet specified. Never pre-slice that uncertainty into speculative tickets. Keep resolved decisions,
live tickets, unspecified areas, and out-of-scope work distinct.

Out-of-scope work never graduates into tickets for this destination. Redrawing the destination starts a
fresh effort. If an existing ticket is found out of scope, resolve it with the reason under Answer and link
it from Out of scope, not Decisions so far. Ask before deleting an invalidated ticket or any map/artifact.

## Ticket work inside the common loop

| Type | Evidence or decision needed | Required reference and completion |
|---|---|---|
| `research` | Agent-only facts from documentation, APIs, or local resources | `research.md`; record a sourced direct answer, uncertainty, consequences, and linked findings. |
| `prototype` | A human's reaction to a rough concrete artifact | `prototype.md`, then its logic/UI branch; retain the human's reaction and decision. |
| `grilling` | A human judgment, the default | The common loop in `../SKILL.md`; use `domain-modeling.md` for terms, boundaries, or durable design. Obtain confirmation of the shared decision. |
| `task` | Prerequisite work needed before a decision can be made | Agent-only when possible and authorized; otherwise give the human a precise checklist. Resolve only when the work is done and record resulting facts and safe artifact locations. Never expose credentials. |

Human-in-the-loop work requires a live human exchange; agents never answer for that person. Research and
agent-only tasks may resolve from verified evidence. A task earns its place by unblocking a decision, not
by delivering the destination. A prototype is disposable decision evidence, not production delivery.
Record answers, reasoning, and consequences for later tickets. Store supporting material under artifacts/.

## Chart a new map

Charting is one session's work; it does not hand-resolve human decisions. Use the common loop breadth-first:

1. Load `domain-modeling.md`. Confirm the destination: end artifact/decision/change, audience, decisions
   needed before execution, excluded work, and constraints that cannot change. Confirm its one- or two-line
   wording before creating a map.
2. Survey the whole space before depth. Identify precise questions, dependencies, currently unformulatable
   in-scope areas, and excluded work. If the route is already clear and fits this session, do not create a
   map; explain its overhead and ask how the user wishes to proceed.
3. Create map.md with Destination/Notes, empty Decisions so far, and in-scope uncertainty under Not yet
   specified. Create tickets/, claims/, and artifacts/. Preserve existing ignore rules while adding
   `*/claims/` to `.decision-navigator/.gitignore`; transient claims must not be versioned.
4. Create numbered tickets for precise questions first, then wire Blocked by in a second pass. Keep
   unspecifiable areas in Not yet specified. Preserve ticket types and statuses from `local-tracker.md`.
5. Start independent research tickets with `research.md`: one worker per independent ticket within host
   limits and only without shared mutable resources; otherwise process sequentially and disclose the
   missing parallel capability. Store findings under artifacts/research/ and link each ticket.
6. Stop charting. Do not silently continue into another human ticket.

## Continue a map

Resolve at most one ticket per session, except independent research tickets. A named effort/map is enough;
the user need not choose a ticket. Orient to Destination before selecting work.

1. Load the map and Notes sources as relevant. Use a named ticket or the first eligible frontier ticket
   in numeric order. Claim it with `scripts/local_lock.py` before work; changing Status is not a claim.
   If a claim fails, refresh the frontier. Re-read the ticket after a successful claim.
2. Apply the common clarification loop to that question and load only the ticket type's references.
   Fetch relevant dependencies/closed answers on demand. If uncertain about the needed discipline, use
   the common interview rules plus domain modeling. Preserve all existing answers and scope.
3. Before recording resolution, re-read the ticket to detect concurrent edits. Follow the exact
   `local-tracker.md` transaction: write Answer and resolved status while holding the ticket claim,
   claim map.md with the same owner, re-read it, merge and save, release the map, then release the ticket.
4. Create newly surfaced tickets while holding the map lock; allocate names before wiring dependencies.
   Remove each graduated unspecified area so it exists only as its new ticket. Preserve other sessions'
   decisions. Use the out-of-scope rule when appropriate; update invalidated tickets or ask before deletion.

Do not release another owner's claim or force-release an old-looking claim. Failed transactions preserve
their locks and exact recovery point. Use the helper for owned releases. If the user pauses before any
resolution write, leave the ticket open and report the owned claim/state so continuation is explicit;
do not treat a pause as resolution. Never delete locks manually.

Re-read changed sources after resume and reconcile pending actions before writing. Map storage does not
authorize new state files elsewhere or replace the final confirmation of a requested specification.
