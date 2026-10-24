# Model evaluations

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

Before reporting or acting on a measured speedup, regression, cost, or eval score, including one outside a model
trial, name what bounds it, confirm the run did the intended work, and, when variance matters, alternate the
compared sides over at least five runs each within an authorized budget; otherwise report the number as unconfirmed.

Expand only for an unresolved decision that more cases can answer and within an explicitly authorized larger
budget. Otherwise report inconclusive results and request a concrete extension only when needed. A budget
ceiling is not a target. Stop new starts at the first case/call/time cap, user stop, unavailable required
capability, known quota exhaustion, or invalid measurement environment. Preserve usable partial evidence;
an infrastructure failure is not a quality failure or a pass.

For subprocess trials, select an existing timeout control no greater than the remaining batch time and clean
up only owned trial processes. If safe interruption is unavailable, stop dispatching and report the pending
call and possible overrun. Instructions cannot enforce a hard timeout. Reopen a stopped batch only with
changed evidence or an explicitly authorized extension, without erasing its prior measurements.
