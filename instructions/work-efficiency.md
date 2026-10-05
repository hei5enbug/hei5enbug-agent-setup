# Work efficiency

Apply these rules to substantial implementation, repeated model evaluation, plugin maintenance, and diagnosis
of repeated execution failures. Short answers and known-file lookups need no additional workflow.
Use the session's delegation policy and the existing implementation assignments; add no scheduler or task database.

## Scope and completion

Record the required result, required evidence, optional follow-ups, owner, and stop conditions in the existing
task facility or conversation. Amend the scope when the user requests new work. Include a newly found defect
only when it prevents the requested result or required verification; otherwise report it as a follow-up.

Group independently reviewable behavior under one owner. Do not dispatch reading, editing, testing, and
documenting the same cohesive change to separate workers. Preserve actual prerequisite acceptance boundaries.
Notify workers for changed requirements, dependencies, defects, or handoffs. Prefer completion events or the
host's waiting facility to repeated status queries. Continue required user progress updates without querying
logs or worker status merely to produce an update.

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

## Model evaluations

These limits govern additional model trials and benchmarks, not ordinary implementation, unit tests,
necessary builds, or the separately governed independent final review. Reuse authorization for the current
evaluation; a closed experiment and its former budget do not authorize a new experiment.

Before launching, state the question, frozen cases and criteria, runner settings, trial budget, and stop reasons.
Default to at most 3 representative cases, including a boundary case, and a 15-minute whole-batch deadline.
For a paired comparison, run each side once: at most 6 top-level trial starts across all hosts. Retries count.
Resumes, host switches, and workers share these counters and deadline; never reset them implicitly.

Check the actual CLI invocation, available authentication without exposing credentials, reported quota when
available, fixture dependencies, and output parsing. Complete one small authorized trial through quality
checking and usage recording before expanding; this probe consumes the batch budget.
Use observed duration to report elapsed time and a range for remaining work before the next batch.
Distinguish elapsed wall time, parallel-worker duration, and partial token coverage. Do not invent monetary
costs or assume an unknown quota is sufficient.

Expand only for an unresolved decision that more cases can answer and within an explicitly authorized larger
budget. Otherwise report inconclusive results and request a concrete extension only when needed. A budget
ceiling is not a target. Stop new starts at the first case/call/time cap, user stop, unavailable required
capability, known quota exhaustion, or invalid measurement environment. Preserve usable partial evidence;
an infrastructure failure is not a quality failure or a pass.

For subprocess trials, select an existing timeout control no greater than the remaining batch time and clean
up only owned trial processes. If safe interruption is unavailable, stop dispatching and report the pending
call and possible overrun. Instructions cannot enforce a hard timeout. Reopen a stopped batch only with
changed evidence or an explicitly authorized extension, without erasing its prior measurements.

## Failure and maintenance

Classify a failure before retrying. Missing executables or hook files, denied capabilities, permission
boundaries, and known quota exhaustion require changed conditions or an authorized working path, not an
unchanged retry. An apparently transient error permits at most one unchanged retry. After another failure,
diagnose it and obtain evidence of a changed input, environment, or service state before trying again.
Service access still follows its existing per-path fallback rules.

If a plugin hook path is missing, stop actions that depend on it and report the exact blocker. Never remove
hook entries, fake a successful guard, lower trust, or copy a different version into the old directory.
Recover the exact verified version or use the host's supported fresh-session path with the required approval.
When a host-generated Stop loop is outside agent control, report the external recovery step; neither a missing
script nor an instruction can guarantee that the host's loop ends.

Do not start a cache-replacing plugin update inside an active coding-agent session. An idle prompt still
holds a live session. Use the updater's explicit offline boundary after affected sessions have ended, or
apply an already-installed version. Preserve installed files and guard behavior when an update is deferred.
This does not control manual updates or another process deleting a loaded directory.
