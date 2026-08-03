# Local tracker contract

All decision-navigator state lives inside the repository under `.decision-navigator/`. Never read
or write an external issue tracker, even when the repository has a remote.

## Effort layout

```text
.decision-navigator/<effort>/
├── map.md
├── tickets/
│   ├── 01-first-question.md
│   └── 02-second-question.md
├── claims/
│   ├── 01-first-question.lock/
│   └── map.lock/
└── artifacts/
    ├── research/
    └── prototypes/
```

Use a short, readable effort slug. Number tickets from `01` in map order. The
`claims/` directory contains transient lock directories and their metadata.
Ensure `.decision-navigator/.gitignore` contains `*/claims/`. Preserve any existing
entries when adding it. Maps, tickets, and artifacts may be versioned according
to the repository's normal policy; claims must remain local.

## Ticket format

```markdown
# Ticket name

Type: grilling
Status: open
Blocked by:

## Question

The decision or investigation this ticket resolves.

## Answer
```

Allowed types are `research`, `prototype`, `grilling`, and `task`. Allowed
statuses are `open` and `resolved`. A claim is represented only by a lock, not
by another status value.

List blockers by filename stem, separated by commas:

```text
Blocked by: 01-first-question, 03-api-limits
```

## Atomic locks

Use the bundled helper for ticket claims and serialized map updates:

```text
python3 <skill-root>/scripts/local_lock.py claim \
  .decision-navigator/<effort>/tickets/01-first-question.md \
  --owner "<session-owner>"
```

Choose a stable owner string for the session and reuse it when releasing the
lock. Inspect a lock with:

```text
python3 <skill-root>/scripts/local_lock.py inspect <resource-path>
```

Release it with:

```text
python3 <skill-root>/scripts/local_lock.py release \
  <resource-path> --owner "<session-owner>"
```

The helper creates a lock directory atomically. Only one concurrent claimant
can succeed. If a claim fails, skip that ticket and refresh the frontier.

Never force-release a lock merely because it looks old. Inspect its metadata
and ask the user before using `release --force`.

## Frontier

Scan ticket files in numeric order. A frontier ticket must satisfy all three:

1. `Status: open`;
2. every filename listed in `Blocked by:` has `Status: resolved`;
3. no matching directory exists under `claims/`.

Re-read the chosen ticket after its claim succeeds.

## Resolution transaction

Keep the ticket claim while resolving it. Then:

1. write the answer and set `Status: resolved`;
2. claim `map.md` with the same owner;
3. re-read `map.md`, merge the new context pointer, fog, and ticket changes;
4. save `map.md` and release its lock;
5. release the ticket lock.

Create newly surfaced ticket files while holding the map lock so two sessions
cannot allocate the same number. If a failure occurs, preserve both locks and
report the exact recovery point instead of guessing.

## Scope and deletion

When a ticket moves out of scope, set it to `resolved`, explain why under
`## Answer`, and link it from the map's `Out of scope` section. Do not delete
maps, tickets, or artifacts without the user's approval. Release owned locks
through the helper; never remove a lock directory manually.
