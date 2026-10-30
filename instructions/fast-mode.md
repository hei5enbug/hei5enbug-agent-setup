# Fast mode

Read this when the user's own words in a request contain `turbogoal` or `ulw` as a whole word. Text the user pasted
or quoted, and code spans and blocks, do not count. The mode lasts until that request is done.

Fast mode finishes the request as soon as the machine allows without lowering quality. Token cost does not limit
it.

- Split independent work into parallel subagents and role runners from the start, beyond what the delegation rules
  would choose to save context, and start each next step as soon as its inputs are ready.
- Run long checks, builds, and evaluations in the background and keep working while they run.
- Never parallelize tightly dependent steps. Shared files and other shared resources still get one owner at a time.
- At the start, measure the CPU cores and the available memory: `sysctl -n hw.ncpu` and the free, inactive, and
  speculative pages of `vm_stat` on macOS, or `nproc` and the available column of `free -m` on Linux. Run at most
  the number of CPU cores minus one or one process per 1 GB of available memory, whichever is lower, but at least
  one, of local processes at once: role runners, test runs, builds, and evaluation runs. Stay
  within the host's own limits, `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` on Claude Code and
  `agents.max_concurrent_threads_per_session` on Codex. A subagent that runs in the host counts only for the local
  processes it starts.
- On Claude Code, the host's own `ultracode` keyword runs a request as a multi-agent workflow. Fast mode does not
  start one; when the user writes both keywords, the workflow runs under the same cap.
- Keep the pinned or user-requested models and efforts, every required check, the final review, and every approval rule.
- In the final report, say that fast mode ran and give the cap you computed.
