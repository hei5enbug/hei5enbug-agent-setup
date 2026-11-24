# Improvement work across several issues

Owner decision, 2026-11-24. Apply this rule to improvement work that spans several issues in this repository.

1. Order the work by priority and efficiency.
2. If the work is difficult, have a `claude-fable-5-2` subagent draft the plan at effort `high`, have
   `gpt-6.2-astra` review it once at effort `xhigh`, improve the plan from that review, and only then start.
3. Implement defect fixes and needed improvements first. Verify what you implemented.
4. Defer detailed measurement, including repeat runs, integrated regression runs, and detailed before-and-after
   comparisons, to a follow-up issue. Record the commands to run and their cost. When a verdict requires that
   measurement, leave the verdict open for the follow-up issue.
