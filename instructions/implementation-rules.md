# Implementation rules

Apply these rules to every implementation, including an assigned worker's and the main session's own edits.

## Every implementation

- Meet the request with the fewest new parts: add no layer, stored state, option, flag, or dependency that no stated
  requirement needs.
- Before adding a function, constant, rule, or stored value, search for an existing one that does or holds the same
  thing, and use or extend it. Keep one source for each rule, state, and value.
- Add no exception handler, default value, or fallback that lets a failed operation look successful. Handle a failure
  only where the request, the assignment, or the surrounding code states what must happen on it; otherwise let it
  surface.
- Before changing what a function accepts or returns, a schema, a stored format, or a setting, find its callers and
  consumers, and keep each one working or change it in the same task. Report one that lies outside the allowed paths.
- Rely on a fact only after reading it in the code, the data, a contract, or official documentation, or after running
  it. When a comment, a name, or a document disagrees with the code, take the code as the current behavior, report the
  difference, and change neither to match the other unless the task asks for it.

## Under a stated condition

- When the task fixes a reported defect, find the rule the code breaks and every reachable path that breaks it, and
  fix it where that rule is broken, which can be the caller. When a check can reproduce the defect, add the failing
  check before the fix.
- When an operation can be retried, run twice, or run at the same time as itself, make a repeated run leave the same
  result, guard its shared state against concurrent runs, and test the repeated run, and the concurrent run where a
  deterministic test can force it.
- When a behavior depends on a real engine, service, or browser, check it there or on an environment the repository
  names as equivalent; otherwise report it as unverified with the check that would settle it.
