# Writing a skill for more than one host

### Multiple target hosts

When a skill must run on more than one host, keep one canonical skill body as the single source of
truth. Never fork a per-host copy and maintain the copies separately; forks drift apart almost
immediately.

- Keep behavior rules, quality criteria, terminology, output contracts, and review checklists in
  the shared body.
- Put only genuine host differences in an adapter: trigger and discovery metadata, tool names,
  script invocation, host-required metadata, and workflows that use a host-only capability.
- Evaluate every target host against the same eval corpus and acceptance criteria so results stay
  comparable.
- Attribute a failure before editing. When all hosts fail a case, fix the shared rule. When one
  host fails, first check whether the shared rule is ambiguous and clarify it. Add an adapter rule
  only when the clarified shared rule still fails on that host. Rerun the corpus on every host
  after either change.
- Do not weaken or pad shared rules to a lowest common denominator because one host follows them
  poorly. Contain that host's gap in its adapter.
