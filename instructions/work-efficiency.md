# Work efficiency

Apply these rules to substantial implementation. Short answers and known-file lookups need no additional workflow.
Use the session's delegation policy and the existing implementation assignments; add no scheduler or task database.

## Scope and completion

Record the required result, required evidence, optional follow-ups, owner, and stop conditions in the existing
task facility or conversation. Amend the scope when the user requests new work. Include a newly found defect
only when it prevents the requested result or required verification; otherwise report it as a follow-up.

Group independently reviewable behavior under one owner. Do not dispatch reading, editing, testing, and
documenting the same cohesive change to separate workers. Preserve actual prerequisite acceptance boundaries.
Notify workers for changed requirements, dependencies, defects, or handoffs. Prefer completion events or the
host's waiting facility to repeated status queries. Continue required user progress updates without querying
logs or worker status merely to produce an update. When starting a background wait or monitor, tell the user in
one line what runs (a script or a model), against what, and the expected duration.

After 15 minutes without a new accepted result or actionable evidence, reassess the approach once and report
the blocker and next bounded action. Productive implementation does not stop merely because it is long.
Finish when required results and checks are accepted. Report implemented behavior, verified behavior, and
remaining limits separately. Optional follow-ups and an unperformed optional independent review do not keep
an accepted implementation open; the existing independent-review approval contract still applies.

## Check evidence

Keep a compact record of each check's scope, command, result, and relevant input/environment state. Accept
valid worker evidence without repeating the same check. Reuse a result only while its covered source,
dependencies, fixtures, configuration, and toolchain remain unchanged. Invalidate affected results when those
inputs change; use a targeted rerun when coverage is uncertain, never assume a pass.

Run assigned narrow checks during implementation and necessary integration checks after integration.
Expand testing for a demonstrated failure or unresolved risk. Repository-required release checks remain
mandatory. A failed required check remains a failure even when the cause lies outside the assigned change.
